"""组合数学分析测试 —— 相关性/协方差/风险贡献必须由代码算，不能只靠 LLM 自述。

覆盖：纯计算层（合成收益矩阵、可解析的解析解、退化输入）、取数层（合成
price_fetcher 的降级路径）、渲染层，以及 portfolio_advisor 节点的接线
（R2 且解析出 >= 2 只基金时追加 PORTFOLIO ANALYTICS；R1 或取数失败时不追加）。
"""

import numpy as np
import pandas as pd
import pytest

from ifa.agents.managers.portfolio_advisor import create_portfolio_advisor
from ifa.portfolio.analytics import (
    MIN_COMMON_OBSERVATIONS,
    analyze_portfolio,
    compute_analytics,
    format_portfolio_analytics,
)

MODERATE = "moderate"


def _advice(categories: str, funds: str, tail: str = "- RATIONALE: 测试用\n- RISK ASSESSMENT: 无\n") -> str:
    return f"PORTFOLIO ADVICE:\n- ASSET ALLOCATION: {categories}\n- FUND SELECTIONS: {funds}\n{tail}"


class _MockLLM:
    def __init__(self, content: str) -> None:
        self._content = content

    def invoke(self, *args, **kwargs):
        content = self._content

        class _Response:
            pass

        response = _Response()
        response.content = content
        return response


def _dates(n: int = 250) -> pd.DatetimeIndex:
    return pd.bdate_range("2025-01-02", periods=n)


def _random_returns(seed: int = 7, n: int = 250) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0004, 0.010, n)
    b = 0.6 * a + rng.normal(0.0003, 0.008, n)
    c = rng.normal(0.0002, 0.006, n)
    return pd.DataFrame({"510300": a, "159919": b, "161725": c}, index=_dates(n))


def _frame(dates: pd.DatetimeIndex, values: np.ndarray, basis: str | None = None) -> pd.DataFrame:
    df = pd.DataFrame({"日期": dates, "收盘": values})
    if basis:
        df.attrs["price_basis"] = basis
    return df


class TestComputeAnalyticsMath:
    def test_perfectly_correlated_funds_have_no_diversification(self):
        n = 200
        a = np.tile([0.01, -0.01], n // 2)
        b = 2.0 * a
        returns = pd.DataFrame({"A": a, "B": b}, index=_dates(n))
        result = compute_analytics(returns, {"A": 50, "B": 50})
        assert result is not None
        assert result.avg_pairwise_correlation == pytest.approx(1.0)
        assert result.diversification_ratio == pytest.approx(1.0, abs=1e-3)
        # B 的波动率是 A 的两倍，完全相关下风险贡献按波动率分摊 -> 1/3 与 2/3
        assert result.risk_contribution_pct["A"] == pytest.approx(100.0 / 3, abs=0.01)
        assert result.risk_contribution_pct["B"] == pytest.approx(200.0 / 3, abs=0.01)
        assert result.risk_contribution_ratio["A"] == pytest.approx(2.0 / 3, abs=1e-3)
        assert result.risk_contribution_ratio["B"] == pytest.approx(4.0 / 3, abs=1e-3)

    def test_orthogonal_funds_diversify_by_root_two(self):
        # a 与 b 的收益序列正交且同方差 -> 组合波动 = sigma/sqrt(2)，分散化比率 = sqrt(2)
        n = 248
        a = np.tile([0.01, -0.01], n // 2)
        b = np.tile([0.01, 0.01, -0.01, -0.01], n // 4)
        returns = pd.DataFrame({"A": a, "B": b}, index=_dates(n))
        result = compute_analytics(returns, {"A": 50, "B": 50})
        assert result is not None
        assert result.avg_pairwise_correlation == pytest.approx(0.0, abs=1e-9)
        assert result.diversification_ratio == pytest.approx(np.sqrt(2.0), abs=1e-3)
        assert result.annualized_vol_pct < result.weighted_avg_vol_pct

    def test_weights_are_normalized_and_contributions_sum_to_one(self):
        result = compute_analytics(_random_returns(), {"510300": 45, "159919": 35, "161725": 20})
        assert result is not None
        assert sum(result.weights.values()) == pytest.approx(1.0)
        assert sum(result.risk_contribution_pct.values()) == pytest.approx(100.0, abs=0.05)

    def test_correlation_matrix_is_symmetric_with_unit_diagonal(self):
        result = compute_analytics(_random_returns(), {"510300": 40, "159919": 30, "161725": 30})
        assert result is not None
        matrix = result.correlation
        assert len(matrix) == 3
        for i in range(3):
            assert matrix[i][i] == pytest.approx(1.0)
            for j in range(3):
                assert matrix[i][j] == pytest.approx(matrix[j][i])

    def test_low_correlation_portfolio_has_ratio_above_one(self):
        result = compute_analytics(_random_returns(seed=11), {"510300": 40, "159919": 30, "161725": 30})
        assert result is not None
        assert result.diversification_ratio > 1.0
        assert result.avg_pairwise_correlation is not None
        assert result.avg_pairwise_correlation < 0.5

    def test_single_fund_returns_none(self):
        returns = _random_returns()[["510300"]]
        assert compute_analytics(returns, {"510300": 100}) is None

    def test_all_zero_weights_returns_none(self):
        assert compute_analytics(_random_returns(), {"510300": 0, "159919": 0, "161725": 0}) is None

    def test_zero_variance_column_returns_none(self):
        returns = _random_returns()
        returns["161725"] = 0.0
        assert compute_analytics(returns, {"510300": 40, "159919": 30, "161725": 30}) is None


class TestAnalyzePortfolioFetching:
    def test_fetches_series_and_reports_basis(self):
        dates = _dates(250)
        rng = np.random.default_rng(3)
        series = {
            "510300": 1 + np.cumsum(rng.normal(0, 0.01, 250)),
            "159919": 1 + np.cumsum(rng.normal(0, 0.012, 250)),
        }

        def fetcher(code, start, end):
            return _frame(dates, series[code], basis="ETF 前复权收盘价（分红已还原）")

        result = analyze_portfolio({"510300": 60, "159919": 40}, price_fetcher=fetcher, as_of="2026-10-15")
        assert result is not None
        assert result.observations == 249
        assert result.price_bases["510300"] == "ETF 前复权收盘价（分红已还原）"
        assert any("价格口径" in note for note in result.notes)
        assert any("历史已实现数据" in note for note in result.notes)

    def test_one_fund_fetch_failure_is_dropped_with_note(self):
        dates = _dates(250)
        rng = np.random.default_rng(5)

        def fetcher(code, start, end):
            if code == "161725":
                raise RuntimeError("数据源挂了")
            return _frame(dates, 1 + np.cumsum(rng.normal(0, 0.01, 250)))

        result = analyze_portfolio({"510300": 50, "159919": 30, "161725": 20}, price_fetcher=fetcher)
        assert result is not None
        assert result.dropped == ["161725"]
        assert "161725" not in result.weights
        assert any("未纳入计算的基金" in note for note in result.notes)

    def test_all_fetches_failing_returns_none(self):
        def fetcher(code, start, end):
            raise RuntimeError("全挂")

        assert analyze_portfolio({"510300": 50, "159919": 50}, price_fetcher=fetcher) is None

    def test_fetcher_returning_none_is_dropped(self):
        assert analyze_portfolio({"510300": 50, "159919": 50}, price_fetcher=lambda *a: None) is None

    def test_short_history_returns_none(self):
        dates = _dates(40)
        rng = np.random.default_rng(9)

        def fetcher(code, start, end):
            return _frame(dates, 1 + np.cumsum(rng.normal(0, 0.01, 40)))

        result = analyze_portfolio(
            {"510300": 50, "159919": 50},
            price_fetcher=fetcher,
            min_observations=MIN_COMMON_OBSERVATIONS,
        )
        assert result is None

    def test_single_weight_returns_none(self):
        assert analyze_portfolio({"510300": 100}, price_fetcher=lambda *a: None) is None

    def test_zero_weight_funds_are_ignored(self):
        assert analyze_portfolio({"510300": 100, "159919": 0}, price_fetcher=lambda *a: None) is None

    def test_invalid_as_of_returns_none(self):
        assert analyze_portfolio({"510300": 50, "159919": 50}, as_of="2026/10/15") is None

    def test_zero_volatility_fund_is_dropped(self):
        dates = _dates(250)
        rng = np.random.default_rng(13)

        def fetcher(code, start, end):
            if code == "161725":
                return _frame(dates, np.full(250, 1.0))
            return _frame(dates, 1 + np.cumsum(rng.normal(0, 0.01, 250)))

        result = analyze_portfolio({"510300": 50, "159919": 30, "161725": 20}, price_fetcher=fetcher)
        assert result is not None
        assert "161725" in result.dropped
        assert any("波动率为 0" in note for note in result.notes)


class TestFormatPortfolioAnalytics:
    def test_renders_tables_and_notes(self):
        result = compute_analytics(_random_returns(), {"510300": 45, "159919": 35, "161725": 20})
        assert result is not None
        rendered = format_portfolio_analytics(result)
        assert "## PORTFOLIO ANALYTICS（代码计算，非 LLM 自述）" in rendered
        assert "组合年化波动率" in rendered
        assert "加权平均波动率" in rendered
        assert "分散化比率" in rendered
        assert "平均两两相关系数" in rendered
        assert "| 基金 | 权重 | 年化波动率 | 风险贡献占比 | 贡献占比 / 权重占比 |" in rendered
        assert "相关系数矩阵" in rendered
        for code in ("510300", "159919", "161725"):
            assert code in rendered

    def test_reports_unavailable_average_correlation(self):
        result = compute_analytics(_random_returns(), {"510300": 50, "159919": 50})
        assert result is not None
        result.avg_pairwise_correlation = None
        assert "不可用" in format_portfolio_analytics(result)


class TestPortfolioAdvisorAnalyticsWiring:
    def _patch_analytics(self, monkeypatch, result):
        monkeypatch.setattr("ifa.agents.managers.portfolio_advisor.analyze_portfolio", lambda weights: result)

    def test_r2_advice_gets_analytics_appendix(self, monkeypatch):
        analytics = compute_analytics(_random_returns(), {"510300": 50, "110020": 50})
        self._patch_analytics(monkeypatch, analytics)
        advice = _advice("宽基指数 100%", "510300 (50%), 110020 (50%)")
        node = create_portfolio_advisor(_MockLLM(advice))
        result = node({"risk_profile": MODERATE, "screen_results": "候选基金清单"})
        assert result["portfolio_advice"].startswith(advice)
        assert "## PORTFOLIO ANALYTICS" in result["portfolio_advice"]
        assert "组合年化波动率" in result["portfolio_advice"]

    def test_r1_without_screen_results_skips_analytics(self, monkeypatch):
        analytics = compute_analytics(_random_returns(), {"510300": 50, "110020": 50})
        self._patch_analytics(monkeypatch, analytics)
        advice = _advice("宽基指数 100%", "510300 (50%), 110020 (50%)")
        node = create_portfolio_advisor(_MockLLM(advice))
        result = node({"risk_profile": MODERATE})
        assert "PORTFOLIO ANALYTICS" not in result["portfolio_advice"]

    def test_analytics_failure_is_swallowed(self, monkeypatch):
        def boom(weights):
            raise RuntimeError("取数层爆炸")

        monkeypatch.setattr("ifa.agents.managers.portfolio_advisor.analyze_portfolio", boom)
        advice = _advice("宽基指数 50%, 债券 30%, QDII 20%", "510300 (30%), 110020 (30%), 000834 (20%), 017641 (20%)")
        node = create_portfolio_advisor(_MockLLM(advice))
        result = node({"risk_profile": MODERATE, "screen_results": "候选基金清单"})
        assert result["portfolio_advice"] == advice

    def test_analytics_none_leaves_advice_untouched(self, monkeypatch):
        self._patch_analytics(monkeypatch, None)
        advice = _advice("宽基指数 50%, 债券 30%, QDII 20%", "510300 (30%), 110020 (30%), 000834 (20%), 017641 (20%)")
        node = create_portfolio_advisor(_MockLLM(advice))
        result = node({"risk_profile": MODERATE, "screen_results": "候选基金清单"})
        assert result["portfolio_advice"] == advice

    def test_single_fund_advice_skips_analytics(self, monkeypatch):
        analytics = compute_analytics(_random_returns(), {"510300": 100})
        self._patch_analytics(monkeypatch, analytics)
        advice = _advice("宽基指数 100%", "510300 (100%)")
        node = create_portfolio_advisor(_MockLLM(advice))
        result = node({"risk_profile": MODERATE, "screen_results": "候选基金清单"})
        assert "PORTFOLIO ANALYTICS" not in result["portfolio_advice"]
