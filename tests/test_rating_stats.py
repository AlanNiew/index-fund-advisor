# tests/test_rating_stats.py
"""评级验证统计层测试 —— 纯计算，不碰网络/LLM。

覆盖四类「口径错误」的防线：
  1. 绝对命中率 vs 超额命中率（前者主要反映 beta）；
  2. 多视界隔离（60 日收益不许冒充 120 日）；
  3. 评级梯度（rank IC / 分档 / 单调性）而非只看 2x2 命中率；
  4. 置信度校准（High 是否真的比 Low 准）。
"""

from __future__ import annotations

import pytest

from ifa.backtest.rating_stats import (
    DEFAULT_HORIZONS,
    RATING_ORDER,
    RATING_SCORES,
    BucketStats,
    ConfidenceStats,
    HorizonStats,
    classify,
    compute_horizon_stats,
    horizon_returns,
    ic_t_stat,
    mean,
    median,
    one_sample_t,
    ordered_horizons,
    sample_stdev,
    spearman,
    wilson_ci,
)
from ifa.backtest.rating_validator import RatingRecord, compute_statistics


def _rec(
    code: str = "510300",
    date: str = "2024-01-15",
    rating: str = "BUY",
    fwd: float | None = None,
    bench: float | None = None,
    confidence: str = "Medium",
    returns: dict[int, float] | None = None,
    benches: dict[int, float] | None = None,
    excesses: dict[int, float] | None = None,
    fetch_error: str = "",
) -> RatingRecord:
    """构造一条记录；扁平字段与逐视界字段都可单独控制。"""
    record = RatingRecord(fund_code=code, analysis_date=date, rating=rating, confidence=confidence)
    record.forward_return_pct = fwd
    record.benchmark_return_pct = bench
    record.excess_return_pct = None if (fwd is None or bench is None) else fwd - bench
    record.returns_by_horizon = dict(returns or {})
    record.benchmark_by_horizon = dict(benches or {})
    record.excess_by_horizon = dict(excesses or {})
    record.fetch_error = fetch_error
    return record


class TestClassify:
    @pytest.mark.parametrize("rating", ["STRONG_BUY", "BUY"])
    def test_bullish(self, rating):
        assert classify(rating) == "bullish"

    @pytest.mark.parametrize("rating", ["UNDERWEIGHT", "SELL"])
    def test_bearish(self, rating):
        assert classify(rating) == "bearish"

    @pytest.mark.parametrize("rating", ["HOLD", "", "买入", "unknown"])
    def test_neutral(self, rating):
        assert classify(rating) == "neutral"


class TestWilsonCI:
    def test_empty(self):
        assert wilson_ci(0, 0) == (0.0, 1.0)

    def test_bounds(self):
        assert wilson_ci(0, 10)[0] == 0.0
        assert wilson_ci(10, 10)[1] == 1.0

    def test_larger_n_narrower(self):
        wide = wilson_ci(5, 10)
        narrow = wilson_ci(50, 100)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


class TestDistribution:
    def test_mean(self):
        assert mean([]) is None
        assert mean([1.0, 2.0, 3.0]) == 2.0

    def test_median(self):
        assert median([]) is None
        assert median([3.0, 1.0, 2.0]) == 2.0
        assert median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_sample_stdev(self):
        assert sample_stdev([5.0]) is None
        assert sample_stdev([2.0, 2.0, 2.0]) == 0.0
        assert sample_stdev([0.0, 10.0]) == pytest.approx(7.0710678, abs=1e-6)


class TestOneSampleT:
    def test_too_few(self):
        assert one_sample_t([1.0]) == (None, None, 1)
        assert one_sample_t([]) == (None, None, 0)

    def test_zero_variance(self):
        assert one_sample_t([1.0, 1.0, 1.0]) == (None, None, 3)

    def test_known_value(self):
        t, p, n = one_sample_t([1.0, 2.0, 3.0, 4.0, 5.0])
        assert n == 5
        assert t == pytest.approx(4.2426, abs=1e-3)
        assert p is not None and p < 0.05

    def test_zero_mean_gives_zero_t(self):
        t, p, n = one_sample_t([-3.0, 3.0])
        assert t == pytest.approx(0.0, abs=1e-9)
        assert p == pytest.approx(1.0, abs=1e-9)
        assert n == 2


class TestSpearman:
    def test_perfect_positive(self):
        assert spearman([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == pytest.approx(1.0)

    def test_perfect_negative(self):
        assert spearman([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) == pytest.approx(-1.0)

    def test_ties_average_ranks(self):
        ic = spearman([1.0, 1.0, 2.0, 2.0], [1.0, 2.0, 3.0, 4.0])
        assert ic is not None and 0.0 < ic < 1.0

    def test_no_variance_is_unknown(self):
        assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None

    def test_too_few(self):
        assert spearman([1.0, 2.0], [1.0, 2.0]) is None


class TestIcTStat:
    def test_none_input(self):
        assert ic_t_stat(None, 10) is None

    def test_degenerate(self):
        assert ic_t_stat(1.0, 10) is None
        assert ic_t_stat(0.5, 2) is None

    def test_known_value(self):
        assert ic_t_stat(0.5, 10) == pytest.approx(1.6330, abs=1e-3)


class TestHorizonReturns:
    def test_per_horizon_values_are_used(self):
        record = _rec(returns={20: 3.0, 60: 5.0, 120: 9.0}, benches={60: 2.0})
        assert horizon_returns(record, 20, 60) == (3.0, None, None)
        assert horizon_returns(record, 60, 60) == (5.0, 2.0, 3.0)
        assert horizon_returns(record, 120, 60) == (9.0, None, None)

    def test_flat_fields_only_backfill_the_primary_horizon(self):
        record = _rec(fwd=5.0, bench=2.0)
        assert horizon_returns(record, 60, 60) == (5.0, 2.0, 3.0)
        # 关键防线：60 日收益绝不许冒充 20/120 日
        assert horizon_returns(record, 20, 60) == (None, None, None)
        assert horizon_returns(record, 120, 60) == (None, None, None)

    def test_excess_is_derived_when_missing(self):
        record = _rec(returns={60: 5.0}, benches={60: 2.0})
        assert horizon_returns(record, 60, 60) == (5.0, 2.0, 3.0)


class TestOrderedHorizons:
    def test_default(self):
        assert ordered_horizons(None, 60) == DEFAULT_HORIZONS

    def test_sorted_deduped_and_primary_included(self):
        assert ordered_horizons([120, 20, 120, -5, 0], 60) == (20, 60, 120)

    def test_primary_always_present(self):
        assert ordered_horizons([20, 120], 45) == (20, 45, 120)


class TestComputeHorizonStats:
    def test_absolute_and_excess_hit_rates(self):
        records = [
            _rec("A", "2024-01-15", "BUY", fwd=5.0, bench=2.0),
            _rec("B", "2024-01-15", "BUY", fwd=-1.0, bench=2.0),
        ]
        stats = compute_horizon_stats(records, 60, primary_hold_days=60)
        assert stats.valid == 2
        assert stats.bullish_n == 2
        assert stats.bullish_hit_rate == 0.5  # 只有一条上涨
        assert stats.bullish_excess_hit_rate == 0.5  # 只有一条跑赢
        assert stats.mean_excess_pct == pytest.approx(0.0)
        assert stats.benchmark_up_rate == 1.0
        assert stats.alpha_vs_benchmark == pytest.approx(-0.5)

    def test_bearish_excess_uses_negative_excess(self):
        records = [
            _rec("A", "2024-01-15", "SELL", fwd=-5.0, bench=-2.0),  # 超额 -3 → 命中
            _rec("B", "2024-01-15", "SELL", fwd=5.0, bench=1.0),  # 超额 +4 → 未命中
        ]
        stats = compute_horizon_stats(records, 60, primary_hold_days=60)
        assert stats.bearish_n == 2
        assert stats.bearish_hit_rate == 0.5
        assert stats.bearish_excess_hit_rate == 0.5

    def test_hold_bucket_records_mean_excess(self):
        records = [
            _rec("A", "2024-01-15", "HOLD", fwd=1.0, bench=1.0),
            _rec("B", "2024-01-15", "HOLD", fwd=-1.0, bench=-1.0),
        ]
        stats = compute_horizon_stats(records, 60, primary_hold_days=60)
        assert stats.hold_n == 2
        assert stats.hold_mean_excess_pct == pytest.approx(0.0)
        hold_bucket = next(b for b in stats.buckets if b.label == "HOLD")
        assert hold_bucket.excess_hit_rate is None  # HOLD 无方向声明

    def test_buckets_only_include_present_ratings(self):
        records = [_rec("A", "2024-01-15", "BUY", fwd=1.0, bench=0.0)]
        stats = compute_horizon_stats(records, 60, primary_hold_days=60)
        assert [b.label for b in stats.buckets] == ["BUY"]

    def test_monotonicity_with_three_buckets(self):
        records = [
            _rec("A", "2024-01-15", "STRONG_BUY", fwd=9.0, bench=1.0),
            _rec("B", "2024-01-15", "BUY", fwd=6.0, bench=1.0),
            _rec("C", "2024-01-15", "HOLD", fwd=3.0, bench=1.0),
            _rec("D", "2024-01-15", "SELL", fwd=-4.0, bench=1.0),
        ]
        stats = compute_horizon_stats(records, 60, primary_hold_days=60)
        assert stats.monotonicity == pytest.approx(1.0)
        assert stats.monotonicity_n == 4

    def test_rank_ic_needs_eight_samples(self):
        small = [
            _rec(f"F{i}", "2024-01-15", "BUY", fwd=float(i), bench=0.0) for i in range(7)
        ]
        stats = compute_horizon_stats(small, 60, primary_hold_days=60)
        assert stats.rank_ic is None
        assert stats.rank_ic_n == 0

        ratings = ["STRONG_BUY", "STRONG_BUY", "BUY", "BUY", "HOLD", "HOLD", "UNDERWEIGHT", "SELL"]
        big = [
            _rec(f"F{i}", "2024-01-15", rating, fwd=float(8 - i), bench=0.0)
            for i, rating in enumerate(ratings)
        ]
        stats = compute_horizon_stats(big, 60, primary_hold_days=60)
        assert stats.rank_ic_n == 8
        assert stats.rank_ic is not None and stats.rank_ic > 0.9
        assert stats.rank_ic_t is not None

    def test_confidence_calibration_and_spread(self):
        records = [
            _rec("A", "2024-01-15", "BUY", fwd=5.0, bench=0.0, confidence="High"),
            _rec("B", "2024-01-15", "BUY", fwd=4.0, bench=0.0, confidence="High"),
            _rec("C", "2024-01-15", "BUY", fwd=-5.0, bench=0.0, confidence="Low"),
            _rec("D", "2024-01-15", "BUY", fwd=-4.0, bench=0.0, confidence="Low"),
        ]
        stats = compute_horizon_stats(records, 60, primary_hold_days=60)
        high = next(c for c in stats.confidence if c.label == "High")
        low = next(c for c in stats.confidence if c.label == "Low")
        assert high.absolute_hit_rate == 1.0
        assert low.absolute_hit_rate == 0.0
        assert stats.confidence_spread == pytest.approx(1.0)
        assert high.mean_abs_excess_pct == pytest.approx(4.5)

    def test_horizon_without_own_data_is_empty(self):
        records = [_rec("A", "2024-01-15", "BUY", fwd=5.0, bench=1.0)]
        stats = compute_horizon_stats(records, 20, primary_hold_days=60)
        assert stats.valid == 0
        assert stats.has_data() is False
        assert stats.bullish_hit_rate is None

    def test_fetch_error_records_are_skipped(self):
        records = [
            _rec("A", "2024-01-15", "BUY", fwd=5.0, bench=1.0),
            _rec("B", "2024-01-15", "BUY", fwd=5.0, bench=1.0, fetch_error="失败"),
        ]
        stats = compute_horizon_stats(records, 60, primary_hold_days=60)
        assert stats.valid == 1


class TestDataclassSerialization:
    def test_to_dict_round_trip_keys(self):
        bucket = BucketStats(label="BUY", n=3, mean_excess_pct=1.5)
        assert bucket.to_dict()["label"] == "BUY"
        assert bucket.to_dict()["mean_excess_pct"] == 1.5

        confidence = ConfidenceStats(label="High", n=2, directional_n=2)
        assert confidence.to_dict()["directional_n"] == 2

        horizon = HorizonStats(hold_days=60, valid=2, excess_n=2)
        payload = horizon.to_dict()
        assert payload["hold_days"] == 60
        assert "excess_p_normal_approx" in payload


class TestComputeStatisticsIntegration:
    def test_flat_records_only_fill_primary_horizon(self):
        records = [
            _rec("A", "2024-01-15", "BUY", fwd=5.0, bench=2.0),
            _rec("B", "2024-02-15", "SELL", fwd=-3.0, bench=1.0),
        ]
        result = compute_statistics(records, hold_days=60)
        by_horizon = {h.hold_days: h for h in result.horizons}
        assert set(by_horizon) == set(DEFAULT_HORIZONS)
        assert by_horizon[60].valid == 2
        assert by_horizon[20].valid == 0
        assert by_horizon[120].valid == 0
        # 扁平字段取主视界
        assert result.bullish_n == 1
        assert result.bearish_n == 1
        assert result.mean_excess_pct == pytest.approx(-0.5)  # 超额 +3 与 -4 的均值

    def test_warnings_cover_no_independent_horizon_data(self):
        records = [_rec("A", "2024-01-15", "BUY", fwd=5.0, bench=2.0)]
        result = compute_statistics(records, hold_days=60)
        assert any("无独立数据" in w for w in result.warnings)
        assert any("多重比较" in w for w in result.warnings)

    def test_per_horizon_records_are_reported_separately(self):
        records = [
            _rec("A", "2024-01-15", "BUY", fwd=5.0, bench=2.0, returns={20: 1.0, 60: 5.0, 120: 12.0}),
            _rec("B", "2024-01-15", "BUY", fwd=-1.0, bench=2.0, returns={20: -1.0, 60: -1.0, 120: -6.0}),
        ]
        result = compute_statistics(records, hold_days=60, horizons=(20, 60, 120))
        by_horizon = {h.hold_days: h for h in result.horizons}
        assert by_horizon[20].valid == 2
        assert by_horizon[20].mean_forward_pct == pytest.approx(0.0)
        assert by_horizon[120].mean_forward_pct == pytest.approx(3.0)
        assert not any("无独立数据" in w for w in result.warnings)

    def test_rating_scores_cover_every_rating_in_order(self):
        assert list(RATING_SCORES) == list(RATING_ORDER)
