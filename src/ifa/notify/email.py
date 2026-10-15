# ifa/notify/email.py
"""SMTP 邮件通知 —— 把每日分析报告发到指定邮箱。

设计约束（每条都对应本仓库踩过的坑）:

- **只用标准库**（`smtplib` + `email` + 自写的 `markdown.py`）。发信是运维管道，不该为一个
  通知功能引入第三方依赖，也不该让 wheel 的依赖面变大。
- **配了就必须生效**：SMTP 配置缺项时抛 :class:`EmailConfigError` 并列出缺了哪几项，
  而不是静默跳过发信 —— 「tushare 配了却被静默回退到 akshare」是同一种病。
- **密码优先走环境变量** `IFA_SMTP_PASSWORD`，避免明文落进 `config.json`。
- **正文同时带 text/plain 与 text/html 两个版本**（`multipart/alternative`）：邮件客户端不渲染
  Markdown，HTML 版因此由 :mod:`ifa.notify.markdown` 现场渲染（报告本身就是 Markdown），
  纯文本版是可读的等宽摘要（`_render_table` 按显示宽度补空格，CJK 全角算 2 列）——
  任何客户端都能读到内容，附件仍是唯一权威版本。
- **报告全文进不进正文由体积决定**：HTML 正文超过 :data:`MAX_BODY_CHARS` 时显式省略全文并指向
  `.md` 附件 —— 省略必须写出来，不能让收件人以为报告只有摘要。
- **附件缺失不影响正文**：附件文件读不到只记 warning，不中断发信。

为什么 HTML 自己渲染而不引入 `markdown`：见 :mod:`ifa.notify.markdown` 顶部说明（依赖面 +
`tests/test_dependency_declarations.py` 门禁 + requirements.lock 的一致性要求）。
"""

from __future__ import annotations

import html
import logging
import math
import re
import smtplib
import ssl
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .markdown import render_markdown

logger = logging.getLogger(__name__)

#: 正文上限（字符）。QQ/163 等对单封邮件体积有限制，超长时只截断正文并显式标注，
#: 完整内容始终在 .md 附件里 —— 宁可截断，也不让整封邮件被服务器拒收。
MAX_BODY_CHARS = 120_000

DEFAULT_SSL_PORT = 465
DEFAULT_STARTTLS_PORT = 587
DEFAULT_SMTP_TIMEOUT = 30

#: 配置键 → 环境变量名。错误信息里同时给出两条路，用户才知道怎么补。
_ENV_BY_KEY: dict[str, str] = {
    "smtp_host": "IFA_SMTP_HOST",
    "smtp_port": "IFA_SMTP_PORT",
    "smtp_user": "IFA_SMTP_USER",
    "smtp_password": "IFA_SMTP_PASSWORD",
    "smtp_sender": "IFA_SMTP_SENDER",
    "smtp_recipients": "IFA_EMAIL_TO",
    "smtp_use_ssl": "IFA_SMTP_USE_SSL",
    "smtp_timeout": "IFA_SMTP_TIMEOUT",
}


#: 判断「是否配过邮件」只看这几个键 —— smtp_port / smtp_use_ssl / smtp_timeout 都有默认值，
#: 若把它们也算作配置证据，没配过的用户会被判成「配了一半」而收到误导性的缺项报错。
_IDENTITY_KEYS: tuple[str, ...] = ("smtp_host", "smtp_user", "smtp_password", "smtp_sender", "smtp_recipients")


class EmailConfigError(ValueError):
    """SMTP 配置缺失或非法 —— 绝不静默跳过发信。"""


class EmailSendError(RuntimeError):
    """SMTP 连接 / 认证 / 投递失败。"""


def _is_set(value: Any) -> bool:
    """判断配置值是否算「已填写」（None / 空串 / 空列表都算没填）。"""
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)):
        return any(str(item).strip() for item in value)
    return bool(str(value).strip())


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise EmailConfigError(f"smtp_use_ssl 需要布尔值（true/false），收到 {value!r}")


def parse_recipients(raw: Any) -> tuple[str, ...]:
    """解析收件人列表：支持字符串（逗号/分号/空白分隔）与序列。"""
    if raw is None:
        return ()
    if isinstance(raw, str):
        items = re.split(r"[,;\s]+", raw)
    elif isinstance(raw, Iterable):
        items = [str(item) for item in raw]
    else:
        items = [str(raw)]
    return tuple(item.strip() for item in items if item.strip())


@dataclass(frozen=True)
class EmailConfig:
    """一封邮件需要的全部连接信息。

    密码只在内存中流转：不写日志、不进异常信息。
    """

    host: str
    recipients: tuple[str, ...]
    sender: str
    user: str | None = None
    password: str | None = None
    port: int | None = None
    use_ssl: bool = True
    timeout: int = DEFAULT_SMTP_TIMEOUT

    @property
    def resolved_port(self) -> int:
        """显式端口优先；否则按加密方式推导（465 SSL / 587 STARTTLS）。"""
        if self.port:
            return self.port
        return DEFAULT_SSL_PORT if self.use_ssl else DEFAULT_STARTTLS_PORT

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> EmailConfig | None:
        """从运行时配置构建。

        返回 None 表示**完全没配**（调用方可以安静跳过）；只要配了一部分就必须能凑齐，
        否则抛 :class:`EmailConfigError` 并列出缺项。
        """
        raw = {key: config.get(key) for key in _ENV_BY_KEY}
        if not any(_is_set(raw.get(key)) for key in _IDENTITY_KEYS):
            return None

        host = str(raw.get("smtp_host") or "").strip()
        recipients = parse_recipients(raw.get("smtp_recipients"))
        user = str(raw.get("smtp_user") or "").strip() or None
        sender = str(raw.get("smtp_sender") or "").strip() or user
        password_raw = raw.get("smtp_password")
        password = str(password_raw).strip() if _is_set(password_raw) else None

        missing: list[str] = []
        if not host:
            missing.append("smtp_host")
        if not recipients:
            missing.append("smtp_recipients")
        if not sender:
            missing.append("smtp_sender")
        # 给了用户名却没给密码几乎必然是漏配（QQ/163 用的是授权码，不是登录密码）
        if user and not password:
            missing.append("smtp_password")
        if missing:
            raise EmailConfigError(
                "邮件通知配置不完整，缺少: "
                + ", ".join(missing)
                + "。用 `ifa config <key> <value>` 写入用户配置，或设置环境变量 "
                + "、".join(_ENV_BY_KEY[key] for key in missing)
                + "（详见 README「每日邮件报告」）。"
            )

        # missing 检查已保证 sender 非空，这里收窄类型（mypy: str | None → str）
        sender = sender or ""

        try:
            port_raw = raw.get("smtp_port")
            port = int(str(port_raw).strip()) if _is_set(port_raw) else None
            timeout_raw = raw.get("smtp_timeout")
            timeout = int(str(timeout_raw).strip()) if _is_set(timeout_raw) else DEFAULT_SMTP_TIMEOUT
        except ValueError as exc:
            raise EmailConfigError(f"smtp_port / smtp_timeout 必须是整数: {exc}") from exc

        use_ssl_raw = raw.get("smtp_use_ssl")
        use_ssl = True if use_ssl_raw is None else _as_bool(use_ssl_raw)

        return cls(
            host=host,
            recipients=recipients,
            sender=sender,
            user=user,
            password=password,
            port=port,
            use_ssl=use_ssl,
            timeout=timeout,
        )


def _format_number(value: Any, suffix: str = "") -> str:
    """格式化估值数字，None/NaN 返回 '-'。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    try:
        return f"{float(value):.2f}{suffix}"
    except (TypeError, ValueError):
        return "-"


def _format_erp(value: Any) -> str:
    """ERP 带符号显示（正值加 +）。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"+{number:.2f}%" if number >= 0 else f"{number:.2f}%"


def _display_width(text: str) -> int:
    """估算等宽字体下的显示宽度（CJK 全角字符占 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """纯文本表格（不带 Rich 标记 —— 邮件里没人解析 markup）。"""
    widths = [_display_width(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], _display_width(cell))

    lines = ["  ".join(_pad(header, widths[index]) for index, header in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend("  ".join(_pad(cell, widths[index]) for index, cell in enumerate(row)) for row in rows)
    return "\n".join(lines)


def _short_date(value: Any) -> str:
    """2026-10-13 → 10-13（年份已经写在标题里）。"""
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[5:10]
    return text or "-"


def _format_nav(value: Any, nav_date: Any) -> str:
    """基金净值保留 4 位小数，并带上净值日期 —— 净值是哪天的必须写清楚。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    date_text = _short_date(nav_date)
    return f"{number:.4f}（{date_text}）" if date_text != "-" else f"{number:.4f}"


def _format_change(value: Any) -> str:
    """日涨跌幅带符号；缺失显示 '-'。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:+.2f}%"


def _fund_info_rows(
    results: Sequence[Mapping[str, Any]],
    fund_snapshots: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[list[str]]]:
    """核心参数表的表头与数据行（纯文本 / HTML 两个渲染器共用同一份数据）。"""
    headers = ["基金代码", "基金名称", "净值(日期)", "日涨跌", "评级", "置信度", "耗时", "状态"]
    rows: list[list[str]] = []
    for result in results:
        code = str(result.get("fund_code", ""))
        snapshot = fund_snapshots.get(code) or {}
        rows.append(
            [
                code,
                str(snapshot.get("name") or "-"),
                _format_nav(snapshot.get("nav"), snapshot.get("nav_date")),
                _format_change(snapshot.get("change_pct")),
                str(result.get("rating", "N/A")),
                str(result.get("confidence", "N/A")),
                f"{float(result.get('elapsed') or 0):.1f}s",
                "失败" if result.get("error") else "成功",
            ]
        )
    return headers, rows


def _fund_info_table(
    results: Sequence[Mapping[str, Any]],
    fund_snapshots: Mapping[str, Mapping[str, Any]],
) -> str:
    """核心参数表（纯文本）：名称 / 净值(日期) / 日涨跌 + 评级 / 置信度 / 耗时 / 状态。"""
    headers, rows = _fund_info_rows(results, fund_snapshots)
    return _render_table(headers, rows)


def _valuation_rows(
    results: Sequence[Mapping[str, Any]],
    fund_metrics: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[list[str]]] | None:
    """指数估值表的表头与数据行；认不出跟踪指数的基金整行跳过 —— 不猜指数，免得张冠李戴。"""
    rows: list[list[str]] = []
    for result in results:
        code = str(result.get("fund_code", ""))
        metrics = fund_metrics.get(code) or {}
        index_name = str(metrics.get("index_name") or "").strip()
        if not index_name:
            continue
        rows.append(
            [
                code,
                index_name,
                str(metrics.get("date") or "-"),
                _format_number(metrics.get("pe_ttm")),
                _format_number(metrics.get("pb")),
                _format_number(metrics.get("roe"), "%"),
                _format_number(metrics.get("dividend_yield"), "%"),
                _format_erp(metrics.get("erp")),
            ]
        )
    if not rows:
        return None
    headers = ["基金代码", "跟踪指数", "数据日期", "PE(TTM)", "PB", "ROE", "股息率", "ERP"]
    return headers, rows


def _valuation_table(
    results: Sequence[Mapping[str, Any]],
    fund_metrics: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """指数估值表（纯文本）；没有可展示的行时返回 None（调用方据此整节省略）。"""
    data = _valuation_rows(results, fund_metrics)
    if data is None:
        return None
    headers, rows = data
    return _render_table(headers, rows)


def _valuation_anchor_note(
    results: Sequence[Mapping[str, Any]],
    fund_metrics: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """标注哪些基金本次没有估值锚（PE/PB 都取不到）—— 评级里没有估值百分位信息。

    没有估值锚与「认不出跟踪指数」是两件事，分开列：前者是数据源没覆盖，后者是识别失败。
    全部基金都有估值锚时返回 None（调用方据此不输出这一行）。
    """
    no_anchor: list[str] = []
    unknown_index: list[str] = []
    with_anchor = 0
    for result in results:
        code = str(result.get("fund_code", ""))
        metrics = fund_metrics.get(code) or {}
        index_name = str(metrics.get("index_name") or "").strip()
        if not index_name:
            unknown_index.append(code)
        elif metrics.get("pe_ttm") is None and metrics.get("pb") is None:
            no_anchor.append(f"{code}({index_name})")
        else:
            with_anchor += 1

    if not no_anchor and not unknown_index:
        return None

    parts = [f"估值锚: {with_anchor} 只基金有 PE/PB 数据。"]
    if no_anchor:
        parts.append("无估值锚: " + "、".join(no_anchor) + "（数据源未覆盖该指数，本次评级未使用估值百分位）。")
    if unknown_index:
        parts.append("未识别跟踪指数: " + "、".join(unknown_index) + "（未参与估值判断）。")
    return " ".join(parts)


_FONT_STACK = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,"
    "'PingFang SC','Microsoft YaHei',sans-serif"
)


def _html_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """HTML 表格：老式 border/cellpadding 属性 + 内联样式，邮件客户端普遍支持。"""

    def cell(tag: str, text: str) -> str:
        styles = "padding:6px 8px;text-align:left" + (";background:#f2f2f2" if tag == "th" else "")
        return f'<{tag} style="{styles}">{html.escape(str(text))}</{tag}>'

    head = "".join(cell("th", header) for header in headers)
    body = "".join("<tr>" + "".join(cell("td", value) for value in row) + "</tr>" for row in rows)
    return (
        '<table border="1" cellspacing="0" cellpadding="6" '
        'style="border-collapse:collapse;font-size:13px;margin:8px 0">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def _reports_html(results: Sequence[Mapping[str, Any]]) -> str:
    """把每只基金的报告全文渲染成 HTML（`report` 字段本身就是 Markdown）。"""
    blocks: list[str] = []
    for result in results:
        report = str(result.get("report") or "").strip()
        if not report:
            continue
        code = html.escape(str(result.get("fund_code") or ""))
        blocks.append(f"<h3>{code} 报告全文</h3>")
        blocks.append(render_markdown(report))
    return "".join(blocks)


def _build_html_body(
    *,
    analysis_date: str,
    results: Sequence[Mapping[str, Any]],
    fund_metrics: Mapping[str, Mapping[str, Any]],
    fund_snapshots: Mapping[str, Mapping[str, Any]],
    mode: str,
    generated_at: str,
    success: int,
    total_seconds: float,
) -> str:
    """HTML 正文：摘要表 + （放得下时）渲染后的报告全文。

    全文是否进正文只由体积决定，且省略时会在正文里写明 —— 静默省略会让人以为报告只有摘要。
    """
    parts: list[str] = [
        f'<div style="font-family:{_FONT_STACK};font-size:14px;color:#222;line-height:1.6">',
        f'<h2 style="margin:0 0 6px">IFA 每日基金分析报告 — {html.escape(analysis_date)}</h2>',
        '<p style="margin:0;color:#555">'
        f"分析模式: {html.escape(mode)} &nbsp;|&nbsp; 生成时间: {html.escape(generated_at)}</p>",
        '<p style="margin:4px 0 12px;color:#555">'
        f"基金数量: {len(results)} &nbsp; 成功: {success} &nbsp; 失败: {len(results) - success} "
        f"&nbsp; 总耗时: {total_seconds:.1f}s</p>",
        "<h3>核心参数</h3>",
        _html_table(*_fund_info_rows(results, fund_snapshots)),
    ]

    valuation = _valuation_rows(results, fund_metrics)
    if valuation is not None:
        parts += [
            "<h3>指数估值</h3>",
            _html_table(*valuation),
            '<p style="color:#777;font-size:12px">'
            "注: 股息率为该指数自身股息率（中证指数官方指标，总股本口径）；'-' 表示该指数暂无数据。</p>",
        ]
        anchor_note = _valuation_anchor_note(results, fund_metrics)
        if anchor_note:
            parts.append(f'<p style="color:#777;font-size:12px">{html.escape(anchor_note)}</p>')

    failures = [result for result in results if result.get("error")]
    if failures:
        items = "".join(
            f"<li>{html.escape(str(result.get('fund_code')))}: {html.escape(str(result.get('error')))}</li>"
            for result in failures
        )
        parts.append(f"<h3>失败明细</h3><ul>{items}</ul>")

    reports = _reports_html(results)
    if reports:
        if sum(len(part) for part in parts) + len(reports) <= MAX_BODY_CHARS:
            parts += ["<h3>报告全文</h3>", reports]
        else:
            parts.append(
                '<p style="color:#777;font-size:12px">'
                f"报告全文超过正文上限（{MAX_BODY_CHARS} 字符），已省略；完整内容见 .md 附件。</p>"
            )

    parts.append(
        '<hr style="border:none;border-top:1px solid #ddd;margin:16px 0">'
        f'<p style="color:#777;font-size:12px">本邮件由 IFA 自动生成（模式: {html.escape(mode)}）。'
        "完整报告（含【智识诚实声明】与全部数据）见 .md 附件；评级与置信度由多 Agent 辩论生成，"
        "不构成投资建议。</p></div>"
    )
    return "\n".join(parts)


def build_daily_report_email(
    *,
    analysis_date: str,
    results: Sequence[Mapping[str, Any]],
    fund_metrics: Mapping[str, Mapping[str, Any]] | None = None,
    fund_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    mode: str = "deep",
    generated_at: str | None = None,
) -> tuple[str, str, str, list[Path]]:
    """组装每日报告邮件，返回 (主题, 纯文本正文, HTML 正文, 附件路径列表)。

    results 的每一项形如
    `{"fund_code", "rating", "confidence", "elapsed", "error", "report_path", "report"}`，
    与 `scripts/daily_analysis.py` 的结果字典一致。两个正文版本都含摘要表与失败明细，
    区别是 HTML 版还会把 `report` 里的 Markdown 现场渲染成 HTML（体积超上限时显式省略并
    指向附件）；`report_path` 指定的 `.md` 文件始终是唯一权威版本。

    fund_snapshots 形如 `{fund_code: {"name", "nav", "nav_date", "change_pct"}}`；
    fund_metrics 形如 `{fund_code: {"index_name", "date", "pe_ttm", "pb", "roe",
    "dividend_yield", "erp"}}`，其中 dividend_yield 为该指数自身股息率（中证指数官方）。
    两者缺失时正文相应退化为「-」或整节省略；PE/PB 都取不到的基金会额外标注「无估值锚」。
    """
    metrics = fund_metrics or {}
    snapshots = fund_snapshots or {}
    generated_at = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success = sum(1 for result in results if not result.get("error"))
    total_seconds = sum(float(result.get("elapsed") or 0) for result in results)

    subject = f"[IFA] {analysis_date} 基金分析报告（{len(results)} 只 / 成功 {success}）"

    parts: list[str] = [
        f"IFA 每日基金分析报告 — {analysis_date}",
        f"分析模式: {mode}    生成时间: {generated_at}",
        f"基金数量: {len(results)}    成功: {success}    失败: {len(results) - success}    总耗时: {total_seconds:.1f}s",
        "",
        "== 核心参数 ==",
        _fund_info_table(results, snapshots),
    ]

    valuation = _valuation_table(results, metrics)
    if valuation:
        parts += [
            "",
            "== 指数估值 ==",
            valuation,
            "注: 股息率为该指数自身股息率（中证指数官方指标，总股本口径）；'-' 表示该指数暂无数据。",
        ]
        anchor_note = _valuation_anchor_note(results, metrics)
        if anchor_note:
            parts.append(anchor_note)

    failures = [result for result in results if result.get("error")]
    if failures:
        parts += ["", "== 失败明细 =="]
        parts.extend(f"- {result.get('fund_code')}: {result.get('error')}" for result in failures)

    attachments = [Path(str(result["report_path"])) for result in results if result.get("report_path")]

    parts += [
        "",
        "--",
        f"本邮件由 IFA 自动生成（模式: {mode}）。正文为盘后摘要，完整报告（含【智识诚实声明】"
        "与全部数据）见 .md 附件；评级与置信度由多 Agent 辩论生成，不构成投资建议。",
    ]

    text_body = "\n".join(parts)
    html_body = _build_html_body(
        analysis_date=analysis_date,
        results=results,
        fund_metrics=metrics,
        fund_snapshots=snapshots,
        mode=mode,
        generated_at=generated_at,
        success=success,
        total_seconds=total_seconds,
    )
    return subject, text_body, html_body, attachments


def _build_message(
    subject: str,
    body: str,
    config: EmailConfig,
    attachments: Iterable[str | Path],
    html_body: str | None = None,
) -> tuple[EmailMessage, int]:
    """构造 EmailMessage，返回 (消息, 实际附上的附件数)。

    `html_body` 非空时用 multipart/alternative 带上 HTML 版本（纯文本必须在前，客户端挑它能
    渲染的那一个）。附件最后追加，EmailMessage 会自动把结构升级成 multipart/mixed。
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)

    text = body
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS] + f"\n\n…（正文超过 {MAX_BODY_CHARS} 字符已截断；完整内容见 .md 附件）"
    message.set_content(text)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    attached = 0
    for item in attachments:
        path = Path(item)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            logger.warning("附件 %s 读取失败，跳过（不影响正文）: %s", path, exc)
            continue
        message.add_attachment(payload, maintype="text", subtype="markdown", filename=path.name)
        attached += 1
    return message, attached


def send_email(
    subject: str,
    body: str,
    *,
    config: EmailConfig,
    attachments: Iterable[str | Path] = (),
    html_body: str | None = None,
) -> int:
    """发送邮件，返回实际附上的附件数；失败抛 :class:`EmailSendError`。

    `body` 是纯文本版本，`html_body` 是可选的 HTML 版本，两者一起构成 multipart/alternative。
    `use_ssl=True` 走 SMTPS（默认 465），否则走 STARTTLS（默认 587）。
    """
    message, attached = _build_message(subject, body, config, attachments, html_body)
    port = config.resolved_port

    try:
        if config.use_ssl:
            with smtplib.SMTP_SSL(
                config.host, port, timeout=config.timeout, context=ssl.create_default_context()
            ) as client:
                _login_if_needed(client, config)
                client.send_message(message)
        else:
            with smtplib.SMTP(config.host, port, timeout=config.timeout) as client:
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
                _login_if_needed(client, config)
                client.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailSendError(f"发送邮件到 {config.host}:{port} 失败（{type(exc).__name__}: {exc}）") from exc

    logger.info("邮件已发送至 %s（附件 %d 个）", ", ".join(config.recipients), attached)
    return attached


def _login_if_needed(client: smtplib.SMTP, config: EmailConfig) -> None:
    """有用户名才登录（内部中继可能允许匿名投递）。"""
    if config.user and config.password:
        client.login(config.user, config.password)
