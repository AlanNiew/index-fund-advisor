# tests/test_backtest_fees.py
"""P1 回测口径修正：交易成本模型、净值口径、无风险利率来源。

这些测试刻意把「价格口径」与「投资者口径」的差额写成可手算的数字 —— 回测最危险的
失败模式不是报错，而是给出一个看起来合理、实际口径错的收益率。
"""

from __future__ import annotations

import pandas as pd
import pytest

from ifa.backtest import engine
from ifa.backtest.fees import (
    DEFAULT_COMMISSION_PCT,
    DEFAULT_PURCHASE_PCT,
    DEFAULT_REDEMPTION_PCT,
    FeeAssumptions,
    _operating_fee_pct,
    _parse_pct,
    _pick_redemption_pct,
    _tier_lower_bound,
    resolve_fees,
)

REDEMPTION_TABLE = pd.DataFrame(
    {
        "持有期限": ["小<7天", "大于等于7天，小于365天", "大于等于365天，小于730天", "大于等于730天"],
        "赎回费率": ["1.50%", "0.50%", "0.25%", "0.00%"],
    }
)
OPERATING_TABLE = pd.DataFrame(
    [["管理费率", "1.00%（每年）", "托管费率", "0.20%（每年）", "销售服务费率", "0.00%（每年）"]]
)


class TestParseHelpers:
    def test_parse_pct_variants(self) -> None:
        assert _parse_pct("1.50%") == 1.5
        assert _parse_pct("0.20%（每年）") == 0.2
        assert _parse_pct("无") is None
        assert _parse_pct(None) is None

    def test_operating_fee_sums_management_and_custody(self) -> None:
        # 管理费 1.00 + 托管费 0.20 + 销售服务费 0.00
        assert _operating_fee_pct(OPERATING_TABLE) == 1.2

    def test_operating_fee_without_percentages_is_none(self) -> None:
        assert _operating_fee_pct(pd.DataFrame([["管理费率", "见说明书"]])) is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("小<7天", 0),
            ("大于等于7天，小于365天", 7),
            ("大于等于365天，小于730天", 365),
            ("大于等于730天", 730),
            ("没有数字", 0),
        ],
    )
    def test_tier_lower_bound(self, text: str, expected: int) -> None:
        assert _tier_lower_bound(text) == expected

    @pytest.mark.parametrize(
        ("holding_days", "expected"),
        [(3, 1.5), (7, 0.5), (200, 0.5), (365, 0.25), (400, 0.25), (800, 0.0)],
    )
    def test_pick_redemption_pct_by_holding_period(self, holding_days: int, expected: float) -> None:
        assert _pick_redemption_pct(REDEMPTION_TABLE, holding_days) == expected

    def test_pick_redemption_pct_needs_two_columns(self) -> None:
        assert _pick_redemption_pct(pd.DataFrame({"持有期限": ["小<7天"]}), 3) is None


class TestFeeAssumptions:
    def test_entry_exit_split(self) -> None:
        fees = FeeAssumptions(applies=True, purchase_pct=0.15, redemption_pct=0.5, commission_pct=0.03)
        assert fees.entry_pct == pytest.approx(0.18)
        assert fees.exit_pct == pytest.approx(0.53)

    def test_describe_mentions_every_component(self) -> None:
        fees = FeeAssumptions(
            applies=True,
            holding_days=400,
            purchase_pct=0.15,
            redemption_pct=0.25,
            commission_pct=0.03,
            operating_pct=1.2,
        )
        text = fees.describe()
        assert "申购费 0.15%" in text
        assert "赎回费 0.25%（持有 400 天）" in text
        assert "券商佣金 0.030%/单边" in text
        assert "运作费率 1.20%/年已含在净值中（不重复扣除）" in text

    def test_describe_when_fees_disabled(self) -> None:
        assert "未计任何交易成本" in FeeAssumptions(applies=False).describe()

    def test_as_dict_rounds_and_keeps_notes(self) -> None:
        payload = FeeAssumptions(applies=True, purchase_pct=0.123456, notes=("a", "b")).as_dict()
        assert payload["purchase_pct"] == 0.1235
        assert payload["notes"] == ["a", "b"]
        assert payload["operating_pct"] is None


class TestResolveFees:
    def test_index_is_not_investable_so_no_fees(self) -> None:
        fees = resolve_fees("000300", "INDEX", 400)
        assert fees.applies is False
        assert fees.source == "not_applicable"
        assert any("不可直接投资" in note for note in fees.notes)

    def test_etf_uses_commission_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "ifa.dataflows.a_share_public_fund.fetch_fund_fee_table",
            lambda symbol, indicator: OPERATING_TABLE if indicator == "运作费用" else None,
        )
        fees = resolve_fees("510300", "ETF", 400)
        assert fees.commission_pct == DEFAULT_COMMISSION_PCT
        assert fees.purchase_pct == 0.0
        assert fees.operating_pct == 1.2
        assert any("默认" in note for note in fees.notes)

    def test_etf_commission_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "ifa.dataflows.a_share_public_fund.fetch_fund_fee_table",
            lambda symbol, indicator: None,
        )
        fees = resolve_fees("510300", "ETF", 400, commission_pct=0.01)
        assert fees.commission_pct == 0.01
        assert fees.source == "explicit"

    def test_public_fund_uses_real_fee_tables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake(symbol: str, indicator: str):
            if indicator == "运作费用":
                return OPERATING_TABLE
            if indicator == "赎回费率":
                return REDEMPTION_TABLE
            if indicator == "申购费率":
                return pd.DataFrame([["申购费率", "0.12%"]])
            return None

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_fee_table", fake)
        fees = resolve_fees("161725", "PUBLIC_FUND", 400)
        assert fees.purchase_pct == 0.12
        assert fees.redemption_pct == 0.25  # 持有 400 天 → 365~730 档
        assert fees.source == "fund_fee_em"
        assert fees.notes == ()

    def test_public_fund_falls_back_to_conservative_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "ifa.dataflows.a_share_public_fund.fetch_fund_fee_table",
            lambda symbol, indicator: None,
        )
        fees = resolve_fees("161725", "PUBLIC_FUND", 30)
        assert fees.purchase_pct == DEFAULT_PURCHASE_PCT
        assert fees.redemption_pct == DEFAULT_REDEMPTION_PCT
        assert fees.source == "default"
        assert len([n for n in fees.notes if "保守估算" in n]) == 2

    def test_public_fund_survives_fee_api_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(symbol: str, indicator: str):
            raise RuntimeError("network down")

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_fee_table", boom)
        fees = resolve_fees("161725", "PUBLIC_FUND", 30)
        assert fees.source == "default"
        assert any("费率接口失败" in note for note in fees.notes)

    def test_unknown_asset_type_is_not_charged(self) -> None:
        assert resolve_fees("x", "UNKNOWN", 10).applies is False


def _price_frame(dates: list[str], closes: list[float], basis: str = "测试口径", asset: str = "ETF") -> pd.DataFrame:
    df = pd.DataFrame({"date": pd.to_datetime(dates), "close": closes})
    df.attrs["price_basis"] = basis
    df.attrs["asset_type"] = asset
    return df


class TestRunBacktestCosts:
    """价格口径 100 → 120；申购 1.0%、赎回 0.5%、无佣金。"""

    @staticmethod
    def _fake_fetch(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=250, freq="B").strftime("%Y-%m-%d").tolist()
        closes = [100.0 + 20.0 * i / 249 for i in range(250)]
        return _price_frame(dates, closes)

    @pytest.fixture(autouse=True)
    def _patch(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(engine, "_fetch_price_data", self._fake_fetch)
        monkeypatch.setattr(engine, "resolve_risk_free_rate", lambda: (1.65, "中债10年期国债收益率"))
        monkeypatch.setattr(
            engine,
            "resolve_fees",
            lambda symbol, asset_type, holding_days, commission_pct=None: FeeAssumptions(
                applies=True,
                holding_days=holding_days,
                purchase_pct=1.0,
                redemption_pct=0.5,
                operating_pct=1.2,
            ),
        )

    def test_net_math_is_hand_checkable(self) -> None:
        result = engine.run_backtest("510300", "2024-01-01", "2024-12-31")
        assert result.error == ""
        # 价格口径：100 → 120
        assert result.total_return_pct == pytest.approx(20.0)
        assert result.final_value == pytest.approx(120000.0, abs=0.01)
        # 投资者口径：100000 × 0.99 = 99000 → ×1.2 = 118800 → ×0.995 = 118206
        assert result.net_final_value == pytest.approx(118206.0, abs=0.02)
        assert result.net_total_return_pct == pytest.approx(18.21, abs=0.01)
        assert result.fee_impact_pct == pytest.approx(1.79, abs=0.01)
        assert result.risk_free_rate_pct == pytest.approx(1.65)
        assert result.risk_free_source == "中债10年期国债收益率"
        assert result.price_basis == "测试口径"
        assert result.fee_assumptions["describe"]

    def test_equity_curve_starts_at_cost_basis(self) -> None:
        result = engine.run_backtest("510300", "2024-01-01", "2024-12-31")
        assert result.equity_curve[0]["value"] == pytest.approx(99000.0, abs=1.0)

    def test_include_fees_false_equals_price_basis(self) -> None:
        result = engine.run_backtest("510300", "2024-01-01", "2024-12-31", include_fees=False)
        assert result.net_final_value == pytest.approx(120000.0, abs=0.01)
        assert result.net_total_return_pct == pytest.approx(20.0)
        assert result.fee_impact_pct == pytest.approx(0.0)
        assert result.fee_assumptions["source"] == "disabled"

    def test_fee_resolution_failure_degrades_instead_of_raising(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("fee source down")

        monkeypatch.setattr(engine, "resolve_fees", boom)
        result = engine.run_backtest("510300", "2024-01-01", "2024-12-31")
        assert result.error == ""
        assert result.net_total_return_pct == pytest.approx(20.0)
        assert result.fee_assumptions["source"] == "error"
        assert any("未计交易成本" in note for note in result.fee_assumptions["notes"])

    def test_report_shows_both_bases(self) -> None:
        result = engine.run_backtest("510300", "2024-01-01", "2024-12-31")
        report = engine.format_backtest_report(result)
        assert "交易成本口径" in report
        assert "投资者口径（计费后）总收益：**+18.21%**" in report
        assert "费用拖累：1.79 个百分点" in report
        assert "已包含在净值中" in report
        assert "中债10年期国债收益率" in report


class TestPriceBasisLabel:
    def test_labels_are_distinct(self) -> None:
        assert "前复权" in engine._price_basis_label("ETF")
        assert "不含分红" in engine._price_basis_label("INDEX")
        # 场外基金的具体口径（累计净值 / 单位净值）只有取数后才知道，_fetch_fund_data 会写进
        # df.attrs["price_basis"]；这里的兜底文案刻意不宣称是累计净值。
        assert engine._price_basis_label("PUBLIC_FUND") == "基金净值（口径见下）"
        assert engine._price_basis_label("SOMETHING") == "收盘价"

    def test_holding_days_counts_calendar_days(self) -> None:
        df = pd.DataFrame({"date": pd.to_datetime(["2024-01-01", "2024-12-31"]), "close": [1.0, 2.0]})
        assert engine._holding_days(df) == 365


class TestFundNavBasis:
    """累计净值优先；退回单位净值时口径必须写在 attrs 上，不能悄悄变乐观。"""

    def test_prefers_cumulative_nav(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake(symbol: str, indicator: str = "累计净值走势") -> pd.DataFrame:
            calls.append(indicator)
            return pd.DataFrame({"净值日期": ["2024-01-01", "2024-06-30"], "累计净值": [1.0, 1.2]})

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_nav_series", fake)
        df = engine._fetch_fund_data("161725", "2024-01-01", "2024-12-31")
        assert df is not None
        assert calls == ["累计净值走势", "单位净值走势"]
        assert "累计净值" in df.attrs["price_basis"]
        assert df["close"].tolist() == [1.0, 1.2]

    def test_falls_back_to_unit_nav_and_labels_the_drawback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake(symbol: str, indicator: str = "累计净值走势") -> pd.DataFrame:
            if indicator == "累计净值走势":
                return pd.DataFrame()
            return pd.DataFrame({"净值日期": ["2024-01-01", "2024-06-30"], "单位净值": [1.0, 1.1]})

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_nav_series", fake)
        df = engine._fetch_fund_data("161725", "2024-01-01", "2024-12-31")
        assert df is not None
        assert "未计分红" in df.attrs["price_basis"]

    def test_data_source_error_is_not_reported_as_insufficient_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake(symbol: str, indicator: str = "累计净值走势") -> pd.DataFrame:
            raise ValueError("DATA_SOURCE_ERRORConnectionError: boom")

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_nav_series", fake)
        result = engine.run_backtest("161725", "2024-01-01", "2024-12-31")
        assert "数据获取失败" in result.error
        assert "ConnectionError: boom" in result.error

    def test_split_nav_falls_back_to_adjusted_price(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """份额折算后累计净值不可比，必须改用前复权价（含分红与折算还原）。"""

        def fake(symbol: str, indicator: str = "累计净值走势") -> pd.DataFrame:
            if indicator == "累计净值走势":
                return pd.DataFrame(
                    {"净值日期": ["2024-01-01", "2024-06-30", "2024-12-31"], "累计净值": [1.0, 1.2, 1.44]}
                )
            return pd.DataFrame({"净值日期": ["2024-01-01", "2024-06-30", "2024-12-31"], "单位净值": [1.0, 1.0, 0.6]})

        def fake_price(symbol: str, start_date: str, end_date: str):
            idx = pd.to_datetime(["2024-01-01", "2024-06-30", "2024-12-31"])
            return pd.Series([1.0, 0.7, 0.4], index=idx), "ETF/LOF 前复权收盘价（分红与份额折算已还原）"

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_nav_series", fake)
        monkeypatch.setattr("ifa.dataflows.a_share_index_fund._etf_price_series", fake_price)
        df = engine._fetch_fund_data("161725", "2024-01-01", "2024-12-31")
        assert df is not None
        assert "份额折算" in df.attrs["price_basis"]
        assert "前复权价" in df.attrs["price_basis"]
        assert df["close"].tolist() == [1.0, 0.7, 0.4]

    def test_split_nav_without_market_price_labels_unit_nav(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """没有场内价可退时只能退回单位净值，并且必须写明原因与代价。"""

        def fake(symbol: str, indicator: str = "累计净值走势") -> pd.DataFrame:
            if indicator == "累计净值走势":
                return pd.DataFrame(
                    {"净值日期": ["2024-01-01", "2024-06-30", "2024-12-31"], "累计净值": [1.0, 1.2, 1.44]}
                )
            return pd.DataFrame({"净值日期": ["2024-01-01", "2024-06-30", "2024-12-31"], "单位净值": [1.0, 1.0, 0.6]})

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_nav_series", fake)
        monkeypatch.setattr("ifa.dataflows.a_share_index_fund._etf_price_series", lambda *a, **k: (None, ""))
        df = engine._fetch_fund_data("161725", "2024-01-01", "2024-12-31")
        assert df is not None
        assert "份额折算" in df.attrs["price_basis"]
        assert "分红未计入" in df.attrs["price_basis"]
        assert df["close"].tolist() == [1.0, 1.0, 0.6]

    def test_misclassified_fund_still_fetches_nav(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """资产类型被判成股票（实测 000834）时不能直接放弃，否则回测是 0 天。"""
        from ifa.dataflows.asset_type import AssetType

        frame = pd.DataFrame({"date": pd.to_datetime(["2024-01-01", "2024-12-31"]), "close": [1.0, 1.1]})
        frame.attrs["price_basis"] = "基金累计净值（分红再投已计入）"
        monkeypatch.setattr("ifa.dataflows.asset_type.detect_asset_type", lambda symbol: AssetType.STOCK)
        monkeypatch.setattr(engine, "_fetch_fund_data", lambda *a, **k: frame.copy())
        df = engine._fetch_price_data("000834", "2024-01-01", "2024-12-31")
        assert df is not None
        assert df.attrs["price_basis"] == "基金累计净值（分红再投已计入）"

    def test_short_window_still_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake(symbol: str, indicator: str = "累计净值走势") -> pd.DataFrame:
            return pd.DataFrame({"净值日期": ["2024-01-01"], "累计净值": [1.0]})

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_nav_series", fake)
        assert engine._fetch_fund_data("161725", "2024-01-01", "2024-12-31") is None
