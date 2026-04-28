# api/models/schemas.py
"""API 请求/响应模型。"""

from pydantic import BaseModel, Field


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
