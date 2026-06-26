"""IFA — AI 驱动的中国指数基金分析工具。

顶层导出采用懒加载（PEP 562）：`import ifa` 不会立即拉起分析引擎
（langchain / langgraph）等重依赖，仅在真正访问 `build_advisor` /
`AdvisorGraph` 等符号时才按需导入。这使得只装了数据层的轻量发行版
也能正常 `import ifa` 使用 MCP / 数据工具。
"""

__all__ = [
    "AdvisorGraph",
    "build_advisor",
    "build_state",
    "save_report",
]


def __getattr__(name: str):
    """按需导入顶层公共 API，保持 `import ifa` 轻量。"""
    if name in ("build_advisor", "build_state", "save_report"):
        from ifa.common import build_advisor, build_state, save_report

        return {"build_advisor": build_advisor, "build_state": build_state, "save_report": save_report}[name]
    if name == "AdvisorGraph":
        from ifa.graph.advisor_graph import AdvisorGraph

        return AdvisorGraph
    raise AttributeError(f"module 'ifa' has no attribute {name!r}")
