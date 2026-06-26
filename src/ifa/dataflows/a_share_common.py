from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from functools import lru_cache

import akshare as ak
import pandas as pd

_tls = threading.local()
_TLS_KEY = "no_proxy_active"
_patch_lock = threading.Lock()
_patched = False


def _ensure_proxy_patch() -> None:
    """一次性永久 patch requests.utils.get_environ_proxies。

    patch 后的函数读取线程局部标记：标记活跃时返回空代理（绕过系统代理），
    标记不活跃时走原始逻辑。永久 patch 不涉及进入/退出竞态，
    线程局部标记保证多线程隔离。
    """
    global _patched
    if _patched:
        return
    with _patch_lock:
        if _patched:
            return
        import requests.utils  # type: ignore[import-untyped]

        _original_get_environ_proxies = requests.utils.get_environ_proxies

        def _patched_get_environ_proxies(*args, **kwargs):
            if getattr(_tls, _TLS_KEY, False):
                return {}
            return _original_get_environ_proxies(*args, **kwargs)

        requests.utils.get_environ_proxies = _patched_get_environ_proxies
        _patched = True


@contextmanager
def no_proxy():
    """
    临时绕过系统代理，避免代理干扰 AkShare 请求。

    通过一次性永久 patch ``requests.utils.get_environ_proxies`` + 线程局部标记实现，
    不修改全局 ``os.environ``，不修改全局 ``requests.Session.__init__``，
    线程安全且支持并发。
    """
    _ensure_proxy_patch()
    old_active = getattr(_tls, _TLS_KEY, False)
    setattr(_tls, _TLS_KEY, True)
    try:
        yield
    finally:
        setattr(_tls, _TLS_KEY, old_active)


SH_PREFIXES = (
    "500",
    "501",
    "510",
    "511",
    "512",
    "513",
    "514",
    "515",
    "516",
    "517",
    "518",
    "519",
    "560",
    "561",
    "562",
    "563",
    "588",
    "600",
    "601",
    "603",
    "605",
    "688",
    "689",
)
SZ_PREFIXES = (
    "000",
    "001",
    "002",
    "003",
    "159",
    "150",
    "151",
    "160",
    "161",
    "162",
    "163",
    "164",
    "165",
    "166",
    "167",
    "168",
    "169",
    "300",
    "301",
    "399",
)
BJ_PREFIXES = (
    "430",
    "431",
    "832",
    "833",
    "834",
    "835",
    "836",
    "837",
    "838",
    "839",
    "870",
    "871",
    "872",
    "873",
    "874",
    "875",
    "876",
    "877",
    "878",
    "879",
    "920",
)


def _infer_exchange(code: str) -> str:
    """
    推断股票所属交易所。

    参数：
        code: 证券代码。

    返回：
        str: 函数执行结果。
    """
    if code.startswith(SH_PREFIXES):
        return "SH"
    if code.startswith(SZ_PREFIXES):
        return "SZ"
    if code.startswith(BJ_PREFIXES):
        return "BJ"
    raise ValueError(f"Unsupported A-share symbol '{code}'. Expected a 6-digit Shanghai, Shenzhen, or Beijing code.")


def normalize_ashare_symbol(symbol: str) -> str:
    """
    将用户输入规范化为 ``000001.SZ``、``600519.SH`` 或 ``430047.BJ``。

    参数：
        symbol: 待分析标的的 A 股股票代码。

    返回：
        str: 规范化后的代码结果。
    """
    normalized = symbol.strip().upper().replace(" ", "")
    if not normalized:
        raise ValueError("Ticker symbol cannot be empty.")

    exchange_prefix_match = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", normalized)
    if exchange_prefix_match:
        exchange, code = exchange_prefix_match.groups()
        return f"{code}.{exchange}"

    exchange_suffix_match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", normalized)
    if exchange_suffix_match:
        code, exchange = exchange_suffix_match.groups()
        return f"{code}.{exchange}"

    digits_match = re.fullmatch(r"\d{6}", normalized)
    if digits_match:
        code = digits_match.group(0)
        return f"{code}.{_infer_exchange(code)}"

    raise ValueError("Unsupported A-share symbol format. Use a 6-digit code such as 600519 or 000001.")


def to_plain_symbol(symbol: str) -> str:
    """
    转换为不带交易所后缀的代码。

    参数：
        symbol: 待分析标的的 A 股股票代码。

    返回：
        str: 转换后的代码结果。
    """
    return normalize_ashare_symbol(symbol).split(".", 1)[0]


def to_exchange_prefixed_symbol(symbol: str) -> str:
    """
    转换为带交易所前缀的代码。

    参数：
        symbol: 待分析标的的 A 股股票代码。

    返回：
        str: 转换后的代码结果。
    """
    code, exchange = normalize_ashare_symbol(symbol).split(".", 1)
    return f"{exchange}{code}"


def safe_plain_code(symbol: str) -> str:
    """
    安全提取 6 位纯数字代码。

    对于标准 A 股/ETF/指数代码使用 normalize + to_plain 流程；
    对于无法规范化的场外基金代码，直接提取 6 位数字。

    参数：
        symbol: 待分析标的的代码。

    返回：
        str: 纯数字代码。
    """
    try:
        return to_plain_symbol(symbol)
    except (ValueError, TypeError):
        match = re.search(r"\d{6}", str(symbol))
        if match:
            return match.group(0)
        return str(symbol).strip()


def safe_display_symbol(symbol: str) -> str:
    """
    安全获取展示用代码。

    优先使用规范化格式（如 ``000001.SZ``），失败则用原始输入。

    参数：
        symbol: 待分析标的的代码。

    返回：
        str: 展示用代码。
    """
    try:
        return normalize_ashare_symbol(symbol)
    except (ValueError, TypeError):
        return str(symbol).strip()


def format_date_for_api(date_str: str) -> str:
    """
    将日期格式化为接口所需格式。

    参数：
        date_str: YYYY-MM-DD 格式的日期字符串。

    返回：
        str: 格式化后的字符串结果。
    """
    return pd.Timestamp(date_str).strftime("%Y%m%d")


@lru_cache(maxsize=1)
def get_trade_calendar() -> tuple[pd.Timestamp, ...]:
    """
    返回交易日历。

    返回：
        tuple[pd.Timestamp, ...]: 交易日时间戳元组。
    """
    trade_dates = ak.tool_trade_date_hist_sina()["trade_date"]
    return tuple(pd.to_datetime(trade_dates, errors="coerce").dropna().sort_values())


@lru_cache(maxsize=1)
def _get_trade_date_set() -> frozenset:
    """缓存交易日历的 frozenset，避免每次调用 is_trade_date 时重建 set。"""
    return frozenset(get_trade_calendar())


def is_trade_date(date_str: str) -> bool:
    """
    判断是否为交易日。

    参数：
        date_str: YYYY-MM-DD 格式的日期字符串。

    返回：
        bool: 条件满足时返回 True，否则返回 False。
    """
    target = pd.Timestamp(date_str).normalize()
    return target in _get_trade_date_set()


def get_previous_trade_date(date_str: str) -> str:
    """
    返回此前最近一个交易日。

    参数：
        date_str: YYYY-MM-DD 格式的日期字符串。

    返回：
        str: 当前查询结果。
    """
    target = pd.Timestamp(date_str).normalize()
    eligible = [trade_date for trade_date in get_trade_calendar() if trade_date <= target]
    if not eligible:
        raise ValueError(f"No A-share trading date found on or before {date_str}.")
    return eligible[-1].strftime("%Y-%m-%d")


def get_date_range(start_date: str, end_date: str) -> list[str]:
    """
    返回日期区间列表。

    参数：
        start_date: 起始日期（含当日），格式为 YYYY-MM-DD。
        end_date: 结束日期（含当日），格式为 YYYY-MM-DD。

    返回：
        list[str]: 当前查询得到的日期列表。
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return [value.strftime("%Y-%m-%d") for value in pd.date_range(start=start, end=end, freq="D")]


def parse_date_column(series: pd.Series) -> pd.Series:
    """
    解析日期列。

    参数：
        series: 包含日期型值的 Pandas Series。

    返回：
        pd.Series: 解析后的序列结果。
    """
    return pd.to_datetime(series, errors="coerce")


@contextmanager
def suppress_akshare_progress():
    """
    临时关闭 AkShare 内部 tqdm 进度条输出。

    返回：
        None: 无返回值。
    """
    import sys

    from akshare.utils import tqdm as ak_tqdm

    replacements = {}

    def silent_get_tqdm(enable=True):
        return lambda iterable, *args, **kwargs: iterable

    replacements[(ak_tqdm, "get_tqdm")] = ak_tqdm.get_tqdm
    ak_tqdm.get_tqdm = silent_get_tqdm

    for module in list(sys.modules.values()):
        module_name = getattr(module, "__name__", "")
        if not module_name.startswith("akshare."):
            continue
        if hasattr(module, "get_tqdm"):
            replacements[(module, "get_tqdm")] = module.get_tqdm
            module.get_tqdm = silent_get_tqdm
    try:
        yield
    finally:
        for (module, attr), original in replacements.items():
            setattr(module, attr, original)


def is_retryable_akshare_error(exc: Exception) -> bool:
    """
    判断异常是否属于可重试的 AkShare 网络错误。

    参数：
        exc: 待判断的异常对象。

    返回：
        bool: 条件满足时返回 True，否则返回 False。
    """
    from http.client import RemoteDisconnected

    import requests

    if isinstance(exc, (requests.exceptions.RequestException, RemoteDisconnected, TimeoutError)):
        return True

    message = str(exc)
    retryable_markers = (
        "Remote end closed connection without response",
        "Connection aborted",
        "Read timed out",
        "ConnectTimeout",
        "Max retries exceeded",
        "temporarily unavailable",
    )
    return any(marker in message for marker in retryable_markers)


def find_column(df, *candidates: str) -> str | None:
    """
    在 DataFrame 列中按候选名称依次查找，返回第一个匹配的列名。

    参数：
        df: Pandas DataFrame。
        candidates: 候选列名（按优先级排列）。

    返回：
        str | None: 匹配到的列名，无匹配时返回 None。
    """
    for col in candidates:
        if col in df.columns:
            return col
    return None
