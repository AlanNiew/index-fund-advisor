"""宏观数据参数校验测试 — 不调用实际 API，仅验证参数校验和纯函数逻辑。"""

from datetime import date

import pandas as pd
import pytest

import ifa.dataflows.a_share_macro as macro
from ifa.dataflows.a_share_macro import (
    _INDEX_METHODS,
    _INDEX_VALUATION_NAMES,
    _calc_bogle_pb_signal,
    _calc_bogle_pe_signal,
    _calc_ey_signal,
    _clean_float,
    _compute_metric,
    _get_bond_yield_10y,
    _valuation_label,
    fetch_index_dividend_yield,
    fetch_valuation_metrics,
    get_index_valuation,
    get_macro_indicator,
    get_market_valuation,
    get_north_flow,
    get_valuation_signal,
)

# ════════════════════════════════════════════
#  参数校验
# ════════════════════════════════════════════


class TestMacroIndicatorValidation:
    """get_macro_indicator 参数校验测试。"""

    def test_invalid_indicator_shows_options(self):
        """无效指标返回包含可选值列表的错误提示。"""
        result = get_macro_indicator("INVALID_METRIC")
        assert "不支持的宏观指标" in result
        assert "GDP" in result  # 确保可选值中包含 GDP

    def test_invalid_indicator_case_insensitive(self):
        """指标参数不区分大小写（大小写规范化）。"""
        # 小写的 "gdp" 应被 .upper() 转为 "GDP"，是有效指标
        # 但会调用 API，所以只测试无效参数
        result = get_macro_indicator("notexist")
        assert "不支持的宏观指标" in result


class TestNorthFlowValidation:
    """get_north_flow 参数回退测试。"""

    def test_invalid_symbol_falls_back(self):
        """无效渠道自动回退到北向资金（mock AkShare，不依赖网络）。"""
        from unittest.mock import patch

        fake_df = pd.DataFrame({
            "日期": ["2024-01-01", "2024-01-02"],
            "当日成交净买额": [100.5, -50.3],
            "买入成交额": [200.0, 150.0],
            "卖出成交额": [99.5, 200.3],
            "历史累计净买额": [1000.0, 949.7],
            "当日资金流入": [100.5, -50.3],
        })

        with patch("ifa.dataflows.a_share_macro._call_akshare_api", return_value=fake_df):
            result = get_north_flow("无效渠道")

        assert isinstance(result, str)
        assert "北向资金" in result  # 回退到北向资金
        assert "2024-01-01" in result  # 包含数据行


class TestMarketValuationValidation:
    """get_market_valuation 参数校验测试。"""

    def test_invalid_indicator_shows_options(self):
        """无效估值指标返回包含可选值的错误提示。"""
        result = get_market_valuation("无效PE")
        assert "不支持的估值指标" in result
        assert "上证PE" in result


class TestIndexValuationValidation:
    """get_index_valuation 参数校验测试。"""

    def test_invalid_index_shows_options(self):
        """无效指数返回包含可选值的错误提示。"""
        result = get_index_valuation("纳斯达克100")
        assert "不支持的指数" in result
        # 应列出可用指数
        assert "沪深300" in result

    def test_valid_index_names(self):
        """_INDEX_VALUATION_NAMES 包含预期的指数。"""
        expected = {"沪深300", "上证50", "中证500", "中证1000", "上证红利", "深证100"}
        assert expected == _INDEX_VALUATION_NAMES


class TestValuationSignalValidation:
    """get_valuation_signal 参数校验测试。"""

    def test_invalid_index_shows_options(self):
        """无效指数返回错误提示。"""
        result = get_valuation_signal("标普500")
        assert "不支持的指数" in result

    def test_index_methods_coverage(self):
        """_INDEX_METHODS 覆盖所有支持的指数。"""
        assert set(_INDEX_METHODS.keys()) == _INDEX_VALUATION_NAMES

    def test_method_flags_structure(self):
        """每个指数的方法标志都有 ey/bogle_pe/bogle_pb 键。"""
        for index_name, methods in _INDEX_METHODS.items():
            assert "ey" in methods, f"{index_name} 缺少 ey 标志"
            assert "bogle_pe" in methods, f"{index_name} 缺少 bogle_pe 标志"
            assert "bogle_pb" in methods, f"{index_name} 缺少 bogle_pb 标志"


# ════════════════════════════════════════════
#  纯函数
# ════════════════════════════════════════════


class TestValuationLabel:
    """_valuation_label 百分位标签测试。"""

    def test_severely_undervalued(self):
        """百分位 < 20 为严重低估。"""
        assert _valuation_label(10) == "严重低估"
        assert _valuation_label(19.9) == "严重低估"

    def test_undervalued(self):
        """20 <= 百分位 < 30 为低估。"""
        assert _valuation_label(20) == "低估"
        assert _valuation_label(29) == "低估"

    def test_slightly_low(self):
        """30 <= 百分位 < 40 为偏低。"""
        assert _valuation_label(30) == "偏低"
        assert _valuation_label(39) == "偏低"

    def test_reasonable(self):
        """40 <= 百分位 < 60 为合理。"""
        assert _valuation_label(40) == "合理"
        assert _valuation_label(50) == "合理"
        assert _valuation_label(59) == "合理"

    def test_slightly_high(self):
        """60 <= 百分位 < 70 为偏高。"""
        assert _valuation_label(60) == "偏高"
        assert _valuation_label(69) == "偏高"

    def test_overvalued(self):
        """70 <= 百分位 < 80 为高估。"""
        assert _valuation_label(70) == "高估"
        assert _valuation_label(79) == "高估"

    def test_severely_overvalued(self):
        """百分位 >= 80 为严重高估。"""
        assert _valuation_label(80) == "严重高估"
        assert _valuation_label(95) == "严重高估"


class TestComputeMetric:
    """_compute_metric 空数据处理测试。"""

    def test_empty_series(self):
        """空 Series 返回暂无数据。"""
        series = pd.Series([], dtype=float)
        result = _compute_metric(series, "PE")
        assert "暂无数据" in result

    def test_all_nan_series(self):
        """全 NaN 的 Series 返回暂无数据。"""
        series = pd.Series([float("nan"), float("nan")])
        result = _compute_metric(series, "PB")
        assert "暂无数据" in result

    def test_valid_series_format(self):
        """有效 Series 返回 Markdown 表格行格式。"""
        series = pd.Series([10.0, 12.0, 11.5, 13.0, 12.5])
        result = _compute_metric(series, "PE-TTM")
        assert "PE-TTM" in result
        assert "12.50" in result  # 当前值（最后一个）


# ════════════════════════════════════════════
#  估值信号数学（纯函数，无网络）
# ════════════════════════════════════════════


class TestCleanFloat:
    """_clean_float 把 NaN/inf/非数值统一收敛为 None。"""

    def test_invalid_values_become_none(self):
        assert _clean_float(None) is None
        assert _clean_float("abc") is None
        assert _clean_float([]) is None

    def test_nan_and_inf_become_none(self):
        assert _clean_float(float("nan")) is None
        assert _clean_float(float("inf")) is None
        assert _clean_float(float("-inf")) is None

    def test_normal_values_pass_through(self):
        assert _clean_float(12.5) == 12.5
        assert _clean_float("12.5") == 12.5
        assert _clean_float(0) == 0.0


def _line_containing(lines: list[str], marker: str) -> str:
    return next(line for line in lines if marker in line)


class TestEarningsYieldSignal:
    """盈利收益率法：EY > 2×国债 → 买入；EY < 国债 → 卖出；其余持有。"""

    def test_buy_branch(self):
        lines = _calc_ey_signal(pe_ttm=5.0, bond_yield=3.0)  # EY=20% > 6%
        assert "买入" in _line_containing(lines, "投资信号")
        assert "| 盈利收益率(EY) | 20.00% |" in lines

    def test_hold_branch(self):
        lines = _calc_ey_signal(pe_ttm=25.0, bond_yield=3.0)  # EY=4%，落在 3%~6%
        assert "持有" in _line_containing(lines, "投资信号")

    def test_sell_branch(self):
        lines = _calc_ey_signal(pe_ttm=50.0, bond_yield=3.0)  # EY=2% < 3%
        assert "卖出" in _line_containing(lines, "投资信号")

    def test_zero_pe_is_treated_as_zero_ey(self):
        """PE<=0（亏损指数）不能触发除零，应落到卖出分支。"""
        lines = _calc_ey_signal(pe_ttm=0.0, bond_yield=3.0)
        assert "| 盈利收益率(EY) | 0.00% |" in lines
        assert "卖出" in _line_containing(lines, "投资信号")

    def test_thresholds_derive_from_bond_yield(self):
        lines = _calc_ey_signal(pe_ttm=20.0, bond_yield=2.5)
        assert "| 国债收益率 × 2（买入线） | 5.00% |" in lines
        assert "| 国债收益率 × 1（卖出线） | 2.50% |" in lines


class TestBoglePeSignal:
    """博格公式（PE）：股息率 + EPS 增长率 + PE 均值回归。"""

    _SHORT = pd.Series([10.0, 11.0, 12.0])
    _LONG = pd.Series([20 - i * (10 / 1299) for i in range(1300)])  # ≥1260 才启用 EPS 推算

    def test_short_series_reports_no_eps_data(self):
        lines = _calc_bogle_pe_signal(12.0, self._SHORT, 2.5)
        assert "暂无数据" in _line_containing(lines, "EPS")

    def test_long_series_computes_eps_growth(self):
        lines = _calc_bogle_pe_signal(10.0, self._LONG, 2.5)
        eps_line = _line_containing(lines, "EPS")
        assert "暂无数据" not in eps_line
        assert "%" in eps_line

    def test_none_dividend_yield_is_labelled(self):
        lines = _calc_bogle_pe_signal(12.0, self._SHORT, None)
        assert "暂无数据" in _line_containing(lines, "股息率")

    def test_expected_return_line_present(self):
        lines = _calc_bogle_pe_signal(12.0, self._SHORT, 2.5)
        assert any("预期年化收益率" in line for line in lines)

    def test_zero_pe_does_not_crash(self):
        lines = _calc_bogle_pe_signal(0.0, self._SHORT, 2.5)
        assert any("PE 均值回归贡献" in line for line in lines)


class TestBoglePbSignal:
    """博格公式（PB）：ROE ≈ PB/PE + PB 均值回归。"""

    def test_roe_and_mean_reversion(self):
        lines = _calc_bogle_pb_signal(pb=1.5, pe_ttm=12.0, pb_series=pd.Series([1.0, 1.2, 1.5, 1.3, 1.4]))
        assert "12.50%" in _line_containing(lines, "ROE")  # 1.5 / 12 × 100
        assert any("PB 均值回归贡献" in line for line in lines)

    def test_zero_pe_yields_zero_roe(self):
        lines = _calc_bogle_pb_signal(pb=1.5, pe_ttm=0.0, pb_series=pd.Series([1.0, 1.5]))
        assert "0.00%" in _line_containing(lines, "ROE")

    def test_zero_pb_does_not_crash(self):
        lines = _calc_bogle_pb_signal(pb=0.0, pe_ttm=12.0, pb_series=pd.Series([1.0, 1.5]))
        assert any("预期年化收益率" in line for line in lines)


class TestBondYield10Y:
    """10 年期国债收益率取值与降级。"""

    @staticmethod
    def _df(curve: str = "中债国债收益率曲线", value: float = 2.75) -> pd.DataFrame:
        return pd.DataFrame({"曲线名称": [curve], "10年": [value]})

    def test_success(self, monkeypatch):
        monkeypatch.setattr(macro, "_call_akshare_api", lambda *a, **k: self._df())
        assert _get_bond_yield_10y() == 2.75

    def test_missing_curve_returns_none(self, monkeypatch):
        """只有「中债国债收益率曲线」才是无风险利率，其他曲线必须忽略。"""
        monkeypatch.setattr(macro, "_call_akshare_api", lambda *a, **k: self._df(curve="中债中短期票据收益率曲线"))
        assert _get_bond_yield_10y() is None

    def test_exception_returns_none(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("债券接口挂了")

        monkeypatch.setattr(macro, "_call_akshare_api", boom)
        assert _get_bond_yield_10y() is None


def _macro_fake_api(func, *args, **kwargs):
    """按被调用的 akshare 函数名分发假数据。"""
    name = getattr(func, "__name__", "")
    if name == "stock_index_pe_lg":
        return pd.DataFrame({"日期": ["2024-01-02", "2024-01-03"], "滚动市盈率": [11.0, 12.0]})
    if name == "stock_index_pb_lg":
        return pd.DataFrame({"日期": ["2024-01-02", "2024-01-03"], "市净率": [1.2, 1.5]})
    if name == "stock_a_gxl_lg":
        return pd.DataFrame({"日期": ["2024-01-02"], "股息率": [2.5]})
    if name == "stock_zh_index_value_csindex":
        # 真实接口返回的是倒序表（最新在最前）—— 必须取到 2024-01-03 的 2.6
        return pd.DataFrame(
            {
                "日期": [date(2024, 1, 3), date(2024, 1, 2)],
                "市盈率1": [12.0, 11.0],
                "股息率1": [2.6, 2.4],
                "股息率2": [2.4, 2.2],
            }
        )
    raise AssertionError(f"未预期的 akshare 调用: {name}")


class TestFetchIndexDividendYield:
    """指数自身股息率 —— 官方文件是倒序表，取错方向会静默给出过期数据。"""

    def test_takes_latest_row_from_descending_table(self, monkeypatch):
        """akshare 的 indicator.xls 按日期倒序（最新在最前），必须取最新一行而不是 iloc[-1]。"""

        def fake(func, *args, **kwargs):
            assert getattr(func, "__name__", "") == "stock_zh_index_value_csindex"
            return pd.DataFrame(
                {
                    "日期": [date(2024, 1, 3), date(2024, 1, 2)],
                    "市盈率1": [12.0, 11.0],
                    "股息率1": [2.6, 2.4],
                    "股息率2": [2.4, 2.2],
                }
            )

        monkeypatch.setattr(macro, "_call_akshare_api", fake)

        d = fetch_index_dividend_yield("沪深300")
        assert d["available"] is True
        assert d["date"] == "2024-01-03"
        assert d["dividend_yield"] == 2.6  # 总股本口径（主口径）
        assert d["dividend_yield_calc"] == 2.4  # 计算用股本口径
        assert d["source"] == "csindex:000300"

    def test_unregistered_index_does_not_call_api(self, monkeypatch):
        """未实测可用的指数直接返回 available=False，绝不拿别的指数顶上。"""

        def boom(*args, **kwargs):
            raise AssertionError("未登记的指数不应发起请求")

        monkeypatch.setattr(macro, "_call_akshare_api", boom)

        d = fetch_index_dividend_yield("创业板50")
        assert d["available"] is False
        assert d["dividend_yield"] is None
        assert d["source"] is None

    def test_fetch_failure_is_unavailable(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("404 Not Found")

        monkeypatch.setattr(macro, "_call_akshare_api", boom)

        d = fetch_index_dividend_yield("沪深300")
        assert d["available"] is False
        assert d["date"] is None

    def test_nan_dividend_is_unavailable_not_zero(self, monkeypatch):
        """官方文件首行是表头文本，数值被 akshare 转成 NaN —— 不能当成 0。"""

        def fake(func, *args, **kwargs):
            return pd.DataFrame({"日期": [pd.NaT, date(2024, 1, 3)], "股息率1": [float("nan"), float("nan")]})

        monkeypatch.setattr(macro, "_call_akshare_api", fake)

        d = fetch_index_dividend_yield("沪深300")
        assert d["available"] is False
        assert d["dividend_yield"] is None
        assert d["date"] == "2024-01-03"


class TestFetchValuationMetrics:
    """结构化估值指标 —— MCP / 脚本直接消费，字段语义错误会静默传播。"""

    def test_full_success(self, monkeypatch):
        monkeypatch.setattr(macro, "_call_akshare_api", _macro_fake_api)
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        m = fetch_valuation_metrics("沪深300")
        assert m["index_name"] == "沪深300"
        assert m["date"] == "2024-01-03"
        assert m["pe_ttm"] == 12.0
        assert m["pb"] == 1.5
        assert m["roe"] == pytest.approx(12.5)  # PB/PE×100
        assert m["dividend_yield"] == 2.6  # 指数自身（中证指数官方，总股本口径）
        assert m["dividend_yield_source"] == "csindex:000300"
        assert m["dividend_yield_reference"] == 2.5  # 全市场参考值，不可与上面混用
        assert m["earnings_yield"] == pytest.approx(100 / 12)
        assert m["risk_free_rate"] == 2.5
        assert m["erp"] == pytest.approx(round(100 / 12 - 2.5, 2))

    def test_negative_pe_skips_earnings_yield_and_roe(self, monkeypatch):
        def fake(func, *args, **kwargs):
            name = getattr(func, "__name__", "")
            if name == "stock_index_pe_lg":
                return pd.DataFrame({"日期": ["2024-01-02"], "滚动市盈率": [-5.0]})
            if name == "stock_index_pb_lg":
                return pd.DataFrame({"市净率": [1.5]})
            if name == "stock_a_gxl_lg":
                return pd.DataFrame({"股息率": [2.5]})
            raise AssertionError(name)

        monkeypatch.setattr(macro, "_call_akshare_api", fake)
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        m = fetch_valuation_metrics("沪深300")
        assert m["pe_ttm"] == -5.0
        assert m["earnings_yield"] is None
        assert m["roe"] is None
        assert m["erp"] is None

    def test_partial_failure_keeps_other_fields(self, monkeypatch):
        """PE 接口挂了不该影响 PB / 股息率 —— 各数据块独立 try/except。"""

        def fake(func, *args, **kwargs):
            name = getattr(func, "__name__", "")
            if name == "stock_index_pe_lg":
                raise RuntimeError("PE 接口超时")
            if name == "stock_index_pb_lg":
                return pd.DataFrame({"市净率": [1.5]})
            if name == "stock_a_gxl_lg":
                return pd.DataFrame({"股息率": [2.5]})
            if name == "stock_zh_index_value_csindex":
                return pd.DataFrame({"日期": [date(2024, 1, 3)], "股息率1": [2.6]})
            raise AssertionError(name)

        monkeypatch.setattr(macro, "_call_akshare_api", fake)
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        m = fetch_valuation_metrics("沪深300")
        assert m["pe_ttm"] is None
        assert m["pb"] == 1.5
        assert m["dividend_yield"] == 2.6  # 官方口径独立于 PE/PB 的失败
        assert m["dividend_yield_reference"] == 2.5
        assert m["roe"] is None
        assert m["risk_free_rate"] == 2.5

    def test_all_sources_fail_returns_all_none(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("全挂")

        monkeypatch.setattr(macro, "_call_akshare_api", boom)
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: None)

        m = fetch_valuation_metrics("沪深300")
        assert m["index_name"] == "沪深300"
        assert all(value is None for key, value in m.items() if key != "index_name")

    def test_empty_dataframe_is_ignored(self, monkeypatch):
        monkeypatch.setattr(macro, "_call_akshare_api", lambda *a, **k: pd.DataFrame())
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: None)

        m = fetch_valuation_metrics("沪深300")
        assert m["pe_ttm"] is None
        assert m["pb"] is None


class TestValuationSignalComposition:
    """get_valuation_signal 的三方法编排与数据不足分支。"""

    def test_report_contains_overview_and_verdict(self, monkeypatch):
        monkeypatch.setattr(macro, "_call_akshare_api", _macro_fake_api)
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        out = get_valuation_signal("沪深300")
        assert "# Valuation Signal Report: 沪深300" in out
        assert "| 当前 PE-TTM | 12.00 |" in out
        assert "| 当前 PB | 1.50 |" in out
        assert "## 综合判断" in out

    def test_enabled_methods_appear(self, monkeypatch):
        methods = _INDEX_METHODS["沪深300"]
        monkeypatch.setattr(macro, "_call_akshare_api", _macro_fake_api)
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        out = get_valuation_signal("沪深300")
        if methods["ey"]:
            assert "## 方法一：盈利收益率法" in out
        if methods["bogle_pe"]:
            assert "## 方法二：博格公式（市盈率）" in out
        if methods["bogle_pb"]:
            assert "## 方法三：博格公式（市净率）" in out

    def test_no_data_returns_explicit_message(self, monkeypatch):
        monkeypatch.setattr(macro, "_call_akshare_api", lambda *a, **k: None)
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: None)

        out = get_valuation_signal("沪深300")
        assert "未获取到「沪深300」的估值数据。" in out

    def test_missing_bond_yield_marks_method_one_insufficient(self, monkeypatch):
        if not _INDEX_METHODS["沪深300"]["ey"]:
            pytest.skip("该指数未启用盈利收益率法")

        monkeypatch.setattr(macro, "_call_akshare_api", _macro_fake_api)
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: None)

        out = get_valuation_signal("沪深300")
        assert "数据不足，无法计算。" in out


class TestValuationAnchorAnnotations:
    """P0-4：没有估值锚必须显式标注 —— 否则读者会以为评级看过估值百分位。"""

    @staticmethod
    def _fake(pe: bool = True, pb: bool = True):
        def fake(func, *args, **kwargs):
            name = getattr(func, "__name__", "")
            if name == "stock_index_pe_lg":
                if not pe:
                    raise RuntimeError("PE 接口挂了")
                return pd.DataFrame(
                    {
                        "日期": ["2024-01-02", "2024-01-03"],
                        "滚动市盈率": [11.0, 12.0],
                        "静态市盈率": [10.5, 11.5],
                    }
                )
            if name == "stock_index_pb_lg":
                if not pb:
                    raise RuntimeError("PB 接口挂了")
                return pd.DataFrame({"日期": ["2024-01-02", "2024-01-03"], "市净率": [1.2, 1.5]})
            if name == "stock_a_gxl_lg":
                return pd.DataFrame({"日期": ["2024-01-02"], "股息率": [2.5]})
            if name == "stock_zh_index_value_csindex":
                return pd.DataFrame({"日期": [date(2024, 1, 3)], "股息率1": [2.6], "股息率2": [2.4]})
            raise AssertionError(f"未预期的 akshare 调用: {name}")

        return fake

    def test_index_valuation_labels_market_reference(self, monkeypatch):
        """全市场股息率必须自带「市场参考」字样，指数自身股息率单独成行。"""
        monkeypatch.setattr(macro, "_call_akshare_api", self._fake())
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        out = get_index_valuation("沪深300")
        assert "A股股息率(市场参考)" in out
        assert "指数自身股息率（中证指数官方，总股本口径，2024-01-03）: 2.60%" in out
        assert "缺少估值锚" not in out

    def test_index_valuation_flags_missing_anchor(self, monkeypatch):
        """PE/PB 都取不到时明确写「缺少估值锚」，并说明股息率不能替代。"""
        monkeypatch.setattr(macro, "_call_akshare_api", self._fake(pe=False, pb=False))
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        out = get_index_valuation("沪深300")
        assert "缺少估值锚（PE/PB 均不可用）" in out
        assert "股息率不能替代 PE/PB 估值锚" in out
        assert "2.60%" in out

    def test_index_valuation_flags_partial_anchor(self, monkeypatch):
        """只有 PE 没有 PB 时估值锚不完整，同样要标注。"""
        monkeypatch.setattr(macro, "_call_akshare_api", self._fake(pb=False))
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        out = get_index_valuation("沪深300")
        assert "本次缺少 PB 数据（估值锚不完整）" in out
        assert "缺少估值锚（PE/PB 均不可用）" not in out

    def test_valuation_signal_uses_own_index_dividend(self, monkeypatch):
        monkeypatch.setattr(macro, "_call_akshare_api", self._fake())
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        out = get_valuation_signal("沪深300")
        assert "股息率(指数自身, 2024-01-03)" in out
        assert "2.60%" in out

    def test_valuation_signal_falls_back_to_market_reference(self, monkeypatch):
        """指数自身股息率取不到时才退到全市场参考值，且必须标出是哪个口径。"""
        monkeypatch.setattr(macro, "_call_akshare_api", self._fake())
        monkeypatch.setattr(
            macro,
            "fetch_index_dividend_yield",
            lambda name: {
                "index_name": name,
                "available": False,
                "date": None,
                "dividend_yield": None,
                "dividend_yield_calc": None,
                "source": None,
            },
        )
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        out = get_valuation_signal("沪深300")
        assert "股息率(市场参考)" in out
        assert "2.50%" in out

    def test_valuation_signal_flags_missing_anchor(self, monkeypatch):
        monkeypatch.setattr(macro, "_call_akshare_api", self._fake(pe=False, pb=False))
        monkeypatch.setattr(macro, "_get_bond_yield_10y", lambda: 2.5)

        out = get_valuation_signal("沪深300")
        assert "缺少估值锚" in out
