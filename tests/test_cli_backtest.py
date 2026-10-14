"""`ifa backtest` 命令的测试（不经过 LLM、不触网）。"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from ifa.cli.main import app

runner = CliRunner()


@pytest.fixture()
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    def fake_run(symbol: str, start_date: str, end_date: str, initial_investment: float = 100000.0) -> Any:
        calls.update(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_investment=initial_investment,
        )
        return SimpleNamespace(error=None)

    # 命令内部 from ifa.backtest.engine import run_backtest，故 patch 模块属性即可。
    monkeypatch.setattr("ifa.backtest.engine.run_backtest", fake_run)
    monkeypatch.setattr("ifa.backtest.engine.format_backtest_report", lambda result: "BACKTEST-REPORT-BODY")
    return calls


class TestBacktestCommand:
    def test_command_is_registered(self) -> None:
        # Typer 的 CommandInfo.name 对未显式命名的命令是 None，需回落到回调函数名。
        names = {command.name or command.callback.__name__ for command in app.registered_commands}
        assert "backtest" in names
        assert {"analyze", "screen", "portfolio", "search", "info", "validate"} <= names

    def test_help_is_available(self) -> None:
        assert runner.invoke(app, ["backtest", "--help"]).exit_code == 0

    def test_default_range_is_last_three_years(self, captured: dict[str, Any]) -> None:
        result = runner.invoke(app, ["backtest", "510300"])
        assert result.exit_code == 0
        assert "BACKTEST-REPORT-BODY" in result.output
        assert captured["symbol"] == "510300"
        assert captured["end_date"] == date.today().isoformat()
        assert captured["start_date"] == (date.today() - timedelta(days=365 * 3)).isoformat()
        assert captured["initial_investment"] == 100000.0

    def test_explicit_range_and_amount(self, captured: dict[str, Any]) -> None:
        result = runner.invoke(
            app,
            ["backtest", "000834", "--start", "2020-01-01", "--end", "2023-12-31", "--amount", "50000"],
        )
        assert result.exit_code == 0
        assert captured["start_date"] == "2020-01-01"
        assert captured["end_date"] == "2023-12-31"
        assert captured["initial_investment"] == 50000.0

    def test_error_result_exits_non_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("ifa.backtest.engine.run_backtest", lambda *a, **k: SimpleNamespace(error="数据源挂了"))
        monkeypatch.setattr("ifa.backtest.engine.format_backtest_report", lambda result: "⚠️ 数据源挂了")
        result = runner.invoke(app, ["backtest", "510300"])
        assert result.exit_code == 1
        assert "回测失败" in result.output
