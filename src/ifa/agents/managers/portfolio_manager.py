# ifa/agents/managers/portfolio_manager.py
"""投资组合经理 —— 综合风险评估辩论结果，做出最终投资决策。"""

from ifa.agents.prompts.managers import PORTFOLIO_MANAGER_PROMPT
from ifa.agents.utils import (
    get_final_language_instruction,
    invoke_llm_safely,
)


def create_portfolio_manager(llm, memory=None):
    """创建投资组合经理节点。

    参数:
        llm: LLM 实例（deep_think_llm，关键决策节点）
        memory: FinancialSituationMemory 实例，可选
    """

    def portfolio_manager_node(state) -> dict:
        fund_codes = state.get("fund_codes", "")
        fund_analysis = state.get("fund_analysis_report", "")
        fund_debate_state = state.get("fund_debate_state", {})
        risk_debate_state = state["risk_debate_state"]
        portfolio_advice = state.get("portfolio_advice", "")

        history = risk_debate_state["history"]

        curr_situation = f"基金代码: {fund_codes}\n\n基金分析报告:\n{fund_analysis}"

        past_memory_str = ""
        if memory:
            past_memories = memory.get_memories(curr_situation, n_matches=2)
            for rec in past_memories:
                past_memory_str += rec["recommendation"] + "\n\n"

        language_instruction = get_final_language_instruction()

        research_decision = fund_debate_state.get("judge_decision", "无")

        prompt = PORTFOLIO_MANAGER_PROMPT.format(
            fund_codes=fund_codes,
            research_decision=research_decision,
            portfolio_advice=portfolio_advice,
            past_memory_str=past_memory_str,
            history=history,
            language_instruction=language_instruction,
        )

        response = invoke_llm_safely(llm, prompt)

        new_risk_debate_state = {
            "judge_decision": response.content,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "messages": [response],
        }

    return portfolio_manager_node
