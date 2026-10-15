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

from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from ifa.agents.analysts.fund_analyst import create_fund_analyst
from ifa.agents.analysts.fund_screener import create_fund_screener
from ifa.agents.analysts.index_analyst import create_index_analyst
from ifa.agents.managers.portfolio_advisor import create_portfolio_advisor
from ifa.agents.managers.portfolio_manager import create_portfolio_manager
from ifa.agents.managers.report_generator import create_report_generator
from ifa.agents.managers.research_manager import create_research_manager
from ifa.agents.memory import FinancialSituationMemory
from ifa.agents.researchers.researcher import create_bear_researcher, create_bull_researcher
from ifa.agents.risk_mgmt.debator import create_aggressive_debator, create_conservative_debator, create_neutral_debator
from ifa.agents.tools.constituent_tools import (
    get_constituent_overview,
    get_constituent_performance,
    get_constituent_sector_distribution,
)
from ifa.agents.tools.etf_index_tools import get_etf_fund_info
from ifa.agents.tools.macro_tools import (
    get_index_valuation,
    get_macro_indicator,
    get_margin_data,
    get_market_fund_flow,
    get_market_valuation,
    get_north_flow,
    get_sector_fund_flow,
    get_valuation_signal,
)
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
from ifa.default_config import DEFAULT_MAX_DEBATE_ROUNDS, DEFAULT_MAX_RISK_DISCUSS_ROUNDS

from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor, parse_decision_signals

# ── 节点名称 → 用户友好的中文进度描述 ──
_NODE_DESCRIPTIONS: dict[str, str] = {
    "Fund Analyst": "基金分析师正在分析...",
    "Index Analyst": "指数分析师正在分析...",
    "Fund Screener": "正在筛选基金...",
    "Bull Researcher": "看涨研究员辩论中...",
    "Bear Researcher": "看跌研究员辩论中...",
    "Research Manager": "研究经理正在裁决...",
    "Report Generator": "正在生成分析报告...",
    "Portfolio Advisor R1": "组合顾问正在初步规划...",
    "Portfolio Advisor R2": "组合顾问正在优化方案...",
    "Aggressive Analyst": "积极分析师辩论中...",
    "Conservative Analyst": "保守分析师辩论中...",
    "Neutral Analyst": "中立分析师辩论中...",
    "Portfolio Manager": "组合经理正在决策...",
}

# 需要跳过进度报告的节点前缀（内部节点，不向用户展示）
_SKIP_NODE_PREFIXES = ("Msg Clear ", "tools_")


def _should_skip_node(name: str) -> bool:
    """判断节点是否应跳过进度报告。"""
    return any(name.startswith(p) for p in _SKIP_NODE_PREFIXES)


class AdvisorGraph:
    """IFA 工作流编排器，支持四种分析模式。"""

    def __init__(
        self,
        quick_llm,
        deep_llm,
        config: dict[str, Any] | None = None,
        callbacks: list | None = None,
    ):
        self.quick_llm = quick_llm
        self.deep_llm = deep_llm
        self.config = config or {}
        self.callbacks = callbacks or []

        # 兜底默认值取自 default_config 的常量，避免与 DEFAULT_CONFIG 各自维护而漂移
        max_debate_rounds = self.config.get("max_debate_rounds", DEFAULT_MAX_DEBATE_ROUNDS)
        max_risk_discuss_rounds = self.config.get("max_risk_discuss_rounds", DEFAULT_MAX_RISK_DISCUSS_ROUNDS)

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
        self.curr_state: dict[str, Any] | None = None

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
                # 宏观经济 / 市场情绪 / 估值
                get_macro_indicator,
                get_north_flow,
                get_market_fund_flow,
                get_margin_data,
                get_index_valuation,
                get_valuation_signal,
            ]
        )

        self.index_analyst_tools = ToolNode(
            [
                get_constituent_overview,
                get_constituent_sector_distribution,
                get_constituent_performance,
                get_etf_fund_info,
                # 宏观经济 / 市场情绪 / 估值
                get_macro_indicator,
                get_north_flow,
                get_market_fund_flow,
                get_sector_fund_flow,
                get_market_valuation,
                get_index_valuation,
                get_valuation_signal,
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
    #  图构建辅助方法
    # ════════════════════════════════════════════

    @staticmethod
    def _tools_key(name: str) -> str:
        """将 Agent 名转为工具节点 key（如 'Fund Analyst' → 'tools_fund_analyst'）。"""
        return f"tools_{name.lower().replace(' ', '_')}"

    @staticmethod
    def _clear_key(name: str) -> str:
        """将 Agent 名转为消息清理节点 key（如 'Fund Analyst' → 'Msg Clear Fund Analyst'）。"""
        return f"Msg Clear {name}"

    def _add_tool_agent(
        self,
        workflow: StateGraph,
        name: str,
        agent_fn,
        tool_node: ToolNode,
    ) -> None:
        """添加带工具调用的 Agent 节点组（Agent + Tools + MsgClear）。"""
        workflow.add_node(name, agent_fn)
        workflow.add_node(self._tools_key(name), tool_node)
        workflow.add_node(self._clear_key(name), create_msg_delete())

    def _add_tool_loop(
        self,
        workflow: StateGraph,
        name: str,
        continue_fn,
        next_node: str,
    ) -> None:
        """为 Agent 添加工具循环 + 条件跳转（tools → agent 循环, clear → next）。"""
        workflow.add_conditional_edges(
            name,
            continue_fn,
            [self._tools_key(name), self._clear_key(name)],
        )
        workflow.add_edge(self._tools_key(name), name)
        workflow.add_edge(self._clear_key(name), next_node)

    def _add_fund_debate(
        self,
        workflow: StateGraph,
        manager_name: str = "Research Manager",
    ) -> None:
        """添加 Bull/Bear 研究辩论循环。"""
        condition_fn = self.conditional_logic.should_continue_fund_debate
        workflow.add_conditional_edges(
            "Bull Researcher",
            condition_fn,
            {"Bear Researcher": "Bear Researcher", manager_name: manager_name},
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            condition_fn,
            {"Bull Researcher": "Bull Researcher", manager_name: manager_name},
        )

    def _add_risk_debate(self, workflow: StateGraph, manager_name: str) -> None:
        """添加 Aggressive/Conservative/Neutral 三方风险辩论循环。"""
        condition_fn = self.conditional_logic.should_continue_risk_analysis
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            condition_fn,
            {"Conservative Analyst": "Conservative Analyst", manager_name: manager_name},
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            condition_fn,
            {"Neutral Analyst": "Neutral Analyst", manager_name: manager_name},
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            condition_fn,
            {"Aggressive Analyst": "Aggressive Analyst", manager_name: manager_name},
        )

    def _add_to_report(
        self,
        workflow: StateGraph,
        manager_name: str,
        report_name: str = "Report Generator",
    ) -> None:
        """添加 manager → msg_clear → report → END 链路。"""
        workflow.add_edge(manager_name, self._clear_key(manager_name))
        workflow.add_edge(self._clear_key(manager_name), report_name)
        workflow.add_edge(report_name, END)

    # ════════════════════════════════════════════
    #  图构建方法
    # ════════════════════════════════════════════

    def build_deep_analysis_graph(self) -> CompiledStateGraph:
        """构建深度分析图（含辩论）。

        流程: Fund Analyst → Index Analyst? → Bull/Bear Debate → Research Manager → Report Generator
        """
        fund_analyst = create_fund_analyst(self.quick_llm)
        index_analyst = create_index_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        bull_researcher = create_bull_researcher(self.quick_llm, self.bull_memory)
        bear_researcher = create_bear_researcher(self.quick_llm, self.bear_memory)
        research_manager = create_research_manager(self.deep_llm, self.research_manager_memory)

        workflow = StateGraph(IFAdvisorState)

        # ── 分析阶段 ──
        self._add_tool_agent(workflow, "Fund Analyst", fund_analyst, self.fund_analyst_tools)
        self._add_tool_agent(workflow, "Index Analyst", index_analyst, self.index_analyst_tools)

        # ── 辩论阶段 ──
        workflow.add_node("Bull Researcher", bull_researcher)
        workflow.add_node("Bear Researcher", bear_researcher)
        workflow.add_node("Research Manager", research_manager)
        workflow.add_node(self._clear_key("Research Manager"), create_msg_delete())

        # ── 报告阶段 ──
        workflow.add_node("Report Generator", report_generator)

        # ── 边 ──
        workflow.add_edge(START, "Fund Analyst")

        # Fund Analyst 工具循环 → Index Analyst 条件跳转
        workflow.add_conditional_edges(
            "Fund Analyst",
            self.conditional_logic.should_continue_fund_analyst,
            [self._tools_key("Fund Analyst"), self._clear_key("Fund Analyst")],
        )
        workflow.add_edge(self._tools_key("Fund Analyst"), "Fund Analyst")

        workflow.add_conditional_edges(
            self._clear_key("Fund Analyst"),
            self.conditional_logic.should_skip_index_analyst,
            {"Index Analyst": "Index Analyst", "Skip Index Analyst": "Bull Researcher"},
        )

        workflow.add_conditional_edges(
            "Index Analyst",
            self.conditional_logic.should_continue_index_analyst,
            [self._tools_key("Index Analyst"), self._clear_key("Index Analyst")],
        )
        workflow.add_edge(self._tools_key("Index Analyst"), "Index Analyst")
        workflow.add_edge(self._clear_key("Index Analyst"), "Bull Researcher")

        # ── 辩论循环 ──
        self._add_fund_debate(workflow)
        self._add_to_report(workflow, "Research Manager")

        return workflow.compile()

    def build_deep_simple_graph(self) -> CompiledStateGraph:
        """构建简化版深度分析图（无辩论，向后兼容）。

        流程: Fund Analyst → Index Analyst? → Report Generator
        """
        fund_analyst = create_fund_analyst(self.quick_llm)
        index_analyst = create_index_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        workflow = StateGraph(IFAdvisorState)

        self._add_tool_agent(workflow, "Fund Analyst", fund_analyst, self.fund_analyst_tools)
        self._add_tool_agent(workflow, "Index Analyst", index_analyst, self.index_analyst_tools)
        workflow.add_node("Report Generator", report_generator)

        workflow.add_edge(START, "Fund Analyst")

        # Fund Analyst 工具循环 → Index Analyst 条件跳转
        workflow.add_conditional_edges(
            "Fund Analyst",
            self.conditional_logic.should_continue_fund_analyst,
            [self._tools_key("Fund Analyst"), self._clear_key("Fund Analyst")],
        )
        workflow.add_edge(self._tools_key("Fund Analyst"), "Fund Analyst")

        workflow.add_conditional_edges(
            self._clear_key("Fund Analyst"),
            self.conditional_logic.should_skip_index_analyst,
            {"Index Analyst": "Index Analyst", "Skip Index Analyst": "Report Generator"},
        )

        workflow.add_conditional_edges(
            "Index Analyst",
            self.conditional_logic.should_continue_index_analyst,
            [self._tools_key("Index Analyst"), self._clear_key("Index Analyst")],
        )
        workflow.add_edge(self._tools_key("Index Analyst"), "Index Analyst")
        workflow.add_edge(self._clear_key("Index Analyst"), "Report Generator")

        workflow.add_edge("Report Generator", END)

        return workflow.compile()

    def build_screen_graph(self) -> CompiledStateGraph:
        """构建筛选对比图（含辩论）。

        流程: Fund Screener → Fund Analyst → Bull/Bear Debate → Research Manager → Report Generator
        """
        fund_screener = create_fund_screener(self.quick_llm)
        fund_analyst = create_fund_analyst(self.quick_llm)
        report_generator = create_report_generator(self.deep_llm)

        bull_researcher = create_bull_researcher(self.quick_llm, self.bull_memory)
        bear_researcher = create_bear_researcher(self.quick_llm, self.bear_memory)
        research_manager = create_research_manager(self.deep_llm, self.research_manager_memory)

        workflow = StateGraph(IFAdvisorState)

        self._add_tool_agent(workflow, "Fund Screener", fund_screener, self.fund_screener_tools)
        self._add_tool_agent(workflow, "Fund Analyst", fund_analyst, self.fund_analyst_tools)

        workflow.add_node("Bull Researcher", bull_researcher)
        workflow.add_node("Bear Researcher", bear_researcher)
        workflow.add_node("Research Manager", research_manager)
        workflow.add_node(self._clear_key("Research Manager"), create_msg_delete())
        workflow.add_node("Report Generator", report_generator)

        workflow.add_edge(START, "Fund Screener")
        self._add_tool_loop(
            workflow, "Fund Screener", self.conditional_logic.should_continue_fund_screener, "Fund Analyst"
        )
        self._add_tool_loop(
            workflow, "Fund Analyst", self.conditional_logic.should_continue_fund_analyst, "Bull Researcher"
        )

        self._add_fund_debate(workflow)
        self._add_to_report(workflow, "Research Manager")

        return workflow.compile()

    def build_portfolio_graph(self) -> CompiledStateGraph:
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

        workflow = StateGraph(IFAdvisorState)

        workflow.add_node("Portfolio Advisor R1", portfolio_advisor)
        self._add_tool_agent(workflow, "Fund Screener", fund_screener, self.fund_screener_tools)
        self._add_tool_agent(workflow, "Fund Analyst", fund_analyst, self.fund_analyst_tools)

        workflow.add_node("Portfolio Advisor R2", portfolio_advisor)
        workflow.add_node(self._clear_key("Portfolio Advisor R2"), create_msg_delete())

        # ── 风险辩论 ──
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager)
        workflow.add_node(self._clear_key("Portfolio Manager"), create_msg_delete())

        workflow.add_node("Report Generator", report_generator)

        # ── 边 ──
        workflow.add_edge(START, "Portfolio Advisor R1")
        workflow.add_edge("Portfolio Advisor R1", "Fund Screener")

        self._add_tool_loop(
            workflow, "Fund Screener", self.conditional_logic.should_continue_fund_screener, "Fund Analyst"
        )
        self._add_tool_loop(
            workflow, "Fund Analyst", self.conditional_logic.should_continue_fund_analyst, "Portfolio Advisor R2"
        )
        workflow.add_edge("Portfolio Advisor R2", self._clear_key("Portfolio Advisor R2"))
        workflow.add_edge(self._clear_key("Portfolio Advisor R2"), "Aggressive Analyst")

        # ── 风险辩论循环 ──
        self._add_risk_debate(workflow, "Portfolio Manager")
        self._add_to_report(workflow, "Portfolio Manager")

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

    def run(self, mode: str, state: dict, on_progress=None) -> dict:
        """执行分析图并返回最终状态。

        参数:
            mode: 分析模式 (deep/screen/portfolio/deep_simple)
            state: 图的初始状态
            on_progress: 可选进度回调，签名为 (node_name, description) -> None。
                         为 None 时使用原 invoke 路径（向后兼容）。

        顶层异常保护：即使图执行失败，也尝试保存已有日志并返回错误信息。
        """
        import logging
        import uuid

        from ifa.observability.tracer import end_trace, start_trace

        logger = logging.getLogger(__name__)

        # 开始请求追踪
        fund_codes = state.get("fund_codes", "")
        results_dir = self.config.get("results_dir", "results")
        # 生成 request_id 并写入 state,让下游(save_report / _log_state)可读,
        # 使报告/日志/追踪三处文件名共享同一 id,既防并发覆盖又便于交叉检索
        request_id = state.get("request_id") or uuid.uuid4().hex[:12]
        state["request_id"] = request_id
        trace = start_trace(request_id, mode, fund_codes)
        trace.start_span("AdvisorGraph.run", "orchestrator")

        first_code = fund_codes.split(",")[0].strip() if fund_codes else ""
        if first_code:
            try:
                asset_type = detect_asset_type(first_code)
                state["asset_type"] = asset_type.value
            except Exception as e:
                logger.warning("资产类型检测失败 (%s): %s，继续执行", first_code, e)

        graph = self.build_graph(mode)

        try:
            if on_progress is not None:
                # ── 流式路径：逐节点报告进度 ──
                config: dict[str, Any] = {"recursion_limit": self.propagator.max_recur_limit}
                if self.callbacks:
                    config["callbacks"] = self.callbacks

                final_state: dict = state
                for stream_mode, chunk in graph.stream(state, config=config, stream_mode=["values", "updates"]):
                    if stream_mode == "updates":
                        node_name = next(iter(chunk))
                        if not _should_skip_node(node_name):
                            desc = _NODE_DESCRIPTIONS.get(node_name, node_name)
                            on_progress(node_name, desc)
                    elif stream_mode == "values":
                        final_state = chunk
            else:
                # ── 原有 invoke 路径，保持不变 ──
                args = self.propagator.get_graph_args(self.callbacks)
                final_state = graph.invoke(state, **args)

            # request_id 兜底:图执行可能返回不含 request_id 的快照,这里确保带回去
            final_state.setdefault("request_id", request_id)

            trace.finish_current(status="ok")
        except Exception as e:
            logger.error("图执行失败: %s", e)
            trace.fail_current(str(e))
            # 即使失败也尝试保存已有状态
            partial_state = {**state, "error": str(e)}
            self.curr_state = partial_state
            try:
                self._log_state(partial_state)
            except Exception:
                logger.error("日志保存也失败，放弃")
            end_trace(output_dir=results_dir)
            return partial_state

        self.curr_state = final_state

        # ── 提取评级/置信度写入 state（修复 final_rating 从不写入的 bug）──
        # ReportGenerator 只填 final_report，不填 final_rating/final_confidence。
        # 这里在图执行成功后统一提取一次，让 MCP/API/日志/回测验证都能读到结构化评级。
        # 用 try/except 隔离：提取失败不影响主流程（评级留空，消费者自行兜底）。
        if not final_state.get("error") and final_state.get("final_report"):
            try:
                needs_rating = not final_state.get("final_rating")
                needs_confidence = not final_state.get("final_confidence")
                if needs_rating or needs_confidence:
                    # 第一优先级：管理层裁决/最终报告里机器可读的 Rating:/Confidence: 行（零 LLM 调用）
                    parsed_rating, parsed_confidence = self.resolve_decision_signals(final_state)
                    if parsed_rating or parsed_confidence:
                        logger.debug(
                            "评级/置信度取自决策文本的机器可读行（未调用 LLM）: %s / %s",
                            parsed_rating,
                            parsed_confidence,
                        )
                    if needs_rating:
                        final_state["final_rating"] = parsed_rating or self.process_signal(final_state["final_report"])
                    if needs_confidence:
                        final_state["final_confidence"] = parsed_confidence or self.process_confidence(
                            final_state["final_report"]
                        )
            except Exception as e:
                logger.warning("评级提取失败，final_rating/final_confidence 留空: %s", e)

        try:
            self._log_state(final_state)
        except Exception as e:
            logger.warning("日志保存失败: %s（不影响分析结果）", e)

        end_trace(output_dir=results_dir)
        return final_state

    @staticmethod
    def _safe_get_nested(state: dict, *keys, default=""):
        """安全访问嵌套字典，任一层缺失返回 default。"""
        current = state
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key, default)
            if current is default:
                return default
        return current

    def _log_state(self, final_state: dict):
        """将完整状态保存为结构化 JSON 日志。"""
        results_dir = self.config.get("results_dir", "results")
        fund_codes = final_state.get("fund_codes", "unknown").replace(",", "_").strip()
        analysis_date = final_state.get("analysis_date", "unknown")
        mode = final_state.get("mode", "unknown")

        g = self._safe_get_nested

        log_entry = {
            "fund_codes": final_state.get("fund_codes", ""),
            "analysis_date": final_state.get("analysis_date", ""),
            "mode": mode,
            "asset_type": final_state.get("asset_type", ""),
            "fund_analysis_report": final_state.get("fund_analysis_report", ""),
            "index_analysis_report": final_state.get("index_analysis_report", ""),
            "portfolio_advice": final_state.get("portfolio_advice", ""),
            "fund_debate_state": {
                "bull_history": g(final_state, "fund_debate_state", "bull_history"),
                "bear_history": g(final_state, "fund_debate_state", "bear_history"),
                "history": g(final_state, "fund_debate_state", "history"),
                "judge_decision": g(final_state, "fund_debate_state", "judge_decision"),
                "count": g(final_state, "fund_debate_state", "count", default=0),
            },
            "risk_debate_state": {
                "aggressive_history": g(final_state, "risk_debate_state", "aggressive_history"),
                "conservative_history": g(final_state, "risk_debate_state", "conservative_history"),
                "neutral_history": g(final_state, "risk_debate_state", "neutral_history"),
                "history": g(final_state, "risk_debate_state", "history"),
                "judge_decision": g(final_state, "risk_debate_state", "judge_decision"),
                "count": g(final_state, "risk_debate_state", "count", default=0),
            },
            "final_report": final_state.get("final_report", ""),
            "final_rating": final_state.get("final_rating", ""),
            "final_confidence": final_state.get("final_confidence", ""),
            "request_id": final_state.get("request_id", ""),
            "error": final_state.get("error", ""),
        }

        directory = Path(results_dir) / "logs" / fund_codes
        # request_id 后缀防并发覆盖(与 save_report / tracer 一致);缺失 fallback 到秒级时间戳
        suffix = (final_state.get("request_id") or datetime.now().strftime("%H%M%S"))[:8]
        log_path = directory / f"{analysis_date}_{mode}_{suffix}.json"
        # 延迟导入避免与 common.py 的循环导入(common 顶部 import AdvisorGraph)
        from ifa.common import _atomic_write_json

        _atomic_write_json(log_path, log_entry)

    def resolve_decision_signals(self, state: dict) -> tuple[str | None, str | None]:
        """确定性解析评级/置信度：管理层裁决优先，其次最终报告；都不命中返回 (None, None)。

        管理层（Research/Portfolio Manager）与报告生成器都被要求输出机器可读的
        `Rating: X` / `Confidence: Y` 行，因此正常情况下这里不需要再花一次 LLM 调用。
        portfolio 模式下 risk_debate_state 的裁决才是最终决策，故排在 fund_debate_state 之前。
        """
        candidates: list[str] = []
        for key in ("risk_debate_state", "fund_debate_state"):
            debate = state.get(key)
            if isinstance(debate, dict):
                decision = debate.get("judge_decision")
                if decision:
                    candidates.append(str(decision))
        report = state.get("final_report")
        if report:
            candidates.append(str(report))

        rating: str | None = None
        confidence: str | None = None
        for text in candidates:
            parsed_rating, parsed_confidence = parse_decision_signals(text)
            if rating is None and parsed_rating:
                rating = parsed_rating
            if confidence is None and parsed_confidence:
                confidence = parsed_confidence
            if rating and confidence:
                break
        return rating, confidence

    def process_signal(self, full_signal: str) -> str:
        """从最终决策中提取标准化评级。"""
        return self.signal_processor.process_signal(full_signal)

    def process_confidence(self, full_signal: str) -> str:
        """从最终决策中提取置信度。"""
        return self.signal_processor.process_confidence(full_signal)

    def reflect_and_remember(self, returns_losses):
        """基于实际收益/亏损反思决策并更新记忆（按模式条件性执行）。"""
        if self.curr_state is None:
            return
        self.reflector.reflect_all(
            self.curr_state,
            returns_losses,
            self.bull_memory,
            self.bear_memory,
            self.research_manager_memory,
            self.portfolio_manager_memory,
        )
