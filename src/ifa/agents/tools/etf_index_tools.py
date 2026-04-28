# ifa/agents/tools/etf_index_tools.py
"""ETF、指数、场外基金的 LangChain @tool 工具定义。"""

from typing import Annotated

from langchain_core.tools import tool

from ifa.data_tools.api import run_data_tool
from ifa.dataflows.data_cleaning import cap_tool_result


@tool
def get_etf_data(
    symbol: Annotated[str, "ETF ticker symbol, e.g. 510300, 159919"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    获取指定 ETF 基金的历史行情数据（OHLCV）。
    使用已配置的 `etf_index_apis` 数据供应商。
    参数：
        symbol (str): ETF 代码，例如 510300（沪深300ETF）、159919。
        start_date (str): 开始日期，格式为 YYYY-MM-DD。
        end_date (str): 结束日期，格式为 YYYY-MM-DD。
    返回：
        str: 指定 ETF 在给定日期区间内的格式化行情数据表。
    """
    return cap_tool_result(
        run_data_tool(
            "get_etf_data",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
    )


@tool
def get_index_data(
    symbol: Annotated[str, "Index ticker symbol, e.g. 000300, 399006"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    获取指定股票指数的历史行情数据（OHLCV）。
    使用已配置的 `etf_index_apis` 数据供应商。
    参数：
        symbol (str): 指数代码，例如 000300（沪深300）、399006（创业板指）。
        start_date (str): 开始日期，格式为 YYYY-MM-DD。
        end_date (str): 结束日期，格式为 YYYY-MM-DD。
    返回：
        str: 指定指数在给定日期区间内的格式化行情数据表。
    """
    return cap_tool_result(
        run_data_tool(
            "get_index_data",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
    )


@tool
def get_etf_fund_info(
    symbol: Annotated[str, "ETF ticker symbol, e.g. 510300, 159919"],
) -> str:
    """
    获取 ETF 基金基本信息，包括基金规模、费率、跟踪指数、基金公司等。
    参数：
        symbol (str): ETF 代码，例如 510300、159919。
    返回：
        str: ETF 基金基本信息文本。
    """
    return cap_tool_result(run_data_tool("get_etf_fund_info", symbol=symbol))


@tool
def get_index_constituents(
    symbol: Annotated[str, "Index ticker symbol, e.g. 000300, 000905"],
) -> str:
    """
    获取指数的成分股列表及权重信息。
    参数：
        symbol (str): 指数代码，例如 000300（沪深300）、000905（中证500）。
    返回：
        str: 成分股代码、名称及权重分布。
    """
    return cap_tool_result(run_data_tool("get_index_constituents", symbol=symbol))


@tool
def get_fund_nav(
    symbol: Annotated[str, "Fund ticker symbol, e.g. 160119, 501010"],
) -> str:
    """
    获取场外指数基金（联接基金/LOF）的历史净值数据。
    参数：
        symbol (str): 基金代码，例如 160119（沪深300联接）、501010。
    返回：
        str: 基金历史净值数据文本。
    """
    return cap_tool_result(run_data_tool("get_fund_nav", symbol=symbol))
