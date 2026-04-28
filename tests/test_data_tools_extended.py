"""Data Tools 层测试 — Storage 和 Executor。"""

import json
import time
from pathlib import Path

import pandas as pd
import pytest

from ifa.data_tools.storage import LocalArtifactStore
from ifa.data_tools.types import DataToolDefinition, SnapshotConfig


class TestLocalArtifactStore:
    """storage.py LocalArtifactStore 测试。"""

    @pytest.fixture
    def store(self, tmp_path):
        return LocalArtifactStore(
            cache_dir=str(tmp_path / "cache"),
            snapshot_dir=str(tmp_path / "snapshots"),
        )

    def test_init_creates_dirs(self, tmp_path):
        cache_dir = tmp_path / "cache"
        snapshot_dir = tmp_path / "snapshots"
        LocalArtifactStore(str(cache_dir), str(snapshot_dir))
        assert cache_dir.exists()
        assert snapshot_dir.exists()

    def test_build_cache_key_deterministic(self, store):
        key1 = store.build_cache_key("get_fund_data", {"symbol": "510300"})
        key2 = store.build_cache_key("get_fund_data", {"symbol": "510300"})
        assert key1 == key2
        assert len(key1) == 40  # SHA1 hex digest

    def test_build_cache_key_differs_for_different_params(self, store):
        key1 = store.build_cache_key("get_fund_data", {"symbol": "510300"})
        key2 = store.build_cache_key("get_fund_data", {"symbol": "159919"})
        assert key1 != key2

    def test_build_cache_key_differs_for_different_tools(self, store):
        key1 = store.build_cache_key("tool_a", {"x": 1})
        key2 = store.build_cache_key("tool_b", {"x": 1})
        assert key1 != key2

    def test_save_and_load_text(self, store):
        path = store.save_cache("my_tool", {"k": "v"}, "hello world")
        assert path.exists()
        result = store.load_cache("my_tool", {"k": "v"})
        assert result is not None
        assert result[0] == "hello world"

    def test_save_and_load_dict(self, store):
        data = {"key": "value", "nums": [1, 2, 3]}
        store.save_cache("my_tool", {"p": 1}, data)
        result = store.load_cache("my_tool", {"p": 1})
        assert result is not None
        assert result[0] == data

    def test_save_and_load_dataframe(self, store):
        df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
        store.save_cache("my_tool", {"sym": "test"}, df)
        result = store.load_cache("my_tool", {"sym": "test"})
        assert result is not None
        pd.testing.assert_frame_equal(result[0], df)

    def test_load_cache_miss(self, store):
        assert store.load_cache("nonexistent", {}) is None

    def test_save_snapshot_creates_structure(self, store):
        path = store.save_snapshot("tool_x", {"x": 1}, "data", snapshot_date="2024-06-01")
        assert path.exists()
        assert "daily" in str(path)
        assert "2024-06-01" in str(path)

    def test_manifest_structure(self, store):
        store.save_cache("my_tool", {"p": 1}, "value", metadata={"ns": "test"})
        manifest_path = store._cache_manifest_path("my_tool", {"p": 1})
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["tool_name"] == "my_tool"
        assert manifest["payload_format"] == "text"
        assert "created_at" in manifest


class TestCachedDataToolExecutor:
    """executor.py CachedDataToolExecutor 测试。"""

    @pytest.fixture
    def executor(self, tmp_path):
        from ifa.data_tools.registry import DataToolRegistry

        registry = DataToolRegistry()
        store = LocalArtifactStore(
            cache_dir=str(tmp_path / "cache"),
            snapshot_dir=str(tmp_path / "snapshots"),
        )
        return type("Executor", (), {
            "registry": registry,
            "artifact_store": store,
        })

    def _make_registry_with_tool(self, tmp_path, handler, cache_enabled=True):
        from ifa.data_tools.registry import DataToolRegistry

        registry = DataToolRegistry()
        registry._tools["test_tool"] = DataToolDefinition(
            name="test_tool",
            namespace="test",
            description="test tool",
            handler=handler,
            cache_enabled=cache_enabled,
        )
        store = LocalArtifactStore(
            cache_dir=str(tmp_path / "cache"),
            snapshot_dir=str(tmp_path / "snapshots"),
        )
        from ifa.data_tools.executor import CachedDataToolExecutor
        return CachedDataToolExecutor(registry, store)

    def test_execute_no_cache(self, tmp_path):
        executor = self._make_registry_with_tool(tmp_path, lambda: "result", cache_enabled=False)
        result = executor.execute("test_tool", use_cache=False)
        assert result.value == "result"
        assert not result.from_cache

    def test_execute_with_cache_first_miss(self, tmp_path):
        call_count = 0

        def handler():
            nonlocal call_count
            call_count += 1
            return "hello"

        executor = self._make_registry_with_tool(tmp_path, handler)
        result = executor.execute("test_tool")
        assert result.value == "hello"
        assert not result.from_cache
        assert call_count == 1

    def test_execute_with_cache_hit(self, tmp_path):
        call_count = 0

        def handler():
            nonlocal call_count
            call_count += 1
            return "cached_result"

        executor = self._make_registry_with_tool(tmp_path, handler)
        executor.execute("test_tool")
        result = executor.execute("test_tool")
        assert result.value == "cached_result"
        assert result.from_cache
        assert call_count == 1

    def test_execute_cache_expiry(self, tmp_path):
        call_count = 0

        def handler():
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        executor = self._make_registry_with_tool(tmp_path, handler)
        executor.execute("test_tool")
        time.sleep(0.1)
        result = executor.execute("test_tool", max_age_seconds=0.01)
        assert not result.from_cache
        assert call_count == 2

    def test_execute_snapshot_persist(self, tmp_path):
        executor = self._make_registry_with_tool(tmp_path, lambda: "data")
        snapshot = SnapshotConfig(persist=True, group="test_group", date="2024-06-15")
        result = executor.execute("test_tool", snapshot=snapshot)
        assert result.snapshot_path is not None
