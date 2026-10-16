# ifa/backtest/benchmarks.py
"""基准解析：为每只基金找出「它真正该比的那个指数」。

原实现（1d0c151 之前）对纳指基金、标普基金、白酒基金一律拿沪深300 当基准，
却把结果标成「Alpha vs 沪深300」——那不是 alpha，那是「这只基金和沪深300 的差距」，
连「跑赢了自己该比的指数没有」都回答不了。这里把基准变成显式的、逐条可查的对象。

解析顺序（先具体后笼统，且每一步都能被报告审计）：
  1. 调用方显式指定的 override（--benchmark 参数 / API 入参）；
  2. 基金名称里识别出的跟踪指数 → 中证指数代码；
  3. 都认不出来时退回沪深300，并在 note 里写明为什么（含「跟踪的是海外指数，
     本仓库没有对应行情」这种可解释的降级，而不是含糊的「未识别」）。

绝不静默换基准：每条记录都会带上 benchmark_code / benchmark_label / benchmark_source，
报告里逐条列出并统计有多少条走了回退。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BENCHMARK_CODE = "000300"
DEFAULT_BENCHMARK_LABEL = "沪深300"
_UNKNOWN_INDEX_NOTE = "未识别到跟踪指数"

# 这些指数有 A 股行情可取（已实测 ak.index_zh_a_hist 对下列代码全部返回数据），
# 代码取自 ifa.dataflows.a_share_macro 的中证指数登记表，避免维护第二份注册表。
_USABLE_INDEX_NAMES: tuple[str, ...] = (
    "沪深300",
    "上证50",
    "上证380",
    "中证500",
    "上证180",
    "中证1000",
    "上证红利",
    "中证100",
    "中证800",
    "中证白酒",
    "中证红利",
)

# 按名称长度降序，避免「中证1000」被更短的「中证100」抢先命中（真实踩过的坑）。
_INDEX_NAMES_BY_LENGTH = tuple(sorted(_USABLE_INDEX_NAMES, key=len, reverse=True))

# 能认出来、但本仓库取不到行情的指数：明确说明降级原因，比「未识别」诚实得多。
_FOREIGN_INDEX_NAMES: tuple[str, ...] = (
    "纳斯达克100",
    "纳斯达克",
    "标普500",
    "标普",
    "道琼斯",
    "恒生指数",
    "恒生",
    "日经225",
    "德国DAX",
    "法国CAC",
    "MSCI",
)


@dataclass(frozen=True)
class BenchmarkSpec:
    """一条记录使用的基准及其来源。"""

    code: str
    label: str
    source: str  # explicit / fund_name / default
    note: str = ""

    def describe(self) -> str:
        """给报告用的一句话说明。"""
        if self.source == "explicit":
            return f"{self.label}（{self.code}，调用方指定）"
        if self.source == "fund_name":
            return f"{self.label}（{self.code}，按基金名称识别）"
        return f"{self.label}（{self.code}，回退：{self.note or _UNKNOWN_INDEX_NOTE}）"


def detect_index_name(fund_name: str) -> str | None:
    """从基金名称识别跟踪指数（只认有 A 股行情的指数）。"""
    text = (fund_name or "").strip()
    if not text:
        return None
    for name in _INDEX_NAMES_BY_LENGTH:
        if name in text:
            return name
    return None


def detect_foreign_index(fund_name: str) -> str | None:
    """识别「跟踪海外指数」这类无法用 A 股指数做基准的基金。"""
    text = (fund_name or "").strip()
    if not text:
        return None
    for name in sorted(_FOREIGN_INDEX_NAMES, key=len, reverse=True):
        if name in text:
            return name
    return None


def _split_override(value: str) -> tuple[str, str]:
    """解析 override，支持「000905」与「000905:中证500」两种写法。"""
    raw = (value or "").strip()
    for sep in (":", "：", "="):
        if sep in raw:
            code, label = raw.split(sep, 1)
            return code.strip(), label.strip()
    return raw, ""


def resolve_benchmark(
    fund_code: str,
    fund_name: str | None = None,
    *,
    overrides: dict[str, str] | None = None,
) -> BenchmarkSpec:
    """解析某只基金应使用的基准指数。

    参数:
        fund_code: 基金代码（override 的键）
        fund_name: 基金名称（可为 None，此时只能靠 override 或回退）
        overrides: {基金代码: 指数代码或「代码:名称」}，优先级最高
    """
    from ifa.dataflows.a_share_macro import csindex_code

    override = (overrides or {}).get(fund_code.strip())
    if override:
        code, label = _split_override(override)
        return BenchmarkSpec(code=code, label=label or code, source="explicit")

    index_name = detect_index_name(fund_name or "")
    if index_name:
        resolved = csindex_code(index_name)
        if resolved:
            return BenchmarkSpec(code=resolved, label=index_name, source="fund_name")

    foreign = detect_foreign_index(fund_name or "")
    if foreign:
        return BenchmarkSpec(
            code=DEFAULT_BENCHMARK_CODE,
            label=DEFAULT_BENCHMARK_LABEL,
            source="default",
            note=f"该基金跟踪 {foreign}，本仓库无对应指数行情，以沪深300 代替",
        )

    return BenchmarkSpec(
        code=DEFAULT_BENCHMARK_CODE,
        label=DEFAULT_BENCHMARK_LABEL,
        source="default",
        note=f"{_UNKNOWN_INDEX_NOTE}，以沪深300 代替",
    )
