# ifa/agents/types.py
"""IFA 专用 Agent 状态类型定义。"""

from typing import Annotated, Literal

from langgraph.graph import MessagesState
from typing_extensions import TypedDict


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
    portfolio_advice: Annotated[str, "组合配置建议"]

    # ── 最终输出 ──
    final_report: Annotated[str, "Markdown 格式最终报告"]
