# ifa/agents/managers/research_manager.py
"""研究经理 —— 评估看涨/看跌辩论，做出投资方向裁决。"""

from ifa.agents.utils import (
    get_final_language_instruction,
    invoke_llm_safely,
)


def create_research_manager(llm, memory=None):
    """创建研究经理节点。

    参数:
        llm: LLM 实例（deep_think_llm，关键决策节点）
        memory: FinancialSituationMemory 实例，可选
    """

    def research_manager_node(state) -> dict:
        fund_codes = state.get("fund_codes", "")
        fund_analysis = state.get("fund_analysis_report", "")
        index_analysis = state.get("index_analysis_report", "")
        fund_debate_state = state["fund_debate_state"]
        history = fund_debate_state.get("history", "")

        curr_situation = f"基金代码: {fund_codes}\n\n基金分析报告:\n{fund_analysis}\n\n指数分析报告:\n{index_analysis}"

        past_memory_str = ""
        if memory:
            past_memories = memory.get_memories(curr_situation, n_matches=2)
            for rec in past_memories:
                past_memory_str += rec["recommendation"] + "\n\n"

        language_instruction = get_final_language_instruction()

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate between the Bull and Bear researchers and make a definitive decision: align with the bull researcher (invest/recommend), the bear researcher (caution/redeem), or choose Hold only if strongly justified.

Summarize the key points from both sides concisely. Your recommendation — STRONG BUY / BUY / HOLD / UNDERWEIGHT / SELL — must be clear and actionable. Avoid defaulting to Hold simply because both sides have valid points; commit to a stance grounded in the debate's strongest arguments.

Additionally, provide:
1. Your Recommendation: A decisive stance with the rating.
2. Rationale: Why these arguments lead to your conclusion.
3. Key Risks: Top 2-3 risks regardless of your recommendation.
4. Time Horizon: Recommended holding period.

Take into account your past mistakes on similar situations:
\"{past_memory_str}\"

Here is the debate history:
{history}

{language_instruction}"""

        response = invoke_llm_safely(llm, prompt)

        new_fund_debate_state = {
            "judge_decision": response.content,
            "history": fund_debate_state.get("history", ""),
            "bull_history": fund_debate_state.get("bull_history", ""),
            "bear_history": fund_debate_state.get("bear_history", ""),
            "current_response": response.content,
            "count": fund_debate_state["count"],
        }

        return {
            "fund_debate_state": new_fund_debate_state,
            "messages": [response],
        }

    return research_manager_node
