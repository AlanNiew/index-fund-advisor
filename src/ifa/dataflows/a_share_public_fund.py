# ifa/dataflows/a_share_public_fund.py
"""公募基金（股票型/混合型/债券型/货币型/QDII/FOF 等）数据获取实现（基于 AkShare）。"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

from .a_share import (
    DATA_SOURCE_ERROR_MARKER,
    _call_akshare_api,
    _format_data_error,
    _format_key_value,
    _format_table,
    _round_numeric_frame,
)
from .a_share_common import find_column, safe_display_symbol, safe_plain_code
from .a_share_index_fund import _fetch_etf_daily_row
from .asset_type import AssetType, detect_asset_type

logger = logging.getLogger(__name__)

# ── 1. 全部基金列表 ─────────────────────────────────────────────


def get_fund_list() -> str:
    """
    获取全部公募基金列表（代码/名称/类型）。

    返回：
        str: 基金列表 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_name_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# All Public Funds List", exc)

    if df is None or df.empty:
        return "未获取到基金列表数据。"

    # 选取核心列，避免数据过大
    preferred_cols = ["基金代码", "基金简称", "基金类型"]
    available_cols = [c for c in preferred_cols if c in df.columns]
    if not available_cols:
        available_cols = list(df.columns[:4])

    selected = df[available_cols].copy()
    # 限制行数，避免返回全部 2 万+ 基金撑爆 LLM 上下文
    total = len(selected)
    sample = selected.head(30)
    header = f"# All Public Funds List\n# Total: {total} funds (showing top 30)\n\n"
    return header + str(sample.to_csv(index=False))


# ── 1b. 公募基金搜索 ────────────────────────────────────────────

# 搜索结果默认与最大行数。上限用于防止把 2.8 万只基金一次性塞进上下文。
DEFAULT_FUND_SEARCH_LIMIT = 20
MAX_FUND_SEARCH_LIMIT = 200

# 参与关键词匹配的字段：代码 / 简称 / 类型 / 拼音，匹配大小写不敏感。
_FUND_SEARCH_FIELDS = ("基金代码", "基金简称", "基金类型", "拼音缩写", "拼音全称")


def _normalize_fund_code(value: object) -> str:
    """把基金代码规范化为 6 位字符串（兼容数值型代码与 "159919.0" 形态）。"""
    text = str(value).strip().split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def _select_fund_columns(df: pd.DataFrame) -> pd.DataFrame:
    """选取基金列表输出列（代码 / 简称 / 类型），并把代码统一补成 6 位。"""
    preferred_cols = ["基金代码", "基金简称", "基金类型"]
    available_cols = [c for c in preferred_cols if c in df.columns]
    if not available_cols:
        available_cols = list(df.columns[:4])
    selected = df[available_cols].copy()
    if "基金代码" in selected.columns:
        selected["基金代码"] = selected["基金代码"].map(_normalize_fund_code)
    return selected


def _filter_funds(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """在完整基金列表中按关键词做大小写不敏感的子串过滤。"""
    needle = (query or "").strip().upper()
    if not needle:
        return df
    mask = pd.Series(False, index=df.index)
    for field in _FUND_SEARCH_FIELDS:
        if field in df.columns:
            mask = mask | df[field].astype(str).str.upper().str.contains(needle, regex=False, na=False)
    return df[mask]


def search_funds(query: str = "", limit: int = DEFAULT_FUND_SEARCH_LIMIT) -> str:
    """
    在**全部**公募基金中按关键词搜索（不再只搜列表头部 30 行）。

    说明：
        CLI / REST / MCP 此前的搜索都是在 get_fund_list() 返回的「前 30 行」文本上
        做关键字过滤，任何不在前 30 行的基金都搜不到（如「沪深300」有 366 只命中，
        但 CLI 返回「未找到」）。本函数在完整列表（约 2.8 万只）上过滤，只对**结果**
        分页。

    参数：
        query: 关键词，匹配基金代码 / 简称 / 类型 / 拼音；留空返回列表头部。
        limit: 最多返回多少行（默认 20，上限 200）。

    返回：
        str: 带匹配总数的 CSV 文本；数据源失败时返回带 DATA_SOURCE_ERROR_MARKER
        标记的错误文本。
    """
    try:
        df = _call_akshare_api(ak.fund_name_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# Fund Search", exc)

    if df is None or df.empty:
        return "未获取到基金列表数据。"

    keyword = (query or "").strip()
    matched = _filter_funds(df, keyword)
    total = len(matched)
    label = keyword or "（全部）"
    title = f"# Fund Search: {label}"
    if total == 0:
        return f"{title}\n# Matches: 0\n\n未找到匹配「{label}」的基金。"

    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = DEFAULT_FUND_SEARCH_LIMIT
    limit_value = max(1, min(limit_value, MAX_FUND_SEARCH_LIMIT))
    rows = _select_fund_columns(matched).head(limit_value)
    return f"{title}\n# Matches: {total} (showing {len(rows)})\n\n{rows.to_csv(index=False)}"


# ── 2. 基金基本信息 ─────────────────────────────────────────────


def get_fund_basic_info(symbol: str) -> str:
    """
    获取基金基本信息。

    场内 ETF 与场外基金必须走不同数据源——两者字段不同，而且互不在对方的库里：
    ETF 走东财场内行情表（简称/类型/单位净值/市价），场外基金走蛋卷基金
    （规模/经理/成立日期等）。ETF 若走蛋卷的 fund_individual_basic_info_xq，
    上游会直接 KeyError: 'data'（蛋卷只有场外基金库）。

    参数：
        symbol: 基金代码（如 000001、510300）。

    返回：
        str: 基金基本信息文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)

    if detect_asset_type(symbol) == AssetType.ETF:
        try:
            row = _fetch_etf_daily_row(plain)
        except Exception as exc:  # noqa: BLE001
            return _format_data_error(f"# Fund Basic Info for {display}", exc)

        if row is None:
            return f"未找到 {display} 的 ETF 行情记录：该代码可能不是场内 ETF，或尚未上市交易。"

        return _format_key_value(row.iloc[0], f"# Fund Basic Info for {display}")

    try:
        df = _call_akshare_api(
            ak.fund_individual_basic_info_xq,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Basic Info for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的基金基本信息。"

    return f"# Fund Basic Info for {display}\n\n{df.to_csv(index=False)}"


# ── 3. 开放式基金排行 ──────────────────────────────────────────


def get_open_fund_rank(symbol: str = "") -> str:
    """
    获取开放式基金排行（多时间维度收益率）。

    参数：
        symbol: 基金类型筛选，如 "全部"、"股票型"、"混合型"、"债券型"、"指数型"、"QDII" 等。

    返回：
        str: 基金排行 CSV 数据。
    """
    filter_label = symbol if symbol else "全部"
    try:
        df = _call_akshare_api(
            ak.fund_open_fund_rank_em,
            symbol=filter_label,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Open Fund Rank ({filter_label})", exc)

    if df is None or df.empty:
        return f"未找到类型为「{filter_label}」的开放式基金排行数据。"

    # 取前 50 条避免数据过大
    output = _round_numeric_frame(df.head(50))
    header = f"# Open Fund Rank ({filter_label})\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ── 4. 基金股票持仓 ────────────────────────────────────────────


def get_fund_stock_holdings(symbol: str, date: str = "") -> str:
    """
    获取基金股票持仓明细。

    参数：
        symbol: 基金代码（如 000001）。
        date: 报告期，格式 YYYY 或 YYYY-MM-DD。为空时取最新。

    返回：
        str: 股票持仓 CSV 数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    report_date = date[:4] if date else ""

    try:
        df = _call_akshare_api(
            ak.fund_portfolio_hold_em,
            symbol=plain,
            date=report_date,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Stock Holdings for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的股票持仓数据。"

    header = f"# Fund Stock Holdings for {display} ({report_date or 'latest'})\n# Records: {len(df)}\n\n"
    # 保留前 20 行（按持仓比例排序，前 20 = 十大重仓股，最有价值）
    return header + str(df.head(20).to_csv(index=False))


# ── 5. 基金债券持仓 ────────────────────────────────────────────


def get_fund_bond_holdings(symbol: str, date: str = "") -> str:
    """
    获取基金债券持仓明细。

    参数：
        symbol: 基金代码（如 000001）。
        date: 报告期，格式 YYYY 或 YYYY-MM-DD。为空时取最新。

    返回：
        str: 债券持仓 CSV 数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    report_date = date[:4] if date else ""

    try:
        df = _call_akshare_api(
            ak.fund_portfolio_bond_hold_em,
            symbol=plain,
            date=report_date,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Bond Holdings for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的债券持仓数据。"

    header = f"# Fund Bond Holdings for {display} ({report_date or 'latest'})\n# Records: {len(df)}\n\n"
    # 保留前 20 行（前 20 = 主要债券持仓）
    return header + str(df.head(20).to_csv(index=False))


# ── 6. 行业配置 ────────────────────────────────────────────────


def get_fund_industry_allocation(symbol: str, date: str = "") -> str:
    """
    获取基金行业配置。

    参数：
        symbol: 基金代码（如 000001）。
        date: 报告期，格式 YYYY 或 YYYY-MM-DD。为空时取最新。

    返回：
        str: 行业配置 CSV 数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    report_date = date[:4] if date else ""

    try:
        df = _call_akshare_api(
            ak.fund_portfolio_industry_allocation_em,
            symbol=plain,
            date=report_date,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Industry Allocation for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的行业配置数据。"

    return _format_table(df, f"# Fund Industry Allocation for {display} ({report_date or 'latest'})", rows=30)


# ── 7. 风险分析 ────────────────────────────────────────────────


def get_fund_risk_analysis(symbol: str) -> str:
    """
    获取基金风险分析（波动率/夏普比率/最大回撤等）。

    参数：
        symbol: 基金代码（如 000001）。

    返回：
        str: 风险分析文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_individual_analysis_xq,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Risk Analysis for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的风险分析数据。"

    return f"# Fund Risk Analysis for {display}\n\n{df.to_csv(index=False)}"


# ── 8. 基金业绩 ────────────────────────────────────────────────


def get_fund_achievement(symbol: str) -> str:
    """
    获取基金业绩（年度/阶段收益 + 同类排名）。

    参数：
        symbol: 基金代码（如 000001）。

    返回：
        str: 业绩数据文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_individual_achievement_xq,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Achievement for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的业绩数据。"

    return f"# Fund Achievement for {display}\n\n{df.to_csv(index=False)}"


# ── 9. ETF 实时行情 ────────────────────────────────────────────


def get_etf_spot_data() -> str:
    """
    获取 ETF 实时行情（折价率/资金流向等）。

    返回：
        str: ETF 实时行情 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_etf_spot_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# ETF Spot Data", exc)

    if df is None or df.empty:
        return "未获取到 ETF 实时行情数据。"

    # 取前 100 条避免数据过大
    output = _round_numeric_frame(df.head(100))
    header = f"# ETF Spot Data\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ── 9b. ETF 折溢价率 ──────────────────────────────────────────

_PREMIUM_WARN_PCT = 1.0
_PREMIUM_ALERT_PCT = 3.0


def get_etf_premium_discount(symbol: str = "", top_n: int = 10) -> str:
    """
    获取 ETF 场内价格相对 IOPV（基金份额参考净值）的折溢价率。

    溢价率 = (最新价 / IOPV - 1) * 100%，优先取东财「基金折价率」列并取反
    （该列是折价口径，负数即溢价）。跨境/QDII ETF 常年溢价，溢价过高时买入
    会额外承担溢价回落的风险，本工具对此显式告警。

    参数：
        symbol: 可选，ETF 代码（如 513100）。留空则按溢价率绝对值从大到小列出前 top_n 只。
        top_n: 留空 symbol 时返回的条数，默认 10，最多 50。

    返回：
        str: 折溢价率表格 + 口径说明 + 高溢价告警。
    """
    try:
        df = _call_akshare_api(ak.fund_etf_spot_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# ETF Premium / Discount", exc)

    if df is None or df.empty:
        return "未获取到 ETF 实时行情数据。"

    code_col = find_column(df, "代码", "基金代码")
    name_col = find_column(df, "名称", "基金简称")
    price_col = find_column(df, "最新价")
    iopv_col = find_column(df, "IOPV实时估值", "IOPV")
    discount_col = find_column(df, "基金折价率", "折价率")
    date_col = find_column(df, "数据日期", "更新时间")

    if code_col is None or name_col is None:
        return "ETF 实时行情缺少代码/名称列，无法计算折溢价率。"

    price = pd.to_numeric(df[price_col], errors="coerce") if price_col else None
    iopv = pd.to_numeric(df[iopv_col], errors="coerce") if iopv_col else None
    discount = pd.to_numeric(df[discount_col], errors="coerce") if discount_col else None

    frame = pd.DataFrame(
        {
            "代码": df[code_col].astype(str),
            "名称": df[name_col].astype(str),
        }
    )
    if discount is not None and discount.notna().any():
        # 东财该列是折价口径：折价率为负即溢价
        frame["溢价率%"] = (-discount).round(2)
        basis = "东财基金折价率列取反（折价率为负即溢价）"
    elif price is not None and iopv is not None and iopv.gt(0).any():
        frame["溢价率%"] = ((price / iopv - 1) * 100).round(2)
        basis = "由最新价与 IOPV 实时估值计算"
    else:
        return "ETF 实时行情缺少折价率与 IOPV 列，无法计算折溢价率。"

    if price is not None:
        frame["最新价"] = price
    if iopv is not None:
        frame["IOPV"] = iopv
    if date_col is not None:
        frame["数据日期"] = df[date_col].astype(str)

    frame = frame[frame["溢价率%"].notna()]
    if frame.empty:
        return "未获取到有效的 ETF 折溢价率数据。"

    target = safe_plain_code(symbol) if symbol else ""
    if target:
        hit = frame[frame["代码"].str.contains(target, regex=False, na=False)]
        if hit.empty:
            return f"未在 ETF 实时行情中找到代码 {target}（该代码可能不是场内 ETF）。"
        frame = hit
    else:
        limit = max(1, min(int(top_n or 10), 50))
        frame = frame.loc[frame["溢价率%"].abs().sort_values(ascending=False).index].head(limit)

    lines = [
        f"# ETF 折溢价率（口径：{basis}）",
        f"# 记录数：{len(frame)}",
        "",
        frame.to_string(index=False),
        "",
        "## 口径与含义",
        "- 溢价率 > 0：场内价格高于基金参考净值（溢价买入，相当于多付钱）。",
        "- 溢价率 < 0：场内价格低于基金参考净值（折价买入，相当于打折）。",
        "- 折溢价会随申购额度与市场情绪变化，不是无风险套利机会；暂停申购的跨境 ETF 溢价可能长期存在。",
    ]
    warn = frame[frame["溢价率%"].abs() >= _PREMIUM_WARN_PCT]
    if not warn.empty:
        lines.append("")
        lines.append(f"## 告警（|溢价率| >= {_PREMIUM_WARN_PCT:.1f}%）")
        for _, row in warn.iterrows():
            level = "高溢价/高折价" if abs(float(row["溢价率%"])) >= _PREMIUM_ALERT_PCT else "折溢价偏高"
            lines.append(f"- {row['代码']} {row['名称']}：{row['溢价率%']:+.2f}%（{level}）")
        lines.append("- 买入高溢价品种时，即使指数不跌，溢价回落也会造成亏损；建议等待溢价收敛或改用场外联接基金。")
    return "\n".join(lines)


# ── 10. 基金历史净值 / 累计收益率 / 排名走势 ──────────────────


def get_fund_history_nav(symbol: str, indicator: str = "单位净值走势") -> str:
    """
    获取基金历史净值走势、累计收益率走势或同类排名走势。

    参数：
        symbol: 基金代码（如 000001）。
        indicator: 指标类型，可选 "单位净值走势"、"累计净值走势"、"累计收益率走势"、"同类排名走势"。

    返回：
        str: 历史数据 CSV 文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_open_fund_info_em,
            symbol=plain,
            indicator=indicator,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund {indicator} for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的「{indicator}」数据。"

    # 取最近 120 条数据避免过大
    recent = df.tail(120)
    return _format_table(recent, f"# Fund {indicator} for {display}")


# ─────────────────────────────────────────────────────────────
# Phase 2：增强接口
# ─────────────────────────────────────────────────────────────


# ── 11. 净值估算 ────────────────────────────────────────────────


def get_fund_value_estimation(symbol: str = "") -> str:
    """
    获取基金净值估算数据（盘中实时估值）。

    参数：
        symbol: 基金类型筛选，如 "全部"、"股票型"、"混合型"、"债券型"、"指数型"、"QDII" 等。

    返回：
        str: 净值估算 CSV 数据。
    """
    filter_label = symbol if symbol else "全部"
    try:
        df = _call_akshare_api(ak.fund_value_estimation_em, symbol=filter_label)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Value Estimation ({filter_label})", exc)

    if df is None or df.empty:
        return f"未找到类型为「{filter_label}」的净值估算数据。"

    # 取前 20 条
    output = _round_numeric_frame(df.head(20))
    header = f"# Fund Value Estimation ({filter_label})\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ── 12. 基金分红数据 ────────────────────────────────────────────


def get_fund_dividend(year: str = "") -> str:
    """
    获取基金分红数据。

    参数：
        year: 年份，如 "2025"。为空时取最新。

    返回：
        str: 基金分红 CSV 数据。
    """
    year_label = year if year else "latest"
    try:
        df = _call_akshare_api(ak.fund_fh_em, year=year)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Dividend Data ({year_label})", exc)

    if df is None or df.empty:
        return f"未找到 {year_label} 年的基金分红数据。"

    output = _round_numeric_frame(df.head(100))
    header = f"# Fund Dividend Data ({year_label})\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ── 13. 基金申购状态 ────────────────────────────────────────────


def get_fund_purchase_status() -> str:
    """
    获取全部基金申购/赎回状态。

    返回：
        str: 申购状态 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_purchase_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# Fund Purchase Status", exc)

    if df is None or df.empty:
        return "未获取到基金申购状态数据。"

    return _format_table(df.head(50), "# Fund Purchase Status")


# ── 14. 基金交易费率 ────────────────────────────────────────────


def fetch_fund_fee_table(symbol: str, indicator: str) -> pd.DataFrame | None:
    """取基金费率**原始表**（不截断、不格式化），失败返回 None。

    `fund_fee_em` 是上游接口，字段名与形状随 indicator 变化（运作费用是 1 行 N 列的
    键值对，赎回费率是「持有期限 / 赎回费率」两列多行），格式化后调用方没法解析，
    所以这里把原表直接交出去，由 :mod:`ifa.backtest.fees` 负责解释。
    """
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(ak.fund_fee_em, symbol=plain, indicator=indicator)
    except Exception as exc:  # noqa: BLE001
        logger.warning("费率数据获取失败 (%s / %s): %s", plain, indicator, exc)
        return None
    if df is None or df.empty:
        return None
    return df


def fetch_fund_nav_series(symbol: str, indicator: str = "累计净值走势") -> pd.DataFrame:
    """取基金**完整**历史净值序列（不截断）。

    与 :func:`get_fund_history_nav` 的区别：那个是给 Agent 读的文本工具，取 `tail(120)`
    以免撑爆上下文；回测需要完整历史（120 条只有半年），所以单独走这个函数。
    数据源失败时抛 `ValueError`（带 `DATA_SOURCE_ERROR_MARKER` 前缀），**不要**静默返回
    空表 —— 否则回测会把「数据源挂了」误报成「数据不足（少于 2 个交易日）」。
    """
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(ak.fund_open_fund_info_em, symbol=plain, indicator=indicator)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{DATA_SOURCE_ERROR_MARKER}{exc}") from exc
    if df is None or df.empty:
        return pd.DataFrame()
    return df.reset_index(drop=True)


def get_fund_fee(symbol: str, indicator: str = "申购费率") -> str:
    """
    获取基金交易费率信息。

    参数：
        symbol: 基金代码（如 015641）。
        indicator: 费率类型，可选 "交易状态"/"申购与赎回金额"/"运作费用"/"认购费率（前端）"/"申购费率"/"赎回费率"。

    返回：
        str: 费率信息文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_fee_em,
            symbol=plain,
            indicator=indicator,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Fee for {display} ({indicator})", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的「{indicator}」数据。"

    return f"# Fund {indicator} for {display}\n\n{df.to_csv(index=False)}"


# ── 15. 指数型基金筛选 ─────────────────────────────────────────


def get_index_fund_filter(symbol: str = "", indicator: str = "") -> str:
    """
    获取指数型基金列表及筛选数据。

    参数：
        symbol: 指数分类，如 "全部"/"沪深指数"/"行业主题"/"大盘指数"/"中盘指数"/"小盘指数"。
        indicator: 跟踪方式，如 "全部"/"被动指数型"/"增强指数型"。

    返回：
        str: 指数基金列表 CSV 数据。
    """
    filter_label = symbol if symbol else "全部"
    indicator_label = indicator if indicator else "全部"
    try:
        df = _call_akshare_api(
            ak.fund_info_index_em,
            symbol=filter_label,
            indicator=indicator_label,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Index Fund Filter ({filter_label}/{indicator_label})", exc)

    if df is None or df.empty:
        return f"未找到分类为「{filter_label}」、跟踪方式为「{indicator_label}」的指数基金数据。"

    output = _round_numeric_frame(df.head(50))
    header = f"# Index Fund Filter ({filter_label}/{indicator_label})\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ─────────────────────────────────────────────────────────────
# Phase 3：补充接口
# ─────────────────────────────────────────────────────────────


# ── 16. 货币基金实时数据 ──────────────────────────────────────────


def get_money_fund_daily() -> str:
    """
    获取货币基金实时数据（万份收益/7日年化等）。

    返回：
        str: 货币基金 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_money_fund_daily_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# Money Fund Daily", exc)

    if df is None or df.empty:
        return "未获取到货币基金实时数据。"

    return _format_table(df, "# Money Fund Daily", rows=50)


# ── 17. 盈利概率 ────────────────────────────────────────────────


def get_fund_profit_probability(symbol: str) -> str:
    """
    获取基金盈利概率（历史任意时点买入持有满 X 时间的盈利概率和平均收益）。

    参数：
        symbol: 基金代码（如 000001）。

    返回：
        str: 盈利概率数据文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_individual_profit_probability_xq,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Profit Probability for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的盈利概率数据。"

    return f"# Fund Profit Probability for {display}\n\n{df.to_csv(index=False)}"


# ── 18. 资产配置比例 ────────────────────────────────────────────


def get_fund_asset_allocation(symbol: str, date: str = "") -> str:
    """
    获取基金大类资产配置比例（股票/债券/现金等）。

    参数：
        symbol: 基金代码（如 002804）。
        date: 报告期，格式 YYYYMMDD（如 20231231）。为空时取最新。

    返回：
        str: 资产配置比例文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    report_date = date.replace("-", "") if date else ""
    try:
        df = _call_akshare_api(
            ak.fund_individual_detail_hold_xq,
            symbol=plain,
            date=report_date,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Asset Allocation for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的资产配置数据。"

    return f"# Fund Asset Allocation for {display} ({report_date or 'latest'})\n\n{df.to_csv(index=False)}"


# ── 19. ETF 分时行情 ────────────────────────────────────────────


def get_etf_intraday(
    symbol: str,
    period: str = "5",
    start_date: str = "",
    end_date: str = "",
    adjust: str = "",
) -> str:
    """
    获取 ETF 分时行情数据（分钟级 K 线）。

    参数：
        symbol: ETF 代码（如 513500）。
        period: K 线周期，可选 "1"/"5"/"15"/"30"/"60"。
        start_date: 开始日期时间，格式 "YYYY-MM-DD HH:MM:SS"。
        end_date: 结束日期时间，格式 "YYYY-MM-DD HH:MM:SS"。
        adjust: 复权方式，"" 不复权/"qfq" 前复权/"hfq" 后复权。

    返回：
        str: 分时行情 CSV 数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_etf_hist_min_em,
            symbol=plain,
            period=period,
            start_date=start_date or "1979-09-01 09:32:00",
            end_date=end_date or "2222-01-01 09:32:00",
            adjust=adjust,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# ETF Intraday for {display} ({period}min)", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的 {period} 分钟分时数据。"

    # 取最近 240 条
    recent = df.tail(240)
    return _format_table(recent, f"# ETF Intraday for {display} ({period}min)")


# ── 20. LOF 实时行情 ────────────────────────────────────────────


def get_lof_spot_data() -> str:
    """
    获取 LOF 基金实时行情数据。

    返回：
        str: LOF 实时行情 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_lof_spot_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# LOF Spot Data", exc)

    if df is None or df.empty:
        return "未获取到 LOF 实时行情数据。"

    return _format_table(df, "# LOF Spot Data", rows=50)


# ── 21. 基金每日净值快照（脚本/程序化消费）──────────────────────
#
# 为什么单独开一个「非文本」入口：数据工具层的每个工具都要把结果转成给 LLM 看的 CSV
# 文本，而每日邮件摘要需要的是结构化的 {代码: {净值/日期/涨跌幅}}。这里返回 dict，
# 仿 a_share_macro.fetch_valuation_metrics 的先例。
#
# 三张上游表各请求一次，与基金数量无关；任一表失败只让对应字段缺失，不抛异常：
#   - fund_open_fund_daily_em → 全部场外基金（含 QDII）最近已公布的单位净值
#   - fund_info_index_em      → 场外指数基金的单位净值 + 日期 + 日增长率
#   - fund_etf_fund_daily_em  → 场内 ETF 的单位净值 + 市价 + 日增长率

#: 上游把缺失值写成 '-' / '--' / '---' / 'nan' 等多种形态，统一判为缺失。
_MISSING_VALUE_TOKENS = frozenset({"", "-", "--", "---", "nan", "none", "null"})


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in _MISSING_VALUE_TOKENS


def _to_float(value: object) -> float | None:
    """把上游的净值/涨跌幅转成 float；缺失或非数字返回 None。"""
    if _is_missing(value):
        return None
    try:
        return float(str(value).strip().replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _nav_columns(df: pd.DataFrame) -> list[str]:
    """按表内顺序返回「<日期>-单位净值」列（当天在前、上一交易日在后）。"""
    return [str(column) for column in df.columns if str(column).endswith("-单位净值")]


def _nav_from_row(row: pd.Series, columns: Sequence[str]) -> tuple[float | None, str | None]:
    """取第一个有值的单位净值列，并返回它对应的日期（日期写在列名里）。"""
    for column in columns:
        value = _to_float(row.get(column))
        if value is not None:
            return value, str(column).rsplit("-", 1)[0]
    return None, None


def _rows_for_codes(df: pd.DataFrame, wanted: set[str]) -> dict[str, pd.Series]:
    """从整表里挑出目标代码的行（先向量化过滤再逐行取，避免遍历上万行）。"""
    code_col = find_column(df, "基金代码", "代码")
    if not code_col:
        return {}
    normalized = df[code_col].astype(str).str.strip().str.zfill(6)
    hit = df[normalized.isin(wanted)]
    rows: dict[str, pd.Series] = {}
    for _, row in hit.iterrows():
        rows.setdefault(str(row.get(code_col)).strip().zfill(6), row)
    return rows


def _fill_from_open_fund_daily(snapshots: dict[str, dict]) -> None:
    """全部场外基金（含 QDII）的最近单位净值 —— 该表没有净值日期列，日期写在列名里。"""
    try:
        df = _call_akshare_api(ak.fund_open_fund_daily_em)
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取开放式基金每日净值失败，摘要将缺少场外净值: %s", exc)
        return
    if df is None or df.empty:
        return

    rows = _rows_for_codes(df, set(snapshots))
    name_col = find_column(df, "基金简称", "基金名称")
    nav_cols = _nav_columns(df)
    change_col = find_column(df, "日增长率")
    for code, row in rows.items():
        data = snapshots[code]
        if name_col and not data["name"] and not _is_missing(row.get(name_col)):
            data["name"] = str(row.get(name_col)).strip()
        if data["nav"] is None:
            data["nav"], data["nav_date"] = _nav_from_row(row, nav_cols)
        if data["change_pct"] is None and change_col:
            data["change_pct"] = _to_float(row.get(change_col))


def _fill_from_index_fund_table(snapshots: dict[str, dict]) -> None:
    """场外指数基金：这张表带净值日期与日增长率，比每日净值表更适合做摘要。"""
    try:
        df = _call_akshare_api(ak.fund_info_index_em, symbol="全部", indicator="被动指数型")
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取指数基金列表失败，摘要将缺少场外指数基金的日涨跌: %s", exc)
        return
    if df is None or df.empty:
        return

    rows = _rows_for_codes(df, set(snapshots))
    name_col = find_column(df, "基金名称", "基金简称")
    nav_col = find_column(df, "单位净值")
    date_col = find_column(df, "日期")
    change_col = find_column(df, "日增长率")
    for code, row in rows.items():
        data = snapshots[code]
        if name_col and not data["name"] and not _is_missing(row.get(name_col)):
            data["name"] = str(row.get(name_col)).strip()
        nav = _to_float(row.get(nav_col)) if nav_col else None
        if nav is not None:
            data["nav"] = nav
            if date_col and not _is_missing(row.get(date_col)):
                data["nav_date"] = str(row.get(date_col)).strip()[:10]
        change = _to_float(row.get(change_col)) if change_col else None
        if change is not None:
            data["change_pct"] = change


def _fetch_etf_price_change(code: str) -> float | None:
    """ETF 收盘后从场内日线补当日涨跌幅（每日行情表的「增长率」要更晚才有值）。"""
    end = datetime.now()
    start = end - timedelta(days=15)
    try:
        df = _call_akshare_api(
            ak.fund_etf_hist_em,
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 ETF %s 日线失败，日涨跌留空: %s", code, exc)
        return None
    if df is None or df.empty:
        return None
    change_col = find_column(df, "涨跌幅")
    return _to_float(df.iloc[-1].get(change_col)) if change_col else None


def _etf_sina_symbol(code: str) -> str | None:
    """场内代码 → 新浪符号（新浪日线只认带交易所前缀的符号）。"""
    if len(code) != 6 or not code.isdigit():
        return None
    if code[0] == "5":
        return "sh" + code
    if code[0] == "1":
        return "sz" + code
    if code[0] in {"4", "8"}:
        return "bj" + code
    return None


def _fetch_etf_price_change_sina(code: str) -> float | None:
    """ETF 日涨跌兜底：新浪日线（最近两个交易日收盘价相除）。

    东财 push2his（fund_etf_hist_em）在部分网络下会持续 RemoteDisconnected，
    而同一台机器访问新浪正常，所以换个数据源兜底，而不是让「日涨跌」一直空着。
    """
    symbol = _etf_sina_symbol(code)
    if symbol is None:
        return None
    try:
        df = _call_akshare_api(ak.fund_etf_hist_sina, symbol=symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 ETF %s 新浪日线失败，日涨跌留空: %s", code, exc)
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    closes = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return None
    previous, latest = float(closes.iloc[-2]), float(closes.iloc[-1])
    if not previous:
        return None
    return round((latest - previous) / previous * 100, 2)


def _fill_from_etf_table(snapshots: dict[str, dict]) -> None:
    """场内 ETF：每日行情表给出单位净值/市价，但收盘前的「增长率」是 '---'。"""
    try:
        df = _call_akshare_api(ak.fund_etf_fund_daily_em)
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取场内 ETF 行情失败，摘要将缺少 ETF 净值: %s", exc)
        return
    if df is None or df.empty:
        return

    rows = _rows_for_codes(df, set(snapshots))
    name_col = find_column(df, "基金简称", "基金名称")
    price_col = find_column(df, "市价")
    nav_cols = _nav_columns(df)
    change_col = find_column(df, "增长率", "日增长率")
    for code, row in rows.items():
        data = snapshots[code]
        if name_col and not data["name"] and not _is_missing(row.get(name_col)):
            data["name"] = str(row.get(name_col)).strip()
        if data["nav"] is None:
            data["nav"], data["nav_date"] = _nav_from_row(row, nav_cols)
        if data["change_pct"] is None and change_col:
            data["change_pct"] = _to_float(row.get(change_col))
        if price_col:
            data["price"] = _to_float(row.get(price_col))
        if data["change_pct"] is None:
            data["change_pct"] = _fetch_etf_price_change(code)
        if data["change_pct"] is None:
            data["change_pct"] = _fetch_etf_price_change_sina(code)


def fetch_fund_daily_snapshots(codes: Sequence[str]) -> dict[str, dict]:
    """
    获取一批基金的每日净值快照（名称/单位净值/净值日期/日涨跌幅/市价）。

    面向脚本与程序化消费（每日邮件摘要），返回结构化数据而不是给 LLM 的 CSV 文本。
    上游表里的「当天」净值收盘后才有值，因此拿到的是最近已公布交易日的数据，并在
    nav_date 里如实标注 —— 摘要里不能把昨天的净值写成今天的。

    参数：
        codes: 基金代码序列（6 位，可混含场内 ETF 与场外基金）。

    返回：
        dict[str, dict]: {代码: {"name", "nav", "nav_date", "change_pct", "price"}}；
        上游查不到的代码不会出现在结果里，缺失字段为 None。
    """
    wanted = [safe_plain_code(code) for code in codes if str(code).strip()]
    snapshots: dict[str, dict] = {
        code: {"name": None, "nav": None, "nav_date": None, "change_pct": None, "price": None}
        for code in wanted
        if code
    }
    if not snapshots:
        return {}

    _fill_from_open_fund_daily(snapshots)
    _fill_from_index_fund_table(snapshots)
    _fill_from_etf_table(snapshots)

    return {code: data for code, data in snapshots.items() if data["name"] or data["nav"] is not None}
