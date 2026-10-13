# ifa/dataflows/a_share_index_fund.py
"""ETF、指数、场外指数基金的数据获取实现（基于 AkShare）。"""

from __future__ import annotations

import akshare as ak
import pandas as pd

from .a_share import (
    _call_akshare_api,
    _format_data_error,
    _format_key_value,
    _format_table,
    _round_numeric_frame,
)
from .a_share_common import (
    find_column,
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
    return header + str(output.to_csv(index=False))


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
    return header + str(output.to_csv(index=False))


# ── ETF 基金基本信息 ─────────────────────────────────────────


def _fetch_etf_daily_row(plain: str) -> pd.DataFrame | None:
    """
    从东财「场内基金每日行情」表中取出单只 ETF 的一行。

    场内 ETF 不在蛋卷基金的场外基金库里（fund_individual_basic_info_xq 对 ETF
    会直接 KeyError: 'data'），此表是 ETF 基本信息唯一稳定的来源：约 1700 行、
    单次请求约 1 秒，且能被数据工具缓存层复用。

    参数：
        plain: 6 位 ETF 代码。

    返回：
        pd.DataFrame | None: 单行数据表；查不到时返回 None。
    """
    df = _call_akshare_api(ak.fund_etf_fund_daily_em)
    if df is None or df.empty:
        return None

    code_col = find_column(df, "基金代码", "代码")
    if not code_col:
        return None

    hit = df[df[code_col].astype(str).str.zfill(6) == plain]
    return None if hit.empty else hit.iloc[[0]]


def get_etf_fund_info(symbol: str) -> str:
    """
    获取 ETF 基本信息（简称/类型/单位净值/累计净值/日增长率/市价）。

    注意本数据源的能力边界：ETF 的费率与跟踪指数拿不到——蛋卷基金只覆盖场外
    基金，而上游的 fund_etf_fund_info_em 对场内 ETF 会抛
    "Length mismatch: Expected axis has 14 elements, new values have 13
    elements"（且默认起止日期区间下要跑两分钟才会失败）。

    参数：
        symbol: ETF 代码（如 510300）。

    返回：
        str: 基金基本信息文本（字段/值两列）。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        row = _fetch_etf_daily_row(plain)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# ETF fund info for {display}", exc)

    if row is None:
        return f"未找到 {display} 的 ETF 行情记录：该代码可能不是场内 ETF，或尚未上市交易。"

    return _format_key_value(row.iloc[0], f"# ETF Fund Info for {display}")


# ── 指数成分股 ───────────────────────────────────────────────


def _constituents_source_hint(plain: str, exc: Exception | None = None) -> str:
    """
    生成成分股取数失败时的可操作说明。

    中证成份股文件按「指数代码」寻址：ETF 代码（510300/159919）与深证指数代码
    （399006）在该站点都返回 404，而且响应体是一张 JPEG 图片。此时 pandas 只会
    抛出 "Excel file format cannot be determined, you must specify an engine
    manually."，从中完全看不出真实原因，所以把约束直接写进错误信息。

    遍历 exc 的底层原因也一并附上：该 except 会兜住所有异常，若把网络抖动也
    说成「不是中证指数代码」就会误导排查，原始报错必须留在用户可见处。
    """
    hint = (
        f"中证成份股文件按「指数代码」寻址，而「{plain}」不是中证系列指数代码："
        "ETF 代码（510300/159919）与深证指数代码（399006）在该站点均返回 404。"
        "请改用标的指数的中证代码，例如沪深300→000300、中证500→000905、中证1000→000852。"
    )
    if exc is None:
        return hint
    return f"{hint}（底层错误：{type(exc).__name__}: {str(exc)[:160]}）"


def get_index_constituents_raw(symbol: str) -> pd.DataFrame:
    """
    获取指数成分股原始数据表（未格式化）。

    单独提供原始变体，是为了让上层工具（如 agents/tools/constituent_tools.py）
    能经由 CachedDataToolExecutor 复用同一份缓存；已格式化的
    get_index_constituents() 只服务于直接喂给 LLM 的场景。

    注意：返回的是 DataFrame，缓存层以 CSV 形式落盘，读回时纯数字列会丢失
    前导零（"000001" → 1）。消费方必须先经 _normalize_stock_code 之类的
    规范化再使用代码列。

    参数：
        symbol: 标的指数的中证代码（如 000300）。ETF 代码不受支持，见
            _constituents_source_hint。

    返回：
        pd.DataFrame: 成分股原始数据表；调用失败时抛出带可操作说明的 ValueError，
        由上层决定如何降级。
    """
    plain = safe_plain_code(symbol)
    try:
        return _call_akshare_api(ak.index_stock_cons_csindex, symbol=plain)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(_constituents_source_hint(plain, exc)) from exc


def get_index_constituents(symbol: str) -> str:
    """
    获取指数的成分股列表及权重信息。

    参数：
        symbol: 指数代码（如 000300）。

    返回：
        str: 成分股列表文本。
    """
    display = safe_display_symbol(symbol)
    try:
        df = get_index_constituents_raw(symbol)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Index constituents for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的成分股数据。"

    return _format_table(df, f"# Index Constituents for {display}", rows=60)


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


# ── 个股日线行情（成分股表现分析用）────────────────────────────


def get_stock_daily(symbol: str, start_date: str, end_date: str) -> str:
    """
    获取 A 股个股日线行情（前复权）。

    成分股表现分析此前路由到 `get_stock_data`，但该方法从未注册进
    VENDOR_METHODS，导致每次都抛 ValueError 并被吞成「数据获取失败」。
    本函数提供真实可用的实现。

    参数：
        symbol: 股票代码（如 600519）。
        start_date: 起始日期，格式 YYYY-MM-DD。
        end_date: 结束日期，格式 YYYY-MM-DD。

    返回：
        str: CSV 格式的日线行情数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.stock_zh_a_hist,
            symbol=plain,
            period="daily",
            start_date=format_date_for_api(start_date),
            end_date=format_date_for_api(end_date),
            adjust="qfq",
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Stock price data for {display} from {start_date} to {end_date}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 在 {start_date} 到 {end_date} 之间的个股行情数据。"

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

    selected_columns = [
        col
        for col in ["Date", "Open", "High", "Low", "Close", "Volume", "Amount", "PctChange", "TurnoverPct"]
        if col in renamed.columns
    ]
    output = _round_numeric_frame(renamed.loc[:, selected_columns])
    header = f"# Stock price data for {display} from {start_date} to {end_date}\n"
    header += f"# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))
