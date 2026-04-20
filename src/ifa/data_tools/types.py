from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DataToolDefinition:
    """定义一个可注册的数据获取工具。"""

    name: str
    handler: Callable[..., Any]
    description: str
    namespace: str = "default"
    cache_enabled: bool = True


@dataclass(frozen=True)
class DataCollectionJob:
    """描述一次可独立运行的数据采集任务。"""

    tool_name: str
    params: dict[str, Any]
    snapshot_group: str = "daily"
    snapshot_date: str | None = None
    use_cache: bool = True


@dataclass(frozen=True)
class ToolExecutionResult:
    """描述一次工具执行结果及其本地落盘信息。"""

    tool_name: str
    params: dict[str, Any]
    value: Any
    from_cache: bool
    cache_key: str
    artifact_path: str | None = None
    snapshot_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
