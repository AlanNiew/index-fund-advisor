"""IFA MCP server —— 把 IFA 的基金数据 / 估值 / 分析能力暴露给 MCP 客户端（如 Claude）。

通过 ``ifa-mcp`` 入口启动（stdio 传输）。详见 :mod:`ifa.mcp.server`。
"""

from ifa.mcp.server import main

__all__ = ["main"]
