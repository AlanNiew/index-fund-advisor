# ifa/graph/conditional_logic.py
"""条件边判断逻辑 —— 控制工具调用循环和辩论流程。"""

from ifa.agents.types import IFAdvisorState


class ConditionalLogic:
    """IFA 图的条件边判断逻辑，包含工具调用和辩论流程控制。"""

    def __init__(self, max_debate_rounds: int = 1, max_risk_discuss_rounds: int = 1):
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    # ── 工具调用条件（原有） ──

    def should_continue_fund_analyst(self, state: IFAdvisorState) -> str:
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools_fund_analyst"
        return "Msg Clear Fund Analyst"

    def should_continue_index_analyst(self, state: IFAdvisorState) -> str:
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools_index_analyst"
        return "Msg Clear Index Analyst"

    def should_continue_fund_screener(self, state: IFAdvisorState) -> str:
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools_fund_screener"
        return "Msg Clear Fund Screener"

    def should_skip_index_analyst(self, state: IFAdvisorState) -> str:
        asset_type = state.get("asset_type", "")
        if asset_type in ("etf", "index"):
            return "Index Analyst"
        return "Skip Index Analyst"

    # ── 基金研究辩论条件 ──

    def should_continue_fund_debate(self, state: IFAdvisorState) -> str:
        """控制看涨/看跌辩论循环。"""
        if state["fund_debate_state"]["count"] >= 2 * self.max_debate_rounds:
            return "Research Manager"
        if state["fund_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    # ── 风险评估辩论条件 ──

    def should_continue_risk_analysis(self, state: IFAdvisorState) -> str:
        """控制积极/保守/中立三方辩论循环。"""
        if state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds:
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
