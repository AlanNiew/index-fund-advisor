"""`scripts/daily_analysis.py` 的 --email / --mode / 退出码 测试（不联网、不发真邮件）。"""

from __future__ import annotations

import importlib.util
import smtplib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "daily_analysis.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("ifa_daily_analysis", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ifa_daily_analysis"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch):
    module = _load_script()
    monkeypatch.setattr("ifa.env_loader.load_env_files", lambda: None)
    return module


def _stub_result(fund_code: str, error: str = "") -> dict:
    return {
        "fund_code": fund_code,
        "rating": "BUY" if not error else "N/A",
        "confidence": "High" if not error else "N/A",
        "report_path": None,
        "report": "报告正文" if not error else "",
        "elapsed": 1.0,
        "error": error,
    }


def _patch_main(monkeypatch, module, *, trading_day=True, results=None, email_error=None):
    """把 main() 的外部依赖全部替换掉，返回记录调用的容器。"""
    calls: dict = {"email": [], "analyze": []}

    monkeypatch.setattr(module, "check_trading_day", lambda date_str: trading_day)
    monkeypatch.setattr(module, "fetch_valuations", lambda codes: {})
    monkeypatch.setattr(module, "print_valuation_overview", lambda codes, metrics: None)
    monkeypatch.setattr(module, "print_summary", lambda res, date_str, metrics=None: None)
    monkeypatch.setattr("ifa.common.build_advisor", lambda *args, **kwargs: object())

    def fake_analyze(advisor, fund_code, analysis_date, mode="deep"):
        calls["analyze"].append((fund_code, mode))
        return _stub_result(fund_code)

    monkeypatch.setattr(module, "analyze_single_fund", results or fake_analyze)

    def fake_send(res, analysis_date, mode, fund_metrics=None):
        calls["email"].append({"results": res, "date": analysis_date, "mode": mode, "metrics": fund_metrics})
        if email_error is not None:
            raise email_error

    monkeypatch.setattr(module, "send_report_email", fake_send)
    return calls


def test_non_trading_day_skips_analysis_and_email(monkeypatch, script):
    calls = _patch_main(monkeypatch, script, trading_day=False)
    monkeypatch.setattr(sys, "argv", ["daily_analysis.py", "--date", "2026-10-10", "--email"])

    assert script.main() == 0
    assert calls["analyze"] == []
    assert calls["email"] == []


def test_force_bypasses_trading_day_check(monkeypatch, script):
    calls = _patch_main(monkeypatch, script, trading_day=False)
    monkeypatch.setattr(sys, "argv", ["daily_analysis.py", "--date", "2026-10-10", "--force", "--codes", "510300"])

    assert script.main() == 0
    assert calls["analyze"] == [("510300", "deep")]


def test_trading_day_sends_email_with_selected_mode(monkeypatch, script):
    calls = _patch_main(monkeypatch, script, trading_day=True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["daily_analysis.py", "--date", "2026-10-13", "--codes", "510300,159919", "--mode", "deep_simple", "--email"],
    )

    assert script.main() == 0
    assert calls["analyze"] == [("510300", "deep_simple"), ("159919", "deep_simple")]
    assert len(calls["email"]) == 1
    sent = calls["email"][0]
    assert sent["date"] == "2026-10-13"
    assert sent["mode"] == "deep_simple"
    assert [item["fund_code"] for item in sent["results"]] == ["510300", "159919"]


def test_without_email_flag_nothing_is_sent(monkeypatch, script):
    calls = _patch_main(monkeypatch, script, trading_day=True)
    monkeypatch.setattr(sys, "argv", ["daily_analysis.py", "--date", "2026-10-13", "--codes", "510300"])

    assert script.main() == 0
    assert calls["email"] == []


def test_failed_fund_exits_nonzero_but_still_emails(monkeypatch, script):
    def failing_analyze(advisor, fund_code, analysis_date, mode="deep"):
        return _stub_result(fund_code, error="数据源超时")

    calls = _patch_main(monkeypatch, script, trading_day=True, results=failing_analyze)
    monkeypatch.setattr(sys, "argv", ["daily_analysis.py", "--date", "2026-10-13", "--codes", "510300", "--email"])

    assert script.main() == 1
    assert len(calls["email"]) == 1


def test_email_failure_exits_nonzero(monkeypatch, script):
    from ifa.notify.email import EmailSendError

    calls = _patch_main(monkeypatch, script, trading_day=True, email_error=EmailSendError("smtp down"))
    monkeypatch.setattr(sys, "argv", ["daily_analysis.py", "--date", "2026-10-13", "--codes", "510300", "--email"])

    assert script.main() == 1
    assert len(calls["email"]) == 1


def test_analyze_single_fund_passes_mode_to_build_state_and_run(monkeypatch, script):
    seen: dict = {}

    def fake_build_state(**kwargs):
        seen["build_state"] = kwargs
        return {"fund_codes": kwargs["fund_codes"]}

    monkeypatch.setattr("ifa.common.build_state", fake_build_state)
    monkeypatch.setattr("ifa.common.save_report", lambda state: Path("results/reports/510300/x.md"))

    class StubAdvisor:
        def __init__(self):
            self.run_modes: list[str] = []

        def run(self, mode, state):
            self.run_modes.append(mode)
            return {"final_report": "报告正文", "final_rating": "BUY", "final_confidence": "High"}

        def process_signal(self, report):
            return "BUY"

        def process_confidence(self, report):
            return "High"

    advisor = StubAdvisor()
    result = script.analyze_single_fund(advisor, "510300", "2026-10-13", mode="deep_simple")

    assert seen["build_state"]["mode"] == "deep_simple"
    assert seen["build_state"]["analysis_date"] == "2026-10-13"
    assert advisor.run_modes == ["deep_simple"]
    assert result["report"] == "报告正文"
    assert result["rating"] == "BUY"
    assert result["confidence"] == "High"
    assert result["error"] == ""


def test_send_report_email_requires_configuration(monkeypatch, script):
    from ifa.notify.email import EmailConfigError

    monkeypatch.setattr("ifa.default_config.build_runtime_config", lambda: {})

    with pytest.raises(EmailConfigError, match="未配置邮件通知"):
        script.send_report_email([], "2026-10-13", "deep", {})


def test_send_report_email_wires_body_and_attachment(monkeypatch, script, tmp_path):
    report_file = tmp_path / "510300_2026-10-13_deep_abcd1234.md"
    report_file.write_text("# 报告\n\n【智识诚实声明】", encoding="utf-8")
    results = [
        {
            "fund_code": "510300",
            "rating": "BUY",
            "confidence": "High",
            "report_path": str(report_file),
            "report": "# 报告\n\n【智识诚实声明】",
            "elapsed": 3.0,
            "error": "",
        }
    ]
    monkeypatch.setattr(
        "ifa.default_config.build_runtime_config",
        lambda: {
            "smtp_host": "smtp.example.com",
            "smtp_recipients": "me@example.com",
            "smtp_sender": "ifa@example.com",
        },
    )

    class FakeSMTP:
        sent: list = []

        def __init__(self, host="", port=0, timeout=None, context=None, **kwargs):
            self.host = host
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def login(self, user, password):
            raise AssertionError("未配用户名，不应登录")

        def send_message(self, message):
            FakeSMTP.sent.append(message)

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)

    script.send_report_email(results, "2026-10-13", "deep", {})

    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    assert message["Subject"] == "[IFA] 2026-10-13 基金分析报告（1 只 / 成功 1）"
    assert message["To"] == "me@example.com"
    assert [part.get_filename() for part in message.iter_attachments()] == [report_file.name]
    body_part = message.get_body(preferencelist=("plain",))
    assert body_part is not None
    assert "【智识诚实声明】" in body_part.get_content()
