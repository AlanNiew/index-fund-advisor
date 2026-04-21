# ifa/agents/risk_mgmt/neutral_debator.py
"""中立风险评估 —— 从客观角度评估组合风险，提供平衡观点。"""

from ifa.agents.utils import (
    invoke_llm_safely,
)


def create_neutral_debator(llm):
    """创建中立风险评估节点。"""

    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")

        portfolio_advice = state.get("portfolio_advice", "")
        fund_analysis = state.get("fund_analysis_report", "")
        fund_codes = state.get("fund_codes", "")

        prompt = f"""As the Neutral Risk Analyst, your role is to provide an objective, balanced assessment of the portfolio's risk-return profile. Weigh both the aggressive and conservative perspectives and identify the optimal middle ground.

When evaluating the portfolio advisor's proposal:
- Focus on risk-adjusted returns (Sharpe ratio, Sortino ratio, information ratio).
- Evaluate whether the aggressive analyst is underestimating risks or the conservative analyst is overestimating them.
- Consider rebalancing frequency, liquidity, and transaction costs.

Portfolio Advisor's Proposal:
{portfolio_advice}

Fund Analysis Context:
{fund_analysis}

Target Fund(s): {fund_codes}

Conversation history: {history}
Last aggressive argument: {current_aggressive_response}
Last conservative argument: {current_conservative_response}

If no responses from other viewpoints yet, present your own argument based on the available data. Provide a balanced, data-driven analysis. Output conversationally without special formatting."""

        response = invoke_llm_safely(llm, prompt)

        argument = f"Neutral Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "neutral_history": neutral_history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "latest_speaker": "Neutral",
            "current_neutral_response": argument,
            "current_aggressive_response": risk_debate_state.get("current_aggressive_response", ""),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "judge_decision": risk_debate_state.get("judge_decision", ""),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
