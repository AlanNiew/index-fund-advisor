"""Data Tools 层测试 — Storage 和 Executor。"""

import json
import time

import pandas as pd
import pytest

from ifa.data_tools.storage import CACHE_SCHEMA_VERSION, LocalArtifactStore
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

    def test_build_cache_key_covers_schema_version(self, store, monkeypatch):
        """缓存键必须绑定 schema 版本。

        回归背景：缓存无 TTL，get_fund_list 曾因旧实现的载荷长期命中而遮蔽新实现
        （有缓存的机器搜索正常、干净环境失效）。递增版本号必须让旧键自然失效。
        """
        import ifa.data_tools.storage as storage

        key_before = store.build_cache_key("get_fund_list", {})
        monkeypatch.setattr(storage, "CACHE_SCHEMA_VERSION", CACHE_SCHEMA_VERSION + 1)
        assert store.build_cache_key("get_fund_list", {}) != key_before

    def test_manifest_records_schema_version(self, store):
        store.save_cache("my_tool", {"p": 1}, "text")
        manifest = json.loads(store._cache_manifest_path("my_tool", {"p": 1}).read_text(encoding="utf-8"))
        assert manifest["schema_version"] == CACHE_SCHEMA_VERSION

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
        return type(
            "Executor",
            (),
            {
                "registry": registry,
                "artifact_store": store,
            },
        )

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


class TestTextPayloadNewline:
    """文本载荷换行回归 —— 缓存不得改动被缓存字符串的内容。

    背景：pandas 的 DataFrame.to_csv() 在 Windows 上返回 \r\n。此前的实现
    （Path.write_text 默认换行转换 + Path.read_text 通用换行）会把 \r\n
    写成 \r\r\n、再读成 \n\n，于是「命中缓存」的数据工具返回结果比
    「首次调用」凭空多出空行。该缺陷影响到所有返回格式化文本的数据工具。
    """

    @pytest.fixture
    def store(self, tmp_path):
        return LocalArtifactStore(
            cache_dir=str(tmp_path / "cache"),
            snapshot_dir=str(tmp_path / "snapshots"),
        )

    def test_multiline_text_round_trip_has_no_extra_blank_lines(self, store):
        original = pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(index=False)
        store.save_cache("text_tool", {"symbol": "510300"}, original)
        cached, _ = store.load_cache("text_tool", {"symbol": "510300"})

        assert "\n\n" not in cached, "缓存往返注入了空行"
        # 仅允许换行符风格差异（\r\n → \n），内容行数必须一致
        assert cached == original.replace("\r\n", "\n")
        assert [line for line in cached.splitlines() if line] == [
            line for line in original.splitlines() if line
        ]

    def test_text_with_blank_lines_preserved(self, store):
        """原本就含空行的文本必须原样保留（不能把空行也压掉）。"""
        original = "line1\n\nline3"
        store.save_cache("text2", {"a": 1}, original)
        cached, _ = store.load_cache("text2", {"a": 1})
        assert cached == original

    def test_dataframe_round_trip_documented_as_dtype_lossy(self, store):
        """DataFrame 经 CSV 往返会丢前导零 —— 这是缓存层的已知契约。

        消费方（如 agents/tools/constituent_tools.py）必须自行补零，
        本测试把该契约固定下来，避免有人误以为缓存能保留 dtype。
        """
        df = pd.DataFrame({"代码": ["000001", "600519"], "权重": [1.5, 2.5]})
        store.save_cache("df_tool", {"a": 1}, df)
        cached, _ = store.load_cache("df_tool", {"a": 1})

        assert isinstance(cached, pd.DataFrame)
        assert list(cached["权重"]) == [1.5, 2.5]  # 数值列无损
        assert "000001" not in [str(v) for v in cached["代码"]]  # 前导零已在往返中丢失
        assert str(cached["代码"].iloc[0]).zfill(6) == "000001"  # 消费方补零可恢复
