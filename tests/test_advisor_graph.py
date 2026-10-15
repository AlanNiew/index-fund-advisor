"""AdvisorGraph 图拓扑验证测试 — 四种模式各含正确的节点结构。

比 test_core.py 的 TestAdvisorGraphBuild 更深：
不只断言 graph is not None，而是验证每种模式的图包含预期的业务节点。
"""

import pytest


class MockLLM:
    """最小化 Mock LLM，满足图构建需求（不调用真实 LLM）。"""

    def invoke(self, *a, **kw):
        class R:
            content = "mock"

        return R


@pytest.fixture()
def advisor():
    from ifa.graph.advisor_graph import AdvisorGraph

    return AdvisorGraph(
        quick_llm=MockLLM(),
        deep_llm=MockLLM(),
        config={
            "enable_debate": True,
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "max_recur_limit": 50,
            "results_dir": "test_results",
        },
    )


def _node_names(graph) -> set[str]:
    """提取编译后图的全部业务节点名称。"""
    return set(graph.nodes.keys())


class TestDeepModeTopology:
    """deep 模式：Fund Analyst → Index Analyst → Bull/Bear 辩论 → Manager → Report。"""

    def test_contains_core_analysts(self, advisor):
        nodes = _node_names(advisor.build_graph("deep"))
        assert "Fund Analyst" in nodes
        assert "Index Analyst" in nodes
        assert "Report Generator" in nodes

    def test_contains_debate_nodes(self, advisor):
        nodes = _node_names(advisor.build_graph("deep"))
        assert "Bull Researcher" in nodes
        assert "Bear Researcher" in nodes
        assert "Research Manager" in nodes

    def test_contains_tool_nodes(self, advisor):
        nodes = _node_names(advisor.build_graph("deep"))
        assert "tools_fund_analyst" in nodes
        assert "Msg Clear Fund Analyst" in nodes


class TestDeepSimpleModeTopology:
    """deep_simple 模式：Fund Analyst → Index Analyst → Report（无辩论）。"""

    def test_contains_core_analysts(self, advisor):
        nodes = _node_names(advisor.build_graph("deep_simple"))
        assert "Fund Analyst" in nodes
        assert "Report Generator" in nodes

    def test_excludes_debate_nodes(self, advisor):
        """deep_simple 不含辩论节点。"""
        nodes = _node_names(advisor.build_graph("deep_simple"))
        assert "Bull Researcher" not in nodes
        assert "Bear Researcher" not in nodes
        assert "Research Manager" not in nodes


class TestScreenModeTopology:
    """screen 模式：Fund Screener → Fund Analyst → Bull/Bear 辩论 → Manager → Report。"""

    def test_contains_screener(self, advisor):
        nodes = _node_names(advisor.build_graph("screen"))
        assert "Fund Screener" in nodes

    def test_contains_debate_and_report(self, advisor):
        nodes = _node_names(advisor.build_graph("screen"))
        assert "Bull Researcher" in nodes
        assert "Bear Researcher" in nodes
        assert "Research Manager" in nodes
        assert "Report Generator" in nodes


class TestPortfolioModeTopology:
    """portfolio 模式：Advisor R1 → Screener → Analyst → Advisor R2 → Risk 辩论 → Manager → Report。"""

    def test_contains_portfolio_advisor(self, advisor):
        nodes = _node_names(advisor.build_graph("portfolio"))
        assert "Portfolio Advisor R1" in nodes
        assert "Portfolio Advisor R2" in nodes

    def test_contains_risk_debate_nodes(self, advisor):
        nodes = _node_names(advisor.build_graph("portfolio"))
        assert "Aggressive Analyst" in nodes
        assert "Conservative Analyst" in nodes
        assert "Neutral Analyst" in nodes
        assert "Portfolio Manager" in nodes

    def test_excludes_fund_debate_nodes(self, advisor):
        """portfolio 模式用风险辩论，不用 Bull/Bear 辩论。"""
        nodes = _node_names(advisor.build_graph("portfolio"))
        assert "Bull Researcher" not in nodes
        assert "Bear Researcher" not in nodes


class TestRunExceptionProtection:
    """run() 顶层异常保护：图执行失败时返回 error 字段而非崩溃。"""

    def test_run_returns_error_on_llm_failure(self, advisor):
        """MockLLM 缺少 bind_tools，执行图时必然失败，应被顶层 try/except 捕获。"""
        result = advisor.run(
            "deep_simple",
            {
                "fund_codes": "510300",
                "analysis_date": "2024-01-15",
                "mode": "deep_simple",
            },
        )
        assert isinstance(result, dict)
        assert "error" in result


class TestMemoryPersistenceWiring:
    """AdvisorGraph 与记忆落盘的接线：config 里有没有 memory_dir 决定是否落盘。"""

    def test_config_without_memory_dir_disables_persistence(self, advisor):
        """测试夹具的 config 不含 memory_dir → 四个记忆都不落盘，测试保持无副作用。"""
        for mem in (
            advisor.bull_memory,
            advisor.bear_memory,
            advisor.research_manager_memory,
            advisor.portfolio_manager_memory,
        ):
            assert mem._path is None

    def test_config_memory_dir_is_propagated_to_all_memories(self, tmp_path):
        """config 带 memory_dir 时，四个记忆各自指向 <dir>/<name>.json。"""
        from ifa.graph.advisor_graph import AdvisorGraph

        adv = AdvisorGraph(
            quick_llm=MockLLM(),
            deep_llm=MockLLM(),
            config={
                "enable_debate": True,
                "max_debate_rounds": 1,
                "max_risk_discuss_rounds": 1,
                "max_recur_limit": 50,
                "results_dir": "test_results",
                "memory_dir": str(tmp_path),
            },
        )
        for mem in (
            adv.bull_memory,
            adv.bear_memory,
            adv.research_manager_memory,
            adv.portfolio_manager_memory,
        ):
            assert mem._path == tmp_path / f"{mem.name}.json"

class TestResolveDecisionSignals:
    """AdvisorGraph.resolve_decision_signals：管理层裁决优先，其次最终报告（确定性，零 LLM）。"""

    def test_prefers_risk_debate_decision(self, advisor):
        state = {
            "risk_debate_state": {"judge_decision": "RATING: SELL\nCONFIDENCE: Low"},
            "fund_debate_state": {"judge_decision": "RATING: BUY\nCONFIDENCE: High"},
            "final_report": "Rating: HOLD\nConfidence: Medium",
        }
        assert advisor.resolve_decision_signals(state) == ("SELL", "Low")

    def test_falls_back_to_fund_debate_decision(self, advisor):
        state = {"fund_debate_state": {"judge_decision": "RATING: BUY\nCONFIDENCE: High"}}
        assert advisor.resolve_decision_signals(state) == ("BUY", "High")

    def test_falls_back_to_final_report(self, advisor):
        state = {"final_report": "# 报告\n\nRating: HOLD\nConfidence: Medium"}
        assert advisor.resolve_decision_signals(state) == ("HOLD", "Medium")

    def test_returns_none_when_nothing_parseable(self, advisor):
        assert advisor.resolve_decision_signals({"final_report": "无结构化结论"}) == (None, None)
        assert advisor.resolve_decision_signals({}) == (None, None)

    def test_ignores_non_dict_debate_state(self, advisor):
        state = {"fund_debate_state": "not-a-dict", "final_report": "Rating: BUY"}
        assert advisor.resolve_decision_signals(state) == ("BUY", None)
