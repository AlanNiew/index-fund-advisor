import threading
from typing import Any

from ifa.data_tools.builtin import create_default_data_tool_registry
from ifa.data_tools.executor import CachedDataToolExecutor
from ifa.data_tools.storage import LocalArtifactStore
from ifa.dataflows.config import get_config, set_config

_default_executor: CachedDataToolExecutor | None = None
_executor_lock = threading.Lock()


def build_default_data_executor(config: dict[str, Any] | None = None) -> CachedDataToolExecutor:
    runtime_config = get_config()
    if config:
        set_config(config)
        runtime_config.update(config)
    registry = create_default_data_tool_registry()
    store = LocalArtifactStore(
        cache_dir=runtime_config["data_tools_cache_dir"],
        snapshot_dir=runtime_config["data_tools_snapshot_dir"],
    )
    return CachedDataToolExecutor(registry=registry, artifact_store=store)


def configure_default_data_executor(executor: CachedDataToolExecutor) -> None:
    global _default_executor
    with _executor_lock:
        _default_executor = executor


def get_default_data_executor(config: dict[str, Any] | None = None) -> CachedDataToolExecutor:
    global _default_executor
    if _default_executor is None:
        with _executor_lock:
            if _default_executor is None:
                _default_executor = build_default_data_executor(config)
    return _default_executor


def run_data_tool(tool_name: str, use_cache: bool = True, **params: Any) -> Any:
    """
    运行指定名称的数据工具并返回原始结果。

    参数：
        tool_name: 工具名称。
        use_cache: 是否优先使用缓存。
        params: 透传给工具处理函数的参数。

    返回：
        Any: 工具原始返回值。
    """
    return (
        get_default_data_executor()
        .execute(
            tool_name,
            use_cache=use_cache,
            **params,
        )
        .value
    )
