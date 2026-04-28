# api/routers/analysis.py
"""分析相关 API 路由。"""

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter

from api.models.schemas import (
    DeepAnalyzeRequest,
    PortfolioRequest,
    ScreenRequest,
    TaskDetailResponse,
    TaskResponse,
)
from api.tasks.manager import add_task, get_task

router = APIRouter(prefix="/api/v1")


@router.post("/analyze/deep", response_model=TaskResponse)
async def analyze_deep(req: DeepAnalyzeRequest):
    """提交单只基金深度分析任务（异步）。"""
    task_id = str(uuid.uuid4())
    task = {
        "task_id": task_id,
        "status": "pending",
        "mode": "deep",
        "params": req.model_dump(),
        "created_at": datetime.now().isoformat(),
        "result": None,
        "error": None,
    }
    add_task(task)
    asyncio.create_task(_run_analysis(task))
    return TaskResponse(task_id=task_id, status="pending", mode="deep", created_at=task["created_at"])


@router.post("/analyze/screen", response_model=TaskResponse)
async def analyze_screen(req: ScreenRequest):
    """提交筛选对比分析任务（异步）。"""
    task_id = str(uuid.uuid4())
    conditions = req.conditions or f"类别: {req.index_category}, 跟踪方式: {req.tracking_method}, 前 {req.max_results} 只"
    task = {
        "task_id": task_id,
        "status": "pending",
        "mode": "screen",
        "params": {**req.model_dump(), "conditions": conditions},
        "created_at": datetime.now().isoformat(),
        "result": None,
        "error": None,
    }
    add_task(task)
    asyncio.create_task(_run_analysis(task))
    return TaskResponse(task_id=task_id, status="pending", mode="screen", created_at=task["created_at"])


@router.post("/analyze/portfolio", response_model=TaskResponse)
async def analyze_portfolio(req: PortfolioRequest):
    """提交组合配置建议任务（异步）。"""
    task_id = str(uuid.uuid4())
    task = {
        "task_id": task_id,
        "status": "pending",
        "mode": "portfolio",
        "params": req.model_dump(),
        "created_at": datetime.now().isoformat(),
        "result": None,
        "error": None,
    }
    add_task(task)
    asyncio.create_task(_run_analysis(task))
    return TaskResponse(task_id=task_id, status="pending", mode="portfolio", created_at=task["created_at"])


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task_detail(task_id: str):
    """查询任务状态和结果。"""
    task = get_task(task_id)
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return TaskDetailResponse(**task)


@router.get("/tasks")
async def list_tasks():
    """列出所有任务。"""
    from api.tasks.manager import all_tasks
    return all_tasks()


async def _run_analysis(task: dict):
    """在后台线程中执行 LangGraph 分析图。"""
    task["status"] = "processing"
    try:
        result = await asyncio.to_thread(_execute_graph, task)
        task["result"] = result
        task["status"] = "completed"
    except Exception as e:
        task["error"] = str(e)
        task["status"] = "failed"
    finally:
        task["completed_at"] = datetime.now().isoformat()


def _execute_graph(task: dict) -> dict:
    """同步执行 LangGraph 图（在线程池中运行）。"""
    from dotenv import load_dotenv
    load_dotenv()

    from ifa.common import build_advisor, build_state

    advisor = build_advisor()

    params = task["params"]
    mode = task["mode"]

    if mode == "deep":
        state = build_state(mode, fund_codes=params.get("fund_code", ""),
                            analysis_date=params.get("analysis_date", datetime.now().strftime("%Y-%m-%d")))
    elif mode == "screen":
        state = build_state(mode, screen_conditions=params.get("conditions", ""))
    elif mode == "portfolio":
        state = build_state(mode, risk_profile=params.get("risk_profile", "moderate"))
    else:
        raise ValueError(f"未知模式: {mode}")

    final_state = advisor.run(mode, state)
    return {
        "report_md": final_state.get("final_report", ""),
        "mode": mode,
    }
