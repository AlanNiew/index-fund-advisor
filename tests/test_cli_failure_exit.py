"""CLI 失败必须以非零退出码结束。

历史缺陷：`_run_analysis` 在 final_report 为空时只打印一行黄字就正常返回，
退出码为 0 —— 包装脚本/定时任务因此无法发现故障（Web 入口有正确上报）。
cli/main.py 此前没有测试（覆盖率 0%），这里直接对 `_run_analysis` 做单元测试。
"""

import pytest
import typer

import ifa.common as common
import ifa.default_config as dc
from ifa.cli.main import _run_analysis


class _FakeAdvisor:
    """替身 AdvisorGraph：只回放预设 state，不构建真实图（否则要 LLM 与网络）。"""

    def __init__(self, state):
        self._state = state

    def run(self, mode, state, on_progress=None):
        if on_progress is not None:
            on_progress("report_generator", "生成报告")
        return self._state


def _patch_advisor(monkeypatch, state):
    monkeypatch.setattr(common, "build_advisor", lambda **kwargs: _FakeAdvisor(state))


class TestFailureExitCode:
    def test_no_report_raises_exit_code_1(self, monkeypatch):
        _patch_advisor(monkeypatch, {"error": "LLM 调用失败"})
        with pytest.raises(typer.Exit) as excinfo:
            _run_analysis("deep", {}, "报告")
        assert excinfo.value.exit_code == 1

    def test_no_report_and_no_error_field_still_fails(self, monkeypatch):
        """拿不到报告就是失败，不依赖 error 字段是否存在。"""
        _patch_advisor(monkeypatch, {})
        with pytest.raises(typer.Exit) as excinfo:
            _run_analysis("deep", {}, "报告")
        assert excinfo.value.exit_code == 1

    def test_error_reason_is_printed(self, monkeypatch, capsys):
        _patch_advisor(monkeypatch, {"error": "深度模型不可用"})
        with pytest.raises(typer.Exit):
            _run_analysis("deep", {}, "报告")
        out = capsys.readouterr().out
        assert "分析失败" in out
        assert "深度模型不可用" in out


class TestSuccessPath:
    def test_report_is_saved_and_no_exit(self, monkeypatch):
        _patch_advisor(monkeypatch, {"final_report": "## 报告", "fund_codes": ["510300"]})
        saved = {}

        def fake_save(state):
            saved["state"] = state
            return "results/x.md"

        monkeypatch.setattr(common, "save_report", fake_save)
        _run_analysis("deep", {}, "报告")  # 不应抛 typer.Exit
        assert saved["state"]["final_report"] == "## 报告"


class TestSearchCommand:
    """`ifa search` 的三条路径：有命中 / 无命中 / 数据源失败。

    `search` 内部延迟导入 run_data_tool，故 patch `ifa.data_tools.api.run_data_tool`
    即可拦截取数；无命中必须保持退出码 0，只有取数失败才是非零。
    """

    @staticmethod
    def _patch_result(monkeypatch, result: str):
        import ifa.data_tools.api as data_api

        monkeypatch.setattr(data_api, "run_data_tool", lambda *args, **kwargs: result)

    def test_matches_are_printed(self, monkeypatch, capsys):
        from ifa.cli.main import search

        self._patch_result(
            monkeypatch,
            "# Fund Search: 沪深300\n# Matches: 366 (showing 1)\n\n000051,华夏沪深300ETF联接A,指数型-股票\n",
        )
        search(keyword="沪深300", limit=1)  # 不抛
        out = capsys.readouterr().out
        assert "000051" in out
        assert "Matches: 366" in out

    def test_data_source_failure_exits_nonzero(self, monkeypatch, capsys):
        from ifa.cli.main import search

        self._patch_result(monkeypatch, "数据源访问失败：ConnectionError: 连接被重置")
        with pytest.raises(typer.Exit) as excinfo:
            search(keyword="沪深300", limit=1)
        assert excinfo.value.exit_code == 1
        assert "数据源访问失败" in capsys.readouterr().out

    def test_no_match_stays_exit_zero(self, monkeypatch):
        from ifa.cli.main import search

        self._patch_result(monkeypatch, "# Fund Search: 不存在\n# Matches: 0\n\n未找到匹配「不存在」的基金。")
        search(keyword="不存在", limit=1)  # 查无结果不是故障 → 不得抛 typer.Exit


class TestAnalyzeMode:
    """`ifa analyze --mode` 必须真正切换模式，非法模式必须失败。

    历史缺陷：analyze 没有 --mode，四种模式里只有 deep 能从 CLI 走到；
    deep_simple（无辩论、快得多）实际上只能靠 API/配置触发。
    """

    def test_invalid_mode_exits_nonzero(self, capsys):
        from ifa.cli.main import analyze

        with pytest.raises(typer.Exit) as excinfo:
            analyze(fund_code="510300", date="2024-01-15", mode="deep_medium", debug=False)

        assert excinfo.value.exit_code == 1
        assert "不支持的分析模式" in capsys.readouterr().out

    def test_mode_is_forwarded_to_advisor_and_state(self, monkeypatch):
        from ifa.cli.main import analyze

        seen = {}

        class _Advisor:
            def run(self, mode, state, on_progress=None):
                seen["mode"] = mode
                seen["state_mode"] = state.get("mode")
                return {"final_report": "## 报告", "fund_codes": ["510300"]}

        monkeypatch.setattr(common, "build_advisor", lambda **kwargs: _Advisor())
        monkeypatch.setattr(common, "save_report", lambda state: "results/x.md")

        analyze(fund_code="510300", date="2024-01-15", mode="deep_simple", debug=False)

        assert seen["mode"] == "deep_simple"
        assert seen["state_mode"] == "deep_simple"

    def test_default_mode_is_deep(self):
        """不带 --mode 时默认 deep（含辩论）。

        这里检查声明本身而不是调用函数：直接调用 typer 命令时未传的参数是 OptionInfo
        对象而非其默认值，只有经 typer 解析后才是字符串。
        """
        import inspect

        from ifa.cli.main import analyze

        assert inspect.signature(analyze).parameters["mode"].default.default == "deep"


class TestConfigCommand:
    """`ifa config` 必须真的写用户配置文件。

    历史缺陷：带参数调用只打印一行「配置已更新」黄字，既不落盘也不生效。
    """

    @staticmethod
    def _isolate(monkeypatch, tmp_path):
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(dc, "LEGACY_LAST_CONFIG_PATH", tmp_path / "nonexistent.py")
        return tmp_path / "config.json"

    def test_set_writes_file(self, tmp_path, monkeypatch, capsys):
        import json

        from ifa.cli.main import config_cmd

        target = self._isolate(monkeypatch, tmp_path)
        config_cmd(key="llm_provider", value="deepseek", unset=False)

        assert json.loads(target.read_text(encoding="utf-8"))["llm_provider"] == "deepseek"
        assert "已设置" in capsys.readouterr().out

    def test_unknown_key_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        from ifa.cli.main import config_cmd

        self._isolate(monkeypatch, tmp_path)

        with pytest.raises(typer.Exit) as excinfo:
            config_cmd(key="nope", value="1", unset=False)

        assert excinfo.value.exit_code == 1
        assert "未知配置项" in capsys.readouterr().out

    def test_unset_removes_key_and_file(self, tmp_path, monkeypatch):
        from ifa.cli.main import config_cmd

        target = self._isolate(monkeypatch, tmp_path)
        config_cmd(key="llm_provider", value="deepseek", unset=False)
        assert target.exists()

        config_cmd(key="llm_provider", value=None, unset=True)

        assert not target.exists()

    def test_show_single_key_prints_effective_value(self, tmp_path, monkeypatch, capsys):
        from ifa.cli.main import config_cmd

        self._isolate(monkeypatch, tmp_path)
        monkeypatch.setattr(dc, "load_last_config", lambda: {})

        config_cmd(key="llm_provider", value=None, unset=False)

        assert dc.DEFAULT_CONFIG["llm_provider"] in capsys.readouterr().out
