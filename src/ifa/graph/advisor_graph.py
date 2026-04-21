# ifa/graph/advisor_graph.py
"""IFA 核心图编排，构建四种分析模式的 LangGraph 工作流。

借鉴 TradingAgents 的模块化架构，将职责拆分为：
- AdvisorGraph: 主编排类（对齐 TradingAgentsGraph）
- GraphSetup: 图构建（内嵌）
- Propagator: 状态初始化（独立模块）
- ConditionalLogic: 条件边（独立模块）
- Reflector: 反思（独立模块）
- SignalProcessor: 信号处理（独立模块）

分析模式:
- deep: Fund Analyst → Index Analyst? → Bull/Bear Debate → Research Manager → Report Generator
- screen: Fund Screener → Fund Analyst → Bull/Bear Debate → Research Manager → Report Generator
- portfolio: Portfolio Advisor → Fund Screener → Fund Analyst → Risk Debate → Portfolio Manager → Report Generator
- deep_simple: 原始的 Fund Analyst → Index Analyst? → Report Generator（无辩论，向后兼容）
"""

import json
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ifa.agents.analysts.fund_analyst import create_fund_analyst
from ifa.agents.analysts.fund_screener import create_fund_screener
from ifa.agents.analysts.index_analyst import create_index_analyst
from ifa.agents.managers.portfolio_advisor import create_portfolio_advisor
from ifa.agents.managers.portfolio_manager import create_portfolio_manager
from ifa.agents.managers.report_generator import create_report_generator
from ifa.agents.managers.research_manager import create_research_manager
from ifa.agents.memory import FinancialSituationMemory
from ifa.agents.researchers.bear_researcher import create_bear_researcher
from ifa.agents.researchers.bull_researcher import create_bull_researcher
from ifa.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
from ifa.agents.risk_mgmt.conservative_debator import create_conservative_debator
from ifa.agents.risk_mgmt.neutral_debator import create_neutral_debator
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
from ifa.agents.utils import create_msg_delete
from ifa.dataflows.asset_type import detect_asset_type

from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor


class AdvisorGraph:
    """IFA 工作流编排器，支持四种分析模式。"""

    def __init__(
        self,
        quick_llm,
        deep_llm,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
    ):
        self.quick_llm = quick_llm
        self.deep_llm = deep_llm
        self.config = config or {}
        self.callbacks = callbacks or []

        max_debate_rounds = self.config.get("max_debate_rounds", 1)
        max_risk_discuss_rounds = self.config.get("max_risk_discuss_rounds", 1)

        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=max_debate_rounds,
            max_risk_discuss_rounds=max_risk_discuss_rounds,
        )
        self.propagator = Propagator(max_recur_limit=self.config.get("max_recur_limit", 150))
        self.reflector = Reflector(quick_llm)
        self.signal_processor = SignalProcessor(quick_llm)

        # ── 初始化记忆 ──
        self.bull_memory = FinancialSituationMemory("bull_memory", self.config)
        self.bear_memory = FinancialSituationMemory("bear_memory", self.config)
        self.research_manager_memory = FinancialSituationMemory("research_manager_memory", self.config)
        self.portfolio_manager_memory = FinancialSituationMemory("portfolio_manager_memory", self.config)

        # ── 工具节点 ──
        self._create_tool_nodes()

        # ── 状态追踪 ──
        self.curr_state = None

    def _create_tool_nodes(self):
        """创建各 Agent 的工具节点。"""
        self.fund_analyst_tools = ToolNode(
            [
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
            ]
        )

        self.index_analyst_tools = ToolNode(
            [
                get_constituent_overview,
                get_constituent_sector_distribution,
                get_constituent_performance,
                get_etf_fund_info,
            ]
        )

        self.fund_screener_tools = ToolNode(
            [
                get_fund_list,
                get_fund_basic_info,
                get_index_fund_filter,
                get_open_fund_rank,
                get_etf_spot_data,
            ]
        )

    # ════════════════════════════════════════════
    #  图构建方法
    # ════════════════════════════════════════════

    def build_deep_analysis_graph(self) -> StateGraph:
        """构建深度分析图（含辩论）。

        流程: Fund Analyst → Index Analyst? → Bull/Bear Debate → Research Manager → Report Generator
        """
        fund_analyst = create_fund_analyst(self.quick_llm)
        index_analyst = create_index_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        bull_researcher = create_bull_researcher(self.quick_llm, self.bull_memory)
        bear_researcher = create_bear_researcher(self.quick_llm, self.bear_memory)
        research_manager = create_research_manager(self.deep_llm, self.research_manager_memory)

        workflow = StateGraph(type("IFAdvisorState", (), {"__annotations__": {}}))
        from ifa.agents.types import IFAdvisorState

        workflow = StateGraph(IFAdvisorState)

        # ── 分析阶段 ──
        workflow.add_node("Fund Analyst", fund_analyst)
        workflow.add_node("tools_fund_analyst", self.fund_analyst_tools)
        workflow.add_node("Msg Clear Fund Analyst", create_msg_delete())

        workflow.add_node("Index Analyst", index_analyst)
        workflow.add_node("tools_index_analyst", self.index_analyst_tools)
        workflow.add_node("Msg Clear Index Analyst", create_msg_delete())

        # ── 辩论阶段 ──
        workflow.add_node("Bull Researcher", bull_researcher)
        workflow.add_node("Bear Researcher", bear_researcher)
        workflow.add_node("Research Manager", research_manager)
        workflow.add_node("Msg Clear Research Manager", create_msg_delete())

        # ── 报告阶段 ──
        workflow.add_node("Report Generator", report_generator)

        # ── 边 ──
        workflow.add_edge(START, "Fund Analyst")

        workflow.add_conditional_edges(
            "Fund Analyst",
            self.conditional_logic.should_continue_fund_analyst,
            ["tools_fund_analyst", "Msg Clear Fund Analyst"],
        )
        workflow.add_edge("tools_fund_analyst", "Fund Analyst")

        workflow.add_conditional_edges(
            "Msg Clear Fund Analyst",
            self.conditional_logic.should_skip_index_analyst,
            {"Index Analyst": "Index Analyst", "Skip Index Analyst": "Bull Researcher"},
        )

        workflow.add_conditional_edges(
            "Index Analyst",
            self.conditional_logic.should_continue_index_analyst,
            ["tools_index_analyst", "Msg Clear Index Analyst"],
        )
        workflow.add_edge("tools_index_analyst", "Index Analyst")
        workflow.add_edge("Msg Clear Index Analyst", "Bull Researcher")

        # ── 辩论循环 ──
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_fund_debate,
            {"Bear Researcher": "Bear Researcher", "Research Manager": "Research Manager"},
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_fund_debate,
            {"Bull Researcher": "Bull Researcher", "Research Manager": "Research Manager"},
        )

        workflow.add_edge("Research Manager", "Msg Clear Research Manager")
        workflow.add_edge("Msg Clear Research Manager", "Report Generator")
        workflow.add_edge("Report Generator", END)

        return workflow.compile()

    def build_deep_simple_graph(self) -> StateGraph:
        """构建简化版深度分析图（无辩论，向后兼容）。

        流程: Fund Analyst → Index Analyst? → Report Generator
        """
        fund_analyst = create_fund_analyst(self.quick_llm)
        index_analyst = create_index_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        from ifa.agents.types import IFAdvisorState

        workflow = StateGraph(IFAdvisorState)

        workflow.add_node("Fund Analyst", fund_analyst)
        workflow.add_node("tools_fund_analyst", self.fund_analyst_tools)
        workflow.add_node("Msg Clear Fund Analyst", create_msg_delete())

        workflow.add_node("Index Analyst", index_analyst)
        workflow.add_node("tools_index_analyst", self.index_analyst_tools)
        workflow.add_node("Msg Clear Index Analyst", create_msg_delete())

        workflow.add_node("Report Generator", report_generator)

        workflow.add_edge(START, "Fund Analyst")

        workflow.add_conditional_edges(
            "Fund Analyst",
            self.conditional_logic.should_continue_fund_analyst,
            ["tools_fund_analyst", "Msg Clear Fund Analyst"],
        )
        workflow.add_edge("tools_fund_analyst", "Fund Analyst")

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
        """构建筛选对比图（含辩论）。

        流程: Fund Screener → Fund Analyst → Bull/Bear Debate → Research Manager → Report Generator
        """
        fund_screener = create_fund_screener(self.quick_llm)
        fund_analyst = create_fund_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        bull_researcher = create_bull_researcher(self.quick_llm, self.bull_memory)
        bear_researcher = create_bear_researcher(self.quick_llm, self.bear_memory)
        research_manager = create_research_manager(self.deep_llm, self.research_manager_memory)

        from ifa.agents.types import IFAdvisorState

        workflow = StateGraph(IFAdvisorState)

        workflow.add_node("Fund Screener", fund_screener)
        workflow.add_node("tools_fund_screener", self.fund_screener_tools)
        workflow.add_node("Msg Clear Fund Screener", create_msg_delete())

        workflow.add_node("Fund Analyst", fund_analyst)
        workflow.add_node("tools_fund_analyst", self.fund_analyst_tools)
        workflow.add_node("Msg Clear Fund Analyst", create_msg_delete())

        workflow.add_node("Bull Researcher", bull_researcher)
        workflow.add_node("Bear Researcher", bear_researcher)
        workflow.add_node("Research Manager", research_manager)
        workflow.add_node("Msg Clear Research Manager", create_msg_delete())

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
        workflow.add_edge("Msg Clear Fund Analyst", "Bull Researcher")

        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_fund_debate,
            {"Bear Researcher": "Bear Researcher", "Research Manager": "Research Manager"},
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_fund_debate,
            {"Bull Researcher": "Bull Researcher", "Research Manager": "Research Manager"},
        )

        workflow.add_edge("Research Manager", "Msg Clear Research Manager")
        workflow.add_edge("Msg Clear Research Manager", "Report Generator")
        workflow.add_edge("Report Generator", END)

        return workflow.compile()

    def build_portfolio_graph(self) -> StateGraph:
        """构建组合配置图（含风险评估辩论）。

        流程: Portfolio Advisor(R1) → Fund Screener → Fund Analyst →
              Portfolio Advisor(R2) → Risk Debate → Portfolio Manager → Report Generator
        """
        portfolio_advisor = create_portfolio_advisor(self.deep_llm)
        fund_screener = create_fund_screener(self.quick_llm)
        fund_analyst = create_fund_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        aggressive_analyst = create_aggressive_debator(self.quick_llm)
        conservative_analyst = create_conservative_debator(self.quick_llm)
        neutral_analyst = create_neutral_debator(self.quick_llm)
        portfolio_manager = create_portfolio_manager(self.deep_llm, self.portfolio_manager_memory)

        from ifa.agents.types import IFAdvisorState

        workflow = StateGraph(IFAdvisorState)

        workflow.add_node("Portfolio Advisor R1", portfolio_advisor)
        workflow.add_node("Fund Screener", fund_screener)
        workflow.add_node("tools_fund_screener", self.fund_screener_tools)
        workflow.add_node("Msg Clear Fund Screener", create_msg_delete())

        workflow.add_node("Fund Analyst", fund_analyst)
        workflow.add_node("tools_fund_analyst", self.fund_analyst_tools)
        workflow.add_node("Msg Clear Fund Analyst", create_msg_delete())

        workflow.add_node("Portfolio Advisor R2", portfolio_advisor)
        workflow.add_node("Msg Clear Portfolio Advisor R2", create_msg_delete())

        # ── 风险辩论 ──
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager)
        workflow.add_node("Msg Clear Portfolio Manager", create_msg_delete())

        workflow.add_node("Report Generator", report_generator)

        # ── 边 ──
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
        workflow.add_edge("Portfolio Advisor R2", "Msg Clear Portfolio Advisor R2")
        workflow.add_edge("Msg Clear Portfolio Advisor R2", "Aggressive Analyst")

        # ── 风险辩论循环 ──
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )

        workflow.add_edge("Portfolio Manager", "Msg Clear Portfolio Manager")
        workflow.add_edge("Msg Clear Portfolio Manager", "Report Generator")
        workflow.add_edge("Report Generator", END)

        return workflow.compile()

    def build_graph(self, mode: str):
        """根据模式构建对应的图。"""
        enable_debate = self.config.get("enable_debate", True)
        builders = {
            "deep": self.build_deep_analysis_graph if enable_debate else self.build_deep_simple_graph,
            "deep_simple": self.build_deep_simple_graph,
            "screen": self.build_screen_graph,
            "portfolio": self.build_portfolio_graph,
        }
        builder = builders.get(mode)
        if builder is None:
            raise ValueError(f"未知模式: {mode}，可选: deep, deep_simple, screen, portfolio")
        return builder()

    # ════════════════════════════════════════════
    #  运行与日志
    # ════════════════════════════════════════════

    def run(self, mode: str, state: dict) -> dict:
        """执行分析图并返回最终状态。"""
        fund_codes = state.get("fund_codes", "")
        first_code = fund_codes.split(",")[0].strip() if fund_codes else ""
        if first_code:
            asset_type = detect_asset_type(first_code)
            state["asset_type"] = asset_type.value

        graph = self.build_graph(mode)
        args = self.propagator.get_graph_args(self.callbacks)

        final_state = graph.invoke(state, **args)

        self.curr_state = final_state
        self._log_state(final_state)

        return final_state

    def _log_state(self, final_state: dict):
        """将完整状态保存为结构化 JSON 日志。"""
        results_dir = self.config.get("results_dir", "results")
        fund_codes = final_state.get("fund_codes", "unknown").replace(",", "_").strip()
        analysis_date = final_state.get("analysis_date", "unknown")
        mode = final_state.get("mode", "unknown")

        log_entry = {
            "fund_codes": final_state.get("fund_codes", ""),
            "analysis_date": final_state.get("analysis_date", ""),
            "mode": mode,
            "asset_type": final_state.get("asset_type", ""),
            "fund_analysis_report": final_state.get("fund_analysis_report", ""),
            "index_analysis_report": final_state.get("index_analysis_report", ""),
            "portfolio_advice": final_state.get("portfolio_advice", ""),
            "fund_debate_state": {
                "bull_history": final_state["fund_debate_state"]["bull_history"],
                "bear_history": final_state["fund_debate_state"]["bear_history"],
                "history": final_state["fund_debate_state"]["history"],
                "judge_decision": final_state["fund_debate_state"]["judge_decision"],
                "count": final_state["fund_debate_state"]["count"],
            },
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
                "count": final_state["risk_debate_state"]["count"],
            },
            "final_report": final_state.get("final_report", ""),
        }

        directory = Path(results_dir) / fund_codes / "ifa_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"state_log_{analysis_date}_{mode}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_entry, f, indent=4, ensure_ascii=False)

    def process_signal(self, full_signal: str) -> str:
        """从最终决策中提取标准化评级。"""
        return self.signal_processor.process_signal(full_signal)

    def process_confidence(self, full_signal: str) -> str:
        """从最终决策中提取置信度。"""
        return self.signal_processor.process_confidence(full_signal)

    def reflect_and_remember(self, returns_losses):
        """基于实际收益/亏损反思决策并更新记忆。"""
        if self.curr_state is None:
            return
        self.reflector.reflect_bull_researcher(self.curr_state, returns_losses, self.bull_memory)
        self.reflector.reflect_bear_researcher(self.curr_state, returns_losses, self.bear_memory)
        self.reflector.reflect_research_manager(self.curr_state, returns_losses, self.research_manager_memory)
        self.reflector.reflect_portfolio_manager(self.curr_state, returns_losses, self.portfolio_manager_memory)
