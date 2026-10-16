"""内置 skill 与数据工具注册表的一致性测试。

skill 里的工具表必须由 `ifa tools --markdown` 生成，否则会重演本项目已发生过四次的
文档漂移（工具数 25 → 33 → 35 → 36 → 39）。这里把「生成结果」与「文件内容」钉在一起。
"""

from __future__ import annotations

import re

from ifa.cli.tools_cmd import (
    TOOL_TABLE_BEGIN,
    TOOL_TABLE_END,
    read_bundled_skill,
    tools_markdown,
    tools_payload,
)


def _generated_block(content: str) -> str:
    assert TOOL_TABLE_BEGIN in content, "skill 缺少工具表起始标记"
    assert TOOL_TABLE_END in content, "skill 缺少工具表结束标记"
    return content.split(TOOL_TABLE_BEGIN, 1)[1].split(TOOL_TABLE_END, 1)[0].strip()


class TestSkillToolTable:
    def test_embedded_table_matches_registry(self) -> None:
        assert _generated_block(read_bundled_skill()) == tools_markdown().strip()

    def test_table_covers_every_registered_tool(self) -> None:
        block = _generated_block(read_bundled_skill())
        for tool in tools_payload():
            assert "`" + tool["name"] + "`" in block, tool["name"] + " 未出现在 skill 工具表中"


class TestSkillHasNoProjectCoupling:
    def test_no_cd_commands(self) -> None:
        content = read_bundled_skill()
        assert "cd d:" not in content.lower()
        assert "cd /" not in content.lower()
        for line in content.splitlines():
            assert not re.match(r"^\s*cd\s", line), "skill 不应包含 cd：" + line

    def test_no_python_c_imports(self) -> None:
        """取数必须走 ifa tool，不能再让 agent 现场写 Python 导入 ifa.*。"""
        content = read_bundled_skill()
        assert "python -c" not in content
        assert "run_data_tool" not in content

    def test_frontmatter_is_complete(self) -> None:
        content = read_bundled_skill()
        assert content.startswith("---\n")
        head = content.split("---", 2)[1]
        for key in ("name:", "description:", "argument-hint:", "allowed-tools:"):
            assert key in head, "frontmatter 缺少 " + key
