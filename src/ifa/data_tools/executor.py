import logging
import os
import time
from typing import Any

from ifa.data_tools.registry import DataToolRegistry
from ifa.data_tools.storage import LocalArtifactStore
from ifa.data_tools.types import SnapshotConfig, ToolExecutionResult

logger = logging.getLogger(__name__)


class CachedDataToolExecutor:
    """提供带缓存与快照能力的数据工具执行器。

    缓存操作（读取/写入/快照）均有异常隔离，磁盘故障不会阻塞正常工具执行。
    """

    def __init__(self, registry: DataToolRegistry, artifact_store: LocalArtifactStore):
        self.registry = registry
        self.artifact_store = artifact_store

    def execute(
        self,
        tool_name: str,
        use_cache: bool = True,
        *,
        snapshot: SnapshotConfig | None = None,
        max_age_seconds: float | None = None,
        **params: Any,
    ) -> ToolExecutionResult:
        """执行一个数据工具，并按需进行缓存和快照。"""
        snapshot = snapshot or SnapshotConfig()
        definition = self.registry.get(tool_name)
        metadata = {
            "namespace": definition.namespace,
            "description": definition.description,
        }

        # 尝试读取缓存（异常时降级为直接执行）
        if use_cache and definition.cache_enabled:
            try:
                cached = self._try_read_cache(tool_name, params, max_age_seconds, metadata, snapshot)
                if cached:
                    return cached
            except Exception as e:
                logger.warning("缓存读取失败，降级为直接执行 (%s): %s", tool_name, e)

        # 执行工具
        value = definition.handler(**params)

        # 保存结果（异常时不影响返回值）
        return self._store_result(tool_name, params, value, definition, metadata, snapshot)

    def _try_read_cache(
        self,
        tool_name: str,
        params: dict,
        max_age_seconds: float | None,
        metadata: dict,
        snapshot: SnapshotConfig,
    ) -> ToolExecutionResult | None:
        """尝试从缓存读取结果，缓存有效则返回 ToolExecutionResult，否则返回 None。"""
        cached = self.artifact_store.load_cache(tool_name, params)
        if cached is None:
            return None

        cached_value, artifact_path = cached

        # 检查缓存有效期
        if max_age_seconds is not None and os.path.exists(artifact_path) and time.time() - os.path.getmtime(artifact_path) > max_age_seconds:
            return None

        snapshot_path = self._save_snapshot_if_needed(tool_name, params, cached_value, snapshot, metadata)
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
        snapshot: SnapshotConfig,
    ) -> ToolExecutionResult:
        """执行工具后保存缓存和快照，返回 ToolExecutionResult。"""
        cache_key = self.artifact_store.build_cache_key(tool_name, params)

        artifact_path = None
        if definition.cache_enabled:
            try:
                artifact_path = str(
                    self.artifact_store.save_cache(tool_name, params, value, metadata=metadata)
                )
            except Exception as e:
                logger.warning("缓存写入失败 (%s): %s", tool_name, e)

        snapshot_path = self._save_snapshot_if_needed(tool_name, params, value, snapshot, metadata)

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
        snapshot: SnapshotConfig,
        metadata: dict,
    ) -> str | None:
        """按需保存快照，返回快照路径或 None。快照失败不影响工具执行。"""
        if not snapshot.persist:
            return None
        try:
            return str(
                self.artifact_store.save_snapshot(
                    tool_name, params, value,
                    snapshot_group=snapshot.group,
                    snapshot_date=snapshot.date,
                    metadata=metadata,
                )
            )
        except Exception as e:
            logger.warning("快照保存失败 (%s): %s", tool_name, e)
            return None
