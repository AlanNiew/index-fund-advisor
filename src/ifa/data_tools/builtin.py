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


def create_default_data_tool_registry() -> DataToolRegistry:
    """
    创建带有默认 A 股数据工具的注册表。

    参数：
        无。

    返回：
        DataToolRegistry: 初始化完成的工具注册表。
    """
    registry = DataToolRegistry()
    # ── ETF / 指数 / 场外基金 ──
    registry.register(
        DataToolDefinition(
            name="get_etf_data",
            handler=get_etf_data_tool,
            description="ETF 基金日线行情工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_index_data",
            handler=get_index_data_tool,
            description="A 股指数日线行情工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_etf_fund_info",
            handler=get_etf_fund_info_tool,
            description="ETF 基金基本信息工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_index_constituents",
            handler=get_index_constituents_tool,
            description="指数成分股工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_nav",
            handler=get_fund_nav_tool,
            description="场外基金净值工具",
            namespace="a_share",
        )
    )
    # ── 公募基金 ──
    registry.register(
        DataToolDefinition(
            name="get_fund_list",
            handler=get_fund_list_tool,
            description="公募基金列表查询工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_basic_info",
            handler=get_fund_basic_info_tool,
            description="公募基金基本信息工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_open_fund_rank",
            handler=get_open_fund_rank_tool,
            description="开放式基金排行工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_stock_holdings",
            handler=get_fund_stock_holdings_tool,
            description="基金股票持仓工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_bond_holdings",
            handler=get_fund_bond_holdings_tool,
            description="基金债券持仓工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_industry_allocation",
            handler=get_fund_industry_allocation_tool,
            description="基金行业配置工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_risk_analysis",
            handler=get_fund_risk_analysis_tool,
            description="基金风险分析工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_achievement",
            handler=get_fund_achievement_tool,
            description="基金业绩工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_etf_spot_data",
            handler=get_etf_spot_data_tool,
            description="ETF 实时行情工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_history_nav",
            handler=get_fund_history_nav_tool,
            description="基金历史净值工具",
            namespace="a_share",
        )
    )
    # ── 公募基金（增强） ──
    registry.register(
        DataToolDefinition(
            name="get_fund_value_estimation",
            handler=get_fund_value_estimation_tool,
            description="基金净值估算工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_dividend",
            handler=get_fund_dividend_tool,
            description="基金分红数据工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_purchase_status",
            handler=get_fund_purchase_status_tool,
            description="基金申购状态工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_fee",
            handler=get_fund_fee_tool,
            description="基金交易费率工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_index_fund_filter",
            handler=get_index_fund_filter_tool,
            description="指数型基金筛选工具",
            namespace="a_share",
        )
    )
    # ── 公募基金（补充） ──
    registry.register(
        DataToolDefinition(
            name="get_money_fund_daily",
            handler=get_money_fund_daily_tool,
            description="货币基金实时数据工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_profit_probability",
            handler=get_fund_profit_probability_tool,
            description="基金盈利概率工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_fund_asset_allocation",
            handler=get_fund_asset_allocation_tool,
            description="基金资产配置比例工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_etf_intraday",
            handler=get_etf_intraday_tool,
            description="ETF 分时行情工具",
            namespace="a_share",
        )
    )
    registry.register(
        DataToolDefinition(
            name="get_lof_spot_data",
            handler=get_lof_spot_data_tool,
            description="LOF 实时行情工具",
            namespace="a_share",
        )
    )
    return registry
