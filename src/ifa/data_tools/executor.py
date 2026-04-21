import os
import time
from typing import Any

from ifa.data_tools.registry import DataToolRegistry
from ifa.data_tools.storage import LocalArtifactStore
from ifa.data_tools.types import ToolExecutionResult


class CachedDataToolExecutor:
    """提供带缓存与快照能力的数据工具执行器。"""

    def __init__(self, registry: DataToolRegistry, artifact_store: LocalArtifactStore):
        self.registry = registry
        self.artifact_store = artifact_store

    def execute(
        self,
        tool_name: str,
        use_cache: bool = True,
        persist_snapshot: bool = False,
        snapshot_group: str = "daily",
        snapshot_date: str | None = None,
        max_age_seconds: float | None = None,
        **params: Any,
    ) -> ToolExecutionResult:
        """执行一个数据工具，并按需进行缓存和快照。"""
        definition = self.registry.get(tool_name)
        metadata = {
            "namespace": definition.namespace,
            "description": definition.description,
        }

        # 尝试读取缓存
        if use_cache and definition.cache_enabled:
            cached = self._try_read_cache(tool_name, params, max_age_seconds, metadata, persist_snapshot)
            if cached:
                return cached

        # 执行工具并保存结果
        value = definition.handler(**params)
        return self._store_result(tool_name, params, value, definition, metadata, persist_snapshot, snapshot_group, snapshot_date)

    def _try_read_cache(
        self,
        tool_name: str,
        params: dict,
        max_age_seconds: float | None,
        metadata: dict,
        persist_snapshot: bool,
    ) -> ToolExecutionResult | None:
        """尝试从缓存读取结果，缓存有效则返回 ToolExecutionResult，否则返回 None。"""
        cached = self.artifact_store.load_cache(tool_name, params)
        if cached is None:
            return None

        cached_value, artifact_path = cached

        # 检查缓存有效期
        if max_age_seconds is not None and os.path.exists(artifact_path):
            if time.time() - os.path.getmtime(artifact_path) > max_age_seconds:
                return None

        snapshot_path = self._save_snapshot_if_needed(tool_name, params, cached_value, persist_snapshot, metadata)
        cache_key = self.artifact_store.build_cache_key(tool_name, params)

        return ToolExecutionResult(
            tool_name=tool_name,
            params=params,
            value=cached_value,
            from_cache=True,
            cache_key=cache_key,
            artifact_path=str(artifact_path),
            snapshot_path=snapshot_path,
            metadata=metadata,
        )

    def _store_result(
        self,
        tool_name: str,
        params: dict,
        value: Any,
        definition: Any,
        metadata: dict,
        persist_snapshot: bool,
        snapshot_group: str,
        snapshot_date: str | None,
    ) -> ToolExecutionResult:
        """执行工具后保存缓存和快照，返回 ToolExecutionResult。"""
        cache_key = self.artifact_store.build_cache_key(tool_name, params)

        artifact_path = None
        if definition.cache_enabled:
            artifact_path = str(
                self.artifact_store.save_cache(tool_name, params, value, metadata=metadata)
            )

        snapshot_path = self._save_snapshot_if_needed(tool_name, params, value, persist_snapshot, metadata,
                                                      snapshot_group, snapshot_date)

        return ToolExecutionResult(
            tool_name=tool_name,
            params=params,
            value=value,
            from_cache=False,
            cache_key=cache_key,
            artifact_path=artifact_path,
            snapshot_path=snapshot_path,
            metadata=metadata,
        )

    def _save_snapshot_if_needed(
        self,
        tool_name: str,
        params: dict,
        value: Any,
        persist_snapshot: bool,
        metadata: dict,
        snapshot_group: str = "daily",
        snapshot_date: str | None = None,
    ) -> str | None:
        """按需保存快照，返回快照路径或 None。"""
        if not persist_snapshot:
            return None
        return str(
            self.artifact_store.save_snapshot(
                tool_name, params, value,
                snapshot_group=snapshot_group,
                snapshot_date=snapshot_date,
                metadata=metadata,
            )
        )
