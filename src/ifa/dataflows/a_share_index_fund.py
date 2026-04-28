# ifa/dataflows/a_share_index_fund.py
"""ETF、指数、场外指数基金的数据获取实现（基于 AkShare）。"""

from __future__ import annotations

import akshare as ak
import pandas as pd

from .a_share import (
    _call_akshare_api,
    _format_data_error,
    _format_table,
    _round_numeric_frame,
)
from .a_share_common import (
    format_date_for_api,
    safe_display_symbol,
    safe_plain_code,
)

# ── ETF 行情数据 ─────────────────────────────────────────────


def get_etf_data(symbol: str, start_date: str, end_date: str) -> str:
    """
    获取 ETF 基金历史日线行情数据。

    参数：
        symbol: ETF 代码（如 510300）。
        start_date: 起始日期，格式 YYYY-MM-DD。
        end_date: 结束日期，格式 YYYY-MM-DD。

    返回：
        str: CSV 格式的 OHLCV 行情数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_etf_hist_em,
            symbol=plain,
            period="daily",
            start_date=format_date_for_api(start_date),
            end_date=format_date_for_api(end_date),
            adjust="qfq",
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(
            f"# ETF price data for {display} from {start_date} to {end_date}",
            exc,
        )

    if df is None or df.empty:
        return f"未找到 {display} 在 {start_date} 到 {end_date} 之间的 ETF 行情数据。"

    col_map = {
        "日期": "Date",
        "开盘": "Open",
        "最高": "High",
        "最低": "Low",
        "收盘": "Close",
        "成交量": "Volume",
        "成交额": "Amount",
        "涨跌幅": "PctChange",
        "换手率": "TurnoverPct",
    }
    renamed = df.rename(columns=col_map).copy()
    if "Date" in renamed.columns:
        renamed["Date"] = pd.to_datetime(renamed["Date"]).dt.strftime("%Y-%m-%d")
    if "PctChange" not in renamed.columns and "Close" in renamed.columns:
        renamed["PctChange"] = renamed["Close"].pct_change().mul(100).round(4)

    selected_columns = [
        col
        for col in ["Date", "Open", "High", "Low", "Close", "Volume", "Amount", "PctChange", "TurnoverPct"]
        if col in renamed.columns
    ]
    output = _round_numeric_frame(renamed.loc[:, selected_columns])
    header = f"# ETF price data for {display} from {start_date} to {end_date}\n"
    header += f"# Records: {len(output)}\n\n"
    return header + output.to_csv(index=False)


# ── 指数行情数据 ─────────────────────────────────────────────


def get_index_data(symbol: str, start_date: str, end_date: str) -> str:
    """
    获取股票指数历史日线行情数据。

    参数：
        symbol: 指数代码（如 000300）。
        start_date: 起始日期，格式 YYYY-MM-DD。
        end_date: 结束日期，格式 YYYY-MM-DD。

    返回：
        str: CSV 格式的行情数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.index_zh_a_hist,
            symbol=plain,
            period="daily",
            start_date=format_date_for_api(start_date),
            end_date=format_date_for_api(end_date),
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(
            f"# Index data for {display} from {start_date} to {end_date}",
            exc,
        )

    if df is None or df.empty:
        return f"未找到 {display} 在 {start_date} 到 {end_date} 之间的指数行情数据。"

    col_map = {
        "日期": "Date",
        "开盘": "Open",
        "最高": "High",
        "最低": "Low",
        "收盘": "Close",
        "成交量": "Volume",
        "成交额": "Amount",
        "涨跌幅": "PctChange",
    }
    renamed = df.rename(columns=col_map).copy()
    if "Date" in renamed.columns:
        renamed["Date"] = pd.to_datetime(renamed["Date"]).dt.strftime("%Y-%m-%d")

    selected_columns = [
        col
        for col in ["Date", "Open", "High", "Low", "Close", "Volume", "Amount", "PctChange"]
        if col in renamed.columns
    ]
    output = _round_numeric_frame(renamed.loc[:, selected_columns])
    header = f"# Index data for {display} from {start_date} to {end_date}\n"
    header += f"# Records: {len(output)}\n\n"
    return header + output.to_csv(index=False)


# ── ETF 基金基本信息 ─────────────────────────────────────────


def get_etf_fund_info(symbol: str) -> str:
    """
    获取 ETF 基金基本信息，包括规模、费率、跟踪指数等。

    参数：
        symbol: ETF 代码（如 510300）。

    返回：
        str: 基金基本信息文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_etf_fund_info_em,
            fund=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# ETF fund info for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的 ETF 基金信息。"

    return f"# ETF Fund Info for {display}\n\n{df.to_csv(index=False)}"


# ── 指数成分股 ───────────────────────────────────────────────


def get_index_constituents(symbol: str) -> str:
    """
    获取指数的成分股列表及权重信息。

    参数：
        symbol: 指数代码（如 000300）。

    返回：
        str: 成分股列表文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.index_stock_cons_csindex,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Index constituents for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的成分股数据。"

    result = _format_table(df, f"# Index Constituents for {display}", rows=60)
    return result


# ── 场外基金净值 ─────────────────────────────────────────────


def get_fund_nav(symbol: str) -> str:
    """
    获取场外指数基金（联接基金/LOF）的历史净值数据。

    参数：
        symbol: 基金代码（如 160119、012414）。

    返回：
        str: 历史净值数据文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_open_fund_info_em,
            symbol=plain,
            indicator="单位净值走势",
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund NAV for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的基金净值数据。"

    # 只取最近 60 个交易日
    recent = df.tail(60)
    return _format_table(recent, f"# Fund NAV History for {display}")
