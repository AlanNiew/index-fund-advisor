# ifa/agents/types.py
"""IFA 专用 Agent 状态类型定义。

借鉴 TradingAgents 的 InvestDebateState / RiskDebateState 嵌套状态设计，
为 IFA 增加基金研究辩论状态和风险评估辩论状态。
"""

from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import TypedDict


class FundDebateState(TypedDict):
    """基金研究辩论状态 —— 看涨/看跌双方辩论。"""

    bull_history: Annotated[str, "看涨方论证历史"]
    bear_history: Annotated[str, "看跌方论证历史"]
    history: Annotated[str, "完整对话历史"]
    current_response: Annotated[str, "最新一轮回复"]
    judge_decision: Annotated[str, "研究经理的最终裁决"]
    count: Annotated[int, "当前对话轮次计数"]


class RiskDebateState(TypedDict):
    """风险评估辩论状态 —— 积极/保守/中立三方辩论。"""

    aggressive_history: Annotated[str, "积极方论证历史"]
    conservative_history: Annotated[str, "保守方论证历史"]
    neutral_history: Annotated[str, "中立方论证历史"]
    history: Annotated[str, "完整对话历史"]
    latest_speaker: Annotated[str, "上一次发言者"]
    current_aggressive_response: Annotated[str, "积极方最新回复"]
    current_conservative_response: Annotated[str, "保守方最新回复"]
    current_neutral_response: Annotated[str, "中立方最新回复"]
    judge_decision: Annotated[str, "投资组合经理的最终裁决"]
    count: Annotated[int, "当前对话轮次计数"]


class IFAdvisorState(MessagesState):
    """指数基金分析工作流的统一状态。"""

    # ── 基础输入 ──
    fund_codes: Annotated[str, "目标基金代码（单只或多只，逗号分隔）"]
    analysis_date: Annotated[str, "分析日期 YYYY-MM-DD"]
    mode: Annotated[str, "分析模式: screen / deep / portfolio"]
    asset_type: Annotated[str, "检测到的资产类型"]

    # ── 筛选/组合参数 ──
    screen_conditions: Annotated[str, "用户筛选条件（自然语言）"]
    risk_profile: Annotated[str, "用户风险偏好: conservative / moderate / aggressive / growth"]

    # ── 分析结果 ──
    screen_results: Annotated[str, "筛选结果（候选基金列表）"]
    fund_analysis_report: Annotated[str, "基金分析报告"]
    index_analysis_report: Annotated[str, "成分股/指数分析报告"]
    portfolio_advice: Annotated[str, "组合配置建议（投资组合顾问）"]

    # ── 辩论状态 ──
    fund_debate_state: Annotated[FundDebateState, "基金研究辩论状态（看涨/看跌）"]
    risk_debate_state: Annotated[RiskDebateState, "风险评估辩论状态（积极/保守/中立）"]

    # ── 最终输出 ──
    final_report: Annotated[str, "Markdown 格式最终报告"]
    final_rating: Annotated[str, "标准化评级: STRONG_BUY / BUY / HOLD / UNDERWEIGHT / SELL"]
    final_confidence: Annotated[str, "置信度说明"]
