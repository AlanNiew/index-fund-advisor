from ifa.data_tools.types import DataToolDefinition


class DataToolRegistry:
    """管理可用的数据获取工具集合。"""

    def __init__(self):
        """
        初始化数据工具注册表。

        参数：
            无。

        返回：
            None: 无返回值。
        """
        self._tools: dict[str, DataToolDefinition] = {}

    def register(self, definition: DataToolDefinition) -> None:
        """
        注册一个数据工具定义。

        参数：
            definition: 需要注册的数据工具定义。

        返回：
            None: 无返回值。
        """
        self._tools[definition.name] = definition

    def get(self, tool_name: str) -> DataToolDefinition:
        """
        获取指定名称的数据工具定义。

        参数：
            tool_name: 工具名称。

        返回：
            DataToolDefinition: 命中的工具定义。
        """
        if tool_name not in self._tools:
            raise KeyError(f"未注册的数据工具：{tool_name}")
        return self._tools[tool_name]

    def list_tools(self) -> list[DataToolDefinition]:
        """
        返回当前已注册的全部工具。

        参数：
            无。

        返回：
            list[DataToolDefinition]: 已注册工具列表。
        """
        return list(self._tools.values())
