"""`ifa.notify.markdown` 渲染器测试：只覆盖报告里真实出现的构造 + 安全边界。"""

from __future__ import annotations

from ifa.notify.markdown import render_inline, render_markdown


class TestInline:
    def test_bold_italic_code_and_link(self):
        html = render_inline("**粗** 与 *斜* 与 `code` 与 [链接](https://example.com)")
        assert "<strong>粗</strong>" in html
        assert "<em>斜</em>" in html
        assert "<code>code</code>" in html
        assert '<a href="https://example.com">链接</a>' in html

    def test_html_is_escaped_before_markup(self):
        html = render_inline("<script>alert(1)</script> **粗**")
        assert "<script" not in html
        assert "&lt;script&gt;" in html
        assert "<strong>粗</strong>" in html

    def test_unsafe_link_scheme_is_not_a_link(self):
        html = render_inline("[点我](javascript:alert(1))")
        assert "<a " not in html
        assert "javascript:" in html

    def test_ampersand_in_url_is_escaped(self):
        html = render_inline("[看这里](https://x.com/a?b=1&c=2)")
        assert '<a href="https://x.com/a?b=1&amp;c=2">看这里</a>' in html


class TestBlocks:
    def test_headings_and_hr(self):
        html = render_markdown("# 一级\n\n## 二级\n\n---")
        assert "<h1>一级</h1>" in html
        assert "<h2>二级</h2>" in html
        assert "<hr" in html

    def test_table_with_alignment_row(self):
        html = render_markdown("| 项目 | 数值 |\n| :--- | ---: |\n| **PE** | 12.3 |")
        assert "<table" in html
        assert "<th" in html and "项目" in html
        assert "<strong>PE</strong>" in html
        assert "| :--- |" not in html
        assert "text-align:right" in html

    def test_lists(self):
        html = render_markdown("- 甲\n- 乙\n\n1. 一\n2. 二")
        assert "<ul><li>甲</li><li>乙</li></ul>" in html
        assert "<ol><li>一</li><li>二</li></ol>" in html

    def test_paragraph_and_quote(self):
        html = render_markdown("第一行\n第二行\n\n> 引用")
        assert "<p>第一行<br>第二行</p>" in html
        assert "<blockquote>引用</blockquote>" in html

    def test_code_fence_is_escaped(self):
        html = render_markdown("```python\nprint('<hi>')\n```")
        assert "<pre><code>" in html
        assert "&lt;hi&gt;" in html
        assert "<hi>" not in html

    def test_empty_and_plain_text(self):
        assert render_markdown("") == ""
        assert render_markdown("plain text") == "<p>plain text</p>"

    def test_unknown_construct_falls_back_to_paragraph(self):
        """不认识的构造必须降级成段落，不能把内容吞掉。"""
        html = render_markdown("!!! 奇怪的行")
        assert "奇怪的行" in html
        assert html.startswith("<p>")

    def test_real_report_shape_renders_tables_and_lists(self):
        """照着真实报告（results/reports/017641/2026-04-27_deep.md）的构造跑一遍。"""
        report = (
            "# 指数基金分析报告\n\n## 基金概览\n\n"
            "| 项目 | 详情 |\n| :--- | :--- |\n| **基金名称** | 摩根标普500 |\n\n"
            "---\n\n- **持有满6个月：** 盈利概率 90.00%\n"
        )
        html = render_markdown(report)
        assert "<h1>指数基金分析报告</h1>" in html
        assert "<h2>基金概览</h2>" in html
        assert "<table" in html
        assert "<strong>基金名称</strong>" in html
        assert "<li><strong>持有满6个月：</strong> 盈利概率 90.00%</li>" in html
        assert "| 项目 |" not in html
