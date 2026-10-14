# ifa/notify/__init__.py
"""通知通道 —— 把分析结果送出 IFA 之外（当前只有 SMTP 邮件）。"""

from ifa.notify.email import (
    EmailConfig,
    EmailConfigError,
    EmailSendError,
    build_daily_report_email,
    parse_recipients,
    send_email,
)

__all__ = [
    "EmailConfig",
    "EmailConfigError",
    "EmailSendError",
    "build_daily_report_email",
    "parse_recipients",
    "send_email",
]
