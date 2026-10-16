"""P2 市场指标工具测试：ETF 折溢价率 / 跟踪误差 / 人民币汇率。

全部使用假数据源（monkeypatch _call_akshare_api），不联网。
"""

from __future__ import annotations

import pandas as pd
import pytest

from ifa.dataflows import a_share_index_fund as ix
from ifa.dataflows import a_share_macro as macro
from ifa.dataflows import a_share_public_fund as pf
from ifa.dataflows.asset_type import AssetType


def _spot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": ["513100", "159509", "510300", "161725"],
            "名称": ["纳指ETF国泰", "纳指科技ETF景顺", "沪深300ETF", "招商中证白酒"],
            "最新价": [2.352, 1.5, 4.0, 0.9],
            "IOPV实时估值": [2.0058, 1.2, 4.0, 0.9],
            "基金折价率": [-17.26, -39.09, 0.5, -0.26],
            "数据日期": ["2026-10-16"] * 4,
        }
    )


def _series(values: list[float], dates: list[str] | None = None) -> pd.Series:
    index = pd.to_datetime(dates) if dates else pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=index)


class TestEtfPremiumDiscount:
    """溢价率 = -东财折价率列；缺失时退回最新价/IOPV，并且必须告警。"""

    def test_premium_is_negative_of_discount_column(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pf, "_call_akshare_api", lambda *a, **k: _spot_frame())
        out = pf.get_etf_premium_discount("513100")
        assert "17.26" in out
        assert "折价率列取反" in out
        assert "高溢价" in out

    def test_blank_symbol_sorts_by_absolute_premium(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pf, "_call_akshare_api", lambda *a, **k: _spot_frame())
        out = pf.get_etf_premium_discount(top_n=2)
        assert out.index("39.09") < out.index("17.26")
        assert "0.5" not in out.split("## 口径与含义")[0]

    def test_falls_back_to_price_over_iopv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        frame = _spot_frame().drop(columns=["基金折价率"])
        monkeypatch.setattr(pf, "_call_akshare_api", lambda *a, **k: frame)
        out = pf.get_etf_premium_discount("513100")
        assert "由最新价与 IOPV" in out
        assert "17.26" in out

    def test_missing_both_sources_reports_clearly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        frame = _spot_frame().drop(columns=["基金折价率", "IOPV实时估值"])
        monkeypatch.setattr(pf, "_call_akshare_api", lambda *a, **k: frame)
        assert "无法计算折溢价率" in pf.get_etf_premium_discount("513100")

    def test_missing_code_column_reports_clearly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pf, "_call_akshare_api", lambda *a, **k: pd.DataFrame({"最新价": [1.0]}))
        assert "缺少代码/名称列" in pf.get_etf_premium_discount()

    def test_unknown_code_is_not_silently_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pf, "_call_akshare_api", lambda *a, **k: _spot_frame())
        assert "未在 ETF 实时行情中找到" in pf.get_etf_premium_discount("999999")

    def test_data_source_error_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a, **k):
            raise ConnectionError("网络断了")

        monkeypatch.setattr(pf, "_call_akshare_api", boom)
        out = pf.get_etf_premium_discount("513100")
        assert "数据源访问失败" in out
        assert "网络断了" in out

    def test_empty_frame_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pf, "_call_akshare_api", lambda *a, **k: pd.DataFrame())
        assert "未获取到 ETF 实时行情数据" in pf.get_etf_premium_discount()


class TestCumNavComparable:
    """份额折算会把单位净值重置为 1.0，此后累计净值不再与收益率可比。"""

    def test_steady_ratio_is_comparable(self) -> None:
        unit = _series([1.0, 1.02, 1.04, 1.06])
        cum = _series([1.0, 1.05, 1.10, 1.15])
        assert ix.cum_nav_is_comparable(unit, cum) is True

    def test_ratio_jump_is_not_comparable(self) -> None:
        unit = _series([1.0, 1.2, 1.0, 0.6])
        cum = _series([1.0, 1.2, 1.44, 1.7])
        assert ix.cum_nav_is_comparable(unit, cum) is False

    def test_missing_side_is_treated_as_comparable(self) -> None:
        assert ix.cum_nav_is_comparable(None, _series([1.0, 1.1, 1.2])) is True
        assert ix.cum_nav_is_comparable(_series([1.0, 1.1, 1.2]), None) is True

    def test_too_short_is_treated_as_comparable(self) -> None:
        assert ix.cum_nav_is_comparable(_series([1.0, 1.0]), _series([1.0, 3.0])) is True


class TestComputeTrackingStats:
    """纯计算：完全跟踪 -> TE 0；两倍弹性 -> TE 明显放大；样本不足 -> None。"""

    def test_identical_series_has_zero_tracking_error(self) -> None:
        series = _series([100.0, 101, 102, 103, 104, 105])
        stats = ix.compute_tracking_stats(series, series)
        assert stats["observations"] == 6
        assert stats["tracking_error_pct"] == 0.0
        assert stats["tracking_difference_pct"] == 0.0
        assert stats["mean_abs_deviation_pct"] == 0.0
        assert stats["cumulative_excess_pct"] == 0.0
        # 收益完全同步 -> 相关系数 1.0（差异序列为零才是 TE 0）
        assert stats["correlation"] == 1.0

    def test_leveraged_fund_shows_large_tracking_error(self) -> None:
        index = _series([100.0, 100, 102, 101, 103, 104])
        fund = _series([100.0, 100, 104, 102, 106, 108])
        stats = ix.compute_tracking_stats(fund, index)
        assert stats["tracking_error_pct"] > 0
        assert stats["fund_return_pct"] > stats["index_return_pct"]
        assert stats["cumulative_excess_pct"] > 0
        assert stats["correlation"] > 0.99

    def test_partial_overlap_uses_common_days_only(self) -> None:
        fund = _series(
            [100.0, 101, 102, 103, 104], ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        )
        index = _series([50.0, 51, 52], ["2024-01-03", "2024-01-04", "2024-01-05"])
        stats = ix.compute_tracking_stats(fund, index)
        assert stats["observations"] == 3
        assert stats["start"] == "2024-01-03"

    def test_insufficient_overlap_returns_none_metrics(self) -> None:
        fund = _series([100.0, 101], ["2024-01-01", "2024-01-02"])
        index = _series([50.0, 51], ["2024-01-01", "2024-01-02"])
        stats = ix.compute_tracking_stats(fund, index)
        assert stats["observations"] == 2
        assert stats["tracking_error_pct"] is None
        assert stats["fund_return_pct"] is None


class TestFetchFundReturnSeries:
    """口径优先级：ETF/指数用前复权价；公募在无折算时用累计净值；折算后退前复权价再退单位净值。"""

    @staticmethod
    def _fake_api(
        monkeypatch: pytest.MonkeyPatch, *, cum: list[float] | None, unit: list[float] | None, price: list[float] | None
    ) -> None:
        dates = ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]

        def fake(func, *args, **kwargs):
            name = getattr(func, "__name__", "")
            if name == "fund_open_fund_info_em":
                indicator = kwargs.get("indicator", "")
                if indicator.startswith("累计") and cum is not None:
                    return pd.DataFrame({"净值日期": dates, "累计净值": cum})
                if indicator.startswith("单位") and unit is not None:
                    return pd.DataFrame({"净值日期": dates, "单位净值": unit})
                return pd.DataFrame()
            if name == "fund_etf_hist_em" and price is not None:
                return pd.DataFrame({"日期": dates, "收盘": price})
            return pd.DataFrame()

        monkeypatch.setattr(ix, "_call_akshare_api", fake)

    def test_etf_uses_adjusted_price(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ix, "detect_asset_type", lambda symbol: AssetType.ETF)
        self._fake_api(monkeypatch, cum=None, unit=None, price=[1.0, 1.1, 1.2, 1.3])
        series, basis = ix.fetch_fund_return_series("510300", "2024-01-01", "2024-12-31")
        assert series is not None
        assert series.tolist() == [1.0, 1.1, 1.2, 1.3]
        assert "前复权" in basis

    def test_public_fund_prefers_clean_cumulative_nav(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ix, "detect_asset_type", lambda symbol: AssetType.PUBLIC_FUND)
        self._fake_api(
            monkeypatch, cum=[1.0, 1.05, 1.10, 1.15], unit=[1.0, 1.02, 1.04, 1.06], price=[1.0, 1.05, 1.1, 1.15]
        )
        series, basis = ix.fetch_fund_return_series("110020", "2024-01-01", "2024-12-31")
        assert series is not None
        assert series.tolist() == [1.0, 1.05, 1.1, 1.15]
        assert "累计净值" in basis

    def test_split_fund_falls_back_to_adjusted_price(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ix, "detect_asset_type", lambda symbol: AssetType.OFFSHORE_FUND)
        self._fake_api(monkeypatch, cum=[1.0, 1.2, 1.44, 1.7], unit=[1.0, 1.2, 1.0, 0.6], price=[1.0, 0.8, 0.5, 0.4])
        series, basis = ix.fetch_fund_return_series("161725", "2024-01-01", "2024-12-31")
        assert series is not None
        assert series.tolist() == [1.0, 0.8, 0.5, 0.4]
        assert "份额折算" in basis

    def test_split_fund_without_market_price_uses_unit_nav(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ix, "detect_asset_type", lambda symbol: AssetType.PUBLIC_FUND)
        self._fake_api(monkeypatch, cum=[1.0, 1.2, 1.44, 1.7], unit=[1.0, 1.2, 1.0, 0.6], price=None)
        series, basis = ix.fetch_fund_return_series("161725", "2024-01-01", "2024-12-31")
        assert series is not None
        assert series.tolist() == [1.0, 1.2, 1.0, 0.6]
        assert "分红未计入" in basis

    def test_nothing_available_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ix, "detect_asset_type", lambda symbol: AssetType.PUBLIC_FUND)
        self._fake_api(monkeypatch, cum=None, unit=None, price=None)
        series, basis = ix.fetch_fund_return_series("161725", "2024-01-01", "2024-12-31")
        assert series is None
        assert basis == ""


class TestGetTrackingError:
    """指数代码留空时自动识别；识别不到必须报错而不是拿别的指数顶替。"""

    def test_reports_metrics_with_explicit_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ix,
            "_fund_close_series",
            lambda s, a, b: (_series([1.0, 1.01, 1.02, 1.03]), "ETF 前复权收盘价（分红已还原）"),
        )
        monkeypatch.setattr(ix, "_index_close_series", lambda code, a, b: _series([100.0, 100.5, 101.0, 101.5]))
        out = ix.get_tracking_error("510300", index_code="000300")
        assert "年化跟踪误差" in out
        assert "调用方显式指定" in out
        assert "000300" in out

    def test_unresolved_index_explains_overseas_limits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ix,
            "_resolve_index_code",
            lambda symbol: ("", "", "基金名称未匹配到已知 A 股指数（大成纳斯达克100ETF联接）"),
        )
        out = ix.get_tracking_error("000834")
        assert "未能确定" in out
        assert "海外指数" in out
        assert "沪深300(000300)" in out

    def test_missing_fund_series_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ix, "_fund_close_series", lambda s, a, b: (None, ""))
        out = ix.get_tracking_error("510300", index_code="000300")
        assert "未取到" in out
        assert "无法计算跟踪误差" in out

    def test_insufficient_overlap_refuses_to_conclude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ix, "_fund_close_series", lambda s, a, b: (_series([1.0, 1.01]), "口径"))
        monkeypatch.setattr(ix, "_index_close_series", lambda code, a, b: _series([100.0, 101.0]))
        out = ix.get_tracking_error("510300", index_code="000300")
        assert "样本不足" in out

    def test_days_are_clamped_to_supported_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, str] = {}

        def fake_fund(symbol: str, start: str, end: str):
            seen["start"] = start
            return None, ""

        monkeypatch.setattr(ix, "_fund_close_series", fake_fund)
        ix.get_tracking_error("510300", index_code="000300", days=99999)
        assert seen["start"] != ""


class TestGetFxRate:
    """区间变动以中行折算价为准（央行中间价周末为空，只作参考）。"""

    @staticmethod
    def _frame() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "日期": ["2026-09-16", "2026-09-17", "2026-10-16"],
                "央行中间价": [676.28, None, 672.20],
                "中行折算价": [676.28, 674.00, 672.20],
            }
        )

    def test_reports_conversion_price_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(macro, "_call_akshare_api", lambda *a, **k: self._frame())
        out = macro.get_fx_rate("美元", 30)
        assert "人民币元 / 100 外币" in out
        assert "672.2000" in out
        assert "-0.60%" in out
        assert "央行中间价" in out

    def test_missing_price_columns_reports_clearly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            macro, "_call_akshare_api", lambda *a, **k: pd.DataFrame({"日期": ["2026-10-16"], "中行汇买价": [672.0]})
        )
        assert "无法计算" in macro.get_fx_rate("美元", 30)

    def test_empty_frame_lists_supported_currencies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(macro, "_call_akshare_api", lambda *a, **k: pd.DataFrame())
        out = macro.get_fx_rate("美元", 30)
        assert "未获取到" in out
        assert "欧元" in out

    def test_data_source_error_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a, **k):
            raise ConnectionError("网络断了")

        monkeypatch.setattr(macro, "_call_akshare_api", boom)
        out = macro.get_fx_rate("美元", 30)
        assert "数据源访问失败" in out
        assert "网络断了" in out

    def test_window_is_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, str] = {}

        def fake(func, *args, **kwargs):
            seen["start"] = kwargs.get("start_date", "")
            seen["end"] = kwargs.get("end_date", "")
            return self._frame()

        monkeypatch.setattr(macro, "_call_akshare_api", fake)
        macro.get_fx_rate("美元", 99999)
        delta = pd.to_datetime(seen["end"]) - pd.to_datetime(seen["start"])
        assert delta.days == macro._FX_MAX_DAYS


class TestCsindexCodeAccessor:
    def test_returns_copy_not_internal_dict(self) -> None:
        codes = macro.csindex_codes()
        codes["沪深300"] = "999999"
        assert macro.csindex_codes()["沪深300"] == "000300"

    def test_covers_known_indexes(self) -> None:
        codes = macro.csindex_codes()
        assert codes["中证白酒"] == "399997"
        assert codes["中证1000"] == "000852"
