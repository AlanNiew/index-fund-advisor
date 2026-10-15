# ifa/portfolio/weights.py
"""组合权重的解析与校验 —— LLM 说「合计 100%」不能当真，必须算一遍。

背景：`portfolio_advisor` 的 prompt 要求 LLM 给出「sum to 100%」的权重，RiskProfile 里
也有 max_single_fund_pct / min_bond_pct / max_international_pct 三条硬约束，但此前它们
只是被拼进 prompt 文本，没有任何代码真的检查过 —— 建议里写「债券 50%」而实际给 5%，
或者单只基金占 60%，都不会被拦住。

设计取舍：
- 只做确定性解析与算术修正，不再多花一次 LLM 调用去「重排」：修正结果连同违规项一起
  写回 portfolio_advice，读者能看出原始建议被改了什么、为什么被改。
- 约束不可行时（例如可选基金数 × 单基金上限 < 100%）不硬凑，明确写出「无法满足」，
  而不是悄悄给出一组仍然违规的数字。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ifa.portfolio.models import RiskProfile

# 合计容差：LLM 常写 99% / 101%，这个量级不算违规；超过就说明确实算错了
SUM_TOLERANCE_PCT = 1.0
# 单项约束容差（百分点）：避免 30.0% 对上 30% 上限时误报
BOUND_TOLERANCE_PCT = 0.5

_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# 类别名 + 百分比：名字允许含数字（中证500），但百分比前必须有空格或冒号
_PAIR_RE = re.compile(r"([^\n,，、;；]{1,24}?)\s*(?:[:：]|\s)\s*(\d+(?:\.\d+)?)\s*%")

_BOND_KEYWORDS = ("债券", "债", "固收", "bond")
_INTERNATIONAL_KEYWORDS = (
    "qdii",
    "海外",
    "国际",
    "美股",
    "纳指",
    "标普",
    "纳斯达克",
    "overseas",
    "international",
)
# 「合计 100%」这类汇总行不是类别，必须排除，否则会被当成一个 100% 的类别
_TOTAL_NAME_KEYWORDS = ("合计", "总计", "小计", "total", "sum", "现金合计")
# 小计语境：同一行出现「+」或小计关键词时，形如「= 45%」的百分比是这一组的合计，不是该基金的仓位
_SUBTOTAL_KEYWORDS = ("小计", "合计", "总计", "subtotal", "total")

_CATEGORY_END_MARKERS = ("FUND SELECTIONS", "RATIONALE", "RISK ASSESSMENT", "REBALANCE GUIDANCE")
_FUND_END_MARKERS = ("RATIONALE", "RISK ASSESSMENT", "REBALANCE GUIDANCE")


def _is_bond(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in _BOND_KEYWORDS)


def _is_international(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in _INTERNATIONAL_KEYWORDS)


def _is_total_row(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in _TOTAL_NAME_KEYWORDS)


def _clean_name(raw: str) -> str:
    """去掉列表符号 / markdown 强调 / 表格竖线 / 冒号等噪声（"- **宽基指数**" → "宽基指数"）。"""
    name = raw.strip()
    for _ in range(5):
        cleaned = name.strip().strip(":：-*•·_`|").strip()
        if cleaned == name:
            break
        name = cleaned
    return name


def _first_weight_in_tail(tail: str, chunk: str) -> str | None:
    """取 tail 里第一个百分比；小计语境下跳过「= 45%」这种组内合计。"""
    is_subtotal_context = "+" in chunk or any(keyword in chunk.lower() for keyword in _SUBTOTAL_KEYWORDS)
    for match in _PCT_RE.finditer(tail):
        if is_subtotal_context and re.search(r"=\s*$", tail[: match.start()]):
            continue
        return match.group(1)
    return None


def _section(text: str, start_marker: str, end_markers: Sequence[str]) -> str:
    """取 start_marker 到最近的 end_marker 之间的片段（大小写不敏感，找不到返回空串）。"""
    upper = text.upper()
    start = upper.find(start_marker)
    if start < 0:
        return ""
    end = len(text)
    for marker in end_markers:
        found = upper.find(marker, start + len(start_marker))
        if found >= 0:
            end = min(end, found)
    return text[start + len(start_marker) : end]


def parse_category_weights(text: str) -> dict[str, float]:
    """解析 ASSET ALLOCATION 段的「类别: 百分比」对，返回 {类别: 百分比}（未归一化）。

    解析不到返回空 dict —— 调用方据此报「无法解析」，而不是当成 0% 静默通过。
    """
    segment = _section(text, "ASSET ALLOCATION", _CATEGORY_END_MARKERS)
    if not segment:
        return {}

    weights: dict[str, float] = {}
    for match in _PAIR_RE.finditer(segment):
        name = _clean_name(match.group(1))
        if not name or _is_total_row(name):
            continue
        weights[name] = weights.get(name, 0.0) + float(match.group(2))
    return weights


def parse_fund_weights(text: str) -> dict[str, float]:
    """解析 FUND SELECTIONS 段的「6 位基金代码 + 百分比」对，返回 {代码: 百分比}。

    兼容「510300 沪深300ETF (30%)」与「30% 510300」两种写法。
    同一代码多次出现时取**最大值**而不是累加：真实输出常在明细表之后再用一行
    「宽基小计：510300（20%）+ 510880（15%）= 45%」复述一遍，累加会把这些复述
    当成第二笔仓位，把合规的组合算成 200%（实测 2026-10-14 的组合报告就是如此）。
    取最大值对段落顺序不敏感，且在任何一处声称超配时仍会报出来。
    """
    segment = _section(text, "FUND SELECTIONS", _FUND_END_MARKERS)
    if not segment:
        return {}

    weights: dict[str, float] = {}
    for chunk in re.split(r"[,，、;；\n]", segment):
        codes = list(_CODE_RE.finditer(chunk))
        for index, match in enumerate(codes):
            code = match.group(1)
            tail_end = codes[index + 1].start() if index + 1 < len(codes) else len(chunk)
            tail = chunk[match.end() : tail_end]
            weight = _first_weight_in_tail(tail, chunk)
            if weight is None and index == 0:
                # 「30% 510300」这种写法：只认紧贴在代码前的百分比
                head = chunk[: match.start()]
                trailing = re.search(r"(\d+(?:\.\d+)?)\s*%\s*$", head)
                if trailing is not None:
                    weight = trailing.group(1)
            if weight is None:
                continue
            weights[code] = max(weights.get(code, 0.0), float(weight))
    return weights


@dataclass
class WeightReport:
    """一次组合权重校验的结论（数值均为百分比 0–100）。"""

    profile_level: str
    categories: dict[str, float] = field(default_factory=dict)
    funds: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    corrected_categories: dict[str, float] = field(default_factory=dict)
    corrected_funds: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues


def rebalance_category_weights(weights: dict[str, float], profile: RiskProfile) -> tuple[dict[str, float], list[str]]:
    """把类别权重投影到约束集（合计 100%、债券下限、QDII 上限）；返回 (权重, 无法修正的原因)。"""
    issues: list[str] = []
    result = {name: max(value, 0.0) for name, value in weights.items()}
    total = sum(result.values())
    if total <= 0:
        return {}, ["资产类别权重全为 0，无法修正"]
    result = {name: value / total * 100 for name, value in result.items()}

    bond_keys = [name for name in result if _is_bond(name)]
    intl_keys = [name for name in result if _is_international(name)]
    other_keys = [name for name in result if name not in bond_keys and name not in intl_keys]

    # 1) 债券下限：把债券类整体抬到下限，缺口按比例从其余类别扣
    floor = profile.min_bond_pct * 100
    bond_total = sum(result[name] for name in bond_keys)
    if floor > 0 and bond_total < floor - BOUND_TOLERANCE_PCT:
        if not bond_keys:
            issues.append(f"建议里没有债券类，无法满足债券下限 {floor:.0f}%（不凭空新增类别）")
        else:
            donors = other_keys + intl_keys
            donor_total = sum(result[name] for name in donors)
            deficit = floor - bond_total
            if donor_total <= 0:
                issues.append("无法把债券权重抬到下限：其余类别合计为 0")
            else:
                for name in donors:
                    result[name] -= deficit * result[name] / donor_total
                if bond_total > 0:
                    for name in bond_keys:
                        result[name] *= floor / bond_total
                else:
                    for name in bond_keys:
                        result[name] = floor / len(bond_keys)

    # 2) 海外/QDII 上限：超出的部分按比例转给其他类别
    cap = profile.max_international_pct * 100
    intl_total = sum(result[name] for name in intl_keys)
    if intl_keys and intl_total > cap + BOUND_TOLERANCE_PCT:
        receivers = bond_keys + other_keys
        receiver_total = sum(result[name] for name in receivers)
        excess = intl_total - cap
        if receiver_total <= 0:
            issues.append("无法把海外/QDII 权重压到上限：其余类别合计为 0")
        else:
            for name in intl_keys:
                result[name] *= cap / intl_total
            for name in receivers:
                result[name] += excess * result[name] / receiver_total

    # 3) 归一化回 100%
    total = sum(result.values())
    if total > 0:
        result = {name: value / total * 100 for name, value in result.items()}
    return result, issues


def rebalance_fund_weights(weights: dict[str, float], profile: RiskProfile) -> tuple[dict[str, float], list[str]]:
    """把单基金权重压到 max_single_fund_pct 并归一化；返回 (权重, 无法满足的原因)。"""
    issues: list[str] = []
    cap = profile.max_single_fund_pct * 100
    result = {code: max(value, 0.0) for code, value in weights.items()}
    if not result:
        return {}, ["没有解析到单基金权重"]

    capacity = len(result) * cap
    if capacity < 100 - BOUND_TOLERANCE_PCT:
        issues.append(
            f"{len(result)} 只基金 × 单基金上限 {cap:.0f}% = {capacity:.0f}%，"
            "凑不满 100%（需要更多候选基金或放宽该风险偏好的上限）"
        )

    for _ in range(20):
        total = sum(result.values())
        if total <= 0:
            return {}, [*issues, "单基金权重全为 0"]
        scaled = {code: value / total * 100 for code, value in result.items()}
        over = [code for code, value in scaled.items() if value > cap + 1e-9]
        if not over:
            return scaled, issues
        under = [code for code in scaled if code not in over]
        if not under:
            return dict.fromkeys(scaled, cap), [*issues, f"全部基金都顶到上限 {cap:.0f}%，合计只有 {capacity:.0f}%"]
        remainder = 100 - cap * len(over)
        under_total = sum(scaled[code] for code in under)
        for code in over:
            result[code] = cap
        for code in under:
            result[code] = scaled[code] / under_total * remainder if under_total > 0 else remainder / len(under)

    return result, [*issues, "单基金权重修正未收敛（超过 20 轮）"]


def validate_portfolio_weights(text: str, profile: RiskProfile) -> WeightReport:
    """校验组合建议里的资产类别权重与单基金权重，违规时给出确定性重排结果。"""
    report = WeightReport(profile_level=profile.level)
    report.categories = parse_category_weights(text)
    report.funds = parse_fund_weights(text)

    if not report.categories and not report.funds:
        report.issues.append("未能从组合建议里解析出任何权重（ASSET ALLOCATION / FUND SELECTIONS 段缺失或格式异常）")
        return report

    if report.categories:
        category_issues = _check_category_constraints(report.categories, profile)
        if category_issues:
            report.issues.extend(category_issues)
            report.corrected_categories, extra = rebalance_category_weights(report.categories, profile)
            report.issues.extend(extra)

    if report.funds:
        fund_issues = _check_fund_constraints(report.funds, profile)
        if fund_issues:
            report.issues.extend(fund_issues)
            report.corrected_funds, extra = rebalance_fund_weights(report.funds, profile)
            report.issues.extend(extra)

    return report


def _check_category_constraints(categories: dict[str, float], profile: RiskProfile) -> list[str]:
    issues: list[str] = []
    total = sum(categories.values())
    if abs(total - 100) > SUM_TOLERANCE_PCT:
        issues.append(f"资产类别权重合计 {total:.1f}%，应为 100%（容差 ±{SUM_TOLERANCE_PCT:.0f}%）")

    floor = profile.min_bond_pct * 100
    bond_total = sum(value for name, value in categories.items() if _is_bond(name))
    if floor > 0 and bond_total < floor - BOUND_TOLERANCE_PCT:
        issues.append(f"债券类权重 {bond_total:.1f}% 低于该风险偏好的下限 {floor:.0f}%")

    cap = profile.max_international_pct * 100
    intl_total = sum(value for name, value in categories.items() if _is_international(name))
    if intl_total > cap + BOUND_TOLERANCE_PCT:
        issues.append(f"海外/QDII 权重 {intl_total:.1f}% 超过该风险偏好的上限 {cap:.0f}%")

    return issues


def _check_fund_constraints(funds: dict[str, float], profile: RiskProfile) -> list[str]:
    issues: list[str] = []
    total = sum(funds.values())
    if abs(total - 100) > SUM_TOLERANCE_PCT:
        issues.append(f"单基金权重合计 {total:.1f}%，应为 100%（容差 ±{SUM_TOLERANCE_PCT:.0f}%）")

    cap = profile.max_single_fund_pct * 100
    over = {code: value for code, value in funds.items() if value > cap + BOUND_TOLERANCE_PCT}
    if over:
        detail = "、".join(f"{code} {value:.1f}%" for code, value in sorted(over.items()))
        issues.append(f"单基金权重超过上限 {cap:.0f}%: {detail}")
    return issues


def _format_weights(weights: dict[str, float]) -> str:
    return "、".join(f"{name} {value:.1f}%" for name, value in weights.items())


def format_weight_check(report: WeightReport, profile: RiskProfile) -> str | None:
    """把校验结论渲染成追加到 portfolio_advice 的文本；全部合格时返回 None（不打扰正常流程）。"""
    if report.ok:
        return None

    lines = ["", "## WEIGHT CHECK（代码校验，非 LLM 自述）", "", "发现的问题:"]
    lines.extend(f"- {issue}" for issue in report.issues)
    if report.corrected_categories:
        lines += ["", f"按约束重排后的资产类别权重: {_format_weights(report.corrected_categories)}"]
    if report.corrected_funds:
        lines += ["", f"按约束重排后的单基金权重: {_format_weights(report.corrected_funds)}"]
    lines += [
        "",
        f"约束（{profile.level}）: 单基金 ≤ {profile.max_single_fund_pct:.0%}、"
        f"债券 ≥ {profile.min_bond_pct:.0%}、海外/QDII ≤ {profile.max_international_pct:.0%}",
        "⚠ 上面的原始建议不满足这些约束；请以重排后的权重为准，或重新给出满足约束的方案。",
    ]
    return "\n".join(lines)
