# ifa/agents/tools/public_fund_tools.py
"""公募基金分析专用 LangChain @tool 工具定义。"""

from typing import Annotated

from langchain_core.tools import tool

from ifa.data_tools.api import run_data_tool
from ifa.dataflows.data_cleaning import cap_tool_result


@tool
def get_fund_list() -> str:
    """
    获取全部公募基金列表，包含基金代码、名称、类型等信息。
    可用于搜索和筛选目标基金。
    返回：
        str: 基金列表数据。
    """
    return cap_tool_result(run_data_tool("get_fund_list"))


@tool
def get_fund_basic_info(
    symbol: Annotated[str, "Fund code, e.g. 000001, 110011, 005827"],
) -> str:
    """
    获取基金基本信息，包括基金规模、基金经理、评级、成立日期、管理费率等。
    参数：
        symbol (str): 基金代码，例如 000001（华夏成长）、110011（易方达中小盘）。
    返回：
        str: 基金基本信息文本。
    """
    return cap_tool_result(run_data_tool("get_fund_basic_info", symbol=symbol))


@tool
def get_open_fund_rank(
    symbol: Annotated[
        str,
        "Fund type filter: 全部/股票型/混合型/债券型/指数型/QDII",
    ] = "全部",
) -> str:
    """
    获取开放式基金排行榜，包含多时间维度的收益率数据（近1周/1月/3月/6月/1年/3年等）。
    参数：
        symbol (str): 基金类型筛选，默认为"全部"。
    返回：
        str: 基金排行 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_open_fund_rank", symbol=symbol))


@tool
def get_fund_stock_holdings(
    symbol: Annotated[str, "Fund code, e.g. 000001"],
    date: Annotated[
        str,
        "Report date, format: YYYY or YYYY-MM-DD. Empty for latest.",
    ] = "",
) -> str:
    """
    获取基金股票持仓明细，包括持仓股票代码、名称、占净值比例、持股数、持仓市值等。
    参数：
        symbol (str): 基金代码。
        date (str): 报告期，为空时取最新数据。
    返回：
        str: 股票持仓 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_fund_stock_holdings", symbol=symbol, date=date))


@tool
def get_fund_bond_holdings(
    symbol: Annotated[str, "Fund code, e.g. 000001"],
    date: Annotated[
        str,
        "Report date, format: YYYY or YYYY-MM-DD. Empty for latest.",
    ] = "",
) -> str:
    """
    获取基金债券持仓明细，包括债券代码、名称、占净值比例、持仓市值等。
    参数：
        symbol (str): 基金代码。
        date (str): 报告期，为空时取最新数据。
    返回：
        str: 债券持仓 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_fund_bond_holdings", symbol=symbol, date=date))


@tool
def get_fund_industry_allocation(
    symbol: Annotated[str, "Fund code, e.g. 000001"],
    date: Annotated[
        str,
        "Report date, format: YYYY or YYYY-MM-DD. Empty for latest.",
    ] = "",
) -> str:
    """
    获取基金行业配置分布，基于证监会行业分类。
    参数：
        symbol (str): 基金代码。
        date (str): 报告期，为空时取最新数据。
    返回：
        str: 行业配置分布文本。
    """
    return cap_tool_result(run_data_tool("get_fund_industry_allocation", symbol=symbol, date=date))


@tool
def get_fund_risk_analysis(
    symbol: Annotated[str, "Fund code, e.g. 000001"],
) -> str:
    """
    获取基金风险分析数据，包括年化波动率、夏普比率、最大回撤等指标。
    参数：
        symbol (str): 基金代码。
    返回：
        str: 风险分析指标文本。
    """
    return cap_tool_result(run_data_tool("get_fund_risk_analysis", symbol=symbol))


@tool
def get_fund_achievement(
    symbol: Annotated[str, "Fund code, e.g. 000001"],
) -> str:
    """
    获取基金业绩数据，包括年度收益、阶段收益（近1月/3月/6月/1年/3年/5年）及同类排名。
    参数：
        symbol (str): 基金代码。
    返回：
        str: 业绩数据文本。
    """
    return cap_tool_result(run_data_tool("get_fund_achievement", symbol=symbol))


@tool
def get_etf_spot_data() -> str:
    """
    获取全部 ETF 实时行情数据，包括最新价、折价率、溢价率、资金流向等。
    返回：
        str: ETF 实时行情 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_etf_spot_data"))


@tool
def get_fund_history_nav(
    symbol: Annotated[str, "Fund code, e.g. 000001"],
    indicator: Annotated[
        str,
        "Indicator type: 单位净值走势/累计净值走势/累计收益率走势/同类排名走势",
    ] = "单位净值走势",
) -> str:
    """
    获取基金历史净值走势、累计收益率走势或同类排名走势。
    参数：
        symbol (str): 基金代码。
        indicator (str): 指标类型。
    返回：
        str: 历史数据文本。
    """
    return cap_tool_result(run_data_tool("get_fund_history_nav", symbol=symbol, indicator=indicator))


# ── Phase 2 增强工具 ──────────────────────────────────────────


@tool
def get_fund_value_estimation(
    symbol: Annotated[
        str,
        "Fund type filter: 全部/股票型/混合型/债券型/指数型/QDII",
    ] = "全部",
) -> str:
    """
    获取基金净值估算数据（盘中实时估值），用于盘中判断基金当日表现。
    参数：
        symbol (str): 基金类型筛选，默认为"全部"。
    返回：
        str: 净值估算 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_fund_value_estimation", symbol=symbol))


@tool
def get_fund_dividend(
    year: Annotated[str, "Year, e.g. 2025. Empty for latest."] = "",
) -> str:
    """
    获取基金分红数据，包括权益登记日、除息日、分红金额和发放日。
    参数：
        year (str): 年份，为空时取最新。
    返回：
        str: 基金分红 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_fund_dividend", year=year))


@tool
def get_fund_purchase_status() -> str:
    """
    获取全部基金申购/赎回状态，包括限大额、暂停申购、封闭期等。
    返回：
        str: 申购状态 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_fund_purchase_status"))


@tool
def get_fund_fee(
    symbol: Annotated[str, "Fund code, e.g. 015641"],
    indicator: Annotated[
        str,
        "Fee type: 申购费率/赎回费率/运作费用/交易状态/认购费率（前端）",
    ] = "申购费率",
) -> str:
    """
    获取基金交易费率信息（申购/赎回费率、管理费、托管费等）。
    参数：
        symbol (str): 基金代码。
        indicator (str): 费率类型。
    返回：
        str: 费率信息文本。
    """
    return cap_tool_result(run_data_tool("get_fund_fee", symbol=symbol, indicator=indicator))


@tool
def get_index_fund_filter(
    symbol: Annotated[
        str,
        "Index category: 全部/沪深指数/行业主题/大盘指数/中盘指数/小盘指数",
    ] = "全部",
    indicator: Annotated[
        str,
        "Tracking method: 全部/被动指数型/增强指数型",
    ] = "全部",
) -> str:
    """
    获取指数型基金列表，可按指数分类和跟踪方式筛选。
    返回字段包括基金代码、名称、净值、涨跌幅、跟踪标的、手续费等。
    参数：
        symbol (str): 指数分类。
        indicator (str): 跟踪方式。
    返回：
        str: 指数基金 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_index_fund_filter", symbol=symbol, indicator=indicator))


# ── Phase 3 补充工具 ──────────────────────────────────────────


@tool
def get_money_fund_daily() -> str:
    """
    获取货币基金实时数据，包括万份收益、7日年化收益率、基金经理等。
    返回：
        str: 货币基金 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_money_fund_daily"))


@tool
def get_fund_profit_probability(
    symbol: Annotated[str, "Fund code, e.g. 000001"],
) -> str:
    """
    获取基金盈利概率，即历史任意时点买入、持有满 X 时间的盈利概率和平均收益。
    参数：
        symbol (str): 基金代码。
    返回：
        str: 盈利概率数据文本。
    """
    return cap_tool_result(run_data_tool("get_fund_profit_probability", symbol=symbol))


@tool
def get_fund_asset_allocation(
    symbol: Annotated[str, "Fund code, e.g. 002804"],
    date: Annotated[
        str,
        "Report date, format: YYYYMMDD. Empty for latest.",
    ] = "",
) -> str:
    """
    获取基金大类资产配置比例（股票/债券/现金/其他等）。
    参数：
        symbol (str): 基金代码。
        date (str): 报告期，格式 YYYYMMDD，为空取最新。
    返回：
        str: 资产配置比例文本。
    """
    return cap_tool_result(run_data_tool("get_fund_asset_allocation", symbol=symbol, date=date))


@tool
def get_etf_intraday(
    symbol: Annotated[str, "ETF code, e.g. 513500"],
    period: Annotated[
        str,
        "K-line period: 1/5/15/30/60 (minutes)",
    ] = "5",
    start_date: Annotated[str, "Start datetime, format: YYYY-MM-DD HH:MM:SS"] = "",
    end_date: Annotated[str, "End datetime, format: YYYY-MM-DD HH:MM:SS"] = "",
    adjust: Annotated[
        str,
        "Adjust type: empty string (no adjust)/qfq (forward)/hfq (backward)",
    ] = "",
) -> str:
    """
    获取 ETF 分时行情数据（分钟级 K 线），支持 1/5/15/30/60 分钟周期。
    参数：
        symbol (str): ETF 代码。
        period (str): K 线周期（分钟）。
        start_date (str): 开始日期时间。
        end_date (str): 结束日期时间。
        adjust (str): 复权方式。
    返回：
        str: 分时行情 CSV 数据。
    """
    return cap_tool_result(run_data_tool(
        "get_etf_intraday",
        symbol=symbol,
        period=period,
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    ))


@tool
def get_lof_spot_data() -> str:
    """
    获取 LOF 基金实时行情数据，包括价格、涨跌幅、成交量、换手率等。
    返回：
        str: LOF 实时行情 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_lof_spot_data"))
