# ifa/agents/researchers/bear_researcher.py
"""看跌研究员 —— 从风险角度论证基金投资隐患，与看涨研究员进行对抗辩论。"""

from ifa.agents.utils import (
    get_final_language_instruction,
    invoke_llm_safely,
)
from ifa.dataflows.data_cleaning import truncate_report


def create_bear_researcher(llm, memory=None):
    """创建看跌研究员节点。

    参数:
        llm: LLM 实例（quick_think_llm）
        memory: FinancialSituationMemory 实例，可选
    """

    def bear_researcher_node(state) -> dict:
        fund_debate_state = state.get("fund_debate_state", {})
        if not isinstance(fund_debate_state, dict):
            fund_debate_state = {}
        history = fund_debate_state.get("history", "")
        bear_history = fund_debate_state.get("bear_history", "")
        current_response = fund_debate_state.get("current_response", "")

        fund_codes = state.get("fund_codes", "")
        fund_analysis = truncate_report(state.get("fund_analysis_report", ""))
        index_analysis = truncate_report(state.get("index_analysis_report", ""))

        curr_situation = f"基金代码: {fund_codes}\n\n基金分析报告:\n{fund_analysis}\n\n指数分析报告:\n{index_analysis}"

        past_memory_str = ""
        if memory:
            try:
                past_memories = memory.get_memories(curr_situation, n_matches=2)
                for rec in past_memories:
                    past_memory_str += rec["recommendation"] + "\n\n"
            except Exception:
                past_memory_str = ""

        language_instruction = get_final_language_instruction()

        prompt = f"""You are a Bear Fund Researcher making the case against investing in the target index fund. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided analysis data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:
- Tracking Error and Deviation: Highlight any significant tracking error, or fund-specific risks that differ from the underlying index.
- Sector Concentration Risk: Emphasize over-concentration in specific sectors or stocks within the index.
- Market Timing Risks: Use current market valuations, macroeconomic headwinds, and sentiment data to support a cautious stance.
- Fund Manager Risk: For actively managed index funds, highlight manager turnover, style drift, or underperformance vs benchmark.
- Downside Scenarios: Model potential drawdown scenarios based on historical data and current conditions.
- Bull Counterpoints: Critically analyze the bull argument with specific data, exposing over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull researcher's points.

Resources available:
Fund code(s): {fund_codes}
Fund analysis report: {fund_analysis}
Index/Constituent analysis report: {index_analysis}
Conversation history of the debate: {history}
Last bull argument: {current_response}
Reflections from similar situations: {past_memory_str}

Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate.{language_instruction}"""

        response = invoke_llm_safely(llm, prompt)

        argument = f"Bear Researcher: {response.content}"

        count = fund_debate_state.get("count", 0)
        new_fund_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": fund_debate_state.get("bull_history", ""),
            "current_response": argument,
            "judge_decision": fund_debate_state.get("judge_decision", ""),
            "count": count + 1,
        }

        return {"fund_debate_state": new_fund_debate_state}

    return bear_researcher_node
