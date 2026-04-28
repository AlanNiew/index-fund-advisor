# ifa/agents/researchers/researcher.py
"""看涨/看跌研究员 —— 基于 TradingAgents 的对抗辩论架构。"""

from __future__ import annotations

from ifa.agents.utils import (
    get_final_language_instruction,
    invoke_llm_safely,
)
from ifa.dataflows.data_cleaning import truncate_report


def create_researcher(role: str, prompt_template: str, history_key: str, label: str):
    """
    创建研究员节点。

    参数:
        role: 研究员角色标识（"bull" 或 "bear"）。
        prompt_template: Prompt 模板字符串（含 format 占位符）。
        history_key: 自身历史字段名（"bull_history" 或 "bear_history"）。
        label: 输出标注（如 "Bull Researcher" 或 "Bear Researcher"）。
        llm: LLM 实例（quick_think_llm）。
        memory: FinancialSituationMemory 实例，可选。
    """

    def _make_node(llm, memory=None):
        def researcher_node(state) -> dict:
            fund_debate_state = state.get("fund_debate_state", {})
            if not isinstance(fund_debate_state, dict):
                fund_debate_state = {}
            history = fund_debate_state.get("history", "")
            own_history = fund_debate_state.get(history_key, "")
            current_response = fund_debate_state.get("current_response", "")

            fund_codes = state.get("fund_codes", "")
            fund_analysis = truncate_report(state.get("fund_analysis_report", ""))
            index_analysis = truncate_report(state.get("index_analysis_report", ""))

            curr_situation = (
                f"基金代码: {fund_codes}\n\n基金分析报告:\n{fund_analysis}\n\n指数分析报告:\n{index_analysis}"
            )

            past_memory_str = ""
            if memory:
                try:
                    past_memories = memory.get_memories(curr_situation, n_matches=2)
                    for rec in past_memories:
                        past_memory_str += rec["recommendation"] + "\n\n"
                except Exception:
                    past_memory_str = ""

            language_instruction = get_final_language_instruction()

            prompt = prompt_template.format(
                fund_codes=fund_codes,
                fund_analysis=fund_analysis,
                index_analysis=index_analysis,
                history=history,
                current_response=current_response,
                past_memory_str=past_memory_str,
                language_instruction=language_instruction,
            )

            response = invoke_llm_safely(llm, prompt)

            argument = f"{label}: {response.content}"

            count = fund_debate_state.get("count", 0)
            new_fund_debate_state = {
                "history": history + "\n" + argument,
                history_key: own_history + "\n" + argument,
                "current_response": argument,
                "judge_decision": fund_debate_state.get("judge_decision", ""),
                "count": count + 1,
            }
            for other_key in ("bull_history", "bear_history"):
                if other_key != history_key:
                    new_fund_debate_state[other_key] = fund_debate_state.get(other_key, "")

            return {"fund_debate_state": new_fund_debate_state}

        return researcher_node

    return _make_node


def create_bull_researcher(llm, memory=None):
    """创建看涨研究员节点。"""
    from ifa.agents.prompts.researchers import BULL_RESEARCHER_PROMPT

    factory = create_researcher("bull", BULL_RESEARCHER_PROMPT, "bull_history", "Bull Researcher")
    return factory(llm, memory)


def create_bear_researcher(llm, memory=None):
    """创建看跌研究员节点。"""
    from ifa.agents.prompts.researchers import BEAR_RESEARCHER_PROMPT

    factory = create_researcher("bear", BEAR_RESEARCHER_PROMPT, "bear_history", "Bear Researcher")
    return factory(llm, memory)
