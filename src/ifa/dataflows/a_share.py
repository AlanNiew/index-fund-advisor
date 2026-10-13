"""
A 股数据获取基础设施层。

提供 AkShare 接口调用的通用工具：代理绕过、自动重试、进度条抑制、
表格格式化、数值四舍五入、异常文本化等。具体的 ETF/指数基金、场外基金
数据获取函数分别在 a_share_index_fund.py 和 a_share_public_fund.py 中。
"""

from __future__ import annotations

import time
from contextlib import contextmanager

import pandas as pd

from .a_share_common import is_retryable_akshare_error, no_proxy

# ---------------------------------------------------------------------------
#  通用工具函数（基础设施层）
# ---------------------------------------------------------------------------


@contextmanager
def _temporary_string_storage(storage: str):
    """
    临时切换 pandas 字符串存储模式，并在退出后恢复原配置。

    参数：
        storage: 临时使用的字符串存储模式。

    返回：
        None: 无返回值。
    """
    original = pd.get_option("mode.string_storage")
    pd.set_option("mode.string_storage", storage)
    try:
        yield
    finally:
        pd.set_option("mode.string_storage", original)


def _format_table(df: pd.DataFrame, title: str, rows: int = 10) -> str:
    """
    格式化表格输出。自动清洗数据后再展示。

    参数：
        df: 需要格式化、筛选或转换的数据表。
        title: 表格标题。
        rows: 格式化输出中保留的最大行数。

    返回：
        str: 格式化后的字符串结果。
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return f"{title}\n\n暂无数据。"

    from .data_cleaning import clean_dataframe

    df = clean_dataframe(df, context=title)
    if df.empty:
        return f"{title}\n\n暂无数据（清洗后为空）。"

    return f"{title}\n\n{df.head(rows).to_csv(index=False)}"


def _format_key_value(row: pd.Series, title: str) -> str:
    """
    把单行数据渲染成「字段/值」两列文本。

    场内 ETF 的行情表是「1 行 × 十几列」的宽表，整行输出宽 CSV 对 LLM 不友好，
    转置成纵向两列更易读（与 _format_table 的横向多行表格互补）。

    参数：
        row: 待渲染的单行数据。
        title: 输出标题。

    返回：
        str: 格式化后的字符串结果。
    """
    if row is None or len(row) == 0:
        return f"{title}\n\n暂无数据。"

    pairs = [(str(col), row[col]) for col in row.index]
    frame = pd.DataFrame(pairs, columns=["字段", "值"])
    return f"{title}\n\n{frame.to_csv(index=False)}"


def _round_numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    对数值型数据表执行四舍五入。

    参数：
        df: 需要格式化、筛选或转换的数据表。

    返回：
        pd.DataFrame: 处理后的数据表。
    """
    rounded = df.copy()
    for column in rounded.columns:
        if pd.api.types.is_numeric_dtype(rounded[column]):
            rounded[column] = rounded[column].round(4)
    return rounded


def _safe_truncate(text: str, limit: int = 160) -> str:
    """
    安全截断文本。

    参数：
        text: 需要截断或处理的输入文本。
        limit: 结果中允许保留的最大长度。

    返回：
        str: 安全处理后的字符串结果。
    """
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def _call_akshare_api(func, *args, retries: int = 3, retry_delay: float = 1.0, **kwargs):
    """
    调用 AkShare 接口，并对网络抖动执行有限次重试。
    请求期间临时绕过系统代理，避免代理不通导致失败。

    参数：
        func: 需要执行的 AkShare 函数。
        args: 传给 AkShare 函数的位置参数。
        retries: 最大重试次数。
        retry_delay: 首次重试前的等待秒数，后续按次数递增。
        kwargs: 传给 AkShare 函数的关键字参数。

    返回：
        Any: AkShare 原始返回结果。
    """
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with no_proxy():
                return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries or not is_retryable_akshare_error(exc):
                raise
            time.sleep(retry_delay * attempt)
    # retries <= 0 时循环体从未执行，last_exc 仍为 None——
    # 直接 raise None 会抛 TypeError，这里给出明确错误
    raise RuntimeError(f"AkShare 调用失败：retries={retries} 未执行任何重试尝试") from last_exc


# 数据源失败的统一标记。接口层（CLI / REST / MCP）据此把「取数失败」与「查无结果」
# 区分开：前者必须上报为非零退出码 / 错误响应，而不是被当成空结果安静返回。
DATA_SOURCE_ERROR_MARKER = "数据源访问失败："


def _format_data_error(title: str, exc: Exception) -> str:
    """
    将外部数据源异常转换为可读文本，避免工具节点直接崩溃。

    参数：
        title: 当前数据块标题。
        exc: 原始异常对象。

    返回：
        str: 适合直接返回给上层代理的错误说明。
    """
    return f"{title}\n\n{DATA_SOURCE_ERROR_MARKER}{type(exc).__name__}: {_safe_truncate(str(exc), 220)}"
