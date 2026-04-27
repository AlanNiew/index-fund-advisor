# ifa/agents/risk_mgmt/aggressive_debator.py
"""积极风险评估 —— 从积极角度评估组合风险，主张进取配置。"""

from ifa.agents.prompts.risk_mgmt import AGGRESSIVE_DEBATOR_PROMPT
from ifa.agents.utils import (
    invoke_llm_safely,
)


def create_aggressive_debator(llm):
    """创建积极风险评估节点。"""

    def aggressive_node(state) -> dict:
        risk_debate_state = state.get("risk_debate_state", {})
        if not isinstance(risk_debate_state, dict):
            risk_debate_state = {}
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        portfolio_advice = state.get("portfolio_advice", "")
        fund_analysis = state.get("fund_analysis_report", "")
        fund_codes = state.get("fund_codes", "")

        prompt = AGGRESSIVE_DEBATOR_PROMPT.format(
            portfolio_advice=portfolio_advice,
            fund_analysis=fund_analysis,
            fund_codes=fund_codes,
            history=history,
            current_conservative_response=current_conservative_response,
            current_neutral_response=current_neutral_response,
        )

        response = invoke_llm_safely(llm, prompt)

        argument = f"Aggressive Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "judge_decision": risk_debate_state.get("judge_decision", ""),
            "count": risk_debate_state.get("count", 0) + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
