# api/main.py
"""IFA FastAPI 服务入口。"""

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ifa.env_loader import load_env_files

load_env_files()

_CORS_ORIGINS = [o.strip() for o in os.environ.get("IFA_CORS_ORIGINS", "*").split(",") if o.strip()]

app = FastAPI(
    title="IFA - Index Fund Advisor API",
    description="AI 驱动的指数基金分析 API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_API_KEY = os.environ.get("IFA_API_KEY", "")


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    """API Key 认证：IFA_API_KEY 环境变量非空时启用认证。"""
    if _API_KEY:
        key = request.headers.get("X-API-Key", "")
        if key != _API_KEY:
            return JSONResponse(status_code=401, content={"detail": "无效或缺失的 API Key（X-API-Key header）"})
    return await call_next(request)


from api.routers.analysis import router as analysis_router
from api.routers.data import router as data_router

app.include_router(analysis_router)
app.include_router(data_router)
