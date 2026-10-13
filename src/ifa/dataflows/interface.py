import logging
from collections.abc import Callable
from typing import Any

from .a_share_index_fund import (
    get_etf_data as get_akshare_etf_data,
)
from .a_share_index_fund import (
    get_etf_fund_info as get_akshare_etf_fund_info,
)
from .a_share_index_fund import (
    get_fund_nav as get_akshare_fund_nav,
)
from .a_share_index_fund import (
    get_index_constituents as get_akshare_index_constituents,
)
from .a_share_index_fund import (
    get_index_constituents_raw as get_akshare_index_constituents_raw,
)
from .a_share_index_fund import (
    get_index_data as get_akshare_index_data,
)
from .a_share_index_fund import (
    get_stock_daily as get_akshare_stock_daily,
)
from .a_share_macro import (
    get_index_valuation as get_akshare_index_valuation,
)
from .a_share_macro import (
    get_macro_indicator as get_akshare_macro_indicator,
)
from .a_share_macro import (
    get_margin_data as get_akshare_margin_data,
)
from .a_share_macro import (
    get_market_fund_flow as get_akshare_market_fund_flow,
)
from .a_share_macro import (
    get_market_valuation as get_akshare_market_valuation,
)
from .a_share_macro import (
    get_north_flow as get_akshare_north_flow,
)
from .a_share_macro import (
    get_sector_fund_flow as get_akshare_sector_fund_flow,
)
from .a_share_macro import (
    get_valuation_signal as get_akshare_valuation_signal,
)
from .a_share_public_fund import (
    get_etf_intraday as get_akshare_etf_intraday,
)
from .a_share_public_fund import (
    get_etf_spot_data as get_akshare_etf_spot_data,
)
from .a_share_public_fund import (
    get_fund_achievement as get_akshare_fund_achievement,
)
from .a_share_public_fund import (
    get_fund_asset_allocation as get_akshare_fund_asset_allocation,
)
from .a_share_public_fund import (
    get_fund_basic_info as get_akshare_fund_basic_info,
)
from .a_share_public_fund import (
    get_fund_bond_holdings as get_akshare_fund_bond_holdings,
)
from .a_share_public_fund import (
    get_fund_dividend as get_akshare_fund_dividend,
)
from .a_share_public_fund import (
    get_fund_fee as get_akshare_fund_fee,
)
from .a_share_public_fund import (
    get_fund_history_nav as get_akshare_fund_history_nav,
)
from .a_share_public_fund import (
    get_fund_industry_allocation as get_akshare_fund_industry_allocation,
)
from .a_share_public_fund import (
    get_fund_list as get_akshare_fund_list,
)
from .a_share_public_fund import (
    get_fund_profit_probability as get_akshare_fund_profit_probability,
)
from .a_share_public_fund import (
    get_fund_purchase_status as get_akshare_fund_purchase_status,
)
from .a_share_public_fund import (
    get_fund_risk_analysis as get_akshare_fund_risk_analysis,
)
from .a_share_public_fund import (
    get_fund_stock_holdings as get_akshare_fund_stock_holdings,
)
from .a_share_public_fund import (
    get_fund_value_estimation as get_akshare_fund_value_estimation,
)
from .a_share_public_fund import (
    get_index_fund_filter as get_akshare_index_fund_filter,
)
from .a_share_public_fund import (
    get_lof_spot_data as get_akshare_lof_spot_data,
)
from .a_share_public_fund import (
    get_money_fund_daily as get_akshare_money_fund_daily,
)
from .a_share_public_fund import (
    get_open_fund_rank as get_akshare_open_fund_rank,
)
from .a_share_public_fund import (
    search_funds as get_akshare_search_funds,
)
from .config import get_config

logger = logging.getLogger(__name__)

TOOLS_CATEGORIES = {
    "etf_index_apis": {
        "description": "ETF and index market data",
        "tools": [
            "get_etf_data",
            "get_index_data",
            "get_etf_fund_info",
            "get_index_constituents",
            "get_index_constituents_raw",
            "get_stock_daily",
            "get_fund_nav",
        ],
    },
    "public_fund": {
        "description": "Public fund (公募基金) data including basic info, rankings, holdings, risk, and performance",
        "tools": [
            "search_funds",
            "get_fund_list",
            "get_fund_basic_info",
            "get_open_fund_rank",
            "get_fund_stock_holdings",
            "get_fund_bond_holdings",
            "get_fund_industry_allocation",
            "get_fund_risk_analysis",
            "get_fund_achievement",
            "get_etf_spot_data",
            "get_fund_history_nav",
            # Phase 2 增强
            "get_fund_value_estimation",
            "get_fund_dividend",
            "get_fund_purchase_status",
            "get_fund_fee",
            "get_index_fund_filter",
            # Phase 3 补充
            "get_money_fund_daily",
            "get_fund_profit_probability",
            "get_fund_asset_allocation",
            "get_etf_intraday",
            "get_lof_spot_data",
        ],
    },
    "macro_market": {
        "description": "Macro economy, market sentiment, and sector valuation data",
        "tools": [
            "get_macro_indicator",
            "get_north_flow",
            "get_market_fund_flow",
            "get_margin_data",
            "get_sector_fund_flow",
            "get_market_valuation",
            "get_index_valuation",
            "get_valuation_signal",
        ],
    },
}

VENDOR_LIST = ["akshare"]

VENDOR_METHODS: dict[str, dict[str, Callable[..., Any]]] = {
    # ── ETF / 指数 / 场外基金 ──
    "get_etf_data": {
        "akshare": get_akshare_etf_data,
    },
    "get_index_data": {
        "akshare": get_akshare_index_data,
    },
    "get_etf_fund_info": {
        "akshare": get_akshare_etf_fund_info,
    },
    "get_index_constituents": {
        "akshare": get_akshare_index_constituents,
    },
    "get_index_constituents_raw": {
        "akshare": get_akshare_index_constituents_raw,
    },
    "get_stock_daily": {
        "akshare": get_akshare_stock_daily,
    },
    "get_fund_nav": {
        "akshare": get_akshare_fund_nav,
    },
    # ── 公募基金 ──
    "search_funds": {
        "akshare": get_akshare_search_funds,
    },
    "get_fund_list": {
        "akshare": get_akshare_fund_list,
    },
    "get_fund_basic_info": {
        "akshare": get_akshare_fund_basic_info,
    },
    "get_open_fund_rank": {
        "akshare": get_akshare_open_fund_rank,
    },
    "get_fund_stock_holdings": {
        "akshare": get_akshare_fund_stock_holdings,
    },
    "get_fund_bond_holdings": {
        "akshare": get_akshare_fund_bond_holdings,
    },
    "get_fund_industry_allocation": {
        "akshare": get_akshare_fund_industry_allocation,
    },
    "get_fund_risk_analysis": {
        "akshare": get_akshare_fund_risk_analysis,
    },
    "get_fund_achievement": {
        "akshare": get_akshare_fund_achievement,
    },
    "get_etf_spot_data": {
        "akshare": get_akshare_etf_spot_data,
    },
    "get_fund_history_nav": {
        "akshare": get_akshare_fund_history_nav,
    },
    # ── 公募基金（增强） ──
    "get_fund_value_estimation": {
        "akshare": get_akshare_fund_value_estimation,
    },
    "get_fund_dividend": {
        "akshare": get_akshare_fund_dividend,
    },
    "get_fund_purchase_status": {
        "akshare": get_akshare_fund_purchase_status,
    },
    "get_fund_fee": {
        "akshare": get_akshare_fund_fee,
    },
    "get_index_fund_filter": {
        "akshare": get_akshare_index_fund_filter,
    },
    # ── 公募基金（补充） ──
    "get_money_fund_daily": {
        "akshare": get_akshare_money_fund_daily,
    },
    "get_fund_profit_probability": {
        "akshare": get_akshare_fund_profit_probability,
    },
    "get_fund_asset_allocation": {
        "akshare": get_akshare_fund_asset_allocation,
    },
    "get_etf_intraday": {
        "akshare": get_akshare_etf_intraday,
    },
    "get_lof_spot_data": {
        "akshare": get_akshare_lof_spot_data,
    },
    # ── 宏观经济 / 市场情绪 / 行业估值 ──
    "get_macro_indicator": {
        "akshare": get_akshare_macro_indicator,
    },
    "get_north_flow": {
        "akshare": get_akshare_north_flow,
    },
    "get_market_fund_flow": {
        "akshare": get_akshare_market_fund_flow,
    },
    "get_margin_data": {
        "akshare": get_akshare_margin_data,
    },
    "get_sector_fund_flow": {
        "akshare": get_akshare_sector_fund_flow,
    },
    "get_market_valuation": {
        "akshare": get_akshare_market_valuation,
    },
    "get_index_valuation": {
        "akshare": get_akshare_index_valuation,
    },
    "get_valuation_signal": {
        "akshare": get_akshare_valuation_signal,
    },
}


def get_category_for_method(method: str) -> str:
    """
    获取指定方法所属的数据类别。

    参数：
        method: 用于供应商路由的抽象方法名。

    返回：
        str: 当前查询结果。
    """
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str | None = None) -> str:
    """
    获取某个数据类别或工具方法对应的供应商配置。

    参数：
        category: 当前请求对应的类别名或公告类别。
        method: 用于供应商路由的抽象方法名。

    返回：
        str: 当前查询结果。
    """
    config = get_config()

    # 如果提供了 method，则优先检查工具级配置
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return str(tool_vendors[method])

    # 回退到类别级配置
    return str(config.get("data_vendors", {}).get(category, "akshare"))


def route_to_vendor(method: str, *args, **kwargs):
    """
    将方法调用路由到配置好的 A 股数据实现。

    参数：
        method: 用于供应商路由的抽象方法名。
        args: 透传给底层可调用对象的位置参数。
        kwargs: 透传给底层可调用对象的关键字参数。

    返回：
        Any: 路由后的后端实现返回结果。
    """
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(",")]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    implementations = VENDOR_METHODS[method]
    fallback_vendors = primary_vendors.copy()
    for vendor in implementations:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    last_error: Exception | None = None
    for vendor in fallback_vendors:
        impl_func = implementations.get(vendor)
        if impl_func is None:
            continue

        try:
            return impl_func(*args, **kwargs)
        except Exception as e:
            last_error = e
            logger.warning(
                "供应商 '%s' 执行 '%s' 失败: %s%s",
                vendor,
                method,
                e,
                "，尝试下一个供应商" if vendor != fallback_vendors[-1] else "",
            )
            continue

    raise RuntimeError(f"No available vendor for '{method}': {last_error}") from last_error
