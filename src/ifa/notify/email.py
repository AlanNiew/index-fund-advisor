# ifa/notify/email.py
"""SMTP 邮件通知 —— 把每日分析报告发到指定邮箱。

设计约束（每条都对应本仓库踩过的坑）:

- **只用标准库**（`smtplib` + `email`）。发信是运维管道，不该为一个通知功能引入第三方
  依赖，也不该让 wheel 的依赖面变大。
- **配了就必须生效**：SMTP 配置缺项时抛 :class:`EmailConfigError` 并列出缺了哪几项，
  而不是静默跳过发信 —— 「tushare 配了却被静默回退到 akshare」是同一种病。
- **密码优先走环境变量** `IFA_SMTP_PASSWORD`，避免明文落进 `config.json`。
- **正文与附件同源**：正文放报告全文，同一份报告再作为 `.md` 附件带上；附件文件缺失
  只记 warning，不影响正文送达。

为什么正文用 `text/plain` 而不是 HTML：报告本身就是 Markdown，转 HTML 要么引入
`markdown` 依赖、要么手写一套转义；而 `text/plain` 能让收件人看到与落盘文件逐字一致
的内容（需要排版时打开附件即可）。
"""

from __future__ import annotations

import logging
import math
import re
import smtplib
import ssl
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

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


def _summary_table(
    results: Sequence[Mapping[str, Any]],
    fund_metrics: Mapping[str, Mapping[str, Any]],
) -> str:
    """纯文本汇总表（不带 Rich 标记 —— 邮件里没人解析 markup）。"""
    show_metrics = any(fund_metrics.get(str(result.get("fund_code", ""))) for result in results)
    headers = ["基金代码", "评级", "置信度"]
    if show_metrics:
        headers += ["PE(TTM)", "股息率", "ERP"]
    headers += ["耗时", "状态"]

    rows: list[list[str]] = []
    for result in results:
        metrics = fund_metrics.get(str(result.get("fund_code", ""))) or {}
        row = [
            str(result.get("fund_code", "")),
            str(result.get("rating", "N/A")),
            str(result.get("confidence", "N/A")),
        ]
        if show_metrics:
            row += [
                _format_number(metrics.get("pe_ttm")),
                _format_number(metrics.get("dividend_yield"), "%"),
                _format_erp(metrics.get("erp")),
            ]
        row += [f"{float(result.get('elapsed') or 0):.1f}s", "失败" if result.get("error") else "成功"]
        rows.append(row)

    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row, strict=True)]

    lines = ["  ".join(header.ljust(widths[i]) for i, header in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def build_daily_report_email(
    *,
    analysis_date: str,
    results: Sequence[Mapping[str, Any]],
    fund_metrics: Mapping[str, Mapping[str, Any]] | None = None,
    mode: str = "deep",
    generated_at: str | None = None,
) -> tuple[str, str, list[Path]]:
    """组装每日报告邮件，返回 (主题, 正文, 附件路径列表)。

    results 的每一项形如
    `{"fund_code", "rating", "confidence", "elapsed", "error", "report_path", "report"}`，
    与 `scripts/daily_analysis.py` 的结果字典一致；`report` 为报告全文（进正文），
    `report_path` 为落盘 .md 路径（进附件）。
    """
    metrics = fund_metrics or {}
    generated_at = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success = sum(1 for result in results if not result.get("error"))
    total_seconds = sum(float(result.get("elapsed") or 0) for result in results)

    subject = f"[IFA] {analysis_date} 基金分析报告（{len(results)} 只 / 成功 {success}）"

    parts: list[str] = [
        f"IFA 每日基金分析报告 — {analysis_date}",
        f"分析模式: {mode}    生成时间: {generated_at}",
        f"基金数量: {len(results)}    成功: {success}    失败: {len(results) - success}    总耗时: {total_seconds:.1f}s",
        "",
        "== 评级汇总 ==",
        _summary_table(results, metrics),
        "",
        "== 报告全文 ==",
    ]

    attachments: list[Path] = []
    for result in results:
        code = str(result.get("fund_code", ""))
        report_path = result.get("report_path")
        if report_path:
            attachments.append(Path(str(report_path)))

        parts.append("")
        parts.append(f"---------- {code} ----------")
        report_text = str(result.get("report") or "").strip()
        if report_text:
            parts.append(report_text)
        elif result.get("error"):
            parts.append(f"[分析失败] {result['error']}")
        else:
            parts.append("[本次未产出报告]")

    failures = [result for result in results if result.get("error")]
    if failures:
        parts.append("")
        parts.append("== 失败明细 ==")
        parts.extend(f"- {result.get('fund_code')}: {result.get('error')}" for result in failures)

    parts += [
        "",
        "--",
        f"本邮件由 IFA 自动生成（模式: {mode}）。报告正文含硬注入的【智识诚实声明】，请一并阅读。",
    ]

    return subject, "\n".join(parts), attachments


def _build_message(
    subject: str,
    body: str,
    config: EmailConfig,
    attachments: Iterable[str | Path],
) -> tuple[EmailMessage, int]:
    """构造 EmailMessage，返回 (消息, 实际附上的附件数)。"""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)

    text = body
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS] + f"\n\n…（正文超过 {MAX_BODY_CHARS} 字符已截断；完整内容见 .md 附件）"
    message.set_content(text)

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
) -> int:
    """发送邮件，返回实际附上的附件数；失败抛 :class:`EmailSendError`。

    `use_ssl=True` 走 SMTPS（默认 465），否则走 STARTTLS（默认 587）。
    """
    message, attached = _build_message(subject, body, config, attachments)
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
