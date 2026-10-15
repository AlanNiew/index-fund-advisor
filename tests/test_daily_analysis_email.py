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


def _patch_main(monkeypatch, module, *, trading_day=True, results=None, email_error=None, previous_day="2026-10-12"):
    """把 main() 的外部依赖全部替换掉，返回记录调用的容器。"""
    calls: dict = {"email": [], "analyze": [], "analyze_dates": [], "snapshots": []}

    monkeypatch.setattr(module, "check_trading_day", lambda date_str: trading_day)
    monkeypatch.setattr(module, "previous_trading_day", lambda reference=None: previous_day)
    monkeypatch.setattr(module, "fetch_valuations", lambda codes, fund_snapshots=None: {})

    def fake_snapshots(codes):
        calls["snapshots"].append(list(codes))
        return {"510300": {"name": "沪深300ETF华泰", "nav": 4.3479, "nav_date": "2026-10-13", "change_pct": 0.42}}

    monkeypatch.setattr(module, "fetch_fund_snapshots", fake_snapshots)
    monkeypatch.setattr(module, "print_valuation_overview", lambda codes, metrics: None)
    monkeypatch.setattr(module, "print_summary", lambda res, date_str, metrics=None: None)
    monkeypatch.setattr("ifa.common.build_advisor", lambda *args, **kwargs: object())

    def fake_analyze(advisor, fund_code, analysis_date, mode="deep"):
        calls["analyze"].append((fund_code, mode))
        calls["analyze_dates"].append(analysis_date)
        return _stub_result(fund_code)

    monkeypatch.setattr(module, "analyze_single_fund", results or fake_analyze)

    def fake_send(res, analysis_date, mode, fund_metrics=None, fund_snapshots=None):
        calls["email"].append(
            {
                "results": res,
                "date": analysis_date,
                "mode": mode,
                "metrics": fund_metrics,
                "snapshots": fund_snapshots,
            }
        )
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


def test_default_run_analyzes_previous_trading_day(monkeypatch, script):
    """不带 --date 时分析「前一交易日」—— 早上 08:00 跑批时当天数据还没出来。"""
    calls = _patch_main(monkeypatch, script, trading_day=True)
    monkeypatch.setattr(sys, "argv", ["daily_analysis.py", "--codes", "510300", "--email"])

    assert script.main() == 0
    assert calls["analyze_dates"] == ["2026-10-12"]
    assert calls["email"][0]["date"] == "2026-10-12"


def test_non_trading_today_skips_without_explicit_date(monkeypatch, script):
    """今天休市 → 不发（哪怕「前一交易日」是开市的）。"""
    calls = _patch_main(monkeypatch, script, trading_day=False)
    monkeypatch.setattr(sys, "argv", ["daily_analysis.py", "--codes", "510300", "--email"])

    assert script.main() == 0
    assert calls["analyze"] == []
    assert calls["email"] == []


def test_unavailable_calendar_exits_nonzero(monkeypatch, script):
    """交易日历取不到 → 无法确定分析日期，按失败上报（exit 1），不能静默什么都不做。"""
    calls = _patch_main(monkeypatch, script, trading_day=True, previous_day=None)
    monkeypatch.setattr(sys, "argv", ["daily_analysis.py", "--codes", "510300", "--email"])

    assert script.main() == 1
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
    # 净值快照在分析前取一次，并原样透传给邮件摘要
    assert calls["snapshots"] == [["510300", "159919"]]
    assert sent["snapshots"]["510300"]["nav"] == 4.3479


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


class TestPreviousTradingDay:
    def test_asks_calendar_for_the_day_before_reference(self, monkeypatch, script):
        seen: dict = {}

        def fake_prev(date_str):
            seen["arg"] = date_str
            return "2026-10-12"

        monkeypatch.setattr("ifa.dataflows.a_share_common.get_previous_trade_date", fake_prev)

        assert script.previous_trading_day("2026-10-13") == "2026-10-12"
        assert seen["arg"] == "2026-10-12"  # 查询的是 reference 的前一天，不是 reference 当天

    def test_calendar_failure_returns_none_instead_of_raising(self, monkeypatch, script):
        def boom(date_str):
            raise RuntimeError("日历不可用")

        monkeypatch.setattr("ifa.dataflows.a_share_common.get_previous_trade_date", boom)

        assert script.previous_trading_day("2026-10-13") is None


class TestIndexResolution:
    def test_detect_index_matches_longest_name_first(self, script):
        # 「中证1000」必须先于「中证100」命中，否则 1000 会被误判成 100
        assert script.detect_index_from_name("华夏中证1000ETF联接A") == "中证1000"
        assert script.detect_index_from_name("华泰柏瑞上证红利ETF联接A") == "上证红利"
        assert script.detect_index_from_name("易方达沪深300ETF联接A") == "沪深300"

    def test_detect_index_returns_none_for_unsupported_or_empty(self, script):
        assert script.detect_index_from_name("招商中证白酒指数(LOF)A") is None
        assert script.detect_index_from_name("摩根标普500指数(QDII)人民币A") is None
        assert script.detect_index_from_name("大成纳斯达克100ETF联接(QDII)A") is None
        assert script.detect_index_from_name("") is None

    def test_override_wins_over_name_detection(self, script):
        assert script.resolve_index_name("161725", "华泰柏瑞上证红利ETF联接A") == "中证白酒"
        assert script.resolve_index_name("012761", None) == "上证红利"
        assert script.resolve_index_name("000001", "华夏成长混合") is None


class TestFetchValuations:
    def test_requests_each_index_once_and_copies_metrics_per_fund(self, monkeypatch, script):
        seen: list[str] = []

        def fake_metrics(index_name):
            seen.append(index_name)
            return {"index_name": index_name, "date": "2026-10-13", "pe_ttm": 12.0}

        monkeypatch.setattr("ifa.dataflows.a_share_macro.fetch_valuation_metrics", fake_metrics)
        snapshots = {"110020": {"name": "易方达沪深300ETF联接A"}, "510300": {"name": "沪深300ETF华泰"}}

        metrics = script.fetch_valuations(["110020", "510300"], snapshots)

        assert seen == ["沪深300"]
        assert metrics["110020"]["index_name"] == "沪深300"
        assert metrics["510300"]["pe_ttm"] == 12.0
        # 每只基金拿到的是副本：改一只不能影响共享同一指数的另一只
        metrics["110020"]["pe_ttm"] = 99.0
        assert metrics["510300"]["pe_ttm"] == 12.0

    def test_unresolved_fund_gets_empty_metrics_without_request(self, monkeypatch, script):
        monkeypatch.setattr(
            "ifa.dataflows.a_share_macro.fetch_valuation_metrics",
            lambda index_name: pytest.fail("认不出跟踪指数时不该请求估值"),
        )

        metrics = script.fetch_valuations(["000001"], {"000001": {"name": "华夏成长混合"}})

        assert metrics["000001"] == {"index_name": None}

    def test_snapshot_failure_degrades_to_empty_dict(self, monkeypatch, script):
        def boom(codes):
            raise RuntimeError("网络挂了")

        monkeypatch.setattr("ifa.dataflows.a_share_public_fund.fetch_fund_daily_snapshots", boom)

        assert script.fetch_fund_snapshots(["510300"]) == {}


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

    script.send_report_email(results, "2026-10-13", "deep", {}, {})

    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    assert message["Subject"] == "[IFA] 2026-10-13 基金分析报告（1 只 / 成功 1）"
    assert message["To"] == "me@example.com"
    assert [part.get_filename() for part in message.iter_attachments()] == [report_file.name]
    body_part = message.get_body(preferencelist=("plain",))
    assert body_part is not None
    sent_body = body_part.get_content()
    assert "【智识诚实声明】" in sent_body
    # 纯文本正文是摘要：报告原文（Markdown）不进正文
    assert "# 报告" not in sent_body

    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    sent_html = html_part.get_content()
    # HTML 正文把报告渲染成标签（声明来自报告正文本身）
    assert "<h1>报告</h1>" in sent_html
    assert "【智识诚实声明】" in sent_html
