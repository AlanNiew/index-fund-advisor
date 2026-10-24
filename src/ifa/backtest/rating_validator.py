# ifa/backtest/rating_validator.py
"""评级 vs 实际收益 回测验证模块。

用数字回答「AI 多 Agent 辩论生成的评级，在历史上是否有预测力」：
跑 N 只基金的历史分析 → 取事后实际收益 → 统计命中率 / 置信区间 / 混淆矩阵 / 基准对比。

智识诚实原则（贯穿设计）：
- 小样本命中率是噪声，必须标注 Wilson 置信区间
- 默认不接回反思系统，防止「用随机性强化随机性」的反馈污染
- 不输出绝对判断，只输出描述性统计

口径说明（为什么统计层变复杂了）：
- 绝对命中率（基金自己涨没涨）主要反映 beta，原字段保留以便与历史报告对比；
- 超额命中率（跑赢各自基准没有）才是评级真正的可证伪声明，作为并列指标展示；
- 单一视界的结果极易是数据挖掘产物，故默认同时给 20/60/120 三个视界；
- 3 个视界 x 多项指标 = 多重比较，只有预先指定的主视界可当确认性结论。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ifa.backtest.benchmarks import resolve_benchmark
from ifa.backtest.engine import run_backtest
from ifa.backtest.rating_stats import (
    BucketStats,
    ConfidenceStats,
    HorizonStats,
    compute_horizon_stats,
    ordered_horizons,
    wilson_ci,
)

__all__ = [
    "RatingRecord",
    "RatingValidationResult",
    "add_trading_days",
    "benchmark_return",
    "compute_statistics",
    "format_validation_report",
    "generate_monthly_dates",
    "lookup_fund_names",
    "run_rating_validation",
    "wilson_ci",
]

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────

_CSI300_CODE = "000300"  # 默认基准（沪深300）；逐条实际用哪个见 ifa.backtest.benchmarks
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
    hold_days: int = 0  # 主视界实际持有的交易日数
    fetch_error: str = ""  # 收益率获取失败原因

    # —— 多视界（每个视界单独取数，不再让 60 日收益冒充 120 日）——
    returns_by_horizon: dict[int, float] = field(default_factory=dict)  # {交易日: 基金收益%}
    benchmark_by_horizon: dict[int, float] = field(default_factory=dict)  # {交易日: 基准收益%}
    excess_by_horizon: dict[int, float] = field(default_factory=dict)  # {交易日: 超额%}

    # —— 基准身份（每条记录都能查到「比的是哪个指数」）——
    benchmark_code: str = ""
    benchmark_label: str = ""
    benchmark_source: str = ""  # explicit / fund_name / default
    # 部分视界取数失败的原因（记录本身仍有可用视界时不算 fetch_error）
    horizon_errors: dict[int, str] = field(default_factory=dict)


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

    # —— 多视界（每个视界一份完整统计；[0] 不保证是主视界，按 hold_days 找）——
    horizons: list[HorizonStats] = field(default_factory=list)

    # —— 超额口径（主视界；比「绝对涨跌」更接近评级真正的主张）——
    benchmark_up_rate: float | None = None  # 基准同期上涨比例（csi300_benchmark 的新名字）
    bullish_excess_hit_rate: float | None = None  # 看涨样本中跑赢基准的比例
    bearish_excess_hit_rate: float | None = None  # 看跌样本中跑输基准的比例
    bullish_excess_ci_low: float | None = None
    bullish_excess_ci_high: float | None = None
    bearish_excess_ci_low: float | None = None
    bearish_excess_ci_high: float | None = None
    mean_excess_pct: float | None = None
    median_excess_pct: float | None = None
    excess_t: float | None = None  # 超额均值的单样本 t 统计量
    excess_p: float | None = None  # 双侧 p（正态近似，非 t 分布）
    excess_n: int = 0

    # —— 评级梯度（比 2x2 命中率更强的检验）——
    rank_ic: float | None = None  # 评级分数 vs 超额收益的 Spearman 相关
    rank_ic_n: int = 0
    rank_ic_t: float | None = None
    monotonicity: float | None = None  # 评级分数 vs 分档平均超额 的 Spearman
    monotonicity_n: int = 0
    buckets: list[BucketStats] = field(default_factory=list)

    # —— 置信度校准（High 是否真的比 Low 准）——
    confidence_calibration: list[ConfidenceStats] = field(default_factory=list)
    confidence_spread: float | None = None  # High 方向命中率 - Low 方向命中率
    hold_n: int = 0  # HOLD 记录数（主视界）
    hold_mean_excess_pct: float | None = None  # HOLD 档平均超额（检验「不表态」是否真接近 0）

    # —— 基准使用情况 ——
    benchmark_labels: list[str] = field(default_factory=list)  # 去重后的基准说明
    benchmark_fallback_n: int = 0  # 走了沪深300 回退的记录数

    # —— 元信息 ——
    hold_days: int = 0
    period_start: str = ""
    period_end: str = ""
    warnings: list[str] = field(default_factory=list)


# ── 纯计算函数（可独立测试，不碰网络/LLM）──────────────────────────────


# wilson_ci / classify 已移到纯计算层 ifa.backtest.rating_stats，
# 这里从上面 import 进来继续对外暴露（__all__ 里列了 wilson_ci），既有调用方与测试不受影响。


def _forward_return(record: RatingRecord) -> float:
    """读取 forward_return_pct 并把 Optional 收窄为 float。

    valid_records 已按 `forward_return_pct is not None` 过滤，这里把该不变量写成显式契约：
    既让 mypy 能通过，也让契约被破坏时给出可定位的错误而非静默错误统计。
    """
    if record.forward_return_pct is None:
        raise ValueError(f"记录缺少实际收益: {record.fund_code} @ {record.analysis_date}")
    return record.forward_return_pct


def _benchmark_return(record: RatingRecord) -> float:
    """读取 benchmark_return_pct 并把 Optional 收窄为 float（语义同 _forward_return）。"""
    if record.benchmark_return_pct is None:
        raise ValueError(f"记录缺少基准收益: {record.fund_code} @ {record.analysis_date}")
    return record.benchmark_return_pct


def compute_statistics(
    records: list[RatingRecord],
    hold_days: int,
    horizons: Sequence[int] | None = None,
) -> RatingValidationResult:
    """对一批记录计算统计指标（纯计算，无副作用）。

    多视界的统计委托给 ifa.backtest.rating_stats.compute_horizon_stats；本函数负责：
      1. 保持既有扁平字段（绝对口径）语义不变 —— 历史报告与测试可继续对比；
      2. 把每个视界的完整结果放进 result.horizons；
      3. 汇总警告（样本量、全 HOLD、基准回退、多重比较、梯度/校准反向）。

    参数:
        records: 评级记录（可只带扁平字段，此时只有主视界有数）
        hold_days: 主视界（交易日），扁平字段取该视界
        horizons: 要统计的全部视界；None 时用默认 (20, 60, 120) 并保证含 hold_days
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

    # —— 逐视界统计 ——
    result.horizons = [
        compute_horizon_stats(records, h, primary_hold_days=hold_days) for h in ordered_horizons(horizons, hold_days)
    ]
    primary = next((h for h in result.horizons if h.hold_days == hold_days), None)
    if primary is not None:
        _flatten_primary(result, primary)

    # —— 基准使用情况（逐条可查；回退必须报警，见 _append_warnings）——
    labels = {r.benchmark_label: r.benchmark_code for r in records if r.benchmark_label}
    result.benchmark_labels = [f"{label}（{code}）" for label, code in sorted(labels.items())]
    result.benchmark_fallback_n = sum(1 for r in records if r.benchmark_source == "default")

    # —— 混淆矩阵（评级 × 实际涨跌，主视界口径）——
    matrix: dict[str, dict[str, int]] = {
        "STRONG_BUY": {"up": 0, "down": 0},
        "BUY": {"up": 0, "down": 0},
        "HOLD": {"up": 0, "down": 0},
        "UNDERWEIGHT": {"up": 0, "down": 0},
        "SELL": {"up": 0, "down": 0},
    }
    for r in valid_records:
        if r.rating in matrix:
            direction = "up" if _forward_return(r) > 0 else "down"
            matrix[r.rating][direction] += 1
    result.confusion_matrix = matrix

    _append_warnings(result, skipped)
    return result


def _flatten_primary(result: RatingValidationResult, primary: HorizonStats) -> None:
    """把主视界的统计摊平到既有扁平字段（绝对口径语义保持不变）。"""
    result.bullish_n = primary.bullish_n
    result.bearish_n = primary.bearish_n
    result.bullish_hit_rate = primary.bullish_hit_rate
    result.bearish_hit_rate = primary.bearish_hit_rate
    result.bullish_ci_low = primary.bullish_ci_low
    result.bullish_ci_high = primary.bullish_ci_high
    result.bearish_ci_low = primary.bearish_ci_low
    result.bearish_ci_high = primary.bearish_ci_high
    if primary.bullish_hit_rate is not None:
        result.alpha_vs_random = primary.bullish_hit_rate - _RANDOM_BENCHMARK

    # csi300_benchmark 是历史字段名；基准现在逐基金解析，故同时给语义正确的新名字
    result.csi300_benchmark = primary.benchmark_up_rate
    result.benchmark_up_rate = primary.benchmark_up_rate
    result.alpha_vs_csi300 = primary.alpha_vs_benchmark

    result.bullish_excess_hit_rate = primary.bullish_excess_hit_rate
    result.bearish_excess_hit_rate = primary.bearish_excess_hit_rate
    result.bullish_excess_ci_low = primary.bullish_excess_ci_low
    result.bullish_excess_ci_high = primary.bullish_excess_ci_high
    result.bearish_excess_ci_low = primary.bearish_excess_ci_low
    result.bearish_excess_ci_high = primary.bearish_excess_ci_high
    result.mean_excess_pct = primary.mean_excess_pct
    result.median_excess_pct = primary.median_excess_pct
    result.excess_t = primary.excess_t
    result.excess_p = primary.excess_p
    result.excess_n = primary.excess_n
    result.rank_ic = primary.rank_ic
    result.rank_ic_n = primary.rank_ic_n
    result.rank_ic_t = primary.rank_ic_t
    result.monotonicity = primary.monotonicity
    result.monotonicity_n = primary.monotonicity_n
    result.buckets = primary.buckets
    result.confidence_calibration = primary.confidence
    result.confidence_spread = primary.confidence_spread
    result.hold_n = primary.hold_n
    result.hold_mean_excess_pct = primary.hold_mean_excess_pct


def _append_warnings(result: RatingValidationResult, skipped: list[RatingRecord]) -> None:
    """汇总所有警告：样本量 / 方向缺失 / 基准回退 / 多重比较 / 梯度与校准反向。"""
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

    # 基准：回退必须在报告里被看见，否则「超额收益」会被误读成「跑赢了自己的跟踪指数」
    if result.benchmark_fallback_n:
        result.warnings.append(
            f"{result.benchmark_fallback_n}/{result.total} 条记录的基准是回退值（沪深300）："
            "这些记录的超额收益不代表「跑赢了自己的跟踪指数」"
        )

    # 多重比较：3 个视界 x 多项指标，只有主视界是预先指定的确认性口径
    if len(result.horizons) > 1:
        others = ", ".join(str(h.hold_days) for h in result.horizons if h.hold_days != result.hold_days)
        result.warnings.append(
            f"已在 {len(result.horizons)} 个视界上计算多项指标（多重比较）："
            f"只有主视界 {result.hold_days} 交易日可当确认性结论，{others} 交易日的差异应视为探索性"
        )
    no_data = [h.hold_days for h in result.horizons if not h.has_data()]
    if no_data:
        result.warnings.append(
            f"视界 {', '.join(str(h) for h in no_data)} 交易日无独立数据（记录里没有该视界的收益），未计算统计量"
        )

    # 梯度与校准的反向信号：宁可自己先说出来
    if result.rank_ic is not None and result.rank_ic <= 0:
        result.warnings.append(
            f"评级梯度与超额收益的排序相关 rank IC = {result.rank_ic:+.2f}（<=0，n={result.rank_ic_n}）："
            "本样本上「评级越高越跑赢基准」不成立"
        )
    if result.confidence_spread is not None and result.confidence_spread < 0:
        result.warnings.append(
            f"置信度校准为负（High 命中率比 Low 低 {abs(result.confidence_spread):.1%}）："
            "confidence 字段在本样本上不是有效信号"
        )
    if result.bullish_excess_hit_rate is not None and result.bullish_excess_hit_rate < _RANDOM_BENCHMARK:
        result.warnings.append(
            f"看涨样本的超额命中率 {result.bullish_excess_hit_rate:.1%} 低于随机水平 50%："
            "在这些样本上，看涨评级并不比随机选基更能跑赢基准"
        )

    partial = [r for r in result.records if r.horizon_errors]
    if partial:
        result.warnings.append(
            f"{len(partial)} 条记录的部分视界取数失败：这些视界的统计量只覆盖有数据的记录，"
            "各视界样本数见多视界对比表"
        )

    for r in skipped:
        if r.fetch_error:
            result.warnings.append(f"{r.fund_code} 在 {r.analysis_date} 的收益获取失败：{r.fetch_error}")

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


def benchmark_return(code: str, date: str, horizon: int) -> float | None:
    """基准在「date 之后 horizon 个交易日」的收益率；失败返回 None（不抛）。

    抽成模块级函数是为了让结算脚本（ifa.backtest.settlement）与验证器共用同一套
    基准口径 —— 两处各写一遍迟早会算出不同的超额收益。
    """
    try:
        bt = run_backtest(code, date, add_trading_days(date, horizon))
    except Exception as exc:
        logger.warning("基准收益获取失败 (%s %s +%d): %s", code, date, horizon, exc)
        return None
    return None if bt.error else bt.total_return_pct


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
    horizons: Sequence[int] | None = None,
    fund_names: dict[str, str] | None = None,
    benchmark_overrides: dict[str, str] | None = None,
) -> RatingValidationResult:
    """跑「评级 vs 实际收益」回测验证。

    三阶段流程：
      Phase 1 - 跑历史分析，收集 (fund, date, rating, confidence) 四元组
      Phase 2 - 对每条记录、每个视界各取一次实际收益，并对比「该基金自己的跟踪指数」
      Phase 3 - compute_statistics 统计（多视界 / 超额 / 评级梯度 / 置信度校准）

    参数:
        fund_codes: 基金代码列表（建议 ETF/指数基金）
        analysis_dates: 分析日期列表 YYYY-MM-DD
        hold_days: 主视界（交易日，默认 60）；扁平字段取该视界
        advisor: 可选复用的 AdvisorGraph 实例（批量省初始化）。None 则内部新建。
        on_progress: 进度回调 (phase, i, total, code, date, status) -> None
        update_memory: 显式开关。默认 False（不接反思系统）。
                       设 True 时把结果喂回 reflect_and_remember —— 注意幸存者偏差风险。
        horizons: 要统计的全部视界；None → (20, 60, 120) 并保证含 hold_days。
        fund_names: 代码 → 基金名称，用于识别跟踪指数；None 时自动查一次每日快照。
        benchmark_overrides: 代码 → 基准（"000905" 或 "000905:中证500"），优先级最高。

    返回:
        RatingValidationResult
    """
    # 延迟导入，避免顶层循环依赖
    from ifa.common import build_advisor, build_state

    own_advisor = False
    if advisor is None:
        advisor = build_advisor()
        own_advisor = True

    stat_horizons = ordered_horizons(horizons, hold_days)
    names = dict(fund_names) if fund_names else _lookup_fund_names(fund_codes)

    # 基准按 (code, date, horizon) 记忆化：同一个基准会被多只基金反复用到，
    # 失败也缓存，避免对同一个取不到数的基准重复重试。
    bench_cache: dict[tuple[str, str, int], float | None] = {}

    def _benchmark_return(code: str, date: str, horizon: int) -> float | None:
        key = (code, date, horizon)
        if key not in bench_cache:
            bench_cache[key] = benchmark_return(code, date, horizon)
        return bench_cache[key]

    total_tasks = len(fund_codes) * len(analysis_dates)
    records: list[RatingRecord] = []
    idx = 0

    try:
        # ── Phase 1 + 2 合并：每只基金每个日期，先跑分析拿评级，立刻逐视界取收益 ──
        for code in fund_codes:
            spec = resolve_benchmark(code, names.get(code), overrides=benchmark_overrides)
            for date in analysis_dates:
                idx += 1
                status = "running"

                # —— Phase 1: 跑历史分析拿评级 ——
                record = RatingRecord(
                    fund_code=code,
                    analysis_date=date,
                    rating="",
                    confidence="",
                    benchmark_code=spec.code,
                    benchmark_label=spec.label,
                    benchmark_source=spec.source,
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

                # —— Phase 2: 逐视界取实际收益（复用 run_backtest）——
                primary_hold: int | None = None
                failed_horizons = 0
                for horizon in stat_horizons:
                    end_date = add_trading_days(date, horizon)
                    try:
                        bt = run_backtest(code, date, end_date)
                        if bt.error:
                            record.horizon_errors[horizon] = f"收益数据: {bt.error[:80]}"
                            failed_horizons += 1
                            continue

                        forward = bt.total_return_pct
                        record.returns_by_horizon[horizon] = forward
                        if horizon == hold_days:
                            primary_hold = bt.trading_days

                        bench_return = _benchmark_return(spec.code, date, horizon)
                        if bench_return is not None:
                            record.benchmark_by_horizon[horizon] = bench_return
                            record.excess_by_horizon[horizon] = forward - bench_return
                    except Exception as e:
                        record.horizon_errors[horizon] = f"收益获取异常: {e!s:.80s}"
                        failed_horizons += 1

                # 主视界回填扁平字段（保持既有字段语义：价格口径、主视界）
                if hold_days in record.returns_by_horizon:
                    record.forward_return_pct = record.returns_by_horizon[hold_days]
                    record.hold_days = primary_hold or 0
                if hold_days in record.benchmark_by_horizon:
                    record.benchmark_return_pct = record.benchmark_by_horizon[hold_days]
                if hold_days in record.excess_by_horizon:
                    record.excess_return_pct = record.excess_by_horizon[hold_days]

                # 全部视界都失败 → 这条记录没有可用收益，算 fetch_error；
                # 只有部分失败 → 保留可用视界，失败原因留在 horizon_errors 里（报告会汇总）。
                if not record.returns_by_horizon:
                    first_error = next(iter(record.horizon_errors.values()), "收益数据缺失")
                    record.fetch_error = first_error
                    status = "return_failed"
                elif failed_horizons:
                    status = "partial"

                if on_progress and status in ("return_failed", "return_error", "partial"):
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
    return compute_statistics(records, hold_days, horizons=stat_horizons)


def _lookup_fund_names(fund_codes: list[str]) -> dict[str, str]:
    """查一次每日快照拿基金名称，用于识别跟踪指数。

    失败（网络/接口异常）返回空 dict —— 名称只影响基准选择，
    不能让一次取数失败把整批验证带崩；基准会退回沪深300 并在报告里标注。
    """
    try:
        from ifa.dataflows.a_share_public_fund import fetch_fund_daily_snapshots

        snapshots = fetch_fund_daily_snapshots(list(fund_codes))
    except Exception as e:
        logger.warning("基金名称查询失败，基准将退回默认值: %s", e)
        return {}
    return {code: str(data["name"]) for code, data in snapshots.items() if data.get("name")}


def lookup_fund_names(fund_codes: list[str]) -> dict[str, str]:
    """`_lookup_fund_names` 的公开入口（结算脚本等复用，避免直接依赖私有函数）。"""
    return _lookup_fund_names(fund_codes)

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

口径提醒（读数字前请先读这三条）：
1. 「绝对命中率」= 基金本身涨/跌的比例，主要反映 beta（大盘涨跌），不等于选基能力；
   真正可证伪的是「超额命中率」= 跑赢自己跟踪指数的比例。
2. 同时在多个视界上计算多项指标属于多重比较：只有主视界可当确认性结论，
   其它视界的差异应视为探索性，不要挑最好看的那个汇报。
3. 基准逐基金解析，回退到沪深300 的记录会单独列出 —— 这些记录的「超额」
   不代表跑赢了自己的跟踪指数。
"""


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    """百分比格式化；None 显示为破折号（缺失必须看得见，不能当 0）。"""
    return "—" if value is None else f"{value:+.{digits}f}%"


def _fmt_ratio(value: float | None) -> str:
    """比例（0~1）格式化为百分数；None 显示为破折号。"""
    return "—" if value is None else f"{value:.2%}"


def _fmt_ci(low: float | None, high: float | None) -> str:
    """置信区间格式化；任一端缺失都显示为破折号。"""
    if low is None or high is None:
        return "—"
    return f"[{low:.2%}, {high:.2%}]"


def _render_horizon_table(result: RatingValidationResult) -> list[str]:
    """多视界对比表：同一批记录在不同持有期上的表现。"""
    if not result.horizons:
        return []
    lines = ["## 多视界对比（同一批记录，不同持有期）\n"]
    lines.append("| 视界(交易日) | 有效样本 | 看涨 n | 绝对命中率 | 超额命中率 | 平均超额 | 中位数超额 | rank IC | 单调性 |")
    lines.append("|-------------|---------|-------|-----------|-----------|---------|-----------|---------|--------|")
    for h in result.horizons:
        if not h.has_data():
            lines.append(f"| {h.hold_days} | 0 | 0 | — | — | — | — | — | — |")
            continue
        ic = "—" if h.rank_ic is None else f"{h.rank_ic:+.2f} (n={h.rank_ic_n})"
        mono = "—" if h.monotonicity is None else f"{h.monotonicity:+.2f}"
        lines.append(
            f"| {h.hold_days} | {h.valid} | {h.bullish_n} | {_fmt_ratio(h.bullish_hit_rate)} | "
            f"{_fmt_ratio(h.bullish_excess_hit_rate)} | {_fmt_pct(h.mean_excess_pct)} | "
            f"{_fmt_pct(h.median_excess_pct)} | {ic} | {mono} |"
        )
    lines.append("")
    return lines


def _render_bucket_table(result: RatingValidationResult) -> list[str]:
    """评级分档表：评级越高，平均超额是否真的越高。"""
    if not result.buckets:
        return []
    lines = ["## 评级分档（主视界）\n"]
    lines.append("| 评级 | 样本数 | 平均收益 | 平均超额 | 中位数超额 | 超额>0 比例 |")
    lines.append("|------|--------|---------|---------|-----------|------------|")
    for b in result.buckets:
        lines.append(
            f"| {b.label} | {b.n} | {_fmt_pct(b.mean_forward_pct)} | {_fmt_pct(b.mean_excess_pct)} | "
            f"{_fmt_pct(b.median_excess_pct)} | {_fmt_ratio(b.excess_up_rate)} |"
        )
    lines.append("")
    if result.monotonicity is not None:
        lines.append(
            f"**单调性（评级分数 vs 分档平均超额的 Spearman）**: {result.monotonicity:+.2f}"
            f"（n={result.monotonicity_n} 档）  "
        )
        lines.append("_接近 +1 表示评级梯度与超额收益同向；接近 0 或为负表示评级没有区分度_\n")
    return lines


def _render_confidence_table(result: RatingValidationResult) -> list[str]:
    """置信度校准表：High 是否真的比 Low 更准。"""
    if not result.confidence_calibration:
        return []
    lines = ["## 置信度校准（主视界）\n"]
    lines.append("| 置信度 | 样本数 | 有方向 n | 平均超额 | 平均|超额| | 超额>0 比例 | 方向命中率 |")
    lines.append("|--------|--------|---------|---------|-----------|------------|-----------|")
    for c in result.confidence_calibration:
        lines.append(
            f"| {c.label} | {c.n} | {c.directional_n} | {_fmt_pct(c.mean_excess_pct)} | "
            f"{_fmt_pct(c.mean_abs_excess_pct)} | {_fmt_ratio(c.excess_up_rate)} | "
            f"{_fmt_ratio(c.absolute_hit_rate)} |"
        )
    lines.append("")
    if result.confidence_spread is not None:
        lines.append(f"**置信度区分度（High 命中率 − Low 命中率）**: {result.confidence_spread:+.2%}  ")
        lines.append("_为负说明「高置信」反而更不准，此时 confidence 字段不应被当作信号_\n")
    return lines


def _render_benchmark_section(result: RatingValidationResult) -> list[str]:
    """基准使用说明：每条记录比的是哪个指数、有多少条是回退值。"""
    lines = ["## 基准使用说明\n"]
    if result.benchmark_labels:
        lines.append("本批记录用到的基准：" + "、".join(result.benchmark_labels) + "  ")
    else:
        lines.append("本批记录未标注基准（历史记录或未走基准解析）。  ")
    if result.benchmark_fallback_n:
        lines.append(
            f"⚠️ {result.benchmark_fallback_n}/{result.total} 条记录回退到默认基准（沪深300）："
            "这些记录的「超额」不代表跑赢了自己的跟踪指数。  "
        )
    lines.append("")
    return lines


def format_validation_report(result: RatingValidationResult) -> str:
    """把 RatingValidationResult 格式化为 Markdown 报告。"""
    lines = [f"{_DISCLAIMER}\n---\n", "# 评级验证报告\n"]

    # 概览
    lines.append(f"**样本**: {result.total} 条记录（有效 {result.valid}，跳过 {result.skipped}）  ")
    lines.append(f"**持有周期（主视界）**: {result.hold_days} 个交易日  ")
    if result.horizons:
        lines.append(f"**统计视界**: {' / '.join(str(h.hold_days) for h in result.horizons)} 个交易日  ")
    if result.period_start:
        lines.append(f"**分析日期范围**: {result.period_start} ~ {result.period_end}\n")
    else:
        lines.append("")

    # 命中率（绝对口径，主视界）
    lines.append(f"## 命中率统计（主视界 {result.hold_days} 交易日，绝对口径）\n")
    lines.append("| 方向 | 样本数 | 命中率 | 95% 置信区间 |")
    lines.append("|------|--------|--------|-------------|")
    if result.bullish_hit_rate is not None:
        ci = _fmt_ci(result.bullish_ci_low, result.bullish_ci_high)
        lines.append(f"| 看涨（BUY/STRONG_BUY） | {result.bullish_n} | {result.bullish_hit_rate:.2%} | {ci} |")
    else:
        lines.append("| 看涨（BUY/STRONG_BUY） | 0 | — | — |")
    if result.bearish_hit_rate is not None:
        ci = _fmt_ci(result.bearish_ci_low, result.bearish_ci_high)
        lines.append(f"| 看跌（UNDERWEIGHT/SELL） | {result.bearish_n} | {result.bearish_hit_rate:.2%} | {ci} |")
    else:
        lines.append("| 看跌（UNDERWEIGHT/SELL） | 0 | — | — |")
    lines.append("")
    lines.append("_绝对口径 = 基金本身涨/跌，主要反映 beta；剔除基准后的口径见下表。_\n")

    # 超额口径（主视界）
    lines.append(f"## 超额命中率（主视界 {result.hold_days} 交易日，剔除基准）\n")
    lines.append("| 方向 | 样本数 | 超额命中率 | 95% 置信区间 | 平均超额 | 中位数超额 |")
    lines.append("|------|--------|-----------|-------------|---------|-----------|")
    if result.bullish_excess_hit_rate is not None:
        lines.append(
            f"| 看涨（超额>0） | {result.bullish_n} | {result.bullish_excess_hit_rate:.2%} | "
            f"{_fmt_ci(result.bullish_excess_ci_low, result.bullish_excess_ci_high)} | "
            f"{_fmt_pct(result.mean_excess_pct)} | {_fmt_pct(result.median_excess_pct)} |"
        )
    else:
        lines.append("| 看涨（超额>0） | 0 | — | — | — | — |")
    if result.bearish_excess_hit_rate is not None:
        lines.append(
            f"| 看跌（超额<0） | {result.bearish_n} | {result.bearish_excess_hit_rate:.2%} | "
            f"{_fmt_ci(result.bearish_excess_ci_low, result.bearish_excess_ci_high)} | — | — |"
        )
    else:
        lines.append("| 看跌（超额<0） | 0 | — | — | — | — |")
    if result.hold_n:
        lines.append(f"| HOLD（不表态） | {result.hold_n} | — | — | {_fmt_pct(result.hold_mean_excess_pct)} | — |")
    lines.append("")
    if result.excess_t is not None and result.excess_p is not None:
        lines.append(
            f"**超额收益均值 t 检验**: t = {result.excess_t:+.2f}，p ≈ {result.excess_p:.3f}"
            f"（n = {result.excess_n}，正态近似）  "
        )
        lines.append("_p < 0.05 才谈得上「平均超额显著不为 0」；样本 < 30 时请直接忽略 p 值_\n")

    # 基准对比
    lines.append("## 基准对比\n")
    lines.append("| 基准 | 期望/实际 | 说明 |")
    lines.append("|------|----------|------|")
    lines.append("| 随机基准 | 50.00% | 抛硬币 |")
    if result.benchmark_up_rate is not None:
        lines.append(f"| 同期基准上涨比例 | {result.benchmark_up_rate:.2%} | 逐基金跟踪指数，见「基准使用说明」 |")
    lines.append("")
    if result.alpha_vs_random is not None:
        lines.append(f"**Alpha（vs 随机）**: {result.alpha_vs_random:+.2%}  ")
        lines.append("_正值=比抛硬币好，但需结合置信区间判断是否显著_\n")
    if result.alpha_vs_csi300 is not None:
        lines.append(f"**Alpha（vs 同期基准）**: {result.alpha_vs_csi300:+.2%}  ")
        lines.append("_正值=评级选基跑赢了被动持有同期基准；回退基准的记录不在此列_\n")

    # 多视界 / 分档 / 校准 / 基准说明
    lines.extend(_render_horizon_table(result))
    lines.extend(_render_bucket_table(result))
    lines.extend(_render_confidence_table(result))
    lines.extend(_render_benchmark_section(result))

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
    lines.append("| 基金 | 分析日期 | 评级 | 置信度 | 基准 | 实际收益 | 基准收益 | 超额 |")
    lines.append("|------|---------|------|--------|------|---------|---------|------|")
    for r in result.records:
        fwd = f"{r.forward_return_pct:+.2f}%" if r.forward_return_pct is not None else "—"
        bench = f"{r.benchmark_return_pct:+.2f}%" if r.benchmark_return_pct is not None else "—"
        excess = f"{r.excess_return_pct:+.2f}%" if r.excess_return_pct is not None else "—"
        bench_label = f"{r.benchmark_label}({r.benchmark_code})" if r.benchmark_label else "—"
        err = f" ⚠️{r.fetch_error[:30]}" if r.fetch_error else ""
        lines.append(
            f"| {r.fund_code} | {r.analysis_date} | {r.rating} | {r.confidence} | {bench_label} | "
            f"{fwd} | {bench} | {excess} |{err}"
        )

    return "\n".join(lines)
