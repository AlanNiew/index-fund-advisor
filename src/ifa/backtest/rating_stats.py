# ifa/backtest/rating_stats.py
"""评级验证的统计层：多视界、超额收益、分档、排序相关、置信度校准。

这一层只做纯计算（无网络、无 LLM、无副作用），便于独立测试与复核。

为什么需要它（原实现只回答了一个很弱的问题）：
  1. 原来只统计「看涨评级后基金是否上涨」——A 股宽基在样本期整体涨跌就能决定这个数字，
     衡量的是 beta 而不是「评级有没有选基能力」。这里补上超额收益口径：
     看涨评级后是否跑赢基准，才是评级真正的可证伪声明。
  2. 原来只测一个持有周期（60 交易日）。单一视界的显著结果极可能是数据挖掘产物，
     这里同时给出 20/60/120 三个视界，让「稳健」有可检验的含义。
  3. 原来只做 2x2 命中率。命中率对「评级梯度」完全不敏感——5 档评级若只有 2 档有信号，
     2x2 会把它和「单调有效」混为一谈。这里加 Spearman 排序相关（rank IC）、
     分档平均超额、分档单调性，直接检验梯度是否成立。
  4. 原来把 confidence 字段逐条打印却从不校准。这里按 High/Medium/Low 分档，
     检验「高置信度是否真的更准」——如果不成立，该字段就是噪声，必须说出来。

智识诚实约束（写进实现而非注释）：
  - 样本不足时返回 None，绝不用小样本编出一个数字；
  - 检验统计量用正态近似而非 t 分布（本仓库不依赖 scipy），报告里显式标注；
  - 多视界 x 多指标 = 多重比较，只有预先指定的主视界可当确认性结论（报告里警告）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

# ── 常量 ──────────────────────────────────────────────────────────────

RATING_ORDER: tuple[str, ...] = ("STRONG_BUY", "BUY", "HOLD", "UNDERWEIGHT", "SELL")

# 评级 → 分数（用于 rank IC / 单调性）。等距取值，含义是「相对看多程度」。
RATING_SCORES: dict[str, float] = {
    "STRONG_BUY": 2.0,
    "BUY": 1.0,
    "HOLD": 0.0,
    "UNDERWEIGHT": -1.0,
    "SELL": -2.0,
}

CONFIDENCE_ORDER: tuple[str, ...] = ("High", "Medium", "Low")

_BULLISH_RATINGS = frozenset({"STRONG_BUY", "BUY"})
_BEARISH_RATINGS = frozenset({"UNDERWEIGHT", "SELL"})

# 默认多视界（交易日）：约 1 个月 / 3 个月 / 6 个月。
DEFAULT_HORIZONS: tuple[int, ...] = (20, 60, 120)

_MIN_IC_SAMPLE = 8  # 排序相关至少 8 条，否则一个离群点就能翻转符号
_MIN_T_SAMPLE = 2  # 单样本 t 检验至少要 2 条（n=1 时标准差无定义）
_MIN_MONOTONIC_BUCKETS = 3  # 少于 3 档谈不上「单调」


def classify(rating: str) -> str:
    """把 5 档评级归为 bullish / bearish / neutral。"""
    if rating in _BULLISH_RATINGS:
        return "bullish"
    if rating in _BEARISH_RATINGS:
        return "bearish"
    return "neutral"


# ── 基础统计 ──────────────────────────────────────────────────────────


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


def mean(values: Sequence[float]) -> float | None:
    """算术平均；空序列返回 None（不用 0 冒充「没有数据」）。"""
    if not values:
        return None
    return sum(values) / len(values)


def median(values: Sequence[float]) -> float | None:
    """中位数。收益率分布有厚尾，均值容易被单个离群点主导，所以两者都给。"""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def sample_stdev(values: Sequence[float]) -> float | None:
    """样本标准差（n-1）；n<2 返回 None。"""
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _normal_cdf(z: float) -> float:
    """标准正态分布 CDF（用 math.erf，无需 scipy）。"""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def one_sample_t(values: Sequence[float]) -> tuple[float | None, float | None, int]:
    """单样本 t 检验（检验均值是否显著异于 0），返回 (t, 双侧 p, n)。

    p 值用**正态近似**而非 t 分布：本仓库不依赖 scipy，而 t 分布在 n<30 时更厚尾。
    因此这里的 p 偏乐观，报告里必须显式标注「正态近似」并同时给出 n。
    样本量不足或方差为 0（退化样本，t 会变成无穷）时返回 (None, None, n)。
    """
    n = len(values)
    if n < _MIN_T_SAMPLE:
        return None, None, n
    m = sum(values) / n
    sd = sample_stdev(values)
    if sd is None or sd == 0:
        return None, None, n
    t = m / (sd / math.sqrt(n))
    p = 2 * (1 - _normal_cdf(abs(t)))
    return t, min(1.0, max(0.0, p)), n


def _average_ranks(values: Sequence[float]) -> list[float]:
    """平均秩（并列取平均），Spearman 必须做并列修正，否则同分评级会造出假相关。"""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman 秩相关；n<3 或任一序列无变异时返回 None。"""
    n = len(xs)
    if n != len(ys) or n < 3:
        return None
    rx = _average_ranks(xs)
    ry = _average_ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def ic_t_stat(ic: float | None, n: int) -> float | None:
    """相关系数的 t 统计量 t = r*sqrt((n-2)/(1-r^2))（用于粗略判断是否异于 0）。"""
    if ic is None or n < 3 or abs(ic) >= 1:
        return None
    return ic * math.sqrt((n - 2) / (1 - ic * ic))


# ── 数据模型 ──────────────────────────────────────────────────────────


class RecordLike(Protocol):
    """评级记录的最小结构契约（rating_validator.RatingRecord 结构上满足它）。"""

    rating: str
    confidence: str
    hold_days: int
    fetch_error: str
    forward_return_pct: float | None
    benchmark_return_pct: float | None
    excess_return_pct: float | None
    returns_by_horizon: dict[int, float]
    benchmark_by_horizon: dict[int, float]
    excess_by_horizon: dict[int, float]


@dataclass
class BucketStats:
    """单档评级在一个视界上的表现。"""

    label: str
    n: int
    mean_forward_pct: float | None = None
    mean_excess_pct: float | None = None
    median_excess_pct: float | None = None
    excess_up_rate: float | None = None  # 跑赢基准的比例（无方向性）
    excess_hit_rate: float | None = None  # 方向命中率（HOLD 无方向声明 → None）
    excess_ci_low: float | None = None
    excess_ci_high: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "n": self.n,
            "mean_forward_pct": self.mean_forward_pct,
            "mean_excess_pct": self.mean_excess_pct,
            "median_excess_pct": self.median_excess_pct,
            "excess_up_rate": self.excess_up_rate,
            "excess_hit_rate": self.excess_hit_rate,
            "excess_ci_95": [self.excess_ci_low, self.excess_ci_high],
        }


@dataclass
class ConfidenceStats:
    """单档置信度在一个视界上的校准表现。"""

    label: str
    n: int
    directional_n: int = 0  # 有方向声明的子集大小（HOLD 不参与方向命中率）
    mean_excess_pct: float | None = None
    mean_abs_excess_pct: float | None = None  # 信念强度：高置信度应当伴随更大的绝对偏离
    excess_up_rate: float | None = None
    absolute_hit_rate: float | None = None  # 方向命中率（基于绝对涨跌）

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "n": self.n,
            "directional_n": self.directional_n,
            "mean_excess_pct": self.mean_excess_pct,
            "mean_abs_excess_pct": self.mean_abs_excess_pct,
            "excess_up_rate": self.excess_up_rate,
            "absolute_hit_rate": self.absolute_hit_rate,
        }


@dataclass
class HorizonStats:
    """单个持有视界上的全部统计量。"""

    hold_days: int
    valid: int = 0
    bullish_n: int = 0
    bearish_n: int = 0

    # 绝对口径（原来就有的口径：基金自己涨没涨）
    bullish_hit_rate: float | None = None
    bearish_hit_rate: float | None = None
    bullish_ci_low: float | None = None
    bullish_ci_high: float | None = None
    bearish_ci_low: float | None = None
    bearish_ci_high: float | None = None

    # 超额口径（评级真正的可证伪声明：跑赢基准没有）
    bullish_excess_hit_rate: float | None = None
    bearish_excess_hit_rate: float | None = None
    bullish_excess_ci_low: float | None = None
    bullish_excess_ci_high: float | None = None
    bearish_excess_ci_low: float | None = None
    bearish_excess_ci_high: float | None = None

    # 收益分布（均值易被离群点主导，故同时给中位数）
    mean_forward_pct: float | None = None
    median_forward_pct: float | None = None
    mean_excess_pct: float | None = None
    median_excess_pct: float | None = None

    # 超额均值的单样本 t 检验（p 为正态近似）
    excess_t: float | None = None
    excess_p: float | None = None
    excess_n: int = 0

    # 排序相关：评级分数 vs 超额收益
    rank_ic: float | None = None
    rank_ic_n: int = 0
    rank_ic_t: float | None = None

    # 基准
    benchmark_up_rate: float | None = None
    alpha_vs_benchmark: float | None = None

    # HOLD 档（检验「不表态」是否真的接近零超额）
    hold_n: int = 0
    hold_mean_excess_pct: float | None = None

    # 分档与单调性
    buckets: list[BucketStats] = field(default_factory=list)
    monotonicity: float | None = None
    monotonicity_n: int = 0

    # 置信度校准
    confidence: list[ConfidenceStats] = field(default_factory=list)
    confidence_spread: float | None = None  # High 方向命中率 - Low 方向命中率

    def has_data(self) -> bool:
        """该视界是否有独立数据（多视界回填失败时用来区分「无信号」与「没数据」）。"""
        return self.valid > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "hold_days": self.hold_days,
            "valid": self.valid,
            "bullish_n": self.bullish_n,
            "bearish_n": self.bearish_n,
            "bullish_hit_rate": self.bullish_hit_rate,
            "bearish_hit_rate": self.bearish_hit_rate,
            "bullish_ci_95": [self.bullish_ci_low, self.bullish_ci_high],
            "bearish_ci_95": [self.bearish_ci_low, self.bearish_ci_high],
            "bullish_excess_hit_rate": self.bullish_excess_hit_rate,
            "bearish_excess_hit_rate": self.bearish_excess_hit_rate,
            "bullish_excess_ci_95": [self.bullish_excess_ci_low, self.bullish_excess_ci_high],
            "bearish_excess_ci_95": [self.bearish_excess_ci_low, self.bearish_excess_ci_high],
            "mean_forward_pct": self.mean_forward_pct,
            "median_forward_pct": self.median_forward_pct,
            "mean_excess_pct": self.mean_excess_pct,
            "median_excess_pct": self.median_excess_pct,
            "excess_t": self.excess_t,
            "excess_p_normal_approx": self.excess_p,
            "excess_n": self.excess_n,
            "rank_ic": self.rank_ic,
            "rank_ic_n": self.rank_ic_n,
            "rank_ic_t": self.rank_ic_t,
            "benchmark_up_rate": self.benchmark_up_rate,
            "alpha_vs_benchmark": self.alpha_vs_benchmark,
            "hold_n": self.hold_n,
            "hold_mean_excess_pct": self.hold_mean_excess_pct,
            "monotonicity": self.monotonicity,
            "monotonicity_n": self.monotonicity_n,
            "confidence_spread": self.confidence_spread,
            "buckets": [b.to_dict() for b in self.buckets],
            "confidence": [c.to_dict() for c in self.confidence],
        }


def horizon_returns(
    record: RecordLike, horizon: int, primary_hold_days: int
) -> tuple[float | None, float | None, float | None]:
    """取某视界上的 (基金收益, 基准收益, 超额收益)。

    多视界记录把每个视界的值存进 *_by_horizon；单视界/历史记录只有扁平字段，
    且**只在「请求的视界 == 主视界」时才回退到扁平字段**。
    这条规则是本模块存在的理由：否则会把 60 日收益当成 120 日收益汇报，
    那正是「单一视界冒充多视界」的口径混淆。
    """
    if horizon in record.returns_by_horizon:
        fwd = record.returns_by_horizon.get(horizon)
        bench = record.benchmark_by_horizon.get(horizon)
        excess = record.excess_by_horizon.get(horizon)
        if excess is None and fwd is not None and bench is not None:
            excess = fwd - bench
        return fwd, bench, excess
    if horizon == primary_hold_days:
        return record.forward_return_pct, record.benchmark_return_pct, record.excess_return_pct
    return None, None, None


# ── 主计算入口 ────────────────────────────────────────────────────────


def ordered_horizons(horizons: Sequence[int] | None, primary_hold_days: int) -> tuple[int, ...]:
    """规整视界列表：去重、去非正数、升序，并保证主视界在内。"""
    values = {int(h) for h in (horizons if horizons is not None else DEFAULT_HORIZONS) if int(h) > 0}
    values.add(int(primary_hold_days))
    return tuple(sorted(values))


def compute_horizon_stats(
    records: Sequence[RecordLike], hold_days: int, *, primary_hold_days: int
) -> HorizonStats:
    """计算单个持有视界上的全部统计量（纯计算，无副作用）。

    参数:
        records: 评级记录列表
        hold_days: 本次要统计的视界（交易日）
        primary_hold_days: 主视界。只有等于它时，才允许回退到记录上的扁平字段
            （见 horizon_returns 的说明）
    """
    stats = HorizonStats(hold_days=hold_days)

    valid: list[tuple[RecordLike, float, float | None, float | None]] = []
    for record in records:
        if record.fetch_error:
            continue
        fwd, bench, excess = horizon_returns(record, hold_days, primary_hold_days)
        if fwd is None:
            continue
        valid.append((record, fwd, bench, excess))
    stats.valid = len(valid)
    if not valid:
        return stats

    bullish = [row for row in valid if classify(row[0].rating) == "bullish"]
    bearish = [row for row in valid if classify(row[0].rating) == "bearish"]
    holds = [row for row in valid if classify(row[0].rating) == "neutral"]
    stats.bullish_n = len(bullish)
    stats.bearish_n = len(bearish)
    stats.hold_n = len(holds)

    # —— 绝对口径（基金自己涨没涨）——
    if bullish:
        hits = sum(1 for _, f, _, _ in bullish if f > 0)
        stats.bullish_hit_rate = hits / len(bullish)
        stats.bullish_ci_low, stats.bullish_ci_high = wilson_ci(hits, len(bullish))
    if bearish:
        hits = sum(1 for _, f, _, _ in bearish if f < 0)
        stats.bearish_hit_rate = hits / len(bearish)
        stats.bearish_ci_low, stats.bearish_ci_high = wilson_ci(hits, len(bearish))

    # —— 超额口径（跑赢基准没有）—— 只有取到基准的记录参与
    bull_ex = [e for _, _, _, e in bullish if e is not None]
    bear_ex = [e for _, _, _, e in bearish if e is not None]
    if bull_ex:
        hits = sum(1 for e in bull_ex if e > 0)
        stats.bullish_excess_hit_rate = hits / len(bull_ex)
        stats.bullish_excess_ci_low, stats.bullish_excess_ci_high = wilson_ci(hits, len(bull_ex))
    if bear_ex:
        hits = sum(1 for e in bear_ex if e < 0)
        stats.bearish_excess_hit_rate = hits / len(bear_ex)
        stats.bearish_excess_ci_low, stats.bearish_excess_ci_high = wilson_ci(hits, len(bear_ex))

    # —— 收益分布 ——
    forwards = [f for _, f, _, _ in valid]
    excesses = [e for _, _, _, e in valid if e is not None]
    stats.mean_forward_pct = mean(forwards)
    stats.median_forward_pct = median(forwards)
    stats.mean_excess_pct = mean(excesses)
    stats.median_excess_pct = median(excesses)
    stats.excess_t, stats.excess_p, stats.excess_n = one_sample_t(excesses)

    # —— 基准 ——
    benches = [b for _, _, b, _ in valid if b is not None]
    if benches:
        stats.benchmark_up_rate = sum(1 for b in benches if b > 0) / len(benches)
        if stats.bullish_hit_rate is not None:
            stats.alpha_vs_benchmark = stats.bullish_hit_rate - stats.benchmark_up_rate

    # —— HOLD 档：不表态是否真的接近零超额 ——
    stats.hold_mean_excess_pct = mean([e for _, _, _, e in holds if e is not None])

    # —— rank IC：评级分数 vs 超额收益 ——
    ic_pairs = [
        (RATING_SCORES[row[0].rating], row[3])
        for row in valid
        if row[0].rating in RATING_SCORES and row[3] is not None
    ]
    if len(ic_pairs) >= _MIN_IC_SAMPLE:
        stats.rank_ic = spearman([p[0] for p in ic_pairs], [p[1] for p in ic_pairs])
        stats.rank_ic_n = len(ic_pairs)
        stats.rank_ic_t = ic_t_stat(stats.rank_ic, stats.rank_ic_n)

    # —— 分档 ——
    buckets: list[BucketStats] = []
    for label in RATING_ORDER:
        rows = [row for row in valid if row[0].rating == label]
        if not rows:
            continue
        bucket = BucketStats(label=label, n=len(rows))
        bucket.mean_forward_pct = mean([f for _, f, _, _ in rows])
        row_excess = [e for _, _, _, e in rows if e is not None]
        bucket.mean_excess_pct = mean(row_excess)
        bucket.median_excess_pct = median(row_excess)
        if row_excess:
            bucket.excess_up_rate = sum(1 for e in row_excess if e > 0) / len(row_excess)
        direction = classify(label)
        if row_excess and direction != "neutral":
            hits = sum(1 for e in row_excess if (e > 0 if direction == "bullish" else e < 0))
            bucket.excess_hit_rate = hits / len(row_excess)
            bucket.excess_ci_low, bucket.excess_ci_high = wilson_ci(hits, len(row_excess))
        buckets.append(bucket)
    stats.buckets = buckets

    # —— 单调性：评级分数 vs 分档平均超额（HOLD 档参与，因为它就该在中间）——
    monotonic_pairs = [
        (RATING_SCORES[b.label], b.mean_excess_pct) for b in buckets if b.mean_excess_pct is not None
    ]
    if len(monotonic_pairs) >= _MIN_MONOTONIC_BUCKETS:
        stats.monotonicity = spearman([p[0] for p in monotonic_pairs], [p[1] for p in monotonic_pairs])
        stats.monotonicity_n = len(monotonic_pairs)

    # —— 置信度校准 ——
    confidence_stats: list[ConfidenceStats] = []
    for label in CONFIDENCE_ORDER:
        rows = [row for row in valid if row[0].confidence == label]
        if not rows:
            continue
        cs = ConfidenceStats(label=label, n=len(rows))
        row_excess = [e for _, _, _, e in rows if e is not None]
        cs.mean_excess_pct = mean(row_excess)
        cs.mean_abs_excess_pct = mean([abs(e) for e in row_excess])
        if row_excess:
            cs.excess_up_rate = sum(1 for e in row_excess if e > 0) / len(row_excess)
        hits = 0
        directional_n = 0
        for record, fwd, _, _ in rows:
            direction = classify(record.rating)
            if direction == "neutral":
                continue
            directional_n += 1
            if (fwd > 0) if direction == "bullish" else (fwd < 0):
                hits += 1
        cs.directional_n = directional_n
        if directional_n:
            cs.absolute_hit_rate = hits / directional_n
        confidence_stats.append(cs)
    stats.confidence = confidence_stats

    high = next((c for c in confidence_stats if c.label == "High"), None)
    low = next((c for c in confidence_stats if c.label == "Low"), None)
    if high and low and high.absolute_hit_rate is not None and low.absolute_hit_rate is not None:
        stats.confidence_spread = high.absolute_hit_rate - low.absolute_hit_rate

    return stats
