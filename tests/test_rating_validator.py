# tests/test_rating_validator.py
"""评级验证模块测试 —— 纯计算逻辑，不碰网络/LLM。

测试策略与 test_core.py::TestBacktestEngine 一致：测私有/纯计算函数，
不测 run_rating_validation（它会调 LLM 和网络，需集成测试环境）。
"""

from __future__ import annotations

from ifa.backtest.rating_validator import (
    RatingRecord,
    RatingValidationResult,
    add_trading_days,
    compute_statistics,
    format_validation_report,
    generate_monthly_dates,
    wilson_ci,
)

# ── Wilson 置信区间 ──────────────────────────────────────────────────


class TestWilsonCI:
    def test_zero_successes(self):
        """0/n 次成功，下界应为 0。"""
        low, high = wilson_ci(0, 10)
        assert low == 0.0
        assert 0 < high < 0.5

    def test_all_successes(self):
        """n/n 次成功，上界应为 1。"""
        low, high = wilson_ci(10, 10)
        assert high == 1.0
        assert 0.5 < low < 1.0

    def test_half_success(self):
        """一半成功，中心点应接近 0.5。"""
        low, high = wilson_ci(5, 10)
        assert low < 0.5 < high
        # 区间宽度合理（n=10 时不会太窄）
        assert high - low > 0.1

    def test_empty(self):
        """n=0 时返回 [0, 1] 全区间。"""
        low, high = wilson_ci(0, 0)
        assert low == 0.0
        assert high == 1.0

    def test_never_exceeds_unit_interval(self):
        """边界：p=0 或 p=1 时区间不越界。"""
        for k, n in [(0, 1), (1, 1), (0, 100), (100, 100)]:
            low, high = wilson_ci(k, n)
            assert 0.0 <= low <= 1.0
            assert 0.0 <= high <= 1.0

    def test_larger_n_gives_narrower_interval(self):
        """样本越大，区间越窄（精度越高）。"""
        wide_low, wide_high = wilson_ci(5, 10)
        narrow_low, narrow_high = wilson_ci(50, 100)
        assert (narrow_high - narrow_low) < (wide_high - wide_low)


# ── 命中率统计 ───────────────────────────────────────────────────────


class TestComputeStatistics:
    def _make_record(
        self,
        code: str,
        date: str,
        rating: str,
        fwd: float,
        bench: float = 0.0,
        confidence: str = "Medium",
    ) -> RatingRecord:
        return RatingRecord(
            fund_code=code,
            analysis_date=date,
            rating=rating,
            confidence=confidence,
            forward_return_pct=fwd,
            benchmark_return_pct=bench,
            excess_return_pct=fwd - bench,
        )

    def test_bullish_hit_rate_basic(self):
        """6 涨 + 2 跌 的看涨评级，命中率 75%。"""
        records = [
            self._make_record("510300", "2024-01-15", "BUY", 5.0),    # hit
            self._make_record("510300", "2024-02-15", "BUY", 3.0),    # hit
            self._make_record("510300", "2024-03-15", "BUY", -2.0),   # miss
            self._make_record("159919", "2024-01-15", "BUY", 8.0),    # hit
            self._make_record("159919", "2024-02-15", "BUY", 1.0),    # hit
            self._make_record("159919", "2024-03-15", "STRONG_BUY", 4.0),  # hit
            self._make_record("510500", "2024-01-15", "STRONG_BUY", 12.0), # hit
            self._make_record("510500", "2024-02-15", "BUY", -3.0),   # miss
        ]
        result = compute_statistics(records, hold_days=60)

        assert result.valid == 8
        assert result.bullish_n == 8
        assert result.bullish_hit_rate == 0.75  # 6/8
        # CI 应覆盖 0.75
        assert result.bullish_ci_low < 0.75 < result.bullish_ci_high
        # 小样本警告
        assert any("无统计显著性" in w for w in result.warnings)

    def test_bearish_hit_rate(self):
        """看跌评级：实际下跌的占比。"""
        records = [
            self._make_record("510300", "2024-01-15", "SELL", -5.0),
            self._make_record("510300", "2024-02-15", "UNDERWEIGHT", -3.0),
            self._make_record("510300", "2024-03-15", "SELL", 2.0),  # miss
            self._make_record("159919", "2024-01-15", "UNDERWEIGHT", -8.0),
        ]
        result = compute_statistics(records, hold_days=60)

        assert result.bearish_n == 4
        assert result.bearish_hit_rate == 0.75  # 3/4 实际下跌

    def test_hold_excluded_from_directional(self):
        """HOLD 评级不计入 bullish/bearish 命中率。"""
        records = [
            self._make_record("A", "2024-01-15", "HOLD", 5.0),
            self._make_record("B", "2024-01-15", "HOLD", -3.0),
        ]
        result = compute_statistics(records, hold_days=60)

        assert result.bullish_n == 0
        assert result.bearish_n == 0
        assert result.bullish_hit_rate is None
        assert result.bearish_hit_rate is None
        assert any("均为 HOLD" in w for w in result.warnings)

    def test_skipped_records_excluded(self):
        """fetch_error 非空的记录不进入统计。"""
        records = [
            self._make_record("A", "2024-01-15", "BUY", 5.0),
            RatingRecord("B", "2024-01-15", "BUY", "Medium", fetch_error="数据获取失败"),
        ]
        result = compute_statistics(records, hold_days=60)

        assert result.total == 2
        assert result.valid == 1
        assert result.skipped == 1
        assert result.bullish_n == 1

    def test_confusion_matrix(self):
        """5 档评级 × {涨/跌} 矩阵填对。"""
        records = [
            self._make_record("A", "2024-01-15", "STRONG_BUY", 5.0),
            self._make_record("B", "2024-01-15", "BUY", -2.0),
            self._make_record("C", "2024-01-15", "HOLD", 1.0),
            self._make_record("D", "2024-01-15", "SELL", -3.0),
            self._make_record("E", "2024-01-15", "STRONG_BUY", -1.0),  # STRONG_BUY miss
        ]
        result = compute_statistics(records, hold_days=60)

        assert result.confusion_matrix is not None
        assert result.confusion_matrix["STRONG_BUY"] == {"up": 1, "down": 1}
        assert result.confusion_matrix["BUY"] == {"up": 0, "down": 1}
        assert result.confusion_matrix["HOLD"] == {"up": 1, "down": 0}
        assert result.confusion_matrix["SELL"] == {"up": 0, "down": 1}
        assert result.confusion_matrix["UNDERWEIGHT"] == {"up": 0, "down": 0}

    def test_benchmark_and_alpha(self):
        """基准对比：alpha = bullish_hit_rate - benchmark。"""
        records = [
            self._make_record("A", "2024-01-15", "BUY", 5.0, bench=3.0),   # hit, bench up
            self._make_record("B", "2024-01-15", "BUY", -2.0, bench=1.0),  # miss, bench up
            self._make_record("C", "2024-01-15", "BUY", 3.0, bench=-1.0),  # hit, bench down
        ]
        result = compute_statistics(records, hold_days=60)

        assert result.bullish_hit_rate == 2 / 3
        assert result.csi300_benchmark == 2 / 3  # 3 期里 2 期大盘上涨
        assert result.alpha_vs_random is not None
        assert abs(result.alpha_vs_random - (2 / 3 - 0.5)) < 1e-9
        # alpha_vs_csi300 应约为 0（命中率等于基准）
        assert abs(result.alpha_vs_csi300) < 1e-9

    def test_no_valid_records(self):
        """全部失败时给出明确警告。"""
        records = [
            RatingRecord("A", "2024-01-15", "BUY", "Medium", fetch_error="失败"),
            RatingRecord("B", "2024-01-15", "SELL", "Low", fetch_error="失败"),
        ]
        result = compute_statistics(records, hold_days=60)

        assert result.valid == 0
        assert result.bullish_hit_rate is None
        assert any("无有效记录" in w for w in result.warnings)

    def test_small_sample_warning_threshold(self):
        """valid < 30 必须有统计显著性警告。"""
        records = [self._make_record("A", "2024-01-15", "BUY", 1.0) for _ in range(10)]
        result = compute_statistics(records, hold_days=60)
        assert result.valid == 10
        assert any("无统计显著性" in w for w in result.warnings)

    def test_period_range(self):
        """时间范围取 min/max 分析日期。"""
        records = [
            self._make_record("A", "2024-03-15", "BUY", 1.0),
            self._make_record("A", "2024-01-15", "BUY", 2.0),
            self._make_record("A", "2024-02-15", "BUY", 3.0),
        ]
        result = compute_statistics(records, hold_days=60)
        assert result.period_start == "2024-01-15"
        assert result.period_end == "2024-03-15"


# ── 日期工具 ─────────────────────────────────────────────────────────


class TestDateUtils:
    def test_add_trading_days_basic(self):
        """60 交易日约等于 84 + 余量 日历日。"""
        end = add_trading_days("2024-01-15", 60)
        # 应落在 2024-04 月（1 月 15 日 + 约 89 天 ≈ 4 月中）
        assert end.startswith("2024-04")

    def test_add_trading_days_zero(self):
        """0 个交易日仍给 5 天余量（不返回原日期）。"""
        end = add_trading_days("2024-01-15", 0)
        # 不等于原日期
        assert end != "2024-01-15"

    def test_generate_monthly_dates_count(self):
        """months_back=6 返回至多 6 个日期。"""
        dates = generate_monthly_dates(6, end_date="2024-06-15")
        assert len(dates) <= 6
        assert all(len(d) == 10 for d in dates)  # YYYY-MM-DD 格式

    def test_generate_monthly_dates_sorted(self):
        """返回日期升序。"""
        dates = generate_monthly_dates(4, end_date="2024-06-15")
        assert dates == sorted(dates)

    def test_generate_monthly_dates_no_future(self):
        """所有日期不晚于 end_date。"""
        dates = generate_monthly_dates(3, end_date="2024-06-15")
        assert all(d <= "2024-06-15" for d in dates)


# ── 报告格式化 ───────────────────────────────────────────────────────


class TestFormatReport:
    def test_disclaimer_present(self):
        """报告顶部必须有智识诚实声明。"""
        result = RatingValidationResult(
            records=[], total=0, valid=0, skipped=0, hold_days=60
        )
        report = format_validation_report(result)
        assert "智识诚实声明" in report
        assert "不证明" in report

    def test_confusion_matrix_renders(self):
        """混淆矩阵在报告里完整渲染。"""
        records = [
            RatingRecord(
                "510300", "2024-01-15", "BUY", "High",
                forward_return_pct=5.0, benchmark_return_pct=2.0,
            ),
        ]
        result = compute_statistics(records, hold_days=60)
        report = format_validation_report(result)
        assert "STRONG_BUY" in report
        assert "混淆矩阵" in report
        assert "实际上涨" in report

    def test_empty_result_renders_without_crash(self):
        """空结果不崩。"""
        result = RatingValidationResult(
            records=[], total=0, valid=0, skipped=0, hold_days=60
        )
        report = format_validation_report(result)
        assert isinstance(report, str)
        assert "评级验证报告" in report
