# ifa/backtest/rating_validator.py
"""评级 vs 实际收益 回测验证模块。

用数字回答「AI 多 Agent 辩论生成的评级，在历史上是否有预测力」：
跑 N 只基金的历史分析 → 取事后实际收益 → 统计命中率 / 置信区间 / 混淆矩阵 / 基准对比。

智识诚实原则（贯穿设计）：
- 小样本命中率是噪声，必须标注 Wilson 置信区间
- 默认不接回反思系统，防止「用随机性强化随机性」的反馈污染
- 不输出绝对判断，只输出描述性统计
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ifa.backtest.engine import run_backtest

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────

_BULLISH_RATINGS = frozenset({"STRONG_BUY", "BUY"})
_BEARISH_RATINGS = frozenset({"UNDERWEIGHT", "SELL"})
_CSI300_CODE = "000300"  # 沪深300 指数代码，用作大盘基准
_DEFAULT_HOLD_DAYS = 60  # 默认持有交易日数（约 3 个月）
_MIN_SIGNIFICANT_SAMPLE = 30  # 统计显著性最小样本量
_RANDOM_BENCHMARK = 0.5  # 随机评级的期望命中率


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class RatingRecord:
    """单只基金单次分析的一条记录。"""

    fund_code: str
    analysis_date: str  # 评级产生的日子 YYYY-MM-DD
    rating: str  # STRONG_BUY/BUY/HOLD/UNDERWEIGHT/SELL
    confidence: str  # High/Medium/Low
    # —— 事后填充（Phase 2）——
    forward_return_pct: float | None = None  # 持有 hold_days 的实际收益率
    benchmark_return_pct: float | None = None  # 同期沪深300 收益率
    excess_return_pct: float | None = None  # forward - benchmark
    hold_days: int = 0  # 实际持有交易日数
    fetch_error: str = ""  # 收益率获取失败原因


@dataclass
class RatingValidationResult:
    """整批回测的统计结果。"""

    records: list[RatingRecord]
    total: int
    valid: int  # 有实际收益数据的记录数
    skipped: int  # 因 error/fetch_failed 跳过的记录数

    # —— 命中率统计（仅 valid 记录）——
    bullish_hit_rate: float | None = None  # BUY/STRONG_BUY 中 forward > 0 的比例
    bearish_hit_rate: float | None = None  # UNDERWEIGHT/SELL 中 forward < 0 的比例
    bullish_n: int = 0
    bearish_n: int = 0

    # —— 置信区间（Wilson 二项分布，95%）——
    bullish_ci_low: float | None = None
    bullish_ci_high: float | None = None
    bearish_ci_low: float | None = None
    bearish_ci_high: float | None = None

    # —— 基准对比 ——
    random_benchmark: float | None = None  # 0.5（随机评级期望命中率）
    csi300_benchmark: float | None = None  # 同期沪深300 上涨比例
    alpha_vs_random: float | None = None  # bullish_hit_rate - 0.5
    alpha_vs_csi300: float | None = None  # bullish_hit_rate - csi300_benchmark

    # —— 混淆矩阵（评级 × 实际涨跌）——
    confusion_matrix: dict[str, dict[str, int]] | None = None

    # —— 元信息 ——
    hold_days: int = 0
    period_start: str = ""
    period_end: str = ""
    warnings: list[str] = field(default_factory=list)


# ── 纯计算函数（可独立测试，不碰网络/LLM）──────────────────────────────


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 二项分布置信区间。

    比「正态近似」更准——在 n 小或 p 接近 0/1 时不会给出负数或 >1 的区间。

    参数:
        k: 成功次数
        n: 总次数（n=0 时返回 (0, 1)）
        z: z 值，1.96 对应 95% 置信度

    返回:
        (下界, 上界)，均为 [0, 1] 区间
    """
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def _classify(rating: str) -> str:
    """把 5 档评级归为 bullish/bearish/neutral。"""
    if rating in _BULLISH_RATINGS:
        return "bullish"
    if rating in _BEARISH_RATINGS:
        return "bearish"
    return "neutral"


def compute_statistics(records: list[RatingRecord], hold_days: int) -> RatingValidationResult:
    """对一批记录计算统计指标（纯计算，无副作用）。

    这是 Phase 3 的核心——把原始记录聚合成可读的统计结果。
    """
    valid_records = [r for r in records if r.fetch_error == "" and r.forward_return_pct is not None]
    skipped = [r for r in records if not (r.fetch_error == "" and r.forward_return_pct is not None)]

    result = RatingValidationResult(
        records=records,
        total=len(records),
        valid=len(valid_records),
        skipped=len(skipped),
        hold_days=hold_days,
        random_benchmark=_RANDOM_BENCHMARK,
        warnings=[],
    )

    if not valid_records:
        result.warnings.append("无有效记录（全部获取失败或无收益数据），无法计算统计指标")
        return result

    # 时间范围
    dates = [r.analysis_date for r in valid_records if r.analysis_date]
    if dates:
        result.period_start = min(dates)
        result.period_end = max(dates)

    # —— 命中率 ——
    bullish_records = [r for r in valid_records if _classify(r.rating) == "bullish"]
    bearish_records = [r for r in valid_records if _classify(r.rating) == "bearish"]

    result.bullish_n = len(bullish_records)
    result.bearish_n = len(bearish_records)

    if bullish_records:
        hits = sum(1 for r in bullish_records if r.forward_return_pct > 0)
        result.bullish_hit_rate = hits / len(bullish_records)
        result.bullish_ci_low, result.bullish_ci_high = wilson_ci(hits, len(bullish_records))
        result.alpha_vs_random = result.bullish_hit_rate - _RANDOM_BENCHMARK

    if bearish_records:
        hits = sum(1 for r in bearish_records if r.forward_return_pct < 0)
        result.bearish_hit_rate = hits / len(bearish_records)
        result.bearish_ci_low, result.bearish_ci_high = wilson_ci(hits, len(bearish_records))

    # —— 沪深300 基准：同期上涨比例 ——
    bench_valid = [r for r in valid_records if r.benchmark_return_pct is not None]
    if bench_valid:
        up_count = sum(1 for r in bench_valid if r.benchmark_return_pct > 0)
        result.csi300_benchmark = up_count / len(bench_valid)
        if result.bullish_hit_rate is not None:
            result.alpha_vs_csi300 = result.bullish_hit_rate - result.csi300_benchmark

    # —— 混淆矩阵 ——
    matrix: dict[str, dict[str, int]] = {
        "STRONG_BUY": {"up": 0, "down": 0},
        "BUY": {"up": 0, "down": 0},
        "HOLD": {"up": 0, "down": 0},
        "UNDERWEIGHT": {"up": 0, "down": 0},
        "SELL": {"up": 0, "down": 0},
    }
    for r in valid_records:
        if r.rating in matrix:
            direction = "up" if r.forward_return_pct > 0 else "down"
            matrix[r.rating][direction] += 1
    result.confusion_matrix = matrix

    # —— 警告 ——
    if result.valid < _MIN_SIGNIFICANT_SAMPLE:
        result.warnings.append(
            f"样本量 {result.valid} < {_MIN_SIGNIFICANT_SAMPLE}，命中率统计无统计显著性，仅供参考"
        )
    if result.bullish_n == 0 and result.bearish_n == 0:
        result.warnings.append("所有有效记录均为 HOLD，无法计算 bullish/bearish 命中率（无方向性信号）")
    if result.bullish_n > 0 and result.bullish_n < _MIN_SIGNIFICANT_SAMPLE:
        result.warnings.append(f"看涨样本仅 {result.bullish_n} 个，置信区间极宽，结论不具参考价值")
    if result.bearish_n > 0 and result.bearish_n < _MIN_SIGNIFICANT_SAMPLE:
        result.warnings.append(f"看跌样本仅 {result.bearish_n} 个，置信区间极宽，结论不具参考价值")
    for r in skipped:
        if r.fetch_error:
            result.warnings.append(f"{r.fund_code} 在 {r.analysis_date} 的收益获取失败：{r.fetch_error}")

    return result


# ── 日期工具 ──────────────────────────────────────────────────────────


def add_trading_days(date_str: str, days: int) -> str:
    """粗略推算「日期 + N 个交易日」后的日历日期。

    用日历日 *（7/5）近似交易日（一周 5 个交易日 / 7 天）。
    精确推算需要交易日历，但回测取数会按实际行情过滤非交易日，
    所以这里只需给出一个「足够往后」的日期，多取几天数据不影响正确性。
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    calendar_days = int(days * 7 / 5) + 5  # +5 天余量，宁可多取
    return (dt + timedelta(days=calendar_days)).strftime("%Y-%m-%d")


def generate_monthly_dates(months_back: int, end_date: str | None = None) -> list[str]:
    """生成过去 N 个月每月一个日期（15 号），最近一个月为 end_date 或今天。"""
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
    dates: list[str] = []
    for i in range(months_back):
        # 从最近往回推，每月取 15 号
        year = end.year
        month = end.month - i
        while month <= 0:
            month += 12
            year -= 1
        # 用 15 号；如果 end_date 在本月且 i=0，取 end_date
        day = min(end.day, 28) if i == 0 and end_date is None else 15
        dates.append(f"{year:04d}-{month:02d}-{day:02d}")
    return sorted(set(dates))


# ── 主入口：两阶段编排 ────────────────────────────────────────────────

# 进度回调签名：(phase, i, total, fund_code, analysis_date, status) -> None
ProgressCallback = Callable[[str, int, int, str, str, str], None]


def run_rating_validation(
    fund_codes: list[str],
    analysis_dates: list[str],
    hold_days: int = _DEFAULT_HOLD_DAYS,
    advisor: Any | None = None,
    on_progress: ProgressCallback | None = None,
    update_memory: bool = False,
) -> RatingValidationResult:
    """跑「评级 vs 实际收益」回测验证。

    两阶段流程：
      Phase 1 - 跑历史分析，收集 (fund, date, rating, confidence) 四元组
      Phase 2 - 对每条记录取 [analysis_date, +hold_days] 实际收益，对比基准
      Phase 3 - compute_statistics 统计（命中率 / CI / 混淆矩阵 / alpha）

    参数:
        fund_codes: 基金代码列表（建议 ETF/指数基金）
        analysis_dates: 分析日期列表 YYYY-MM-DD
        hold_days: 评级后持有多少交易日看收益（默认 60，约 3 个月）
        advisor: 可选复用的 AdvisorGraph 实例（批量省初始化）。None 则内部新建。
        on_progress: 进度回调 (phase, i, total, code, date, status) -> None
        update_memory: 显式开关。默认 False（不接反思系统）。
                       设 True 时把结果喂回 reflect_and_remember —— 注意幸存者偏差风险。

    返回:
        RatingValidationResult
    """
    # 延迟导入，避免顶层循环依赖
    from ifa.common import build_advisor, build_state

    own_advisor = False
    if advisor is None:
        advisor = build_advisor()
        own_advisor = True

    total_tasks = len(fund_codes) * len(analysis_dates)
    records: list[RatingRecord] = []
    idx = 0

    try:
        # ── Phase 1 + 2 合并：每只基金每个日期，先跑分析拿评级，立刻取收益 ──
        for code in fund_codes:
            for date in analysis_dates:
                idx += 1
                status = "running"

                # —— Phase 1: 跑历史分析拿评级 ——
                record = RatingRecord(
                    fund_code=code,
                    analysis_date=date,
                    rating="",
                    confidence="",
                )

                try:
                    state = build_state("deep", fund_codes=code, analysis_date=date)
                    final_state = advisor.run("deep", state)

                    if final_state.get("error"):
                        record.fetch_error = f"分析失败: {final_state['error'][:100]}"
                        status = "analysis_failed"
                        if on_progress:
                            on_progress("analyze", idx, total_tasks, code, date, status)
                        records.append(record)
                        continue

                    # 评级来源：优先 state（修 bug 后可用），兜底 process_signal
                    rating = final_state.get("final_rating", "")
                    if not rating:
                        try:
                            rating = advisor.process_signal(final_state.get("final_report", ""))
                        except Exception as e:
                            logger.warning("process_signal 提取评级失败 (%s %s): %s", code, date, e)
                    record.rating = rating or "HOLD"

                    confidence = final_state.get("final_confidence", "")
                    if not confidence:
                        try:
                            confidence = advisor.process_confidence(final_state.get("final_report", ""))
                        except Exception:
                            confidence = "Medium"
                    record.confidence = confidence or "Medium"

                except Exception as e:
                    record.fetch_error = f"分析异常: {e!s:.100s}"
                    status = "error"
                    if on_progress:
                        on_progress("analyze", idx, total_tasks, code, date, status)
                    records.append(record)
                    continue

                if on_progress:
                    on_progress("analyze", idx, total_tasks, code, date, "ok")

                # —— Phase 2: 取实际收益（复用 run_backtest）——
                end_date = add_trading_days(date, hold_days)
                try:
                    bt = run_backtest(code, date, end_date)
                    if bt.error:
                        record.fetch_error = f"收益数据: {bt.error[:80]}"
                        status = "return_failed"
                    else:
                        record.forward_return_pct = bt.total_return_pct
                        record.hold_days = bt.trading_days

                    # 基准：沪深300 同期
                    bench = run_backtest(_CSI300_CODE, date, end_date)
                    if not bench.error:
                        record.benchmark_return_pct = bench.total_return_pct
                        if record.forward_return_pct is not None:
                            record.excess_return_pct = (
                                record.forward_return_pct - bench.total_return_pct
                            )

                except Exception as e:
                    if not record.fetch_error:
                        record.fetch_error = f"收益获取异常: {e!s:.80s}"
                    status = "return_error"

                if on_progress and status in ("return_failed", "return_error"):
                    on_progress("return", idx, total_tasks, code, date, status)
                elif on_progress:
                    on_progress("return", idx, total_tasks, code, date, "ok")

                records.append(record)

        # —— 可选：接回反思系统（默认关闭，防止幸存者偏差反馈环）——
        if update_memory:
            returns_summary = _build_returns_summary(records)
            try:
                advisor.reflect_and_remember(returns_summary)
                logger.warning("已更新 Agent 记忆（用户显式开启 --update-memory）")
            except Exception as e:
                logger.warning("记忆更新失败（不影响验证结果）: %s", e)

    finally:
        if own_advisor:
            # 不显式 close（AdvisorGraph 无 close 接口），交给 GC
            pass

    # —— Phase 3: 统计 ——
    return compute_statistics(records, hold_days)


def _build_returns_summary(records: list[RatingRecord]) -> str:
    """把记录汇总成 Reflector 能理解的 returns_losses 字符串。"""
    lines = []
    for r in records:
        if r.forward_return_pct is not None:
            lines.append(f"{r.fund_code}@{r.analysis_date}: {r.rating}, 收益 {r.forward_return_pct:+.2f}%")
    return "; ".join(lines) if lines else "无可用收益数据"


# ── 报告格式化 ────────────────────────────────────────────────────────

_DISCLAIMER = """【评级验证报告 · 智识诚实声明】
本报告命中率统计基于有限历史样本，存在幸存者偏差和样本选择偏差。
样本量 < 30 时统计结论无显著性。本验证不证明评级系统「有效」或「无效」，
仅描述其在给定样本上的历史表现。过往表现不代表未来结果。
"""


def format_validation_report(result: RatingValidationResult) -> str:
    """把 RatingValidationResult 格式化为 Markdown 报告。"""
    lines = [f"{_DISCLAIMER}\n---\n", "# 评级验证报告\n"]

    # 概览
    lines.append(f"**样本**: {result.total} 条记录（有效 {result.valid}，跳过 {result.skipped}）  ")
    lines.append(f"**持有周期**: {result.hold_days} 个交易日  ")
    if result.period_start:
        lines.append(f"**分析日期范围**: {result.period_start} ~ {result.period_end}\n")

    # 命中率
    lines.append("## 命中率统计\n")
    lines.append("| 方向 | 样本数 | 命中率 | 95% 置信区间 |")
    lines.append("|------|--------|--------|-------------|")
    if result.bullish_hit_rate is not None:
        ci = f"[{result.bullish_ci_low:.2%}, {result.bullish_ci_high:.2%}]" if result.bullish_ci_low is not None else "—"
        lines.append(f"| 看涨（BUY/STRONG_BUY） | {result.bullish_n} | {result.bullish_hit_rate:.2%} | {ci} |")
    else:
        lines.append("| 看涨（BUY/STRONG_BUY） | 0 | — | — |")
    if result.bearish_hit_rate is not None:
        ci = f"[{result.bearish_ci_low:.2%}, {result.bearish_ci_high:.2%}]" if result.bearish_ci_low is not None else "—"
        lines.append(f"| 看跌（UNDERWEIGHT/SELL） | {result.bearish_n} | {result.bearish_hit_rate:.2%} | {ci} |")
    else:
        lines.append("| 看跌（UNDERWEIGHT/SELL） | 0 | — | — |")
    lines.append("")

    # 基准对比
    lines.append("## 基准对比\n")
    lines.append("| 基准 | 期望命中率 | 说明 |")
    lines.append("|------|-----------|------|")
    lines.append("| 随机基准 | 50.00% | 抛硬币 |")
    if result.csi300_benchmark is not None:
        lines.append(f"| 沪深300 同期 | {result.csi300_benchmark:.2%} | 同期大盘上涨比例 |")
    if result.alpha_vs_random is not None:
        lines.append(f"\n**Alpha（vs 随机）**: {result.alpha_vs_random:+.2%}  ")
        lines.append("_正值=比抛硬币好，但需结合置信区间判断是否显著_\n")
    if result.alpha_vs_csi300 is not None:
        lines.append(f"**Alpha（vs 沪深300）**: {result.alpha_vs_csi300:+.2%}  ")
        lines.append("_正值=评级选股跑赢了被动持有大盘_\n")

    # 混淆矩阵
    if result.confusion_matrix:
        lines.append("## 混淆矩阵（评级 × 实际涨跌）\n")
        lines.append("| 评级 | 实际上涨 | 实际下跌 |")
        lines.append("|------|---------|---------|")
        for rating in ["STRONG_BUY", "BUY", "HOLD", "UNDERWEIGHT", "SELL"]:
            row = result.confusion_matrix.get(rating, {"up": 0, "down": 0})
            lines.append(f"| {rating} | {row['up']} | {row['down']} |")
        lines.append("")

    # 警告
    if result.warnings:
        lines.append("## ⚠️ 警告\n")
        for w in result.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # 明细
    lines.append("## 明细记录\n")
    lines.append("| 基金 | 分析日期 | 评级 | 置信度 | 实际收益 | 基准收益 | 超额 |")
    lines.append("|------|---------|------|--------|---------|---------|------|")
    for r in result.records:
        fwd = f"{r.forward_return_pct:+.2f}%" if r.forward_return_pct is not None else "—"
        bench = f"{r.benchmark_return_pct:+.2f}%" if r.benchmark_return_pct is not None else "—"
        excess = f"{r.excess_return_pct:+.2f}%" if r.excess_return_pct is not None else "—"
        err = f" ⚠️{r.fetch_error[:30]}" if r.fetch_error else ""
        lines.append(f"| {r.fund_code} | {r.analysis_date} | {r.rating} | {r.confidence} | {fwd} | {bench} | {excess} |{err}")

    return "\n".join(lines)
