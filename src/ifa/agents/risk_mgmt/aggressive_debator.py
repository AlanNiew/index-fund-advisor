# ifa/agents/risk_mgmt/aggressive_debator.py
"""积极风险评估 —— 从积极角度评估组合风险，主张进取配置。"""

from ifa.agents.utils import (
    invoke_llm_safely,
)


def create_aggressive_debator(llm):
    """创建积极风险评估节点。"""

    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        portfolio_advice = state.get("portfolio_advice", "")
        fund_analysis = state.get("fund_analysis_report", "")
        fund_codes = state.get("fund_codes", "")

        prompt = f"""As the Aggressive Risk Analyst, your role is to actively champion high-reward opportunities in the proposed index fund portfolio, emphasizing bold strategies and growth potential.

When evaluating the portfolio advisor's proposal:
- Focus on upside potential, expected returns, and growth sectors.
- Challenge the conservative and neutral analysts' caution with data-driven rebuttals.
- Highlight where their caution might miss critical opportunities.

Portfolio Advisor's Proposal:
{portfolio_advice}

Fund Analysis Context:
{fund_analysis}

Target Fund(s): {fund_codes}

Conversation history: {history}
Last conservative argument: {current_conservative_response}
Last neutral argument: {current_neutral_response}

If no responses from other viewpoints yet, present your own argument based on the available data. Engage actively by refuting counterpoints and asserting the benefits of risk-taking. Output conversationally without special formatting."""

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
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
