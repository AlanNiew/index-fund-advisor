from typing import Any

from ifa.data_tools.builtin import create_default_data_tool_registry
from ifa.data_tools.executor import CachedDataToolExecutor
from ifa.data_tools.storage import LocalArtifactStore
from ifa.dataflows.config import get_config, set_config

_default_executor: CachedDataToolExecutor | None = None


def build_default_data_executor(config: dict[str, Any] | None = None) -> CachedDataToolExecutor:
    """
    基于当前配置创建默认数据工具执行器。

    参数：
        config: 可选运行时配置。

    返回：
        CachedDataToolExecutor: 构建好的默认执行器。
    """
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
    """
    配置全局默认数据工具执行器。

    参数：
        executor: 需要设置为默认值的执行器。

    返回：
        None: 无返回值。
    """
    global _default_executor
    _default_executor = executor


def get_default_data_executor(config: dict[str, Any] | None = None) -> CachedDataToolExecutor:
    """
    获取全局默认数据工具执行器。

    参数：
        config: 可选运行时配置。

    返回：
        CachedDataToolExecutor: 默认执行器实例。
    """
    global _default_executor
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
