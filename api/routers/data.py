# api/routers/data.py
"""同步数据查询 API 路由。"""

import asyncio

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")


@router.get("/funds/search")
async def search_funds(q: str = "", limit: int = 20):
    """快速搜索基金（同步，不经过 LLM）。"""
    from ifa.data_tools.api import run_data_tool

    result = await asyncio.to_thread(run_data_tool, "get_fund_list")
    lines = result.strip().split("\n")
    matched = [line for line in lines if q.upper() in line.upper()][:limit]
    return {"results": matched, "total": len(matched)}


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
