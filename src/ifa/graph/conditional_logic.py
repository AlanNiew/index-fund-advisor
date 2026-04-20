# ifa/graph/conditional_logic.py
"""简化版条件逻辑，仅处理工具调用判断（无辩论逻辑）。"""

from ifa.agents.types import IFAdvisorState


class ConditionalLogic:
    """IFA 图的条件边判断逻辑。"""

    def should_continue_fund_analyst(self, state: IFAdvisorState) -> str:
        """判断基金分析师是否需要继续调用工具。"""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fund_analyst"
        return "Msg Clear Fund Analyst"

    def should_continue_index_analyst(self, state: IFAdvisorState) -> str:
        """判断成分股分析师是否需要继续调用工具。"""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_index_analyst"
        return "Msg Clear Index Analyst"

    def should_continue_fund_screener(self, state: IFAdvisorState) -> str:
        """判断基金筛选器是否需要继续调用工具。"""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fund_screener"
        return "Msg Clear Fund Screener"

    def should_skip_index_analyst(self, state: IFAdvisorState) -> str:
        """判断是否需要跳过成分股分析（非 ETF/指数类型时跳过）。"""
        asset_type = state.get("asset_type", "")
        if asset_type in ("etf", "index"):
            return "Index Analyst"
        return "Skip Index Analyst"
