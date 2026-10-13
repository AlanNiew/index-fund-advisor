"""数据工具层测试 — 注册表、工具定义、默认注册。"""

import pytest

from ifa.data_tools.builtin import _TOOL_SPECS, create_default_data_tool_registry
from ifa.data_tools.registry import DataToolRegistry
from ifa.data_tools.types import DataToolDefinition

# ════════════════════════════════════════════
#  DataToolDefinition
# ════════════════════════════════════════════


class TestDataToolDefinition:
    """DataToolDefinition 数据类测试。"""

    def test_field_defaults(self):
        """默认字段值正确。"""
        defn = DataToolDefinition(
            name="test_tool",
            handler=lambda: None,
            description="测试工具",
        )
        assert defn.namespace == "default"
        assert defn.cache_enabled is True

    def test_custom_fields(self):
        """自定义字段值正确。"""
        defn = DataToolDefinition(
            name="my_tool",
            handler=print,
            description="自定义工具",
            namespace="a_share",
            cache_enabled=False,
        )
        assert defn.name == "my_tool"
        assert defn.handler is print
        assert defn.namespace == "a_share"
        assert defn.cache_enabled is False

    def test_frozen(self):
        """frozen dataclass 不允许修改。"""
        defn = DataToolDefinition(name="t", handler=lambda: None, description="d")
        with pytest.raises(AttributeError):
            defn.name = "changed"


# ════════════════════════════════════════════
#  DataToolRegistry
# ════════════════════════════════════════════


class TestDataToolRegistry:
    """DataToolRegistry 注册/获取/列表测试。"""

    def test_register_and_get(self):
        """注册后可按名称获取。"""
        registry = DataToolRegistry()
        defn = DataToolDefinition(name="tool_a", handler=lambda: "a", description="工具A")
        registry.register(defn)
        result = registry.get("tool_a")
        assert result is defn

    def test_get_nonexistent_raises(self):
        """获取未注册的工具抛出 KeyError。"""
        registry = DataToolRegistry()
        with pytest.raises(KeyError, match="未注册"):
            registry.get("no_such_tool")

    def test_list_tools_empty(self):
        """空注册表返回空列表。"""
        registry = DataToolRegistry()
        assert registry.list_tools() == []

    def test_list_tools_returns_all(self):
        """注册多个工具后 list_tools 返回全部。"""
        registry = DataToolRegistry()
        for i in range(3):
            registry.register(DataToolDefinition(name=f"tool_{i}", handler=lambda: None, description=f"工具{i}"))
        tools = registry.list_tools()
        assert len(tools) == 3

    def test_register_duplicate_overwrites(self):
        """注册同名工具覆盖旧值。"""
        registry = DataToolRegistry()
        defn_v1 = DataToolDefinition(name="tool", handler=lambda: 1, description="v1")
        defn_v2 = DataToolDefinition(name="tool", handler=lambda: 2, description="v2")
        registry.register(defn_v1)
        registry.register(defn_v2)
        assert registry.get("tool").description == "v2"


# ════════════════════════════════════════════
#  默认工具注册表
# ════════════════════════════════════════════


class TestDefaultDataToolRegistry:
    """create_default_data_tool_registry 集成测试。"""

    def test_all_tools_registered(self):
        """所有 _TOOL_SPECS 中的工具均注册到注册表。"""
        registry = create_default_data_tool_registry()
        tools = registry.list_tools()
        assert len(tools) == len(_TOOL_SPECS)

    def test_tool_count(self):
        """默认注册的工具数量为 35 个。

        构成：ETF/指数/场外 5 + 公募基金 20 + 宏观/情绪/估值 8 +
        成分股原始数据 1 + 个股日线 1（后两个服务于 agents/tools/constituent_tools.py）。
        """
        assert len(_TOOL_SPECS) == 35

    def test_each_tool_has_required_fields(self):
        """每个注册的工具都有名称、描述和处理器。"""
        registry = create_default_data_tool_registry()
        for tool in registry.list_tools():
            assert tool.name, "工具名称不能为空"
            assert tool.description, "工具描述不能为空"
            assert callable(tool.handler), "工具处理器必须是可调用对象"
            assert tool.namespace == "a_share"

    def test_specific_tools_exist(self):
        """关键工具均已注册。"""
        registry = create_default_data_tool_registry()
        expected_names = [
            "get_etf_data",
            "get_index_data",
            "get_fund_list",
            "get_macro_indicator",
            "get_north_flow",
            "get_index_valuation",
            "get_valuation_signal",
        ]
        for name in expected_names:
            tool = registry.get(name)
            assert tool is not None, f"工具 {name} 未注册"
