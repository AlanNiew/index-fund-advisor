# ifa/agents/risk_mgmt/debator.py
"""风险评估三方辩论 —— 积极/保守/中立，基于参数化工厂函数。"""

from __future__ import annotations

from ifa.agents.utils import invoke_llm_safely, truncate_debate_history
from ifa.dataflows.data_cleaning import truncate_report

_SPEAKER_CONFIG = {
    "aggressive": ("aggressive_history", "Aggressive", "current_aggressive_response"),
    "conservative": ("conservative_history", "Conservative", "current_conservative_response"),
    "neutral": ("neutral_history", "Neutral", "current_neutral_response"),
}


def create_debator(style: str, prompt_template: str, llm):
    """
    创建风险辩论节点。

    参数:
        style: 辩论风格标识（"aggressive" / "conservative" / "neutral"）。
        prompt_template: Prompt 模板字符串。
        llm: LLM 实例。
    """
    history_key, label, response_key = _SPEAKER_CONFIG[style]

    def debator_node(state) -> dict:
        risk_debate_state = state.get("risk_debate_state", {})
        if not isinstance(risk_debate_state, dict):
            risk_debate_state = {}
        history = risk_debate_state.get("history", "")
        own_history = risk_debate_state.get(history_key, "")

        # 与研究员一致：报告走 truncate_report（保留头部结论），辩论历史走
        # truncate_debate_history（保留最新发言）。此前这两处都是全文直传。
        portfolio_advice = truncate_report(state.get("portfolio_advice", ""))
        fund_analysis = truncate_report(state.get("fund_analysis_report", ""))
        fund_codes = state.get("fund_codes", "")

        prompt_kwargs = {
            "portfolio_advice": portfolio_advice,
            "fund_analysis": fund_analysis,
            "fund_codes": fund_codes,
            "history": truncate_debate_history(history),
        }
        for other_style, (_, _, other_response_key) in _SPEAKER_CONFIG.items():
            if other_style != style:
                prompt_kwargs[other_response_key] = truncate_debate_history(
                    risk_debate_state.get(other_response_key, "")
                )

        prompt = prompt_template.format(**prompt_kwargs)

        response = invoke_llm_safely(llm, prompt)

        argument = f"{label} Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            history_key: own_history + "\n" + argument,
            "latest_speaker": label,
            response_key: argument,
            "judge_decision": risk_debate_state.get("judge_decision", ""),
            "count": risk_debate_state.get("count", 0) + 1,
        }
        for other_style, (other_history_key, _, other_response_key) in _SPEAKER_CONFIG.items():
            if other_style != style:
                new_risk_debate_state[other_history_key] = risk_debate_state.get(other_history_key, "")
                new_risk_debate_state[other_response_key] = risk_debate_state.get(other_response_key, "")

        return {"risk_debate_state": new_risk_debate_state}

    return debator_node


def create_aggressive_debator(llm):
    """创建积极风险评估节点。"""
    from ifa.agents.prompts.risk_mgmt import AGGRESSIVE_DEBATOR_PROMPT

    return create_debator("aggressive", AGGRESSIVE_DEBATOR_PROMPT, llm)


def create_conservative_debator(llm):
    """创建保守风险评估节点。"""
    from ifa.agents.prompts.risk_mgmt import CONSERVATIVE_DEBATOR_PROMPT

    return create_debator("conservative", CONSERVATIVE_DEBATOR_PROMPT, llm)


def create_neutral_debator(llm):
    """创建中立风险评估节点。"""
    from ifa.agents.prompts.risk_mgmt import NEUTRAL_DEBATOR_PROMPT

    return create_debator("neutral", NEUTRAL_DEBATOR_PROMPT, llm)
