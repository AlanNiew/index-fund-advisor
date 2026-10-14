"""`ifa tool` / `ifa tools` / `ifa skill` 子命令的测试。

这三条命令存在的意义是「不装本项目、不激活 venv、不写 Python 也能取数」，
因此测试重点放在：参数解析（前导零/中文/类型）、错误路径的退出码、以及
生成式工具表与注册表一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from ifa.cli.tools_cmd import (
    parse_params,
    read_bundled_skill,
    register_tool_commands,
    serialize_value,
    tools_markdown,
    tools_payload,
)
from ifa.dataflows.a_share import DATA_SOURCE_ERROR_MARKER

runner = CliRunner()

#: 工具总数由注册表决定；这里的下限断言只是防止注册表被意外清空。
MIN_EXPECTED_TOOLS = 30


@pytest.fixture(scope="module")
def payload() -> list[dict[str, Any]]:
    return tools_payload()


@pytest.fixture()
def cli() -> typer.Typer:
    """只挂本模块三个子命令的独立 app，避免与主 CLI 的命令互相干扰。"""
    app = typer.Typer()
    register_tool_commands(app)
    return app


class _FakeExecution:
    def __init__(self, value: Any, from_cache: bool = False) -> None:
        self.value = value
        self.from_cache = from_cache


class _FakeExecutor:
    def __init__(self, value: Any = None, exc: Exception | None = None) -> None:
        self.value = value
        self.exc = exc
        self.calls: list[tuple[str, bool, dict[str, Any]]] = []

    def execute(self, name: str, use_cache: bool = True, **params: Any) -> _FakeExecution:
        self.calls.append((name, use_cache, params))
        if self.exc is not None:
            raise self.exc
        return _FakeExecution(self.value)


def _install_fake_executor(monkeypatch: pytest.MonkeyPatch, executor: _FakeExecutor) -> None:
    # tools_cmd 在命令内部 from ifa.data_tools.api import get_default_data_executor，
    # 所以 patch 模块属性即可生效。
    monkeypatch.setattr("ifa.data_tools.api.get_default_data_executor", lambda config=None: executor)


class TestToolsListing:
    def test_json_matches_registry(self, cli: typer.Typer, payload: list[dict[str, Any]]) -> None:
        result = runner.invoke(cli, ["tools", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == len(payload) >= MIN_EXPECTED_TOOLS
        assert [t["name"] for t in parsed] == [t["name"] for t in payload]
        assert all(t["parameters"] for t in parsed) or any(not t["parameters"] for t in parsed)

    def test_json_includes_parameter_types(self, cli: typer.Typer) -> None:
        result = runner.invoke(cli, ["tools", "--json"])
        parsed = {t["name"]: t for t in json.loads(result.output)}
        symbol_param = next(p for p in parsed["get_index_constituents_raw"]["parameters"] if p["name"] == "symbol")
        assert symbol_param["required"] is True
        assert symbol_param["type"] == "str"

    def test_markdown_matches_generator(self, cli: typer.Typer) -> None:
        result = runner.invoke(cli, ["tools", "--markdown"])
        assert result.exit_code == 0
        assert result.output.strip() == tools_markdown().strip()

    def test_default_renders_table(self, cli: typer.Typer) -> None:
        result = runner.invoke(cli, ["tools"])
        assert result.exit_code == 0
        assert "IFA 数据工具" in result.output


class TestToolCommand:
    def test_unknown_tool_exits_1(self, cli: typer.Typer) -> None:
        result = runner.invoke(cli, ["tool", "no_such_tool"])
        assert result.exit_code == 1
        assert "未知数据工具" in result.output

    def test_missing_required_parameter_exits_1(self, cli: typer.Typer) -> None:
        result = runner.invoke(cli, ["tool", "get_index_constituents_raw"])
        assert result.exit_code == 1
        assert "缺少必填参数" in result.output

    def test_unknown_parameter_exits_1(self, cli: typer.Typer) -> None:
        result = runner.invoke(cli, ["tool", "get_index_constituents_raw", "-p", "nope=1"])
        assert result.exit_code == 1
        assert "不认识参数" in result.output

    def test_params_are_passed_through(self, cli: typer.Typer, monkeypatch: pytest.MonkeyPatch) -> None:
        executor = _FakeExecutor(value="CSV-CONTENT")
        _install_fake_executor(monkeypatch, executor)
        result = runner.invoke(cli, ["tool", "get_index_constituents_raw", "-p", "symbol=000300"])
        assert result.exit_code == 0
        assert executor.calls == [("get_index_constituents_raw", True, {"symbol": "000300"})]
        assert "CSV-CONTENT" in result.output

    def test_no_cache_flag_is_forwarded(self, cli: typer.Typer, monkeypatch: pytest.MonkeyPatch) -> None:
        executor = _FakeExecutor(value="X")
        _install_fake_executor(monkeypatch, executor)
        result = runner.invoke(cli, ["tool", "get_index_constituents_raw", "-p", "symbol=000300", "--no-cache"])
        assert result.exit_code == 0
        assert executor.calls[0][1] is False

    def test_json_output(self, cli: typer.Typer, monkeypatch: pytest.MonkeyPatch) -> None:
        executor = _FakeExecutor(value={"a": 1})
        _install_fake_executor(monkeypatch, executor)
        result = runner.invoke(cli, ["tool", "get_fund_list", "--json"])
        assert result.exit_code == 0
        body = json.loads(result.output)
        assert body["tool"] == "get_fund_list"
        assert body["result"] == {"a": 1}
        assert body["params"] == {}

    def test_execution_error_exits_1(self, cli: typer.Typer, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_executor(monkeypatch, _FakeExecutor(exc=RuntimeError("boom")))
        result = runner.invoke(cli, ["tool", "get_fund_list"])
        assert result.exit_code == 1
        assert "执行失败" in result.output
        assert "boom" in result.output

    def test_data_source_failure_exits_1(self, cli: typer.Typer, monkeypatch: pytest.MonkeyPatch) -> None:
        """工具内部会把取数异常吞成带标记的文本；CLI 必须还原成非零退出码。"""
        value = DATA_SOURCE_ERROR_MARKER + "ValueError: Excel file format cannot be determined"
        _install_fake_executor(monkeypatch, _FakeExecutor(value=value))
        result = runner.invoke(cli, ["tool", "get_index_constituents_raw", "-p", "symbol=510300"])
        assert result.exit_code == 1
        assert DATA_SOURCE_ERROR_MARKER in result.output

    def test_successful_text_result_exits_0(self, cli: typer.Typer, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_executor(monkeypatch, _FakeExecutor(value="正常数据"))
        assert runner.invoke(cli, ["tool", "get_fund_list"]).exit_code == 0


class TestParamParsing:
    def test_json_literals_are_decoded(self) -> None:
        assert parse_params(["limit=5", "flag=true"]) == {"limit": 5, "flag": True}

    def test_plain_values_keep_leading_zeros_and_chinese(self) -> None:
        parsed = parse_params(["symbol=000300", "index_name=沪深300"])
        assert parsed == {"symbol": "000300", "index_name": "沪深300"}

    def test_none_input_is_empty(self) -> None:
        assert parse_params(None) == {}

    def test_rejects_missing_equals(self) -> None:
        with pytest.raises(ValueError, match="key=value"):
            parse_params(["symbol"])

    def test_rejects_empty_key(self) -> None:
        with pytest.raises(ValueError, match="参数名"):
            parse_params(["=1"])


class TestSerializeValue:
    def test_dataframe_becomes_records(self) -> None:
        pd = pytest.importorskip("pandas")
        assert serialize_value(pd.DataFrame([{"a": 1}])) == [{"a": 1}]

    def test_dict_and_list_pass_through(self) -> None:
        assert serialize_value({"a": 1}) == {"a": 1}
        assert serialize_value([1, 2]) == [1, 2]

    def test_unknown_object_is_stringified(self) -> None:
        assert isinstance(serialize_value(object()), str)


class TestSkillCommand:
    def test_print_outputs_bundled_skill(self, cli: typer.Typer) -> None:
        result = runner.invoke(cli, ["skill", "--print"])
        assert result.exit_code == 0
        assert result.output.strip() == read_bundled_skill().strip()

    def test_install_to_custom_dir(self, cli: typer.Typer, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["skill", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        installed = tmp_path / "fund.md"
        assert installed.read_text(encoding="utf-8") == read_bundled_skill()
        assert "已安装" in result.output

    def test_existing_file_is_not_overwritten(self, cli: typer.Typer, tmp_path: Path) -> None:
        target = tmp_path / "fund.md"
        target.write_text("手改过的内容", encoding="utf-8")
        result = runner.invoke(cli, ["skill", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "已存在" in result.output
        assert target.read_text(encoding="utf-8") == "手改过的内容"

    def test_force_overwrites(self, cli: typer.Typer, tmp_path: Path) -> None:
        target = tmp_path / "fund.md"
        target.write_text("旧内容", encoding="utf-8")
        result = runner.invoke(cli, ["skill", "--dir", str(tmp_path), "--force"])
        assert result.exit_code == 0
        assert target.read_text(encoding="utf-8") == read_bundled_skill()
