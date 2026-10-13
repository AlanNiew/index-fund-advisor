# api/routers/data.py
"""同步数据查询 API 路由。"""

import asyncio

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")


def _parse_match_total(result: str, fallback: int) -> int:
    """从 `# Matches: N (showing M)` 头部解析真实匹配总数。"""
    for line in result.split("\n"):
        if line.startswith("# Matches: "):
            try:
                return int(line.split(":", 1)[1].strip().split()[0])
            except (IndexError, ValueError):
                break
    return fallback


@router.get("/funds/search")
async def search_funds(q: str = "", limit: int = 20):
    """快速搜索基金（同步，不经过 LLM，在全部公募基金中过滤）。"""
    from fastapi import HTTPException

    from ifa.data_tools.api import run_data_tool
    from ifa.dataflows.a_share import DATA_SOURCE_ERROR_MARKER

    result = await asyncio.to_thread(run_data_tool, "search_funds", query=q, limit=limit)
    if DATA_SOURCE_ERROR_MARKER in result:
        # 取数失败不能伪装成「空结果」：返回 502，让调用方能区分「没有匹配」与「数据源不可用」。
        raise HTTPException(status_code=502, detail=result)
    lines = [line for line in result.split("\n") if line and not line.startswith("#")]
    return {"results": lines, "total": _parse_match_total(result, len(lines)), "showing": len(lines)}


@router.get("/funds/{code}/basic")
async def fund_basic(code: str):
    """获取基金基本信息（同步）。"""
    from ifa.data_tools.api import run_data_tool

    result = await asyncio.to_thread(run_data_tool, "get_fund_basic_info", symbol=code)
    return {"fund_code": code, "data": result}


@router.get("/indexes/categories")
async def index_categories():
    """获取指数分类列表。"""
    return {
        "categories": [
            "全部",
            "沪深指数",
            "行业主题",
            "大盘指数",
            "中盘指数",
            "小盘指数",
        ],
        "tracking_methods": ["全部", "被动指数型", "增强指数型"],
    }
