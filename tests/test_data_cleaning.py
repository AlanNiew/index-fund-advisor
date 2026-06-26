"""数据清洗管道补充测试 — truncate_report / cap_tool_result。"""

from ifa.dataflows.data_cleaning import cap_tool_result, truncate_report

# ════════════════════════════════════════════
#  truncate_report
# ════════════════════════════════════════════


class TestTruncateReport:
    """truncate_report 报告截断测试。"""

    def test_short_report_unchanged(self):
        """短报告不截断。"""
        assert truncate_report("short") == "short"

    def test_empty_report(self):
        """空报告原样返回。"""
        assert truncate_report("") == ""

    def test_long_report_truncated(self):
        """超长报告被截断并附加提示。"""
        long_text = "x" * 5000
        result = truncate_report(long_text, max_chars=1000)
        assert len(result) < len(long_text)
        assert "截断" in result

    def test_exact_boundary(self):
        """恰好等于 max_chars 的报告不截断。"""
        text = "x" * 1000
        assert truncate_report(text, max_chars=1000) == text


# ════════════════════════════════════════════
#  cap_tool_result
# ════════════════════════════════════════════


class TestCapToolResult:
    """cap_tool_result 工具结果智能截断测试。"""

    def test_short_result_unchanged(self):
        """短结果不截断。"""
        assert cap_tool_result("short") == "short"

    def test_empty_result(self):
        """空结果原样返回。"""
        assert cap_tool_result("") == ""

    def test_none_result(self):
        """None 原样返回。"""
        assert cap_tool_result(None) is None

    def test_long_result_preserves_headers(self):
        """长结果截断后仍保留标题行（# 开头）。"""
        text = "# Northbound Capital Flow\n# Records: 1000\n\n" + "data_row,data\n" * 500
        result = cap_tool_result(text, max_chars=200)
        assert "# Northbound Capital Flow" in result
        assert len(result) < len(text)

    def test_long_result_has_truncation_notice(self):
        """长结果截断后包含截断提示。"""
        text = "# Header\n" + "x" * 6000
        result = cap_tool_result(text, max_chars=500)
        assert "截断" in result

    def test_header_only_not_truncated_aggressively(self):
        """只有标题行时仍保留所有标题。"""
        text = "# Title 1\n# Title 2\n# Title 3\n"
        result = cap_tool_result(text, max_chars=50)
        assert "# Title 1" in result
        assert "# Title 2" in result
        assert "# Title 3" in result

    def test_data_rows_partial_kept(self):
        """数据行被部分保留（至少保留若干行）。"""
        text = "# Header\n" + "row_{}\n".format("x" * 20) * 100
        result = cap_tool_result(text, max_chars=300)
        assert "# Header" in result
        assert "row_" in result
