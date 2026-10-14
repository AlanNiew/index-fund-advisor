"""Agent 工具函数测试 — invoke_llm_safely, invoke_chain_safely, 语言指令, 标的上下文, 消息清理。"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from ifa.agents.utils import (
    DEBATE_HISTORY_MAX_CHARS,
    AgentLLMError,
    _build_language_instruction,
    build_instrument_context,
    create_msg_delete,
    get_internal_language_instruction,
    invoke_chain_safely,
    invoke_llm_safely,
    truncate_debate_history,
)

# ════════════════════════════════════════════
#  invoke_llm_safely
# ════════════════════════════════════════════


class TestInvokeLLMSafely:
    """invoke_llm_safely 重试逻辑测试。"""

    def test_success_first_try(self):
        """首次调用成功时直接返回结果。"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="ok")
        result = invoke_llm_safely(mock_llm, "test prompt", retries=2)
        assert result.content == "ok"
        assert mock_llm.invoke.call_count == 1

    def test_retry_then_success(self):
        """首次失败后重试成功。"""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [Exception("timeout"), AIMessage(content="recovered")]
        with patch("ifa.agents.utils.time.sleep"):
            result = invoke_llm_safely(mock_llm, "prompt", retries=2)
        assert result.content == "recovered"
        assert mock_llm.invoke.call_count == 2

    def test_all_retries_exhausted(self):
        """所有重试用尽后抛出 AgentLLMError。"""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ConnectionError("network down")
        with patch("ifa.agents.utils.time.sleep"), pytest.raises(AgentLLMError, match="LLM 调用失败"):
            invoke_llm_safely(mock_llm, "prompt", retries=2)
        assert mock_llm.invoke.call_count == 3  # 1 initial + 2 retries


# ════════════════════════════════════════════
#  invoke_chain_safely
# ════════════════════════════════════════════


class TestInvokeChainSafely:
    """invoke_chain_safely 重试逻辑测试。"""

    def test_chain_success(self):
        """链调用成功。"""
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = {"result": "good"}
        result = invoke_chain_safely(mock_chain, {"input": "x"})
        assert result == {"result": "good"}

    def test_chain_retry_exhausted(self):
        """链调用重试耗尽后抛出 AgentLLMError。"""
        mock_chain = MagicMock()
        mock_chain.invoke.side_effect = RuntimeError("chain broken")
        with patch("ifa.agents.utils.time.sleep"), pytest.raises(AgentLLMError, match="Chain 调用失败"):
            invoke_chain_safely(mock_chain, {"input": "x"}, retries=1)
        assert mock_chain.invoke.call_count == 2  # 1 initial + 1 retry


# ════════════════════════════════════════════
#  语言指令
# ════════════════════════════════════════════


class TestLanguageInstruction:
    """语言提示语构建测试。"""

    def test_english_returns_empty(self):
        """英文不需要额外语言指令。"""
        assert _build_language_instruction("English", "test") == ""

    def test_chinese_returns_instruction(self):
        """中文返回包含语言要求的提示语。"""
        result = _build_language_instruction("Chinese", "output language")
        assert "Chinese" in result
        assert "output language" in result

    def test_none_defaults_to_english(self):
        """None 默认为英文，返回空字符串。"""
        assert _build_language_instruction(None, "test") == ""

    def test_internal_language_instruction(self):
        """get_internal_language_instruction 返回格式正确。"""
        with patch("ifa.agents.utils.get_internal_language", return_value="English"):
            assert get_internal_language_instruction() == ""


# ════════════════════════════════════════════
#  build_instrument_context
# ════════════════════════════════════════════


class TestBuildInstrumentContext:
    """标的上文构建测试。"""

    def test_etf_context(self):
        """ETF 基金描述包含 ETF 关键词。"""
        result = build_instrument_context("510300.SH")
        assert "510300.SH" in result
        assert "ETF" in result

    def test_public_fund_context(self):
        """公募基金描述包含 fund 关键词。"""
        # 110011 是典型公募基金代码，会被检测为 STOCK 或 OFFSHORE_FUND
        result = build_instrument_context("110011")
        assert "110011" in result

    def test_index_context(self):
        """指数描述包含 index 关键词。"""
        result = build_instrument_context("000300.SH")
        assert "000300.SH" in result
        assert "index" in result.lower()


# ════════════════════════════════════════════
#  create_msg_delete
# ════════════════════════════════════════════


class TestCreateMsgDelete:
    """消息清理函数测试。"""

    def test_delete_all_messages(self):
        """清理函数移除所有消息并添加占位符。"""
        msg1 = HumanMessage(content="hello", id="1")
        msg2 = AIMessage(content="world", id="2")
        state = {"messages": [msg1, msg2]}

        delete_fn = create_msg_delete()
        result = delete_fn(state)

        # 应包含 2 个 RemoveMessage + 1 个占位 HumanMessage
        assert len(result["messages"]) == 3
        assert isinstance(result["messages"][0], RemoveMessage)
        assert isinstance(result["messages"][2], HumanMessage)
        assert result["messages"][2].content == "Continue"


# ════════════════════════════════════════════
#  Agent 防御性访问测试
# ════════════════════════════════════════════


class TestAgentDefensiveAccess:
    """测试各 Agent 节点在缺失 state 字段时不崩溃。"""

    def _make_mock_llm(self, content: str = "分析结果"):
        """创建返回指定内容的 mock LLM。"""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = content
        mock_response.tool_calls = []
        mock_llm.invoke.return_value = mock_response
        return mock_llm

    def test_portfolio_manager_missing_risk_debate_state(self):
        """Portfolio Manager 缺失 risk_debate_state 时不崩溃。"""
        from ifa.agents.managers.portfolio_manager import create_portfolio_manager

        mock_llm = self._make_mock_llm("BUY rating")
        pm_node = create_portfolio_manager(mock_llm)

        # 完全缺失 risk_debate_state
        state = {"fund_codes": "510300", "fund_analysis_report": "report"}
        result = pm_node(state)
        assert "risk_debate_state" in result
        assert result["risk_debate_state"]["judge_decision"] == "BUY rating"

    def test_portfolio_manager_risk_debate_state_not_dict(self):
        """Portfolio Manager 的 risk_debate_state 不是 dict 时降级。"""
        from ifa.agents.managers.portfolio_manager import create_portfolio_manager

        mock_llm = self._make_mock_llm("HOLD")
        pm_node = create_portfolio_manager(mock_llm)

        state = {"fund_codes": "510300", "risk_debate_state": "invalid"}
        result = pm_node(state)
        assert "risk_debate_state" in result

    def test_aggressive_debator_missing_risk_debate_state(self):
        """Aggressive Debator 缺失 risk_debate_state 时不崩溃。"""
        from ifa.agents.risk_mgmt.debator import create_aggressive_debator

        mock_llm = self._make_mock_llm("积极观点")
        node = create_aggressive_debator(mock_llm)

        state = {"fund_codes": "510300", "fund_analysis_report": "report"}
        result = node(state)
        assert "risk_debate_state" in result
        assert result["risk_debate_state"]["count"] == 1

    def test_conservative_debator_missing_risk_debate_state(self):
        """Conservative Debator 缺失 risk_debate_state 时不崩溃。"""
        from ifa.agents.risk_mgmt.debator import create_conservative_debator

        mock_llm = self._make_mock_llm("保守观点")
        node = create_conservative_debator(mock_llm)

        state = {}
        result = node(state)
        assert "risk_debate_state" in result

    def test_neutral_debator_missing_risk_debate_state(self):
        """Neutral Debator 缺失 risk_debate_state 时不崩溃。"""
        from ifa.agents.risk_mgmt.debator import create_neutral_debator

        mock_llm = self._make_mock_llm("中立观点")
        node = create_neutral_debator(mock_llm)

        state = {}
        result = node(state)
        assert "risk_debate_state" in result


# ════════════════════════════════════════════
#  truncate_debate_history
# ════════════════════════════════════════════


class TestTruncateDebateHistory:
    """辩论历史截断：保留最新发言，丢弃较早内容（与 truncate_report 相反）。"""

    def test_short_text_untouched(self):
        assert truncate_debate_history("Bull: 看多") == "Bull: 看多"

    def test_empty_text_untouched(self):
        assert truncate_debate_history("") == ""

    def test_long_text_keeps_the_tail(self):
        text = "HEAD" + "甲" * (DEBATE_HISTORY_MAX_CHARS * 3) + "TAIL"
        result = truncate_debate_history(text)
        assert result.endswith("TAIL")
        assert "HEAD" not in result
        assert result.startswith("[... 较早的辩论发言已省略 ...]")
        assert len(result) <= DEBATE_HISTORY_MAX_CHARS + 40

    def test_custom_budget(self):
        assert truncate_debate_history("abcdef", max_chars=3).endswith("def")


# ════════════════════════════════════════════
#  重试次数默认值
# ════════════════════════════════════════════


class TestRetryDefaults:
    """重试次数默认值来自配置 llm_max_retries；显式参数优先。"""

    def test_config_value_is_used(self, monkeypatch):
        monkeypatch.setattr("ifa.dataflows.config.get_config", lambda: {"llm_max_retries": 1})
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ConnectionError("network down")
        with patch("ifa.agents.utils.time.sleep"), pytest.raises(AgentLLMError):
            invoke_llm_safely(mock_llm, "prompt")
        assert mock_llm.invoke.call_count == 2  # 1 initial + 1 retry

    def test_explicit_argument_wins(self, monkeypatch):
        monkeypatch.setattr("ifa.dataflows.config.get_config", lambda: {"llm_max_retries": 5})
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ConnectionError("network down")
        with patch("ifa.agents.utils.time.sleep"), pytest.raises(AgentLLMError):
            invoke_llm_safely(mock_llm, "prompt", retries=0)
        assert mock_llm.invoke.call_count == 1

    def test_chain_helper_uses_the_same_budget(self, monkeypatch):
        monkeypatch.setattr("ifa.dataflows.config.get_config", lambda: {"llm_max_retries": 0})
        mock_chain = MagicMock()
        mock_chain.invoke.side_effect = RuntimeError("boom")
        with patch("ifa.agents.utils.time.sleep"), pytest.raises(AgentLLMError):
            invoke_chain_safely(mock_chain, {"input": "x"})
        assert mock_chain.invoke.call_count == 1
