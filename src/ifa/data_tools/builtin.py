from collections.abc import Callable
from typing import Any

from ifa.data_tools.registry import DataToolRegistry
from ifa.data_tools.types import DataToolDefinition
from ifa.dataflows.interface import route_to_vendor

# ── ETF / 指数 / 场外基金工具 ─────────────────────────────


def get_etf_data_tool(symbol: str, start_date: str, end_date: str):
    """执行 ETF 行情工具。"""
    return route_to_vendor("get_etf_data", symbol, start_date, end_date)


def get_index_data_tool(symbol: str, start_date: str, end_date: str):
    """执行指数行情工具。"""
    return route_to_vendor("get_index_data", symbol, start_date, end_date)


def get_etf_fund_info_tool(symbol: str):
    """执行 ETF 基金信息工具。"""
    return route_to_vendor("get_etf_fund_info", symbol)


def get_index_constituents_tool(symbol: str):
    """执行指数成分股工具。"""
    return route_to_vendor("get_index_constituents", symbol)


def get_index_constituents_raw_tool(symbol: str):
    """执行指数成分股原始数据工具（返回 DataFrame，供上层二次加工）。"""
    return route_to_vendor("get_index_constituents_raw", symbol)


def get_stock_daily_tool(symbol: str, start_date: str, end_date: str):
    """执行 A 股个股日线行情工具。"""
    return route_to_vendor("get_stock_daily", symbol, start_date, end_date)


def get_fund_nav_tool(symbol: str):
    """执行场外基金净值工具。"""
    return route_to_vendor("get_fund_nav", symbol)


# ── 公募基金工具 ─────────────────────────────────────────────


def get_fund_list_tool():
    """执行基金列表工具。"""
    return route_to_vendor("get_fund_list")


def get_fund_basic_info_tool(symbol: str):
    """执行基金基本信息工具。"""
    return route_to_vendor("get_fund_basic_info", symbol)


def get_open_fund_rank_tool(symbol: str = ""):
    """执行开放式基金排行工具。"""
    return route_to_vendor("get_open_fund_rank", symbol)


def get_fund_stock_holdings_tool(symbol: str, date: str = ""):
    """执行基金股票持仓工具。"""
    return route_to_vendor("get_fund_stock_holdings", symbol, date)


def get_fund_bond_holdings_tool(symbol: str, date: str = ""):
    """执行基金债券持仓工具。"""
    return route_to_vendor("get_fund_bond_holdings", symbol, date)


def get_fund_industry_allocation_tool(symbol: str, date: str = ""):
    """执行基金行业配置工具。"""
    return route_to_vendor("get_fund_industry_allocation", symbol, date)


def get_fund_risk_analysis_tool(symbol: str):
    """执行基金风险分析工具。"""
    return route_to_vendor("get_fund_risk_analysis", symbol)


def get_fund_achievement_tool(symbol: str):
    """执行基金业绩工具。"""
    return route_to_vendor("get_fund_achievement", symbol)


def get_etf_spot_data_tool():
    """执行 ETF 实时行情工具。"""
    return route_to_vendor("get_etf_spot_data")


def get_fund_history_nav_tool(symbol: str, indicator: str = "单位净值走势"):
    """执行基金历史净值工具。"""
    return route_to_vendor("get_fund_history_nav", symbol, indicator)


# ── 公募基金工具（增强） ─────────────────────────────────


def get_fund_value_estimation_tool(symbol: str = ""):
    """执行净值估算工具。"""
    return route_to_vendor("get_fund_value_estimation", symbol)


def get_fund_dividend_tool(year: str = ""):
    """执行基金分红工具。"""
    return route_to_vendor("get_fund_dividend", year)


def get_fund_purchase_status_tool():
    """执行基金申购状态工具。"""
    return route_to_vendor("get_fund_purchase_status")


def get_fund_fee_tool(symbol: str, indicator: str = "申购费率"):
    """执行基金交易费率工具。"""
    return route_to_vendor("get_fund_fee", symbol, indicator)


def get_index_fund_filter_tool(symbol: str = "", indicator: str = ""):
    """执行指数型基金筛选工具。"""
    return route_to_vendor("get_index_fund_filter", symbol, indicator)


# ── 公募基金工具（补充） ─────────────────────────────────


def get_money_fund_daily_tool():
    """执行货币基金实时数据工具。"""
    return route_to_vendor("get_money_fund_daily")


def get_fund_profit_probability_tool(symbol: str):
    """执行基金盈利概率工具。"""
    return route_to_vendor("get_fund_profit_probability", symbol)


def get_fund_asset_allocation_tool(symbol: str, date: str = ""):
    """执行基金资产配置比例工具。"""
    return route_to_vendor("get_fund_asset_allocation", symbol, date)


def get_etf_intraday_tool(
    symbol: str,
    period: str = "5",
    start_date: str = "",
    end_date: str = "",
    adjust: str = "",
):
    """执行 ETF 分时行情工具。"""
    return route_to_vendor("get_etf_intraday", symbol, period, start_date, end_date, adjust)


def get_lof_spot_data_tool():
    """执行 LOF 实时行情工具。"""
    return route_to_vendor("get_lof_spot_data")


# ── 宏观经济 / 市场情绪 / 行业估值 ─────────────────────────────


def get_macro_indicator_tool(indicator: str = "GDP"):
    """执行宏观经济指标工具。"""
    return route_to_vendor("get_macro_indicator", indicator)


def get_north_flow_tool(symbol: str = "北向资金"):
    """执行北向资金工具。"""
    return route_to_vendor("get_north_flow", symbol)


def get_market_fund_flow_tool():
    """执行大盘资金流向工具。"""
    return route_to_vendor("get_market_fund_flow")


def get_margin_data_tool():
    """执行融资融券工具。"""
    return route_to_vendor("get_margin_data")


def get_sector_fund_flow_tool(indicator: str = "今日", sector_type: str = "行业资金流"):
    """执行板块资金流向工具。"""
    return route_to_vendor("get_sector_fund_flow", indicator, sector_type)


def get_market_valuation_tool(indicator: str = "上证PE"):
    """执行市场估值工具。"""
    return route_to_vendor("get_market_valuation", indicator)


def get_index_valuation_tool(index_name: str = "沪深300"):
    """执行指数综合估值分析工具。"""
    return route_to_vendor("get_index_valuation", index_name)


def get_valuation_signal_tool(index_name: str = "沪深300"):
    """执行指数估值信号工具。"""
    return route_to_vendor("get_valuation_signal", index_name)


# ── 声明式工具注册表（name, handler, description） ──
_TOOL_SPECS: list[tuple[str, Callable[..., Any], str]] = [
    # ETF / 指数 / 场外基金
    ("get_etf_data", get_etf_data_tool, "ETF 基金日线行情工具"),
    ("get_index_data", get_index_data_tool, "A 股指数日线行情工具"),
    ("get_etf_fund_info", get_etf_fund_info_tool, "ETF 基金基本信息工具"),
    ("get_index_constituents", get_index_constituents_tool, "指数成分股工具"),
    ("get_index_constituents_raw", get_index_constituents_raw_tool, "指数成分股原始数据工具"),
    ("get_stock_daily", get_stock_daily_tool, "A 股个股日线行情工具"),
    ("get_fund_nav", get_fund_nav_tool, "场外基金净值工具"),
    # 公募基金
    ("get_fund_list", get_fund_list_tool, "公募基金列表查询工具"),
    ("get_fund_basic_info", get_fund_basic_info_tool, "公募基金基本信息工具"),
    ("get_open_fund_rank", get_open_fund_rank_tool, "开放式基金排行工具"),
    ("get_fund_stock_holdings", get_fund_stock_holdings_tool, "基金股票持仓工具"),
    ("get_fund_bond_holdings", get_fund_bond_holdings_tool, "基金债券持仓工具"),
    ("get_fund_industry_allocation", get_fund_industry_allocation_tool, "基金行业配置工具"),
    ("get_fund_risk_analysis", get_fund_risk_analysis_tool, "基金风险分析工具"),
    ("get_fund_achievement", get_fund_achievement_tool, "基金业绩工具"),
    ("get_etf_spot_data", get_etf_spot_data_tool, "ETF 实时行情工具"),
    ("get_fund_history_nav", get_fund_history_nav_tool, "基金历史净值工具"),
    # 公募基金（增强）
    ("get_fund_value_estimation", get_fund_value_estimation_tool, "基金净值估算工具"),
    ("get_fund_dividend", get_fund_dividend_tool, "基金分红数据工具"),
    ("get_fund_purchase_status", get_fund_purchase_status_tool, "基金申购状态工具"),
    ("get_fund_fee", get_fund_fee_tool, "基金交易费率工具"),
    ("get_index_fund_filter", get_index_fund_filter_tool, "指数型基金筛选工具"),
    # 公募基金（补充）
    ("get_money_fund_daily", get_money_fund_daily_tool, "货币基金实时数据工具"),
    ("get_fund_profit_probability", get_fund_profit_probability_tool, "基金盈利概率工具"),
    ("get_fund_asset_allocation", get_fund_asset_allocation_tool, "基金资产配置比例工具"),
    ("get_etf_intraday", get_etf_intraday_tool, "ETF 分时行情工具"),
    ("get_lof_spot_data", get_lof_spot_data_tool, "LOF 实时行情工具"),
    # 宏观经济 / 市场情绪 / 行业估值
    ("get_macro_indicator", get_macro_indicator_tool, "宏观经济指标工具"),
    ("get_north_flow", get_north_flow_tool, "北向资金流向工具"),
    ("get_market_fund_flow", get_market_fund_flow_tool, "大盘资金流向工具"),
    ("get_margin_data", get_margin_data_tool, "融资融券数据工具"),
    ("get_sector_fund_flow", get_sector_fund_flow_tool, "板块资金流向工具"),
    ("get_market_valuation", get_market_valuation_tool, "市场估值数据工具"),
    ("get_index_valuation", get_index_valuation_tool, "指数综合估值分析工具"),
    ("get_valuation_signal", get_valuation_signal_tool, "指数估值信号分析工具"),
]


def create_default_data_tool_registry() -> DataToolRegistry:
    """
    创建带有默认 A 股数据工具的注册表。

    返回：
        DataToolRegistry: 初始化完成的工具注册表。
    """
    registry = DataToolRegistry()
    for name, handler, description in _TOOL_SPECS:
        registry.register(
            DataToolDefinition(
                name=name,
                handler=handler,
                description=description,
                namespace="a_share",
            )
        )
    return registry
