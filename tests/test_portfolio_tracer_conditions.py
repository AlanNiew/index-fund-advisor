"""Portfolio 模型、Observability Tracer、条件边扩展测试。"""

import json
from pathlib import Path


class TestPortfolioModels:
    """portfolio/models.py 测试。"""

    def test_risk_profile_defaults(self):
        from ifa.portfolio.models import RiskProfile

        rp = RiskProfile(level="test")
        assert rp.description == ""
        assert rp.allocation_template == {}
        assert rp.max_single_fund_pct == 0.30
        assert rp.min_bond_pct == 0.0
        assert rp.max_international_pct == 0.20

    def test_all_risk_profiles_exist(self):
        from ifa.portfolio.models import RISK_PROFILES

        assert set(RISK_PROFILES.keys()) == {"conservative", "moderate", "aggressive", "growth"}

    def test_conservative_has_min_bond(self):
        from ifa.portfolio.models import RISK_PROFILES

        assert RISK_PROFILES["conservative"].min_bond_pct == 0.40

    def test_growth_no_bond_requirement(self):
        from ifa.portfolio.models import RISK_PROFILES

        assert RISK_PROFILES["growth"].min_bond_pct == 0.0

    def test_allocation_templates_sums_approximately_valid(self):
        from ifa.portfolio.models import RISK_PROFILES

        for name, profile in RISK_PROFILES.items():
            total = sum(profile.allocation_template.values())
            assert 0.9 <= total <= 1.1, f"{name} allocation sums to {total}"

    def test_profile_descriptions_nonempty(self):
        from ifa.portfolio.models import RISK_PROFILES

        for name, profile in RISK_PROFILES.items():
            assert profile.description, f"{name} has empty description"


class TestPortfolioStrategies:
    """portfolio/strategies.py 测试。"""

    def test_all_strategies_have_required_fields(self):
        from ifa.portfolio.strategies import STRATEGY_DESCRIPTIONS

        for _key, strategy in STRATEGY_DESCRIPTIONS.items():
            assert "name" in strategy
            assert "description" in strategy
            assert "applicable_profiles" in strategy
            assert len(strategy["applicable_profiles"]) > 0

    def test_all_profiles_covered(self):
        from ifa.portfolio.strategies import STRATEGY_DESCRIPTIONS

        all_profiles = set()
        for strategy in STRATEGY_DESCRIPTIONS.values():
            all_profiles.update(strategy["applicable_profiles"])
        assert "moderate" in all_profiles
        assert "conservative" in all_profiles


class TestTracer:
    """observability/tracer.py 测试。"""

    def test_span_finish(self):
        from ifa.observability.tracer import TraceSpan

        span = TraceSpan("test_span")
        span.finish(ok="true")
        assert span.status == "ok"
        assert span.end_time is not None

    def test_span_fail(self):
        from ifa.observability.tracer import TraceSpan

        span = TraceSpan("test_span")
        span.fail("something broke")
        assert span.status == "error"
        assert span.error == "something broke"

    def test_span_duration(self):
        import time

        from ifa.observability.tracer import TraceSpan

        span = TraceSpan("test")
        time.sleep(0.01)
        span.finish()
        assert span.duration_ms >= 5

    def test_span_to_dict(self):
        from ifa.observability.tracer import TraceSpan

        span = TraceSpan("agent_x", "agent")
        span.finish(custom_key="val")
        d = span.to_dict()
        assert d["name"] == "agent_x"
        assert d["type"] == "agent"
        assert d["custom_key"] == "val"

    def test_tracer_lifecycle(self):
        from ifa.observability.tracer import RequestTracer

        tracer = RequestTracer("req-001", "deep", "510300")
        span = tracer.start_span("Fund Analyst")
        assert span.name == "Fund Analyst"
        span.finish()
        assert len(tracer.spans) == 1

    def test_tracer_finish_current(self):
        from ifa.observability.tracer import RequestTracer

        tracer = RequestTracer("req-002", "screen")
        tracer.start_span("Screener")
        tracer.finish_current(status="ok", tokens=100)
        assert tracer.spans[0].status == "ok"

    def test_tracer_fail_current(self):
        from ifa.observability.tracer import RequestTracer

        tracer = RequestTracer("req-003", "deep")
        tracer.start_span("LLM")
        tracer.fail_current("timeout")
        assert tracer.spans[0].status == "error"

    def test_tracer_finish_current_idempotent(self):
        from ifa.observability.tracer import RequestTracer

        tracer = RequestTracer("req-004", "deep")
        tracer.start_span("A")
        tracer.finish_current()
        tracer.finish_current()
        assert tracer.spans[0].status == "ok"

    def test_tracer_total_duration_no_spans(self):
        from ifa.observability.tracer import RequestTracer

        tracer = RequestTracer("req-005", "deep")
        assert tracer.total_duration_ms == 0

    def test_tracer_save(self, tmp_path):
        from ifa.observability.tracer import RequestTracer

        tracer = RequestTracer("req-006", "deep", "510300")
        tracer.start_span("Analyst").finish()
        path = tracer.save(output_dir=str(tmp_path))
        assert Path(path).exists()
        # trace 文件保存在基金代码子目录下
        assert "510300" in path
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["request_id"] == "req-006"
        assert data["mode"] == "deep"
        assert len(data["spans"]) == 1

    def test_global_trace_lifecycle(self, tmp_path):
        import importlib

        from ifa.observability import tracer as mod

        importlib.reload(mod)

        t = mod.start_trace("g-001", "deep", "510300")
        assert mod.get_current_tracer() is t
        t.start_span("Test").finish()
        path = mod.end_trace(output_dir=str(tmp_path))
        assert path is not None
        assert "510300" in path
        assert mod.get_current_tracer() is None

    def test_end_trace_when_none(self, tmp_path):
        import importlib

        from ifa.observability import tracer as mod

        importlib.reload(mod)
        assert mod.end_trace(output_dir=str(tmp_path)) is None


class TestConditionalLogicExtended:
    """conditional_logic.py 扩展测试 — 工具调用条件边。"""

    def _make_state(self, tool_calls=None, **kwargs):
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.tool_calls = tool_calls or []
        state = {"messages": [msg]}
        state.update(kwargs)
        return state

    def test_should_continue_fund_analyst_with_tools(self):
        from unittest.mock import MagicMock

        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic()
        msg = MagicMock()
        msg.tool_calls = [{"name": "get_fund_data"}]
        state = {"messages": [msg]}
        assert cl.should_continue_fund_analyst(state) == "tools_fund_analyst"

    def test_should_continue_fund_analyst_no_tools(self):
        from unittest.mock import MagicMock

        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic()
        msg = MagicMock()
        msg.tool_calls = []
        state = {"messages": [msg]}
        assert cl.should_continue_fund_analyst(state) == "Msg Clear Fund Analyst"

    def test_should_continue_index_analyst_with_tools(self):
        from unittest.mock import MagicMock

        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic()
        msg = MagicMock()
        msg.tool_calls = [{"name": "get_index_data"}]
        state = {"messages": [msg]}
        assert cl.should_continue_index_analyst(state) == "tools_index_analyst"

    def test_should_continue_fund_screener_with_tools(self):
        from unittest.mock import MagicMock

        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic()
        msg = MagicMock()
        msg.tool_calls = [{"name": "screen_funds"}]
        state = {"messages": [msg]}
        assert cl.should_continue_fund_screener(state) == "tools_fund_screener"

    def test_should_skip_index_analyst_etf(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic()
        state = {"messages": [], "asset_type": "etf"}
        assert cl.should_skip_index_analyst(state) == "Index Analyst"

    def test_should_skip_index_analyst_public_fund(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic()
        state = {"messages": [], "asset_type": "public_fund"}
        assert cl.should_skip_index_analyst(state) == "Skip Index Analyst"

    def test_risk_debate_three_way_rotation(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic(max_risk_discuss_rounds=2)

        state = {
            "messages": [],
            "risk_debate_state": {
                "count": 0,
                "latest_speaker": "Neutral",
            },
        }
        assert cl.should_continue_risk_analysis(state) == "Aggressive Analyst"

        state["risk_debate_state"]["latest_speaker"] = "Aggressive"
        state["risk_debate_state"]["count"] = 1
        assert cl.should_continue_risk_analysis(state) == "Conservative Analyst"

        state["risk_debate_state"]["latest_speaker"] = "Conservative"
        state["risk_debate_state"]["count"] = 2
        assert cl.should_continue_risk_analysis(state) == "Neutral Analyst"

    def test_risk_debate_terminates_at_limit(self):
        from ifa.graph.conditional_logic import ConditionalLogic

        cl = ConditionalLogic(max_risk_discuss_rounds=2)
        state = {
            "messages": [],
            "risk_debate_state": {
                "count": 6,
                "latest_speaker": "Neutral",
            },
        }
        assert cl.should_continue_risk_analysis(state) == "Portfolio Manager"
