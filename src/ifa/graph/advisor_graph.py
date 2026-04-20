# ifa/graph/advisor_graph.py
"""IFA 核心图编排，构建三种分析模式的 LangGraph 工作流。"""

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ifa.agents.analysts.fund_analyst import create_fund_analyst
from ifa.agents.analysts.fund_screener import create_fund_screener
from ifa.agents.analysts.index_analyst import create_index_analyst
from ifa.agents.managers.portfolio_advisor import create_portfolio_advisor
from ifa.agents.managers.report_generator import create_report_generator
from ifa.agents.tools.constituent_tools import (
    get_constituent_overview,
    get_constituent_performance,
    get_constituent_sector_distribution,
)
from ifa.agents.tools.etf_index_tools import get_etf_fund_info
from ifa.agents.tools.public_fund_tools import (
    get_etf_spot_data,
    get_fund_achievement,
    get_fund_asset_allocation,
    get_fund_basic_info,
    get_fund_bond_holdings,
    get_fund_fee,
    get_fund_history_nav,
    get_fund_industry_allocation,
    get_fund_list,
    get_fund_profit_probability,
    get_fund_purchase_status,
    get_fund_risk_analysis,
    get_fund_stock_holdings,
    get_index_fund_filter,
    get_open_fund_rank,
)
from ifa.agents.types import IFAdvisorState
from ifa.agents.utils import create_msg_delete
from ifa.dataflows.asset_type import detect_asset_type

from .conditional_logic import ConditionalLogic


class AdvisorGraph:
    """IFA 工作流编排器，支持三种分析模式。"""

    def __init__(self, quick_llm, deep_llm, config: dict[str, Any] = None):
        self.quick_llm = quick_llm
        self.deep_llm = deep_llm
        self.config = config or {}
        self.conditional_logic = ConditionalLogic()

        # 工具节点
        self.fund_analyst_tools = ToolNode([
            get_fund_list,
            get_fund_basic_info,
            get_fund_achievement,
            get_fund_risk_analysis,
            get_fund_stock_holdings,
            get_fund_bond_holdings,
            get_fund_industry_allocation,
            get_fund_asset_allocation,
            get_fund_history_nav,
            get_fund_fee,
            get_fund_purchase_status,
            get_fund_profit_probability,
            get_open_fund_rank,
        ])

        self.index_analyst_tools = ToolNode([
            get_constituent_overview,
            get_constituent_sector_distribution,
            get_constituent_performance,
            get_etf_fund_info,
        ])

        self.fund_screener_tools = ToolNode([
            get_fund_list,
            get_fund_basic_info,
            get_index_fund_filter,
            get_open_fund_rank,
            get_etf_spot_data,
        ])

    def build_deep_analysis_graph(self) -> StateGraph:
        """构建单只基金深度分析图。

        流程: Fund Analyst → Index Analyst? → Report Generator → END
        """
        fund_analyst = create_fund_analyst(self.quick_llm)
        index_analyst = create_index_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        workflow = StateGraph(IFAdvisorState)

        # 添加节点
        workflow.add_node("Fund Analyst", fund_analyst)
        workflow.add_node("tools_fund_analyst", self.fund_analyst_tools)
        workflow.add_node("Msg Clear Fund Analyst", create_msg_delete())

        workflow.add_node("Index Analyst", index_analyst)
        workflow.add_node("tools_index_analyst", self.index_analyst_tools)
        workflow.add_node("Msg Clear Index Analyst", create_msg_delete())

        workflow.add_node("Report Generator", report_generator)

        # 边
        workflow.add_edge(START, "Fund Analyst")

        workflow.add_conditional_edges(
            "Fund Analyst",
            self.conditional_logic.should_continue_fund_analyst,
            ["tools_fund_analyst", "Msg Clear Fund Analyst"],
        )
        workflow.add_edge("tools_fund_analyst", "Fund Analyst")

        # 条件跳转到 Index Analyst
        workflow.add_conditional_edges(
            "Msg Clear Fund Analyst",
            self.conditional_logic.should_skip_index_analyst,
            {"Index Analyst": "Index Analyst", "Skip Index Analyst": "Report Generator"},
        )

        workflow.add_conditional_edges(
            "Index Analyst",
            self.conditional_logic.should_continue_index_analyst,
            ["tools_index_analyst", "Msg Clear Index Analyst"],
        )
        workflow.add_edge("tools_index_analyst", "Index Analyst")
        workflow.add_edge("Msg Clear Index Analyst", "Report Generator")

        workflow.add_edge("Report Generator", END)

        return workflow.compile()

    def build_screen_graph(self) -> StateGraph:
        """构建筛选对比模式图。

        流程: Fund Screener → Fund Analyst → Report Generator → END
        """
        fund_screener = create_fund_screener(self.quick_llm)
        fund_analyst = create_fund_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        workflow = StateGraph(IFAdvisorState)

        workflow.add_node("Fund Screener", fund_screener)
        workflow.add_node("tools_fund_screener", self.fund_screener_tools)
        workflow.add_node("Msg Clear Fund Screener", create_msg_delete())

        workflow.add_node("Fund Analyst", fund_analyst)
        workflow.add_node("tools_fund_analyst", self.fund_analyst_tools)
        workflow.add_node("Msg Clear Fund Analyst", create_msg_delete())

        workflow.add_node("Report Generator", report_generator)

        workflow.add_edge(START, "Fund Screener")

        workflow.add_conditional_edges(
            "Fund Screener",
            self.conditional_logic.should_continue_fund_screener,
            ["tools_fund_screener", "Msg Clear Fund Screener"],
        )
        workflow.add_edge("tools_fund_screener", "Fund Screener")
        workflow.add_edge("Msg Clear Fund Screener", "Fund Analyst")

        workflow.add_conditional_edges(
            "Fund Analyst",
            self.conditional_logic.should_continue_fund_analyst,
            ["tools_fund_analyst", "Msg Clear Fund Analyst"],
        )
        workflow.add_edge("tools_fund_analyst", "Fund Analyst")
        workflow.add_edge("Msg Clear Fund Analyst", "Report Generator")

        workflow.add_edge("Report Generator", END)

        return workflow.compile()

    def build_portfolio_graph(self) -> StateGraph:
        """构建组合配置建议模式图。

        流程: Portfolio Advisor (R1) → Fund Screener → Fund Analyst →
              Portfolio Advisor (R2) → Report Generator → END
        """
        portfolio_advisor = create_portfolio_advisor(self.deep_llm)
        fund_screener = create_fund_screener(self.quick_llm)
        fund_analyst = create_fund_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        workflow = StateGraph(IFAdvisorState)

        workflow.add_node("Portfolio Advisor R1", portfolio_advisor)
        workflow.add_node("Fund Screener", fund_screener)
        workflow.add_node("tools_fund_screener", self.fund_screener_tools)
        workflow.add_node("Msg Clear Fund Screener", create_msg_delete())
        workflow.add_node("Fund Analyst", fund_analyst)
        workflow.add_node("tools_fund_analyst", self.fund_analyst_tools)
        workflow.add_node("Msg Clear Fund Analyst", create_msg_delete())
        workflow.add_node("Portfolio Advisor R2", portfolio_advisor)
        workflow.add_node("Report Generator", report_generator)

        workflow.add_edge(START, "Portfolio Advisor R1")
        workflow.add_edge("Portfolio Advisor R1", "Fund Screener")

        workflow.add_conditional_edges(
            "Fund Screener",
            self.conditional_logic.should_continue_fund_screener,
            ["tools_fund_screener", "Msg Clear Fund Screener"],
        )
        workflow.add_edge("tools_fund_screener", "Fund Screener")
        workflow.add_edge("Msg Clear Fund Screener", "Fund Analyst")

        workflow.add_conditional_edges(
            "Fund Analyst",
            self.conditional_logic.should_continue_fund_analyst,
            ["tools_fund_analyst", "Msg Clear Fund Analyst"],
        )
        workflow.add_edge("tools_fund_analyst", "Fund Analyst")
        workflow.add_edge("Msg Clear Fund Analyst", "Portfolio Advisor R2")

        workflow.add_edge("Portfolio Advisor R2", "Report Generator")
        workflow.add_edge("Report Generator", END)

        return workflow.compile()

    def build_graph(self, mode: str):
        """根据模式构建对应的图。

        参数:
            mode: "deep" | "screen" | "portfolio"
        """
        builders = {
            "deep": self.build_deep_analysis_graph,
            "screen": self.build_screen_graph,
            "portfolio": self.build_portfolio_graph,
        }
        builder = builders.get(mode)
        if builder is None:
            raise ValueError(f"未知模式: {mode}，可选: deep, screen, portfolio")
        return builder()

    def run(self, mode: str, state: dict) -> dict:
        """执行分析图并返回最终状态。"""
        # 自动检测资产类型
        fund_codes = state.get("fund_codes", "")
        first_code = fund_codes.split(",")[0].strip() if fund_codes else ""
        if first_code:
            asset_type = detect_asset_type(first_code)
            state["asset_type"] = asset_type.value

        graph = self.build_graph(mode)
        return graph.invoke(state)
