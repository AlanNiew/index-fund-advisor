# api/main.py
"""IFA FastAPI 服务入口。"""

import asyncio
import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="IFA - Index Fund Advisor API",
    description="AI 驱动的指数基金分析 API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 内存任务存储 ──
_tasks: dict[str, dict] = {}


# ── 请求/响应模型 ──

class DeepAnalyzeRequest(BaseModel):
    fund_code: str = Field(..., description="基金代码，如 510300")
    analysis_date: str | None = Field(None, description="分析日期 YYYY-MM-DD")
    language: str = Field("zh", description="输出语言")


class ScreenRequest(BaseModel):
    conditions: str | None = Field(None, description="自然语言筛选条件")
    index_category: str = Field("全部", description="指数类别")
    tracking_method: str = Field("全部", description="跟踪方式")
    max_results: int = Field(10, description="最大返回数量")
    language: str = Field("zh", description="输出语言")


class PortfolioRequest(BaseModel):
    risk_profile: str = Field("moderate", description="风险偏好")
    investment_amount: float | None = Field(None, description="投资金额")
    preferences: dict = Field(default_factory=dict, description="附加偏好")
    language: str = Field("zh", description="输出语言")


class TaskResponse(BaseModel):
    task_id: str
    status: str
    mode: str
    created_at: str


class TaskDetailResponse(BaseModel):
    task_id: str
    status: str
    mode: str
    created_at: str
    completed_at: str | None = None
    result: dict | None = None
    error: str | None = None


# ── 核心分析端点 ──

@app.post("/api/v1/analyze/deep", response_model=TaskResponse)
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
    _tasks[task_id] = task
    asyncio.create_task(_run_analysis(task))
    return TaskResponse(task_id=task_id, status="pending", mode="deep", created_at=task["created_at"])


@app.post("/api/v1/analyze/screen", response_model=TaskResponse)
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
    _tasks[task_id] = task
    asyncio.create_task(_run_analysis(task))
    return TaskResponse(task_id=task_id, status="pending", mode="screen", created_at=task["created_at"])


@app.post("/api/v1/analyze/portfolio", response_model=TaskResponse)
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
    _tasks[task_id] = task
    asyncio.create_task(_run_analysis(task))
    return TaskResponse(task_id=task_id, status="pending", mode="portfolio", created_at=task["created_at"])


# ── 任务管理端点 ──

@app.get("/api/v1/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str):
    """查询任务状态和结果。"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return TaskDetailResponse(**task)


@app.get("/api/v1/tasks")
async def list_tasks():
    """列出所有任务。"""
    return list(_tasks.values())


# ── 同步数据查询端点 ──

@app.get("/api/v1/funds/search")
async def search_funds(q: str = "", limit: int = 20):
    """快速搜索基金（同步，不经过 LLM）。"""
    from ifa.data_tools.api import run_data_tool
    result = run_data_tool("get_fund_list")
    lines = result.strip().split("\n")
    matched = [line for line in lines if q.upper() in line.upper()][:limit]
    return {"results": matched, "total": len(matched)}


@app.get("/api/v1/funds/{code}/basic")
async def fund_basic(code: str):
    """获取基金基本信息（同步）。"""
    from ifa.data_tools.api import run_data_tool
    result = run_data_tool("get_fund_basic_info", symbol=code)
    return {"fund_code": code, "data": result}


@app.get("/api/v1/indexes/categories")
async def index_categories():
    """获取指数分类列表。"""
    return {
        "categories": [
            "全部", "沪深指数", "行业主题", "大盘指数", "中盘指数", "小盘指数",
        ],
        "tracking_methods": ["全部", "被动指数型", "增强指数型"],
    }


# ── 后台任务执行 ──

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
