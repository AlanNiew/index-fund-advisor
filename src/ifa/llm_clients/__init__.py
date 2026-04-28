"""IFA LLM 客户端层 — 工厂模式统一接口。"""

from ifa.llm_clients.factory import create_llm_client

__all__ = [
    "create_llm_client",
]
