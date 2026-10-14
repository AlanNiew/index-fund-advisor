"""MCP server 的导入与依赖提示 —— mcp 2.x 把 FastMCP 改名 MCPServer，1.x 代码会直接起不来。

上游在 ``mcp/server/fastmcp.py`` 里故意抛 ModuleNotFoundError 并附迁移链接；
IFA 侧再补一句「装 mcp<2」，否则用户只会看到一句看不懂的 No module named。
"""

from __future__ import annotations

import pytest

from ifa.mcp import server


class TestFastMcpHint:
    """导入失败时的两条提示都必须可操作。"""

    def test_missing_mcp_points_at_the_extra(self):
        assert "index-fund-advisor[mcp]" in server._MCP_MISSING_HINT

    def test_mcp_v2_points_at_the_pin(self):
        assert "mcp<2" in server._MCP_V2_HINT
        assert "MCPServer" in server._MCP_V2_HINT


class TestServerSurface:
    """server.py 用 mcp 1.x 的 API 构建，9 个工具都要在。"""

    def test_server_instance_is_built(self):
        assert server.mcp is not None
        assert hasattr(server.mcp, "run")

    @pytest.mark.parametrize(
        "name",
        [
            "search_funds",
            "get_fund_info",
            "get_index_valuation_metrics",
            "get_index_valuation_report",
            "get_valuation_signal",
            "screen_index_funds",
            "get_index_constituents",
            "get_north_flow",
            "analyze_fund",
        ],
    )
    def test_every_documented_tool_exists(self, name):
        assert callable(getattr(server, name))

    def test_main_runs_the_stdio_server(self, monkeypatch):
        called: list[bool] = []
        monkeypatch.setattr(server.mcp, "run", lambda: called.append(True))
        server.main()
        assert called == [True]
