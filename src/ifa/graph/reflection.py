# ifa/graph/reflection.py
"""反思模块 —— 基于实际收益/亏损，反思各 Agent 决策并更新记忆。

借鉴 TradingAgents 的 Reflector 设计，适配 IFA 的指数基金分析场景。
支持按模式（deep/screen/portfolio/deep_simple）条件性反思，
缺少对应辩论状态的 Agent 自动跳过。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


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
        from ifa.agents.utils import invoke_llm_safely

        messages = [
            ("system", self.reflection_system_prompt),
            (
                "human",
                f"Actual Returns: {returns_losses}\n\nAnalysis/Decision: {report}\n\nFund Analysis Context: {situation}",
            ),
        ]
        result = invoke_llm_safely(self.quick_thinking_llm, messages)
        return result.content if hasattr(result, "content") else str(result)

    def reflect_all(
        self,
        current_state: dict,
        returns_losses,
        bull_memory,
        bear_memory,
        research_manager_memory,
        portfolio_manager_memory,
    ) -> None:
        """根据模式条件性反思所有可用组件。

        deep/screen 模式：反思 bull、bear、research_manager（需要 fund_debate_state）
        portfolio 模式：额外反思 portfolio_manager（需要 risk_debate_state）
        deep_simple 模式：无辩论状态，跳过全部反思
        """
        mode = current_state.get("mode", "")
        if not mode:
            logger.warning("反思跳过：状态中缺少 mode 字段")
            return

        # deep_simple 无辩论，无反思目标
        if mode == "deep_simple":
            logger.debug("deep_simple 模式：跳过反思（无辩论状态）")
            return

        # deep/screen：反思 fund_debate 相关组件
        fund_debate = current_state.get("fund_debate_state")
        if isinstance(fund_debate, dict) and fund_debate.get("history"):
            self.reflect_bull_researcher(current_state, returns_losses, bull_memory)
            self.reflect_bear_researcher(current_state, returns_losses, bear_memory)
            self.reflect_research_manager(current_state, returns_losses, research_manager_memory)
        else:
            logger.debug("反思跳过：无 fund_debate_state 或辩论历史为空")

        # portfolio：额外反思 risk_debate 相关组件
        if mode == "portfolio":
            risk_debate = current_state.get("risk_debate_state")
            if isinstance(risk_debate, dict) and risk_debate.get("judge_decision"):
                self.reflect_portfolio_manager(current_state, returns_losses, portfolio_manager_memory)
            else:
                logger.debug("反思跳过：无 risk_debate_state 或裁决为空")

    def reflect_bull_researcher(self, current_state, returns_losses, bull_memory):
        """反思看涨研究员的分析并更新记忆。"""
        situation = self._extract_current_situation(current_state)
        bull_history = self._safe_get_debate(current_state, "fund_debate_state", "bull_history")
        if not bull_history:
            return
        result = self._reflect_on_component("BULL", bull_history, situation, returns_losses)
        bull_memory.add_situations([(situation, result)])

    def reflect_bear_researcher(self, current_state, returns_losses, bear_memory):
        """反思看跌研究员的分析并更新记忆。"""
        situation = self._extract_current_situation(current_state)
        bear_history = self._safe_get_debate(current_state, "fund_debate_state", "bear_history")
        if not bear_history:
            return
        result = self._reflect_on_component("BEAR", bear_history, situation, returns_losses)
        bear_memory.add_situations([(situation, result)])

    def reflect_research_manager(self, current_state, returns_losses, manager_memory):
        """反思研究经理的裁决并更新记忆。"""
        situation = self._extract_current_situation(current_state)
        judge_decision = self._safe_get_debate(current_state, "fund_debate_state", "judge_decision")
        if not judge_decision:
            return
        result = self._reflect_on_component("RESEARCH MANAGER", judge_decision, situation, returns_losses)
        manager_memory.add_situations([(situation, result)])

    def reflect_portfolio_manager(self, current_state, returns_losses, pm_memory):
        """反思投资组合经理的最终决策并更新记忆。"""
        situation = self._extract_current_situation(current_state)
        judge_decision = self._safe_get_debate(current_state, "risk_debate_state", "judge_decision")
        if not judge_decision:
            return
        result = self._reflect_on_component("PORTFOLIO MANAGER", judge_decision, situation, returns_losses)
        pm_memory.add_situations([(situation, result)])

    @staticmethod
    def _safe_get_debate(state: dict, debate_key: str, field: str, default=""):
        """安全访问嵌套的辩论状态。"""
        debate = state.get(debate_key, {})
        if not isinstance(debate, dict):
            return default
        return debate.get(field, default)
