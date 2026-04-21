# ifa/agents/researchers/bull_researcher.py
"""看涨研究员 —— 从积极角度论证基金投资价值，与看跌研究员进行对抗辩论。"""

from ifa.agents.utils import (
    get_final_language_instruction,
    invoke_llm_safely,
)


def create_bull_researcher(llm, memory=None):
    """创建看涨研究员节点。

    参数:
        llm: LLM 实例（quick_think_llm）
        memory: FinancialSituationMemory 实例，可选
    """

    def bull_researcher_node(state) -> dict:
        fund_debate_state = state["fund_debate_state"]
        history = fund_debate_state.get("history", "")
        bull_history = fund_debate_state.get("bull_history", "")
        current_response = fund_debate_state.get("current_response", "")

        fund_codes = state.get("fund_codes", "")
        fund_analysis = state.get("fund_analysis_report", "")
        index_analysis = state.get("index_analysis_report", "")

        curr_situation = f"基金代码: {fund_codes}\n\n基金分析报告:\n{fund_analysis}\n\n指数分析报告:\n{index_analysis}"

        past_memory_str = ""
        if memory:
            past_memories = memory.get_memories(curr_situation, n_matches=2)
            for rec in past_memories:
                past_memory_str += rec["recommendation"] + "\n\n"

        language_instruction = get_final_language_instruction()

        prompt = f"""You are a Bull Fund Researcher advocating for investing in the target index fund. Your task is to build a strong, evidence-based case emphasizing the fund's growth potential, cost advantages, and positive market indicators. Leverage the provided analysis data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Growth Potential: Highlight the underlying index's market opportunities, sector exposure, and long-term return potential.
- Cost Efficiency: Emphasize low expense ratios, tax efficiency, and tracking accuracy advantages of index funds.
- Market Timing: Use current market conditions, valuations, and macroeconomic indicators to support a buy case.
- Diversification Benefits: Highlight how the fund fits into a diversified portfolio.
- Bear Counterpoints: Critically analyze the bear argument with specific data, addressing concerns thoroughly.
- Engagement: Present your argument in a conversational style, engaging directly with the bear researcher's points.

Resources available:
Fund code(s): {fund_codes}
Fund analysis report: {fund_analysis}
Index/Constituent analysis report: {index_analysis}
Conversation history of the debate: {history}
Last bear argument: {current_response}
Reflections from similar situations: {past_memory_str}

Use this information to deliver a compelling bull argument, refute the bear's concerns, and engage in a dynamic debate.{language_instruction}"""

        response = invoke_llm_safely(llm, prompt)

        argument = f"Bull Researcher: {response.content}"

        new_fund_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": fund_debate_state.get("bear_history", ""),
            "current_response": argument,
            "judge_decision": fund_debate_state.get("judge_decision", ""),
            "count": fund_debate_state["count"] + 1,
        }

        return {"fund_debate_state": new_fund_debate_state}

    return bull_researcher_node
