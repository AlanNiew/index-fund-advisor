"""CLI 失败必须以非零退出码结束。

历史缺陷：`_run_analysis` 在 final_report 为空时只打印一行黄字就正常返回，
退出码为 0 —— 包装脚本/定时任务因此无法发现故障（Web 入口有正确上报）。
cli/main.py 此前没有测试（覆盖率 0%），这里直接对 `_run_analysis` 做单元测试。
"""

import pytest
import typer

import ifa.common as common
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
