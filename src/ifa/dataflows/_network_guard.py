"""数据源出站请求的超时保护。

背景：AkShare 大量接口直接 requests.get(url)（不传 timeout），例如
akshare/index/index_cons.py 的 index_stock_cons_csindex。上游建立连接后不再返回任何
字节时，分析流程会被无限期挂住 —— 进程存活、CPU 接近 0、日志不再增长，且
try/except 永远不会触发（实测 oss-ch.csindex.com.cn 的连接挂死 14 分钟）。

为什么不用 socket.setdefaulttimeout：requests 的 HTTPAdapter.send 把 timeout=None 包成
urllib3 的 Timeout(connect=None, read=None)，urllib3 于是显式 sock.settimeout(None)，
把 socket 默认值覆盖掉。实测（本地「黑洞」服务端，accept 后永不响应）：

- socket 默认 4 秒 + requests.get(url)        -> 挂死（14 秒仍未返回）
- socket 默认 4 秒 + 裸 socket.connect         -> 4.3 秒 TimeoutError（默认值只对裸 socket 生效）
- requests.get(url, timeout=3)                -> 3.3 秒 ReadTimeout
- 给 Session.request 注入默认 timeout           -> 3.3 秒 ReadTimeout

（早先看到「黑洞 IP 约 21 秒抛 ConnectTimeout」是 Windows 系统级 TCP 连接超时，不是
socket 默认值生效。）

对策：导入 ifa.dataflows 时把 requests.sessions.Session.request 包一层，只在调用方没有
传 timeout（或显式传 None）时补上 IFA_DATA_SOURCE_TIMEOUT（默认 30 秒）。选
Session.request 而不是 requests.get，是因为所有高层入口（requests.get/post、
Session.get、requests.api.request）最终都落到这里。

不会影响：
- 显式传了 timeout 的调用（原值原样保留，含 timeout=0 与 (connect, read) 元组形式）；
- LLM 客户端（langchain-openai / openai 走 httpx，不经过 requests）；
- 其他库的 socket（不碰 socket 默认值，uvicorn / streamlit 的事件循环不受影响）。

注意：超时的请求仍被 _call_akshare_api 视为可重试（is_retryable_akshare_error 对
RequestException 返回 True），因此单个工具最坏耗时约为 retries 乘以该超时。
"""

import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DATA_SOURCE_TIMEOUT_ENV = "IFA_DATA_SOURCE_TIMEOUT"
DEFAULT_DATA_SOURCE_TIMEOUT = 30.0
_PATCH_MARKER = "_ifa_default_timeout_patch"

_effective_timeout: float = DEFAULT_DATA_SOURCE_TIMEOUT


def resolve_data_source_timeout() -> float:
    """解析数据源超时秒数；未设置或非法时回落到默认值。"""
    raw = os.environ.get(DATA_SOURCE_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_DATA_SOURCE_TIMEOUT
    try:
        timeout = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r 不是合法秒数，使用默认值 %.0f 秒",
            DATA_SOURCE_TIMEOUT_ENV,
            raw,
            DEFAULT_DATA_SOURCE_TIMEOUT,
        )
        return DEFAULT_DATA_SOURCE_TIMEOUT
    if timeout <= 0:
        logger.warning(
            "%s=%r 必须为正数，使用默认值 %.0f 秒",
            DATA_SOURCE_TIMEOUT_ENV,
            raw,
            DEFAULT_DATA_SOURCE_TIMEOUT,
        )
        return DEFAULT_DATA_SOURCE_TIMEOUT
    return timeout


def current_data_source_timeout() -> float:
    """返回当前生效的数据源默认超时秒数（供诊断与测试）。"""
    return _effective_timeout


def install_data_source_timeout(timeout: float | None = None) -> float | None:
    """给未指定 timeout 的 requests 调用补默认超时，返回生效值（幂等）。

    参数：
        timeout: 显式指定的默认超时秒数；为 None 时读 IFA_DATA_SOURCE_TIMEOUT，
            再回落到 DEFAULT_DATA_SOURCE_TIMEOUT。

    返回：
        float | None: 生效的默认超时秒数；requests 不可用时返回 None。

    重复调用只更新默认值，不会叠加包装层（用函数属性做标记判断）。
    """
    global _effective_timeout

    resolved = timeout if timeout is not None else resolve_data_source_timeout()
    try:
        import requests
    except ImportError:  # pragma: no cover - requests 是本项目硬依赖
        logger.warning("未安装 requests，跳过数据源超时保护")
        return None

    session_cls = requests.sessions.Session
    current = session_cls.request
    if not getattr(current, _PATCH_MARKER, False):
        original: Callable[..., Any] = current

        def request_with_default_timeout(self: Any, *args: Any, **kwargs: Any) -> Any:
            if kwargs.get("timeout") is None:
                kwargs["timeout"] = _effective_timeout
            return original(self, *args, **kwargs)

        setattr(request_with_default_timeout, _PATCH_MARKER, True)  # noqa: B010 - 动态标记包装层
        setattr(request_with_default_timeout, "__wrapped__", original)  # noqa: B010 - 便于排查与测试
        session_cls.request = request_with_default_timeout  # type: ignore[method-assign]

    _effective_timeout = resolved
    return resolved
