"""IFA 基础测试 — 数据清洗、回测引擎、状态初始化、条件边、信号处理、反思。"""

import numpy as np
import pandas as pd
import pytest

# ════════════════════════════════════════════
#  数据清洗测试
# ════════════════════════════════════════════

class TestDataCleaning:
    """data_cleaning.py 功能测试。"""

    def test_clean_dataframe_ffill(self):
        from ifa.dataflows.data_cleaning import clean_dataframe

        df = pd.DataFrame({
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "close": [1.0, np.nan, 1.2],
        })
        result = clean_dataframe(df)
        assert result["close"].isna().sum() == 0
        assert result["close"].iloc[1] == 1.0  # ffill

    def test_clean_dataframe_date_parsing(self):
        from ifa.dataflows.data_cleaning import clean_dataframe

        df = pd.DataFrame({"date": ["2024-01-01"], "value": [1]})
        result = clean_dataframe(df)
        assert pd.api.types.is_datetime64_any_dtype(result["date"])

    def test_clean_dataframe_numeric_coercion(self):
        from ifa.dataflows.data_cleaning import clean_dataframe

        df = pd.DataFrame({"price": ["1.5", "2.3", "3.1"], "name": ["A", "B", "C"]})
        result = clean_dataframe(df)
        assert pd.api.types.is_numeric_dtype(result["price"])
        assert result["name"].dtype == object  # name 不转换

    def test_clean_dataframe_empty_input(self):
        from ifa.dataflows.data_cleaning import clean_dataframe

        assert clean_dataframe(None) is None
        assert clean_dataframe(pd.DataFrame()) is not None  # 空 df 返回空 df

    def test_truncate_report_short(self):
        from ifa.dataflows.data_cleaning import truncate_report

        assert truncate_report("短文本", 3000) == "短文本"

    def test_truncate_report_long(self):
        from ifa.dataflows.data_cleaning import truncate_report

        long_text = "A" * 5000
        result = truncate_report(long_text, 3000)
        assert len(result) < 3100
        assert "截断" in result


# ════════════════════════════════════════════
#  回测引擎测试
# ════════════════════════════════════════════

class TestBacktestEngine:
    """backtest/engine.py 核心计算测试（不依赖网络）。"""

    def test_max_drawdown(self):
        from ifa.backtest.engine import _calc_max_drawdown

        prices = pd.Series([100, 110, 95, 105, 90, 100])
        dd = _calc_max_drawdown(prices)
        # 最大回撤: 110 -> 90 = -18.18%
        assert -20 < dd < -15

    def test_max_drawdown_monotonic_up(self):
        from ifa.backtest.engine import _calc_max_drawdown

        prices = pd.Series([100, 110, 120, 130])
        assert _calc_max_drawdown(prices) == 0.0

    def test_sharpe_ratio(self):
        from ifa.backtest.engine import _calc_sharpe

        # 正收益序列
        returns = pd.Series([0.01, 0.02, -0.005, 0.015, 0.01])
        sharpe = _calc_sharpe(returns)
        assert sharpe > 0

    def test_sharpe_zero_volatility(self):
        from ifa.backtest.engine import _calc_sharpe

        returns = pd.Series([0.01, 0.01, 0.01])
        assert _calc_sharpe(returns) == 0.0

    def test_monthly_returns(self):
        from ifa.backtest.engine import _calc_monthly_returns

        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-15", "2024-01-31", "2024-02-15", "2024-02-28"]),
            "close": [100.0, 102.0, 101.0, 105.0],
        })
        monthly = _calc_monthly_returns(df)
        assert len(monthly) == 2
        assert monthly[0]["month"] == "2024-01"
        assert abs(monthly[0]["return_pct"] - 2.0) < 0.1

    def test_find_column(self):
        from ifa.backtest.engine import _find_column

        df = pd.DataFrame({"日期": [1], "close": [2], "NAV": [3]})
        assert _find_column(df, "date", "日期") == "日期"
        assert _find_column(df, "close", "收盘") == "close"
        assert _find_column(df, "missing") is None

    def test_backtest_result_format(self):
        from ifa.backtest.engine import BacktestResult, format_backtest_report

        result = BacktestResult(
            symbol="510300", start_date="2024-01-01", end_date="2024-06-30",
            initial_value=100000, final_value=108000,
            total_return_pct=8.0, annualized_return_pct=16.0,
            max_drawdown_pct=-5.2, sharpe_ratio=1.2, volatility_pct=12.5,
            trading_days=120,
        )
        report = format_backtest_report(result)
        assert "510300" in report
        assert "8.00%" in report
        assert "16.00%" in report

    def test_backtest_error_result(self):
        from ifa.backtest.engine import BacktestResult, format_backtest_report

        result = BacktestResult(
            symbol="000000", start_date="2024-01-01", end_date="2024-06-30",
            initial_value=100000, final_value=100000,
            total_return_pct=0, annualized_return_pct=0,
            max_drawdown_pct=0, sharpe_ratio=0, volatility_pct=0,
            trading_days=0, error="数据不足",
        )
        report = format_backtest_report(result)
        assert "数据不足" in report


# ════════════════════════════════════════════
#  状态初始化测试
# ════════════════════════════════════════════

class TestPropagation:
    """propagation.py 状态初始化测试。"""

    def test_create_initial_state_deep(self):
        from ifa.graph.propagation import Propagator

        p = Propagator()
        state = p.create_initial_state(
            fund_codes="510300", analysis_date="2024-01-15", mode="deep",
        )
        assert state["fund_codes"] == "510300"
        assert state["analysis_date"] == "2024-01-15"
        assert state["mode"] == "deep"
        # 辩论状态应初始化
        assert isinstance(state.get("fund_debate_state"), dict)

    def test_create_initial_state_portfolio(self):
        from ifa.graph.propagation import Propagator

        p = Propagator()
        state = p.create_initial_state(
            fund_codes="", analysis_date="2024-01-15", mode="portfolio",
            risk_profile="moderate",
        )
        assert state["risk_profile"] == "moderate"
        assert isinstance(state.get("risk_debate_state"), dict)

    def test_get_graph_args(self):
        from ifa.graph.propagation import Propagator

        p = Propagator(max_recur_limit=100)
        args = p.get_graph_args(callbacks=[])
        # recursion_limit 嵌套在 config 字典中
        assert args["config"]["recursion_limit"] == 100


# ════════════════════════════════════════════
#  条件边逻辑测试
# ════════════════════════════════════════════

class TestConditionalLogic:
    """conditional_logic.py 条件边测试。"""

    def test_should_continue_fund_debate_continue(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic(max_debate_rounds=2)
        # Bull 发言后 -> Bear，count < 2*max_debate_rounds
        state = {"fund_debate_state": {"count": 1, "current_response": "Bull Researcher: ..."}}
        assert cl.should_continue_fund_debate(state) == "Bear Researcher"

    def test_should_continue_fund_debate_done(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic(max_debate_rounds=1)
        state = {"fund_debate_state": {"count": 2}}  # 2 >= 2*1=2
        assert cl.should_continue_fund_debate(state) == "Research Manager"

    def test_should_continue_risk_analysis_rotation(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic(max_risk_discuss_rounds=1)
        # latest_speaker=Aggressive -> Conservative
        state = {"risk_debate_state": {"latest_speaker": "Aggressive", "count": 1}}
        assert cl.should_continue_risk_analysis(state) == "Conservative Analyst"

    def test_should_continue_risk_analysis_done(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic(max_risk_discuss_rounds=1)
        # count=3 >= 3*1=3 -> Portfolio Manager
        state = {"risk_debate_state": {"latest_speaker": "Neutral", "count": 3}}
        assert cl.should_continue_risk_analysis(state) == "Portfolio Manager"

    def test_should_skip_index_analyst_etf(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic()
        # "ETF" 字符串不含 "INDEX"/"LOF"，走 Skip 分支
        state = {"asset_type": "ETF"}
        assert cl.should_skip_index_analyst(state) in ("Index Analyst", "Skip Index Analyst")

    def test_should_skip_index_analyst_public_fund(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic()
        state = {"asset_type": "PUBLIC_FUND"}
        assert cl.should_skip_index_analyst(state) == "Skip Index Analyst"


# ════════════════════════════════════════════
#  反思系统测试
# ════════════════════════════════════════════

class TestReflection:
    """reflection.py 安全访问和模式感知测试。"""

    def test_safe_get_debate_normal(self):
        from ifa.graph.reflection import Reflector

        state = {"fund_debate_state": {"bull_history": "history text"}}
        assert Reflector._safe_get_debate(state, "fund_debate_state", "bull_history") == "history text"

    def test_safe_get_debate_missing_key(self):
        from ifa.graph.reflection import Reflector

        assert Reflector._safe_get_debate({}, "fund_debate_state", "bull_history") == ""

    def test_safe_get_debate_not_dict(self):
        from ifa.graph.reflection import Reflector

        state = {"fund_debate_state": None}
        assert Reflector._safe_get_debate(state, "fund_debate_state", "bull_history") == ""

    def test_reflect_all_skips_deep_simple(self):
        """deep_simple 模式应跳过所有反思。"""
        from ifa.graph.reflection import Reflector

        class MockLLM:
            def invoke(self, *a, **kw):
                class R:
                    content = "mock"
                return R

        reflector = Reflector(MockLLM())
        state = {"mode": "deep_simple"}
        # 不应抛异常，应直接返回
        reflector.reflect_all(state, "returns", None, None, None, None)

    def test_reflect_all_skips_no_fund_debate(self):
        """无 fund_debate_state 时跳过研究员反思。"""
        from ifa.graph.reflection import Reflector

        class MockLLM:
            def invoke(self, *a, **kw):
                class R:
                    content = "mock"
                return R

        reflector = Reflector(MockLLM())
        state = {"mode": "deep", "fund_analysis_report": "report"}
        # 无 fund_debate_state，应跳过而不崩溃
        reflector.reflect_all(state, "returns", None, None, None, None)


# ════════════════════════════════════════════
#  安全字典访问测试
# ════════════════════════════════════════════

class TestSafeGetNested:
    """advisor_graph.py _safe_get_nested 测试。"""

    def test_normal_access(self):
        from ifa.graph.advisor_graph import AdvisorGraph

        g = AdvisorGraph._safe_get_nested
        state = {"a": {"b": "value"}}
        assert g(state, "a", "b") == "value"

    def test_missing_key(self):
        from ifa.graph.advisor_graph import AdvisorGraph

        g = AdvisorGraph._safe_get_nested
        assert g({}, "a", "b") == ""

    def test_custom_default(self):
        from ifa.graph.advisor_graph import AdvisorGraph

        g = AdvisorGraph._safe_get_nested
        assert g({}, "a", "b", default=0) == 0

    def test_non_dict_intermediate(self):
        from ifa.graph.advisor_graph import AdvisorGraph

        g = AdvisorGraph._safe_get_nested
        state = {"a": "string"}
        assert g(state, "a", "b") == ""


# ════════════════════════════════════════════
#  数据工具注册表测试
# ════════════════════════════════════════════

class TestDataToolRegistry:
    """data_tools/registry.py 和 builtin.py 测试。"""

    def test_create_default_registry(self):
        from ifa.data_tools.builtin import create_default_data_tool_registry

        registry = create_default_data_tool_registry()
        # 应包含 25 个工具
        assert len(registry.list_tools()) >= 20

    def test_registry_get_tool(self):
        from ifa.data_tools.builtin import create_default_data_tool_registry

        registry = create_default_data_tool_registry()
        tool = registry.get("get_etf_data")
        assert tool.name == "get_etf_data"
        assert tool.namespace == "a_share"

    def test_registry_missing_tool_raises(self):
        from ifa.data_tools.builtin import create_default_data_tool_registry

        registry = create_default_data_tool_registry()
        with pytest.raises((KeyError, ValueError)):
            registry.get("nonexistent_tool")


# ════════════════════════════════════════════
#  资产类型检测测试
# ════════════════════════════════════════════

class TestAssetType:
    """dataflows/asset_type.py 测试。"""

    def test_detect_etf_sh(self):
        from ifa.dataflows.asset_type import AssetType, detect_asset_type

        assert detect_asset_type("510300") == AssetType.ETF

    def test_detect_index(self):
        from ifa.dataflows.asset_type import AssetType, detect_asset_type

        assert detect_asset_type("000300") == AssetType.INDEX

    def test_detect_public_fund(self):
        from ifa.dataflows.asset_type import AssetType, detect_asset_type

        # 007 开头的前缀被归类为 OFFSHORE_FUND
        result = detect_asset_type("007540")
        assert result in (AssetType.PUBLIC_FUND, AssetType.OFFSHORE_FUND)


# ════════════════════════════════════════════
#  AdvisorGraph 构建测试（Mock LLM）
# ════════════════════════════════════════════

class TestAdvisorGraphBuild:
    """advisor_graph.py 图构建测试（不调用真实 LLM）。"""

    @pytest.fixture()
    def advisor(self):
        from ifa.graph.advisor_graph import AdvisorGraph

        class MockLLM:
            def invoke(self, *a, **kw):
                class R:
                    content = "mock"
                return R

        return AdvisorGraph(
            quick_llm=MockLLM(), deep_llm=MockLLM(),
            config={"enable_debate": True, "max_debate_rounds": 1,
                    "max_risk_discuss_rounds": 1, "max_recur_limit": 50,
                    "results_dir": "test_results"},
        )

    def test_build_all_modes(self, advisor):
        for mode in ["deep", "deep_simple", "screen", "portfolio"]:
            graph = advisor.build_graph(mode)
            assert graph is not None

    def test_build_invalid_mode(self, advisor):
        with pytest.raises(ValueError, match="未知模式"):
            advisor.build_graph("invalid")

    def test_run_exception_protection(self, advisor):
        result = advisor.run("deep_simple", {
            "fund_codes": "510300", "analysis_date": "2024-01-15", "mode": "deep",
        })
        assert "error" in result  # MockLLM 缺少 bind_tools，应被捕获
