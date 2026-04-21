# ifa/agents/tools/constituent_tools.py
"""成分股分析师专用 LangChain @tool 工具。"""

from __future__ import annotations

import re
from typing import Annotated

import akshare as ak
from langchain_core.tools import tool

from ifa.dataflows.a_share import _call_akshare_api, _format_data_error, _format_table
from ifa.dataflows.a_share_common import (
    normalize_ashare_symbol,
    to_plain_symbol,
)
from ifa.dataflows.asset_type import AssetType, detect_asset_type
from ifa.dataflows.interface import route_to_vendor


def _safe_display_symbol(symbol: str) -> str:
    """安全获取展示用代码，失败则用原始输入。"""
    try:
        return normalize_ashare_symbol(symbol)
    except (ValueError, TypeError):
        return str(symbol).strip()


def _safe_plain_code(symbol: str) -> str:
    """安全提取 6 位纯数字代码。"""
    try:
        return to_plain_symbol(symbol)
    except (ValueError, TypeError):
        match = re.search(r"\d{6}", str(symbol))
        if match:
            return match.group(0)
        return str(symbol).strip()


@tool
def get_constituent_overview(
    symbol: Annotated[str, "Index or ETF ticker symbol, e.g. 000300, 510300"],
) -> str:
    """
    获取指数/ETF 的前 10 大权重股概况，包括代码、名称、权重占比。
    参数：
        symbol (str): 指数或 ETF 代码。
    返回：
        str: 权重股概况文本。
    """
    asset_type = detect_asset_type(symbol)
    if asset_type == AssetType.OFFSHORE_FUND:
        return f"{_safe_display_symbol(symbol)} 是场外基金，没有明确的成分股列表。场外基金通过跟踪指数间接持有成分股，请使用 get_etf_fund_info 查看基金信息，或使用跟踪的指数代码查询成分股。"

    display = _safe_display_symbol(symbol)
    try:
        plain = _safe_plain_code(symbol)
        df = _call_akshare_api(
            ak.index_stock_cons_csindex,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Top Constituents for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的成分股数据。"

    # 取前 10 大权重股
    top_n = 10
    weight_col = _find_column(df, "权重", "weight", "指数权重")

    df = df.sort_values(weight_col, ascending=False).head(top_n) if weight_col else df.head(top_n)

    selected_cols = [col for col in ["日期", "指数代码", "指数名称", "成分券代码", "成分券名称", "权重"] if col in df.columns]
    if not selected_cols:
        selected_cols = list(df.columns[:5])

    return _format_table(df[selected_cols], f"# Top {top_n} Constituents for {display}")


@tool
def get_constituent_sector_distribution(
    symbol: Annotated[str, "Index or ETF ticker symbol, e.g. 000300, 510300"],
) -> str:
    """
    获取指数/ETF 的行业分布概况（基于申万一级行业分类）。
    参数：
        symbol (str): 指数或 ETF 代码。
    返回：
        str: 行业分布统计文本。
    """
    asset_type = detect_asset_type(symbol)
    if asset_type == AssetType.OFFSHORE_FUND:
        return f"{_safe_display_symbol(symbol)} 是场外基金，无法直接查询行业分布。请使用其跟踪的指数代码查询。"

    display = _safe_display_symbol(symbol)
    try:
        plain = _safe_plain_code(symbol)
        df = _call_akshare_api(
            ak.index_stock_cons_csindex,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Sector Distribution for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的成分股行业分布数据。"

    sector_col = _find_column(df, "行业", "行业代码", "industry", "一级行业")

    if not sector_col:
        return f"成分股数据中未找到行业分类字段。可用列: {list(df.columns)}"

    sector_counts = df[sector_col].value_counts().reset_index()
    sector_counts.columns = ["行业", "成分股数量"]
    sector_counts["占比(%)"] = (sector_counts["成分股数量"] / sector_counts["成分股数量"].sum() * 100).round(2)

    weight_col = _find_column(df, "权重", "weight", "指数权重")

    if weight_col:
        df[weight_col] = df[weight_col].astype(float)
        sector_weights = df.groupby(sector_col)[weight_col].sum().reset_index()
        sector_weights.columns = ["行业", "权重合计(%)"]
        sector_weights["权重合计(%)"] = sector_weights["权重合计(%)"].round(2)
        sector_counts = sector_counts.merge(sector_weights, on="行业", how="left")

    return _format_table(sector_counts, f"# Sector Distribution for {display}", rows=30)


@tool
def get_constituent_performance(
    symbol: Annotated[str, "Index or ETF ticker symbol, e.g. 000300, 510300"],
    look_back_days: Annotated[int, "Number of days to look back for performance"] = 30,
) -> str:
    """
    获取指数/ETF 前 10 大权重股的近期行情表现。
    参数：
        symbol (str): 指数或 ETF 代码。
        look_back_days (int): 回看天数，默认 30 天。
    返回：
        str: 权重股近期表现文本。
    """
    asset_type = detect_asset_type(symbol)
    if asset_type == AssetType.OFFSHORE_FUND:
        return f"{_safe_display_symbol(symbol)} 是场外基金，无法直接查询成分股表现。请使用其跟踪的指数代码查询。"

    display = _safe_display_symbol(symbol)
    try:
        plain = _safe_plain_code(symbol)
        df = _call_akshare_api(
            ak.index_stock_cons_csindex,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Constituent Performance for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的成分股数据。"

    code_col = _find_column(df, "成分券代码", "股票代码", "code")
    name_col = _find_column(df, "成分券名称", "股票名称", "name")
    weight_col = _find_column(df, "权重", "weight", "指数权重")

    if not code_col:
        return f"成分股数据中未找到代码字段。可用列: {list(df.columns)}"

    top_stocks = df.nlargest(10, weight_col) if weight_col else df.head(10)

    results = []
    for _, row in top_stocks.iterrows():
        stock_code = str(row[code_col])
        stock_name = str(row.get(name_col, "")) if name_col else ""

        try:
            stock_data = route_to_vendor(
                "get_stock_data",
                symbol=stock_code,
                start_date=_get_start_date(look_back_days),
                end_date=_get_today_str(),
            )
            results.append(f"## {stock_name}({stock_code})\n{stock_data[:500]}...")
        except Exception:  # noqa: BLE001
            results.append(f"## {stock_name}({stock_code})\n数据获取失败。")

    header = f"# Top 10 Constituent Performance for {display} (Last {look_back_days} days)\n\n"
    return header + "\n\n".join(results)


def _find_column(df, *candidates: str) -> str | None:
    """在 DataFrame 列中按候选名称依次查找，返回第一个匹配的列名。"""
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _get_today_str() -> str:
    """返回今天的日期字符串。"""
    from datetime import date
    return date.today().strftime("%Y-%m-%d")


def _get_start_date(look_back_days: int) -> str:
    """返回 look_back_days 天前的日期字符串。"""
    from datetime import date, timedelta
    return (date.today() - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
