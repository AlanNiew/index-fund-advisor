# ifa/dataflows/a_share_index_fund.py
"""ETF、指数、场外指数基金的数据获取实现（基于 AkShare）。"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
from typing import Any

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
from .a_share_macro import csindex_codes
from .asset_type import AssetType, detect_asset_type

# ── 行情源回退（东财行情接口不可用时的备用源）────────────────────
# 背景：2026-10 在华为云服务器上实测，东财的 push2his / push2 / push2delay 行情域名
# 全部在 TLS 握手完成后被服务端立刻断开（curl 报 52 Empty reply，requests 报
# RemoteDisconnected），同一台机器上新浪、腾讯的行情接口正常；同一时刻本机（家宽 IP）
# 访问东财正常 —— 即东财对机房 IP 有限流/封锁，与代码和网络配置无关。
#
# 后果：ETF/指数行情取不到 → 回测、评级结算的基准收益、ETF 分析全部静默降级。
# 所以行情取数改为「东财优先，失败回退」：
#   ETF  → 腾讯前复权日线（实测与东财 qfq 逐日完全一致：510300 共 2867 行 diff 0.0000%）
#   指数 → 新浪指数日线（同为价格指数口径，与腾讯指数交叉验证一致）
#
# 注意两点：
# 1. ETF 的备用源**必须是前复权**。新浪 fund_etf_hist_sina 是不复权原始价，与东财 qfq
#    在 510300 上最大差 21.66%（分红未还原），拿它算收益会把分红算成亏损。
# 2. 备用源只回填 OHLC：腾讯的 amount 与东财的「成交量（手）/成交额（元）」口径不同，
#    宁可缺列也不输出错单位的数字（下游收益计算只用收盘价）。

_SOURCE_EASTMONEY = "eastmoney"
_SOURCE_TENCENT = "tencent"
_SOURCE_SINA = "sina"
_SOURCE_NONE = "none"

# 东财熔断：该接口在机房 IP 上 100% 失败，每次失败要重试 3 次（ETF 约 4s、指数约 17s），
# 而一个结算批次会取几百次价 —— 不做熔断的话时间几乎全花在等超时上。
# 连续失败达到阈值后，短时窗口内直接走备用源；窗口过后再给东财一次机会（可能已恢复）。
_EASTMONEY_FAILURE_THRESHOLD = 2
_EASTMONEY_COOLDOWN_SECONDS = 300.0

_eastmoney_consecutive_failures = 0
_eastmoney_blocked_until = 0.0


def eastmoney_breaker_open() -> bool:
    """东财行情熔断是否打开（打开时跳过东财，直接用备用源）。"""
    return time.monotonic() < _eastmoney_blocked_until


def reset_eastmoney_breaker() -> None:
    """清空熔断状态（测试用；长驻进程也可手动恢复）。"""
    global _eastmoney_consecutive_failures, _eastmoney_blocked_until
    _eastmoney_consecutive_failures = 0
    _eastmoney_blocked_until = 0.0


def _record_eastmoney_result(ok: bool) -> None:
    """记录一次东财取数结果：成功即清零，连续失败达阈值则打开熔断窗口。"""
    global _eastmoney_consecutive_failures, _eastmoney_blocked_until
    if ok:
        _eastmoney_consecutive_failures = 0
        _eastmoney_blocked_until = 0.0
        return
    _eastmoney_consecutive_failures += 1
    if _eastmoney_consecutive_failures >= _EASTMONEY_FAILURE_THRESHOLD:
        _eastmoney_blocked_until = time.monotonic() + _EASTMONEY_COOLDOWN_SECONDS


def _fetch_eastmoney_frame(func: Any, **kwargs: Any) -> tuple[pd.DataFrame | None, str]:
    """取一次东财行情帧，附带失败原因。

    frame 非 None 表示东财正常应答（可能为空表，空表交由调用方判「未找到」）；
    reason 非空表示这次没拿到应答（接口异常，或熔断直接跳过）。
    """
    if eastmoney_breaker_open():
        return None, "东财熔断中（连续失败，暂时直接走备用源）"
    try:
        frame = _call_akshare_api(func, **kwargs)
    except Exception as exc:  # noqa: BLE001
        _record_eastmoney_result(False)
        return None, f"东财 {type(exc).__name__}: {exc}"
    _record_eastmoney_result(True)
    return frame, ""

def market_prefixed_code(symbol: str, *, is_index: bool) -> str:
    """转成新浪/腾讯行情接口需要的「市场前缀 + 6 位代码」（如 sh510300 / sz159919）。

    指数：399xxx 在深市，其余（000xxx / 880xxx 等）按沪市处理。
    ETF/LOF：5/6 开头为沪市，1 开头（15/16/159）为深市。
    判断不了返回空串，调用方据此跳过回退 —— 宁可报数据源失败，也不要猜错市场。
    """
    plain = safe_plain_code(symbol)
    if not (len(plain) == 6 and plain.isdigit()):
        return ""
    if is_index:
        return ("sz" if plain.startswith("399") else "sh") + plain
    if plain[0] in {"5", "6"}:
        return "sh" + plain
    if plain[0] == "1":
        return "sz" + plain
    return ""


def _fallback_note(kind: str) -> str:
    """回退源生效时写进输出头的说明行（注释行，不参与 CSV 解析）。"""
    return f"# Source: {kind}（东财行情接口不可用时的备用源；不含成交量/成交额）\n"


def _etf_hist_frame_tencent(symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame | None, str]:
    """腾讯前复权日线 → 与东财同构的中文列 DataFrame，附带失败原因。

    只做取数和列名对齐，日期/数值清洗交给上层既有管道（col_map → Date → _round_numeric_frame）。
    """
    tx_code = market_prefixed_code(symbol, is_index=False)
    if not tx_code:
        return None, "无法识别市场（代码非法）"
    try:
        raw = _call_akshare_api(
            ak.stock_zh_a_hist_tx,
            symbol=tx_code,
            start_date=format_date_for_api(start_date),
            end_date=format_date_for_api(end_date),
            adjust="qfq",
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    if raw is None or raw.empty:
        return None, "返回空数据"
    try:
        frame = pd.DataFrame(
            {
                "日期": pd.to_datetime(raw["date"], errors="coerce"),
                "开盘": pd.to_numeric(raw["open"], errors="coerce"),
                "最高": pd.to_numeric(raw["high"], errors="coerce"),
                "最低": pd.to_numeric(raw["low"], errors="coerce"),
                "收盘": pd.to_numeric(raw["close"], errors="coerce"),
            }
        ).dropna(subset=["日期", "收盘"])
    except KeyError:
        return None, "缺少 date/open/close 等必需列"
    if frame.empty:
        return None, "无有效行情行"
    mask = (frame["日期"] >= pd.Timestamp(start_date)) & (frame["日期"] <= pd.Timestamp(end_date))
    frame = frame.loc[mask].sort_values("日期").reset_index(drop=True)
    return (frame, "") if not frame.empty else (None, "请求区间内无数据")


def _index_hist_frame_sina(symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame | None, str]:
    """新浪指数日线 → 与东财同构的中文列 DataFrame，附带失败原因。"""
    sina_code = market_prefixed_code(symbol, is_index=True)
    if not sina_code:
        return None, "无法识别市场（代码非法）"
    try:
        raw = _call_akshare_api(ak.stock_zh_index_daily, symbol=sina_code)
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    if raw is None or raw.empty:
        return None, "返回空数据"
    try:
        frame = pd.DataFrame(
            {
                "日期": pd.to_datetime(raw["date"], errors="coerce"),
                "开盘": pd.to_numeric(raw["open"], errors="coerce"),
                "最高": pd.to_numeric(raw["high"], errors="coerce"),
                "最低": pd.to_numeric(raw["low"], errors="coerce"),
                "收盘": pd.to_numeric(raw["close"], errors="coerce"),
            }
        ).dropna(subset=["日期", "收盘"])
    except KeyError:
        return None, "缺少 date/open/close 等必需列"
    if frame.empty:
        return None, "无有效行情行"
    # 新浪返回全历史，必须按请求区间自行裁剪（字符串日期比较更稳，避免时区/精度问题）
    start_key = pd.Timestamp(start_date).strftime("%Y-%m-%d")
    end_key = pd.Timestamp(end_date).strftime("%Y-%m-%d")
    dates = frame["日期"].dt.strftime("%Y-%m-%d")
    frame = frame.loc[(dates >= start_key) & (dates <= end_key)].sort_values("日期").reset_index(drop=True)
    return (frame, "") if not frame.empty else (None, "请求区间内无数据")


def fetch_etf_hist_frame(symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, str]:
    """ETF 日线（东财前复权口径）：东财优先，失败回退腾讯前复权。

    返回 (行情表, 来源)，来源取值 eastmoney / tencent / none。
    东财正常但无数据 → 返回空表 + none，让调用方保持「查无数据」语义；
    东财异常且回退也拿不到数据 → 抛 RuntimeError，避免把「数据源全挂」误报成「查无数据」。
    """
    errors: list[str] = []
    frame, em_reason = _fetch_eastmoney_frame(
        ak.fund_etf_hist_em,
        symbol=safe_plain_code(symbol),
        period="daily",
        start_date=format_date_for_api(start_date),
        end_date=format_date_for_api(end_date),
        adjust="qfq",
    )
    if em_reason:
        errors.append(em_reason)
    if frame is not None and not frame.empty:
        return frame, _SOURCE_EASTMONEY

    fallback, reason = _etf_hist_frame_tencent(symbol, start_date, end_date)
    if fallback is not None and not fallback.empty:
        return fallback, _SOURCE_TENCENT
    errors.append(f"腾讯前复权日线: {reason}")
    if em_reason:
        raise RuntimeError("；".join(errors))
    return pd.DataFrame(), _SOURCE_NONE


def fetch_index_hist_frame(symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, str]:
    """指数日线（价格指数口径）：东财优先，失败回退新浪指数日线。

    返回 (行情表, 来源)，语义与 fetch_etf_hist_frame 一致。
    """
    errors: list[str] = []
    frame, em_reason = _fetch_eastmoney_frame(
        ak.index_zh_a_hist,
        symbol=safe_plain_code(symbol),
        period="daily",
        start_date=format_date_for_api(start_date),
        end_date=format_date_for_api(end_date),
    )
    if em_reason:
        errors.append(em_reason)
    if frame is not None and not frame.empty:
        return frame, _SOURCE_EASTMONEY

    fallback, reason = _index_hist_frame_sina(symbol, start_date, end_date)
    if fallback is not None and not fallback.empty:
        return fallback, _SOURCE_SINA
    errors.append(f"新浪指数日线: {reason}")
    if em_reason:
        raise RuntimeError("；".join(errors))
    return pd.DataFrame(), _SOURCE_NONE


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
    title = f"# ETF price data for {display} from {start_date} to {end_date}"
    try:
        df, source = fetch_etf_hist_frame(symbol, start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(title, exc)

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
    if source != _SOURCE_EASTMONEY:
        header += _fallback_note("腾讯前复权日线")
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
    title = f"# Index data for {display} from {start_date} to {end_date}"
    try:
        df, source = fetch_index_hist_frame(symbol, start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(title, exc)

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
    if source != _SOURCE_EASTMONEY:
        header += _fallback_note("新浪指数日线")
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


# ── 跟踪误差 / 跟踪偏离度 ─────────────────────────────────────

_TRADING_DAYS = 252


def compute_tracking_stats(fund: pd.Series, index: pd.Series) -> dict[str, Any]:
    """
    对齐基金与指数两条序列并计算跟踪误差指标（纯计算，不发网络请求）。

    参数：
        fund: 基金净值或价格序列（索引为日期）。
        index: 指数收盘价序列（索引为日期）。

    返回：
        dict: 共同交易日数、年化跟踪误差、年化跟踪偏离度、日均绝对偏离、
            日收益率相关系数、区间累计收益与超额。样本不足时相应值为 None。
    """
    f = pd.to_numeric(fund, errors="coerce")
    i = pd.to_numeric(index, errors="coerce")
    aligned = pd.concat([f.rename("fund"), i.rename("index")], axis=1, join="inner")
    aligned = aligned.apply(pd.to_numeric, errors="coerce").dropna()
    aligned = aligned[~aligned.index.duplicated(keep="last")].sort_index()

    stats: dict[str, Any] = {
        "observations": int(len(aligned)),
        "start": str(aligned.index[0].date()) if len(aligned) else None,
        "end": str(aligned.index[-1].date()) if len(aligned) else None,
        "tracking_error_pct": None,
        "tracking_difference_pct": None,
        "mean_abs_deviation_pct": None,
        "correlation": None,
        "fund_return_pct": None,
        "index_return_pct": None,
        "cumulative_excess_pct": None,
    }
    if len(aligned) < 3:
        return stats

    fund_ret = aligned["fund"].pct_change().dropna()
    index_ret = aligned["index"].pct_change().dropna()
    diff = (fund_ret - index_ret).dropna()
    if len(diff) >= 2:
        stats["tracking_error_pct"] = round(float(diff.std(ddof=1)) * math.sqrt(_TRADING_DAYS) * 100, 4)
        stats["tracking_difference_pct"] = round(float(diff.mean()) * _TRADING_DAYS * 100, 4)
        stats["mean_abs_deviation_pct"] = round(float(diff.abs().mean()) * 100, 4)
    if len(fund_ret) >= 3 and float(index_ret.std()) > 0:
        stats["correlation"] = round(float(fund_ret.corr(index_ret)), 4)

    first_fund = float(aligned["fund"].iloc[0])
    first_index = float(aligned["index"].iloc[0])
    if first_fund > 0 and first_index > 0:
        fund_cum = (float(aligned["fund"].iloc[-1]) / first_fund - 1) * 100
        index_cum = (float(aligned["index"].iloc[-1]) / first_index - 1) * 100
        stats["fund_return_pct"] = round(fund_cum, 2)
        stats["index_return_pct"] = round(index_cum, 2)
        stats["cumulative_excess_pct"] = round(fund_cum - index_cum, 2)
    return stats


def _close_series(df: pd.DataFrame | None) -> pd.Series | None:
    """从行情/净值表里抽出按日期排序的收盘价或净值序列。"""
    if df is None or df.empty:
        return None
    value_col = find_column(df, "收盘", "收盘价", "累计净值", "单位净值", "净值")
    date_col = find_column(df, "日期", "净值日期")
    if value_col is None or date_col is None:
        return None
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "value": pd.to_numeric(df[value_col], errors="coerce"),
        }
    ).dropna()
    if frame.empty:
        return None
    series = frame.set_index("date")["value"]
    return series[~series.index.duplicated(keep="last")].sort_index()


def _etf_price_series(symbol: str, start_date: str, end_date: str) -> tuple[pd.Series | None, str]:
    """取 ETF/LOF 场内前复权收盘价序列（东财优先，腾讯回退）。"""
    try:
        etf_df, _source = fetch_etf_hist_frame(symbol, start_date, end_date)
    except Exception:  # noqa: BLE001
        return None, ""
    series = _close_series(etf_df)
    if series is None or len(series) < 3:
        return None, ""
    return series, "ETF 前复权收盘价（分红已还原）"


def _nav_pair(symbol: str) -> tuple[pd.Series | None, pd.Series | None]:
    """取公募基金的（累计净值, 单位净值）两条序列。"""
    try:
        cum_df = _call_akshare_api(ak.fund_open_fund_info_em, symbol=safe_plain_code(symbol), indicator="累计净值走势")
        unit_df = _call_akshare_api(ak.fund_open_fund_info_em, symbol=safe_plain_code(symbol), indicator="单位净值走势")
    except Exception:  # noqa: BLE001
        return None, None
    return _close_series(cum_df), _close_series(unit_df)


def cum_nav_is_comparable(unit: pd.Series | None, cum: pd.Series | None) -> bool:
    """
    判断累计净值序列能否直接用于计算收益率。

    份额折算会把单位净值重置为 1.0（累计净值不重置），此后累计净值与收益率不再
    可比：拿它算收益会把真实亏损算小。判据是累计净值/单位净值比值是否出现过
    跳变；单纯分红只会让比值缓慢上升（每年 2% 到 3% 量级），折算会一步跳 0.2 以上。
    """
    if unit is None or cum is None or len(unit) < 3 or len(cum) < 3:
        return True
    ratio = (cum / unit.replace(0, pd.NA)).dropna()
    if len(ratio) < 3:
        return True
    return bool(float(ratio.diff().abs().max()) < 0.05)


def fetch_fund_return_series(symbol: str, start_date: str, end_date: str) -> tuple[pd.Series | None, str]:
    """
    取可用于计算收益率的基金序列，并返回口径标签。

    优先级：
    1. 场内 ETF/LOF 前复权收盘价（分红与份额折算都已还原）；
    2. 公募基金累计净值（分红再投已计入）—— 仅当没有发生过份额折算时；
    3. 公募基金单位净值（未计分红，收益被低估）—— 发生折算时的兜底。

    参数：
        symbol: 基金代码。
        start_date: 起始日期 YYYY-MM-DD。
        end_date: 结束日期 YYYY-MM-DD。

    返回：
        tuple: (按日期排序的序列或 None, 口径说明)。
    """
    lower = pd.Timestamp(start_date)
    upper = pd.Timestamp(end_date)
    plain = safe_plain_code(symbol)
    try:
        asset = detect_asset_type(plain)
    except Exception:  # noqa: BLE001
        asset = None

    def _window(series: pd.Series | None) -> pd.Series | None:
        if series is None:
            return None
        windowed = series[(series.index >= lower) & (series.index <= upper)]
        return windowed if len(windowed) >= 3 else None

    price_series, price_basis = _etf_price_series(symbol, start_date, end_date)
    price_series = _window(price_series)
    cum, unit = _nav_pair(symbol)
    cum_window = _window(cum)
    unit_window = _window(unit)

    if asset in (AssetType.ETF, AssetType.INDEX):
        if price_series is not None:
            return price_series, price_basis
        if cum_window is not None and cum_nav_is_comparable(unit, cum):
            return cum_window, "基金累计净值（分红再投已计入）"

    if cum_window is not None and cum_nav_is_comparable(unit, cum):
        return cum_window, "基金累计净值（分红再投已计入）"
    if price_series is not None:
        return price_series, "ETF/LOF 前复权收盘价（分红与份额折算已还原）"
    if unit_window is not None:
        return unit_window, "基金单位净值（发生过份额折算，累计净值不可比；分红未计入，收益被低估）"
    return None, ""


def _fund_close_series(symbol: str, start_date: str, end_date: str) -> tuple[pd.Series | None, str]:
    """取基金序列（见 fetch_fund_return_series 的口径优先级）。"""
    return fetch_fund_return_series(symbol, start_date, end_date)


def _index_close_series(index_code: str, start_date: str, end_date: str) -> pd.Series | None:
    """取 A 股指数日线收盘价序列（东财优先，新浪指数回退）。"""
    try:
        frame, _source = fetch_index_hist_frame(index_code, start_date, end_date)
    except Exception:  # noqa: BLE001
        return None
    return _close_series(frame)


def _name_from_frame(df: pd.DataFrame | None, code: str) -> str:
    """在代码/名称表里按代码查名称。"""
    if df is None or df.empty or not code:
        return ""
    code_col = find_column(df, "代码", "基金代码")
    name_col = find_column(df, "名称", "基金简称")
    if code_col is None or name_col is None:
        return ""
    hit = df[df[code_col].astype(str).str.contains(code, regex=False, na=False)]
    if hit.empty:
        return ""
    return str(hit.iloc[0][name_col])


def _lookup_fund_name(symbol: str) -> str:
    """按代码查基金名称（先查 ETF 实时行情，再查全部基金列表）。"""
    code = safe_plain_code(symbol)
    try:
        spot = _call_akshare_api(ak.fund_etf_spot_em)
    except Exception:  # noqa: BLE001
        spot = None
    name = _name_from_frame(spot, code)
    if name:
        return name
    try:
        all_funds = _call_akshare_api(ak.fund_name_em)
    except Exception:  # noqa: BLE001
        return ""
    return _name_from_frame(all_funds, code)


def _resolve_index_code(symbol: str) -> tuple[str, str, str]:
    """由基金名称识别跟踪指数，返回 (指数代码, 指数名称, 来源说明)。"""
    name = _lookup_fund_name(symbol)
    if not name:
        return "", "", "未能取到基金名称"
    codes = csindex_codes()
    for index_name in sorted(codes, key=len, reverse=True):
        if index_name in name:
            return codes[index_name], index_name, f"由基金名称识别（{name}）"
    return "", "", f"基金名称未匹配到已知 A 股指数（{name}）"


def get_tracking_error(symbol: str, index_code: str = "", days: int = 252) -> str:
    """
    计算指数基金相对其跟踪指数的年化跟踪误差（TE）与跟踪偏离度（TD）。

    基金序列优先取 ETF 前复权行情，取不到时退到公募基金累计净值；指数序列取
    A 股指数日线收盘价。指数代码留空时按基金名称自动识别，识别不到会明确报错
    而不是拿别的指数顶替。海外指数（纳斯达克100、标普500 等）没有 A 股行情
    数据源，本工具无法计算。

    参数：
        symbol: 基金代码（如 510300、161725）。
        index_code: 可选，跟踪指数代码（如 000300、399997）。
        days: 回溯天数，默认 252，限制在 20 到 1250 之间。

    返回：
        str: 跟踪误差指标 + 口径说明；样本不足时明确说明不做结论。
    """
    lookback = max(20, min(int(days or 252), 1250))
    end = datetime.now()
    start_date = (end - timedelta(days=int(lookback * 1.7) + 15)).strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    if index_code:
        code = safe_plain_code(index_code)
        label = code
        source = "调用方显式指定"
    else:
        code, index_name, note = _resolve_index_code(symbol)
        if not code:
            supported = "、".join(f"{name}({value})" for name, value in csindex_codes().items())
            return (
                f"未能确定 {safe_display_symbol(symbol)} 的跟踪指数：{note}。"
                f"请显式传入 index_code。已知 A 股指数：{supported}。"
                "注意：纳斯达克100、标普500 等海外指数没有 A 股行情数据源，无法计算跟踪误差。"
            )
        label = f"{index_name}({code})"
        source = note

    fund_series, basis = _fund_close_series(symbol, start_date, end_date)
    if fund_series is None:
        return f"未取到 {safe_display_symbol(symbol)} 在 {start_date} ~ {end_date} 的净值或价格序列，无法计算跟踪误差。"
    index_series = _index_close_series(code, start_date, end_date)
    if index_series is None:
        return f"未取到指数 {label} 在 {start_date} ~ {end_date} 的行情序列，无法计算跟踪误差。"

    stats = compute_tracking_stats(fund_series, index_series)
    if stats["tracking_error_pct"] is None or stats["observations"] < 3:
        return (
            f"{safe_display_symbol(symbol)} 与 {label} 在 {start_date} ~ {end_date} 的共同交易日仅 "
            f"{stats['observations']} 天，样本不足，不做跟踪误差结论。"
        )

    lines = [
        f"# 跟踪误差分析：{safe_display_symbol(symbol)} vs {label}",
        f"# 样本区间：{stats['start']} ~ {stats['end']}（共同交易日 {stats['observations']} 天）",
        f"# 基金口径：{basis}；指数口径：指数收盘价（价格指数，不含分红）",
        f"# 指数确定方式：{source}",
        "",
        f"- 年化跟踪误差（TE）：{stats['tracking_error_pct']:.2f}%",
        f"- 年化跟踪偏离度（TD，基金减指数）：{stats['tracking_difference_pct']:+.2f}%",
        f"- 日均绝对偏离（单日）：{stats['mean_abs_deviation_pct']:.2f}%",
    ]
    if stats["correlation"] is not None:
        lines.append(f"- 日收益率相关系数：{stats['correlation']:.4f}")
    if stats["cumulative_excess_pct"] is not None:
        lines.append(
            f"- 区间累计收益：基金 {stats['fund_return_pct']:+.2f}% / 指数 {stats['index_return_pct']:+.2f}%"
            f" / 超额 {stats['cumulative_excess_pct']:+.2f}%"
        )
    lines += [
        "",
        "## 口径说明",
        "- 年化跟踪误差 = 日超额收益标准差 * sqrt(252)，衡量跟踪稳定性，越小越贴合指数。",
        "- 年化跟踪偏离度 = 日超额收益均值 * 252，衡量系统性偏离（含费率与现金拖累）。",
        "- 日均绝对偏离是单日超额收益绝对值的均值，不年化，用来直观看每天偏离多大。",
        "- 指数口径不含分红而基金累计净值含分红时，偏离度为正属口径差异，不是管理能力。",
        "- 共同交易日少于 60 天时结论不稳定，本工具只给数值不做判断。",
    ]
    return "\n".join(lines)
