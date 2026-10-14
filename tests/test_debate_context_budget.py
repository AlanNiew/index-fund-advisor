"""辩论上下文预算测试 —— 进入 prompt 的历史与报告必须被截断。

背景：2026-10 实测 510300 的 deep 运行 wall 30.4 分钟，其中辩论段独占 86%，因为每个
辩手每轮都要重读整段辩论历史，而历史随轮数增长。修复是只在构造 prompt 时截断（保留
最新发言），state 里保留全文供裁决与最终报告使用。
"""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from ifa.agents.researchers.researcher import create_researcher
from ifa.agents.risk_mgmt.debator import create_debator
from ifa.agents.utils import DEBATE_HISTORY_MAX_CHARS

_HEAD = "HEAD-MARKER"
_TAIL = "TAIL-MARKER"

_RESEARCHER_TEMPLATE = "{fund_codes}|{fund_analysis}|{index_analysis}|{history}|{current_response}|{past_memory_str}|{language_instruction}"
_DEBATOR_TEMPLATE = (
    "{portfolio_advice}|{fund_analysis}|{fund_codes}|{history}|"
    "{current_conservative_response}|{current_neutral_response}"
)


def _llm() -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content="我的发言")
    return llm


def _long_text() -> str:
    """超长文本：头部与末尾各有标记，便于断言保留的是哪一端。"""
    return _HEAD + "甲" * (DEBATE_HISTORY_MAX_CHARS * 4) + _TAIL


def _run_researcher(state: dict) -> tuple[str, dict]:
    llm = _llm()
    node = create_researcher("bull", _RESEARCHER_TEMPLATE, "bull_history", "Bull Researcher")(llm)
    result = node(state)
    return llm.invoke.call_args.args[0], result


def _run_debator(state: dict) -> str:
    llm = _llm()
    node = create_debator("aggressive", _DEBATOR_TEMPLATE, llm)
    node(state)
    return llm.invoke.call_args.args[0]


class TestResearcherContextBudget:
    """看涨/看跌研究员：辩论历史截断保留最新发言。"""

    def test_history_is_truncated_from_the_head(self):
        state = {
            "fund_codes": "510300",
            "fund_debate_state": {"history": _long_text(), "current_response": "", "count": 0},
        }
        prompt, _ = _run_researcher(state)

        assert _TAIL in prompt, "最新发言必须保留"
        assert _HEAD not in prompt, "较早的发言应被丢弃"
        assert "较早的辩论发言已省略" in prompt
        assert len(prompt) < DEBATE_HISTORY_MAX_CHARS * 2

    def test_current_response_is_truncated_too(self):
        state = {
            "fund_codes": "510300",
            "fund_debate_state": {"history": "", "current_response": _long_text(), "count": 0},
        }
        prompt, _ = _run_researcher(state)

        assert _TAIL in prompt
        assert _HEAD not in prompt

    def test_state_keeps_the_full_transcript(self):
        """截断只作用于 prompt：裁决与最终报告仍需要全文。"""
        history = _long_text()
        state = {
            "fund_codes": "510300",
            "fund_debate_state": {"history": history, "current_response": "", "count": 0},
        }
        _, result = _run_researcher(state)

        assert history in result["fund_debate_state"]["history"]
        assert _HEAD in result["fund_debate_state"]["history"]

    def test_short_history_is_untouched(self):
        state = {
            "fund_codes": "510300",
            "fund_debate_state": {"history": "Bull: 看多", "current_response": "Bull: 看多", "count": 0},
        }
        prompt, _ = _run_researcher(state)

        assert "Bull: 看多" in prompt
        assert "较早的辩论发言已省略" not in prompt


class TestDebatorContextBudget:
    """风险辩论：历史、其他辩手发言、以及此前全文直传的两份报告都要截断。"""

    def test_risk_history_is_truncated_from_the_head(self):
        state = {"risk_debate_state": {"history": _long_text(), "count": 0}}
        prompt = _run_debator(state)

        assert _TAIL in prompt
        assert _HEAD not in prompt

    def test_other_speakers_responses_are_truncated(self):
        state = {
            "risk_debate_state": {
                "history": "",
                "current_conservative_response": _long_text(),
                "current_neutral_response": "",
                "count": 0,
            }
        }
        prompt = _run_debator(state)

        assert _TAIL in prompt
        assert _HEAD not in prompt

    def test_reports_are_truncated(self):
        """portfolio_advice / fund_analysis 此前是全文直传，比辩论历史更容易膨胀。"""
        report = "报告开头" + "乙" * 20000 + "报告结尾"
        state = {
            "fund_analysis_report": report,
            "portfolio_advice": report,
            "risk_debate_state": {"history": "", "count": 0},
        }
        prompt = _run_debator(state)

        assert "报告已截断" in prompt
        assert len(prompt) < 12000
