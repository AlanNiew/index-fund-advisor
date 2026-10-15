"""`ifa.notify.email` 的单元测试：全程打桩，不连真实 SMTP。"""

from __future__ import annotations

import smtplib

import pytest

from ifa.notify.email import (
    DEFAULT_SMTP_TIMEOUT,
    DEFAULT_SSL_PORT,
    DEFAULT_STARTTLS_PORT,
    MAX_BODY_CHARS,
    EmailConfig,
    EmailConfigError,
    EmailSendError,
    _display_width,
    _valuation_anchor_note,
    build_daily_report_email,
    parse_recipients,
    send_email,
)


def _full_config(**overrides) -> dict:
    config = {
        "smtp_host": "smtp.example.com",
        "smtp_recipients": "a@example.com, b@example.com",
        "smtp_sender": "ifa@example.com",
        "smtp_user": "ifa@example.com",
        "smtp_password": "secret",
        "smtp_port": None,
        "smtp_use_ssl": True,
        "smtp_timeout": 30,
    }
    config.update(overrides)
    return config


class FakeSMTP:
    """记录调用的假 SMTP 客户端（同时冒充 SMTP 与 SMTP_SSL）。"""

    instances: list[FakeSMTP] = []
    fail_login = False
    fail_send = False

    def __init__(self, host="", port=0, timeout=None, context=None, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.calls: list[str] = []
        self.sent: list = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def ehlo(self):
        self.calls.append("ehlo")
        return (250, b"ok")

    def starttls(self, context=None):
        self.calls.append("starttls")
        self.starttls_context = context
        return (220, b"ready")

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"auth failed")
        self.calls.append(f"login:{user}")
        self.credentials = (user, password)

    def send_message(self, message):
        if FakeSMTP.fail_send:
            raise smtplib.SMTPServerDisconnected("connection lost")
        self.calls.append("send_message")
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeSMTP.instances = []
    FakeSMTP.fail_login = False
    FakeSMTP.fail_send = False
    yield


class TestParseRecipients:
    def test_splits_on_commas_semicolons_and_whitespace(self):
        raw = "a@x.com, b@x.com;c@x.com  d@x.com"
        assert parse_recipients(raw) == ("a@x.com", "b@x.com", "c@x.com", "d@x.com")

    def test_accepts_sequence_and_drops_blanks(self):
        assert parse_recipients(["a@x.com", " b@x.com ", ""]) == ("a@x.com", "b@x.com")

    def test_none_and_blank_yield_empty_tuple(self):
        assert parse_recipients(None) == ()
        assert parse_recipients("   ") == ()


class TestEmailConfigFromConfig:
    def test_unconfigured_returns_none(self):
        assert EmailConfig.from_config({}) is None

    def test_transport_defaults_alone_are_not_configuration(self):
        # smtp_use_ssl / smtp_timeout 有默认值，不能据此认为用户配过邮件
        config = {"smtp_use_ssl": True, "smtp_timeout": 30, "smtp_port": None}
        assert EmailConfig.from_config(config) is None

    def test_partial_config_lists_missing_keys_and_env_names(self):
        with pytest.raises(EmailConfigError) as excinfo:
            EmailConfig.from_config({"smtp_host": "smtp.qq.com"})
        message = str(excinfo.value)
        assert "smtp_recipients" in message
        assert "smtp_sender" in message
        assert "IFA_EMAIL_TO" in message

    def test_complete_config_builds_dataclass(self):
        config = EmailConfig.from_config(_full_config())
        assert config is not None
        assert config.host == "smtp.example.com"
        assert config.recipients == ("a@example.com", "b@example.com")
        assert config.sender == "ifa@example.com"
        assert config.password == "secret"
        assert config.timeout == DEFAULT_SMTP_TIMEOUT
        assert config.resolved_port == DEFAULT_SSL_PORT

    def test_sender_falls_back_to_user(self):
        config = EmailConfig.from_config(_full_config(smtp_sender=None))
        assert config is not None
        assert config.sender == "ifa@example.com"

    def test_user_without_password_is_reported_missing(self):
        with pytest.raises(EmailConfigError, match="smtp_password"):
            EmailConfig.from_config(_full_config(smtp_password=None))

    def test_starttls_port_when_ssl_disabled(self):
        config = EmailConfig.from_config(_full_config(smtp_use_ssl="false"))
        assert config is not None
        assert config.use_ssl is False
        assert config.resolved_port == DEFAULT_STARTTLS_PORT

    def test_explicit_port_wins(self):
        config = EmailConfig.from_config(_full_config(smtp_port="2525"))
        assert config is not None
        assert config.resolved_port == 2525

    def test_invalid_bool_raises(self):
        with pytest.raises(EmailConfigError, match="布尔值"):
            EmailConfig.from_config(_full_config(smtp_use_ssl="maybe"))

    def test_non_integer_port_raises(self):
        with pytest.raises(EmailConfigError, match="必须是整数"):
            EmailConfig.from_config(_full_config(smtp_port="forty"))


class TestBuildDailyReportEmail:
    def test_subject_body_and_attachments(self, tmp_path):
        report_file = tmp_path / "510300_2026-10-13_deep_abcd1234.md"
        report_file.write_text("# 报告\n\n【智识诚实声明】", encoding="utf-8")
        results = [
            {
                "fund_code": "510300",
                "rating": "BUY",
                "confidence": "High",
                "report_path": str(report_file),
                "report": "# 报告\n\n【智识诚实声明】",
                "elapsed": 12.34,
                "error": "",
            }
        ]
        subject, body, html_body, attachments = build_daily_report_email(
            analysis_date="2026-10-13",
            results=results,
            fund_metrics={
                "510300": {
                    "index_name": "沪深300",
                    "date": "2026-10-13",
                    "pe_ttm": 12.3,
                    "pb": 1.42,
                    "roe": 11.37,
                    "dividend_yield": 2.5,
                    "erp": -1.2,
                }
            },
            fund_snapshots={
                "510300": {
                    "name": "沪深300ETF华泰",
                    "nav": 4.3479,
                    "nav_date": "2026-10-13",
                    "change_pct": -0.42,
                }
            },
            mode="deep",
            generated_at="2026-10-13 15:42:00",
        )
        assert subject == "[IFA] 2026-10-13 基金分析报告（1 只 / 成功 1）"
        assert "分析模式: deep" in body
        assert "生成时间: 2026-10-13 15:42:00" in body
        assert "总耗时: 12.3s" in body
        assert "== 核心参数 ==" in body
        assert "沪深300ETF华泰" in body
        assert "4.3479（10-13）" in body
        assert "-0.42%" in body
        assert "== 指数估值 ==" in body
        assert "PE(TTM)" in body
        assert "ERP" in body
        assert "本邮件由 IFA 自动生成" in body
        assert attachments == [report_file]

    def test_plain_text_body_stays_summary_while_html_renders_the_report(self, tmp_path):
        """纯文本正文只放摘要（原始 Markdown 不进正文）；HTML 正文把报告渲染成标签。"""
        report_text = "# 报告\n\n正文很长"
        report_file = tmp_path / "510300_2026-10-13_deep_abcd1234.md"
        report_file.write_text(report_text, encoding="utf-8")
        results = [
            {
                "fund_code": "510300",
                "rating": "BUY",
                "confidence": "High",
                "report_path": str(report_file),
                "report": report_text,
                "elapsed": 1.0,
                "error": "",
            }
        ]
        _subject, body, html_body, attachments = build_daily_report_email(analysis_date="2026-10-13", results=results)
        assert "# 报告" not in body
        assert "正文很长" not in body
        assert len(body) < 1000
        assert "<h1>报告</h1>" in html_body
        assert "正文很长" in html_body
        assert attachments == [report_file]

    def test_html_body_renders_tables_and_escapes_report_text(self):
        """HTML 正文是真表格；报告里的 HTML 必须转义 —— 邮件客户端按 HTML 解析，不能让数据当标签跑。"""
        results = [
            {
                "fund_code": "510300",
                "rating": "BUY",
                "confidence": "High",
                "report_path": None,
                "report": "<script>alert(1)</script>",
                "elapsed": 2.0,
                "error": "",
            }
        ]
        _subject, _body, html_body, _attachments = build_daily_report_email(
            analysis_date="2026-10-13",
            results=results,
            fund_metrics={
                "510300": {
                    "index_name": "沪深300",
                    "pe_ttm": 12.3,
                    "pb": 1.42,
                    "roe": 11.37,
                    "dividend_yield": 2.5,
                    "erp": -1.2,
                }
            },
            fund_snapshots={
                "510300": {
                    "name": "沪深300ETF华泰",
                    "nav": 4.3479,
                    "nav_date": "2026-10-13",
                    "change_pct": -0.42,
                }
            },
        )
        assert "<table" in html_body
        assert "沪深300ETF华泰" in html_body
        assert "PE(TTM)" in html_body
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body

    def test_oversized_report_is_omitted_from_html_with_notice(self):
        """正文上限是硬约束：超长时显式写明「已省略」，不能让收件人以为报告只有摘要。"""
        huge_report = "# 报告\n\n" + ("正文很长" * 30) * 1200
        results = [
            {
                "fund_code": "510300",
                "rating": "BUY",
                "confidence": "High",
                "elapsed": 1.0,
                "error": "",
                "report": huge_report,
            }
        ]
        _subject, _body, html_body, _attachments = build_daily_report_email(analysis_date="2026-10-13", results=results)
        assert "已省略" in html_body
        assert "正文很长" not in html_body

    def test_metrics_columns_absent_without_valuations(self):
        results = [
            {
                "fund_code": "510300",
                "rating": "HOLD",
                "confidence": "Medium",
                "report_path": None,
                "report": "报告",
                "elapsed": 1.0,
                "error": "",
            }
        ]
        _subject, body, html_body, attachments = build_daily_report_email(analysis_date="2026-10-13", results=results)
        assert "PE(TTM)" not in body
        assert "== 指数估值 ==" not in body
        # 没有快照时核心参数表仍然在，只是名称/净值/日涨跌显示 '-'
        assert "== 核心参数 ==" in body
        assert "510300" in body
        assert attachments == []

    def test_index_row_skipped_when_index_unknown(self):
        """认不出跟踪指数的基金不进估值表 —— 不猜指数，免得张冠李戴。"""
        results = [{"fund_code": "000001", "rating": "HOLD", "confidence": "Low", "elapsed": 1.0, "error": ""}]
        _subject, body, _html_body, _attachments = build_daily_report_email(
            analysis_date="2026-10-13",
            results=results,
            fund_metrics={"000001": {"index_name": None, "pe_ttm": 9.9}},
        )
        assert "== 指数估值 ==" not in body
        assert "9.90" not in body

    def test_failed_fund_reports_error_and_no_attachment(self):
        results = [
            {
                "fund_code": "159919",
                "rating": "N/A",
                "confidence": "N/A",
                "report_path": None,
                "report": "",
                "elapsed": 0.4,
                "error": "数据源超时",
            }
        ]
        subject, body, html_body, attachments = build_daily_report_email(analysis_date="2026-10-13", results=results)
        assert "成功 0" in subject
        assert "== 失败明细 ==" in body
        assert "159919: 数据源超时" in body
        assert attachments == []

    def test_cjk_cells_are_aligned_by_display_width(self):
        """CJK 全角算 2 列，否则等宽字体下表格会错位。"""
        results = [{"fund_code": "510300", "rating": "BUY", "confidence": "High", "elapsed": 1.0, "error": ""}]
        snapshots = {"510300": {"name": "沪深300ETF华泰", "nav": 4.3479, "nav_date": "2026-10-13", "change_pct": 0.42}}
        _subject, body, _html_body, _attachments = build_daily_report_email(
            analysis_date="2026-10-13", results=results, fund_snapshots=snapshots
        )
        table_lines = [line for line in body.splitlines() if "510300" in line or line.startswith("基金代码")]
        assert _display_width("沪深300") == 7
        assert len({_display_width(line) for line in table_lines}) == 1


def _sent_body(message) -> str:
    body_part = message.get_body(preferencelist=("plain",))
    assert body_part is not None
    return body_part.get_content()


def _sent_html(message) -> str:
    body_part = message.get_body(preferencelist=("html",))
    assert body_part is not None
    return body_part.get_content()


class TestValuationAnchorNote:
    """P0-4：邮件里必须能看出哪些基金本次没有估值锚（没看估值百分位就评级）。"""

    def test_all_funds_have_anchor_returns_none(self):
        results = [{"fund_code": "510300"}]
        metrics = {"510300": {"index_name": "沪深300", "pe_ttm": 12.0, "pb": 1.5}}
        assert _valuation_anchor_note(results, metrics) is None

    def test_pe_only_still_counts_as_anchor(self):
        """PE / PB 有一个就不算无估值锚（另一个缺失由报告自身标注）。"""
        results = [{"fund_code": "510300"}]
        metrics = {"510300": {"index_name": "沪深300", "pe_ttm": 12.0, "pb": None}}
        assert _valuation_anchor_note(results, metrics) is None

    def test_missing_pe_and_pb_is_listed_with_index_name(self):
        results = [{"fund_code": "510300"}, {"fund_code": "161725"}]
        metrics = {
            "510300": {"index_name": "沪深300", "pe_ttm": 12.0, "pb": 1.5},
            "161725": {"index_name": "中证白酒", "pe_ttm": None, "pb": None},
        }
        note = _valuation_anchor_note(results, metrics)
        assert note is not None
        assert "1 只基金有 PE/PB 数据" in note
        assert "161725(中证白酒)" in note
        assert "未使用估值百分位" in note

    def test_unknown_index_is_reported_separately(self):
        """认不出跟踪指数与数据源没覆盖是两回事，分开列。"""
        results = [{"fund_code": "999999"}, {"fund_code": "161725"}]
        metrics = {"161725": {"index_name": "中证白酒", "pe_ttm": None, "pb": None}}
        note = _valuation_anchor_note(results, metrics)
        assert note is not None
        assert "未识别跟踪指数: 999999" in note
        assert "无估值锚: 161725(中证白酒)" in note

    def test_missing_metrics_mapping_is_unknown_index(self):
        results = [{"fund_code": "510300"}]
        note = _valuation_anchor_note(results, {})
        assert note is not None
        assert "未识别跟踪指数: 510300" in note

    def test_note_reaches_both_bodies(self):
        results = [
            {"fund_code": "510300", "rating": "BUY", "confidence": "High", "elapsed": 1.0, "error": ""},
            {"fund_code": "161725", "rating": "HOLD", "confidence": "Medium", "elapsed": 1.0, "error": ""},
        ]
        fund_metrics = {
            "510300": {
                "index_name": "沪深300",
                "date": "2026-10-13",
                "pe_ttm": 12.0,
                "pb": 1.5,
                "roe": 12.5,
                "dividend_yield": 2.6,
                "erp": 5.0,
            },
            "161725": {
                "index_name": "中证白酒",
                "date": "2026-10-13",
                "pe_ttm": None,
                "pb": None,
                "roe": None,
                "dividend_yield": None,
                "erp": None,
            },
        }
        _subject, body, html_body, _attachments = build_daily_report_email(
            analysis_date="2026-10-13", results=results, fund_metrics=fund_metrics
        )
        assert "161725(中证白酒)" in body
        assert "161725(中证白酒)" in html_body


class TestSendEmail:
    def test_ssl_path_sends_and_logs_in(self, monkeypatch, tmp_path):
        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        attachment = tmp_path / "report.md"
        attachment.write_text("内容", encoding="utf-8")
        config = EmailConfig.from_config(_full_config())
        assert config is not None

        attached = send_email("主题", "正文", config=config, attachments=[attachment])

        assert attached == 1
        client = FakeSMTP.instances[0]
        assert (client.host, client.port, client.timeout) == ("smtp.example.com", DEFAULT_SSL_PORT, 30)
        assert client.context is not None
        assert client.credentials == ("ifa@example.com", "secret")
        message = client.sent[0]
        assert message["Subject"] == "主题"
        assert message["From"] == "ifa@example.com"
        assert message["To"] == "a@example.com, b@example.com"
        assert _sent_body(message).strip() == "正文"
        assert [part.get_filename() for part in message.iter_attachments()] == ["report.md"]

    def test_starttls_path_when_ssl_disabled(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *a, **k: pytest.fail("use_ssl=False 不应走 SMTPS"))
        config = EmailConfig.from_config(_full_config(smtp_use_ssl="false"))
        assert config is not None

        attached = send_email("主题", "正文", config=config)

        assert attached == 0
        client = FakeSMTP.instances[0]
        assert client.port == DEFAULT_STARTTLS_PORT
        assert client.calls == ["ehlo", "starttls", "ehlo", "login:ifa@example.com", "send_message"]
        assert client.starttls_context is not None

    def test_anonymous_relay_skips_login(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        config = EmailConfig.from_config(
            {"smtp_host": "relay.local", "smtp_recipients": "a@x.com", "smtp_sender": "b@x.com"}
        )
        assert config is not None

        send_email("主题", "正文", config=config)

        assert "login" not in " ".join(FakeSMTP.instances[0].calls)

    def test_missing_attachment_is_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        config = EmailConfig.from_config(_full_config())
        assert config is not None

        attached = send_email("主题", "正文", config=config, attachments=[tmp_path / "nope.md"])

        assert attached == 0
        assert FakeSMTP.instances[0].sent

    def test_html_body_rides_along_as_alternative(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        config = EmailConfig.from_config(_full_config())
        assert config is not None

        send_email("主题", "纯文本摘要", config=config, html_body="<p>HTML 版</p>")

        message = FakeSMTP.instances[0].sent[0]
        assert message.get_content_type() == "multipart/alternative"
        assert "纯文本摘要" in _sent_body(message)
        assert "<p>HTML 版</p>" in _sent_html(message)

    def test_long_body_is_truncated_with_notice(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        config = EmailConfig.from_config(_full_config())
        assert config is not None

        send_email("主题", "x" * (MAX_BODY_CHARS + 10), config=config)

        sent_body = _sent_body(FakeSMTP.instances[0].sent[0])
        assert sent_body.startswith("x" * 100)
        assert "已截断" in sent_body
        assert len(sent_body) < MAX_BODY_CHARS + 200

    def test_auth_failure_is_wrapped(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        FakeSMTP.fail_login = True
        config = EmailConfig.from_config(_full_config())
        assert config is not None

        with pytest.raises(EmailSendError, match="smtp.example.com:465"):
            send_email("主题", "正文", config=config)

    def test_send_failure_is_wrapped(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        FakeSMTP.fail_send = True
        config = EmailConfig.from_config(_full_config())
        assert config is not None

        with pytest.raises(EmailSendError, match="SMTPServerDisconnected"):
            send_email("主题", "正文", config=config)

    def test_connect_failure_is_wrapped(self, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(smtplib, "SMTP_SSL", boom)
        config = EmailConfig.from_config(_full_config())
        assert config is not None

        with pytest.raises(EmailSendError, match="OSError"):
            send_email("主题", "正文", config=config)
