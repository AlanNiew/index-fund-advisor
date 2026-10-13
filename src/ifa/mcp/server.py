"""IFA MCP Server —— 把 IFA 的基金数据 / 估值 / 分析能力暴露给 MCP 客户端（如 Claude）。

设计要点
--------
- **直接复用 IFA 数据层 / 分析层**，不经过 HTTP：数据工具走
  :func:`ifa.data_tools.api.run_data_tool` 与
  :func:`ifa.dataflows.a_share_macro.fetch_valuation_metrics`；
  分析走 :func:`ifa.common.build_advisor` / :func:`ifa.common.build_state`。
- **stdio 传输**（默认），适配 Claude Code / Claude Desktop 本地接入。
- 所有底层调用都是同步阻塞（AkShare 网络 / LLM），用
  :func:`asyncio.to_thread` 包到线程池，避免卡住事件循环（Python 3.10+ 自带，无新依赖）。
- 数据 / 估值工具不依赖 LLM；只有 :func:`analyze_fund` 需要 ``.env`` 里配置有效的 LLM API Key。
"""

from __future__ import annotations

import asyncio
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# 加载 .env，使 analyze_fund 能读到 LLM API Key（数据工具走 AkShare 公开数据无需 Key）。
load_dotenv()

mcp = FastMCP("IFA - Index Fund Advisor")


# ── 异步包装辅助 ──────────────────────────────────────────────


async def _run_data_tool(name: str, **params: Any) -> str:
    """在线程池执行同步数据工具（AkShare 网络阻塞），返回其字符串结果。"""
    from ifa.data_tools.api import run_data_tool

    return await asyncio.to_thread(run_data_tool, name, **params)


# ── 数据 / 估值工具（不依赖 LLM）──────────────────────────────


@mcp.tool()
async def search_funds(query: str = "", limit: int = 20) -> dict:
    """按关键词或代码搜索公募基金（不调用 LLM，走 AkShare 公开数据）。

    参数：
        query: 基金代码、名称或拼音缩写（如 "沪深300"、"510300"、"易方达"）；留空返回列表头部。
        limit: 最大返回行数，默认 20。

    返回：{"query": str, "results": list[str], "total": int}，每行含代码与名称。
    """
    from ifa.data_tools.api import run_data_tool
    from ifa.dataflows.a_share import DATA_SOURCE_ERROR_MARKER

    result = await asyncio.to_thread(run_data_tool, "search_funds", query=query, limit=limit)
    if DATA_SOURCE_ERROR_MARKER in result:
        # 区分「数据源不可用」与「查无结果」：前者带 error 字段返回，不伪装成空结果。
        return {"query": query, "results": [], "total": 0, "error": result}
    lines = [line for line in result.split("\n") if line and not line.startswith("#")]
    total = 0
    for line in result.split("\n"):
        if line.startswith("# Matches: "):
            try:
                total = int(line.split(":", 1)[1].strip().split()[0])
            except (IndexError, ValueError):
                total = len(lines)
            break
    else:
        total = len(lines)
    return {"query": query, "results": lines, "total": total}


@mcp.tool()
async def get_fund_info(code: str) -> dict:
    """获取基金基本信息（类型 / 规模 / 基金经理 / 费率 / 成立日期等）。

    参数：
        code: 6 位基金代码，如 "510300"、"161725"。

    返回：{"fund_code": str, "data": str}，data 为结构化文本。
    """
    result = await _run_data_tool("get_fund_basic_info", symbol=code)
    return {"fund_code": code, "data": result}


@mcp.tool()
async def get_index_valuation_metrics(index_name: str = "沪深300") -> dict:
    """获取指数的结构化估值指标（最适合程序消费，返回 dict）。

    参数：
        index_name: 指数名称，如 "沪深300" / "中证500" / "中证1000"。

    返回字段（不可用时为 None）：pe_ttm、pb、roe、dividend_yield（上证A股市场参考值，
        非该指数自身股息率）、earnings_yield、risk_free_rate、erp（股权风险溢价）、date。
    """
    from ifa.dataflows.a_share_macro import fetch_valuation_metrics

    return await asyncio.to_thread(fetch_valuation_metrics, index_name)


@mcp.tool()
async def get_index_valuation_report(index_name: str = "沪深300") -> str:
    """指数综合估值分析报告（含 PE/PB 历史百分位、估值判断、博格公式预期收益等）。

    参数：
        index_name: 指数名称，如 "沪深300" / "中证500"。
    """
    return await _run_data_tool("get_index_valuation", index_name=index_name)


@mcp.tool()
async def get_valuation_signal(index_name: str = "沪深300") -> str:
    """指数估值信号分析（盈利收益率法给出 买入 / 持有 / 卖出 信号）。

    参数：
        index_name: 指数名称，如 "沪深300"。
    """
    return await _run_data_tool("get_valuation_signal", index_name=index_name)


@mcp.tool()
async def screen_index_funds(
    index_category: str = "全部",
    tracking_method: str = "全部",
) -> str:
    """筛选指数型基金（按指数分类 + 跟踪方式）。

    参数：
        index_category: 指数分类，可选 "全部" / "沪深指数" / "行业主题" /
            "大盘指数" / "中盘指数" / "小盘指数"。
        tracking_method: 跟踪方式，可选 "全部" / "被动指数型" / "增强指数型"。

    返回：CSV 文本（前 50 条），含基金代码、名称、规模、费率等。
    """
    return await _run_data_tool(
        "get_index_fund_filter",
        symbol=index_category,
        indicator=tracking_method,
    )


@mcp.tool()
async def get_index_constituents(index_name: str) -> str:
    """获取指数成份股列表。

    参数：
        index_name: 指数名称或代码，如 "沪深300"、"000300"。
    """
    return await _run_data_tool("get_index_constituents", symbol=index_name)


@mcp.tool()
async def get_north_flow(symbol: str = "北向资金") -> str:
    """获取北向资金流向数据（市场情绪参考）。

    参数：
        symbol: 可选 "北向资金" / "沪股通" / "深股通"，默认 "北向资金"。
    """
    return await _run_data_tool("get_north_flow", symbol=symbol)


# ── AI 分析工具（依赖 LLM，慢）──────────────────────────────


@mcp.tool()
async def analyze_fund(
    code: str,
    analysis_date: str = "",
    mode: str = "deep_simple",
) -> dict:
    """对单只基金做 AI 深度分析（调用 IFA 多 agent 工作流）。

    需要在 ``.env`` 配置有效的 LLM API Key（默认走智谱 GLM）。
    耗时：deep_simple 约 30-60 秒；deep（含看涨 / 看跌辩论）约 1-3 分钟。

    参数：
        code: 6 位基金代码，如 "510300"。
        analysis_date: 分析日期 "YYYY-MM-DD"，留空用今天。
        mode: "deep_simple"（快速，默认）或 "deep"（含辩论，更深入）。

    返回：{"fund_code", "mode", "final_rating"（评级）, "final_confidence"（置信度）,
        "final_report"（Markdown 报告）, "error"（失败时的错误信息，成功为 None）}。
    """

    def _run() -> dict:
        try:
            from ifa.common import build_advisor, build_state
        except ImportError as exc:
            return {
                "error": (
                    "AI 分析能力不可用：未安装完整依赖（ifa.common 缺失）。"
                    "轻量发行版仅含数据/估值工具；如需 analyze_fund，"
                    "请安装完整版（含 langchain/langgraph）。"
                    f"（{exc}）"
                )
            }

        state_kwargs: dict[str, str] = {"fund_codes": code}
        if analysis_date:
            state_kwargs["analysis_date"] = analysis_date
        state = build_state(mode, **state_kwargs)
        advisor = build_advisor()
        return advisor.run(mode, state)

    state = await asyncio.to_thread(_run)
    return {
        "fund_code": code,
        "mode": mode,
        "final_rating": state.get("final_rating"),
        "final_confidence": state.get("final_confidence"),
        "final_report": state.get("final_report"),
        "error": state.get("error"),
    }


def main() -> None:
    """启动 IFA MCP server（stdio 传输）。"""
    mcp.run()


if __name__ == "__main__":
    main()
