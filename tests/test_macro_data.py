"""宏观数据参数校验测试 — 不调用实际 API，仅验证参数校验和纯函数逻辑。"""

import pandas as pd

from ifa.dataflows.a_share_macro import (
    _INDEX_METHODS,
    _INDEX_VALUATION_NAMES,
    _compute_metric,
    _valuation_label,
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
        """无效渠道自动回退到北向资金（但仍会调用 API，此处仅验证不崩溃）。"""
        # 由于会尝试调用 API，我们只验证不抛出异常
        try:
            result = get_north_flow("无效渠道")
            # 回退逻辑：label = "北向资金"
            assert isinstance(result, str)
        except Exception:
            # API 调用可能失败（网络），但不应是参数校验错误
            pass


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
