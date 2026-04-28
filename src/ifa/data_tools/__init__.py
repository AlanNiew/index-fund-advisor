"""IFA 数据工具层 — 声明式注册表 + 缓存执行器。"""

from ifa.data_tools.api import get_default_data_executor
from ifa.data_tools.executor import CachedDataToolExecutor

__all__ = [
    "CachedDataToolExecutor",
    "get_default_data_executor",
]
