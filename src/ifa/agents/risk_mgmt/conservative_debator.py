# ifa/agents/risk_mgmt/conservative_debator.py
"""保守风险评估 —— 从防守角度评估组合风险，主张稳健配置。"""

from ifa.agents.utils import (
    invoke_llm_safely,
)


def create_conservative_debator(llm):
    """创建保守风险评估节点。"""

    def conservative_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        conservative_history = risk_debate_state.get("conservative_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        portfolio_advice = state.get("portfolio_advice", "")
        fund_analysis = state.get("fund_analysis_report", "")
        fund_codes = state.get("fund_codes", "")

        prompt = f"""As the Conservative Risk Analyst, your role is to prioritize capital preservation and risk mitigation. Emphasize downside protection, volatility management, and defensive positioning.

When evaluating the portfolio advisor's proposal:
- Focus on drawdown scenarios, correlation risks, and tail events.
- Challenge the aggressive analyst's optimism with historical data on market corrections.
- Evaluate whether the proposed allocation matches the user's stated risk tolerance.

Portfolio Advisor's Proposal:
{portfolio_advice}

Fund Analysis Context:
{fund_analysis}

Target Fund(s): {fund_codes}

Conversation history: {history}
Last aggressive argument: {current_aggressive_response}
Last neutral argument: {current_neutral_response}

If no responses from other viewpoints yet, present your own argument based on the available data. Engage actively by refuting counterpoints and emphasizing the importance of downside protection. Output conversationally without special formatting."""

        response = invoke_llm_safely(llm, prompt)

        argument = f"Conservative Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "conservative_history": conservative_history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_conservative_response": argument,
            "current_aggressive_response": risk_debate_state.get("current_aggressive_response", ""),
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "judge_decision": risk_debate_state.get("judge_decision", ""),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return conservative_node
