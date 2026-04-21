# ifa/graph/reflection.py
"""反思模块 —— 基于实际收益/亏损，反思各 Agent 决策并更新记忆。

借鉴 TradingAgents 的 Reflector 设计，适配 IFA 的指数基金分析场景。
"""

from typing import Any


class Reflector:
    """基于 LLM 的决策反思器，评估历史决策质量并提取经验教训。"""

    def __init__(self, quick_thinking_llm: Any):
        self.quick_thinking_llm = quick_thinking_llm
        self.reflection_system_prompt = self._get_reflection_prompt()

    def _get_reflection_prompt(self) -> str:
        return """
You are an expert index fund analyst tasked with reviewing investment decisions and providing a comprehensive, step-by-step analysis.
Your goal is to deliver detailed insights into fund recommendations and highlight opportunities for improvement.

1. Reasoning:
   - For each fund decision (STRONG_BUY/BUY/HOLD/UNDERWEIGHT/SELL), determine whether it was correct based on the actual returns/losses.
   - Analyze contributing factors: fund performance, tracking error, sector exposure, market timing, expense ratio, risk metrics.
   - Weight the importance of each factor in the decision-making process.

2. Improvement:
   - For any incorrect decisions, propose revisions to maximize returns.
   - Provide a detailed list of corrective actions or improvements.

3. Summary:
   - Summarize the lessons learned from the successes and mistakes.
   - Highlight how these lessons can be adapted for future fund analysis scenarios.

4. Query:
   - Extract key insights into a concise summary of no more than 1000 tokens.
   - Ensure the condensed summary captures the essence of the lessons for easy reference.
"""

    def _extract_current_situation(self, current_state: dict[str, Any]) -> str:
        """从状态中提取当前市场/基金情景。"""
        fund_analysis = current_state.get("fund_analysis_report", "")
        index_analysis = current_state.get("index_analysis_report", "")
        return f"{fund_analysis}\n\n{index_analysis}"

    def _reflect_on_component(self, component_type: str, report: str, situation: str, returns_losses) -> str:
        """生成单个组件的反思。"""
        messages = [
            ("system", self.reflection_system_prompt),
            (
                "human",
                f"Actual Returns: {returns_losses}\n\nAnalysis/Decision: {report}\n\nFund Analysis Context: {situation}",
            ),
        ]
        result = self.quick_thinking_llm.invoke(messages).content
        return result

    def reflect_bull_researcher(self, current_state, returns_losses, bull_memory):
        """反思看涨研究员的分析并更新记忆。"""
        situation = self._extract_current_situation(current_state)
        bull_history = current_state["fund_debate_state"]["bull_history"]
        result = self._reflect_on_component("BULL", bull_history, situation, returns_losses)
        bull_memory.add_situations([(situation, result)])

    def reflect_bear_researcher(self, current_state, returns_losses, bear_memory):
        """反思看跌研究员的分析并更新记忆。"""
        situation = self._extract_current_situation(current_state)
        bear_history = current_state["fund_debate_state"]["bear_history"]
        result = self._reflect_on_component("BEAR", bear_history, situation, returns_losses)
        bear_memory.add_situations([(situation, result)])

    def reflect_research_manager(self, current_state, returns_losses, manager_memory):
        """反思研究经理的裁决并更新记忆。"""
        situation = self._extract_current_situation(current_state)
        judge_decision = current_state["fund_debate_state"]["judge_decision"]
        result = self._reflect_on_component("RESEARCH MANAGER", judge_decision, situation, returns_losses)
        manager_memory.add_situations([(situation, result)])

    def reflect_portfolio_manager(self, current_state, returns_losses, pm_memory):
        """反思投资组合经理的最终决策并更新记忆。"""
        situation = self._extract_current_situation(current_state)
        judge_decision = current_state["risk_debate_state"]["judge_decision"]
        result = self._reflect_on_component("PORTFOLIO MANAGER", judge_decision, situation, returns_losses)
        pm_memory.add_situations([(situation, result)])
