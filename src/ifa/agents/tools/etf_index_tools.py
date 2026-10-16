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


@tool
def get_etf_premium_discount(
    symbol: Annotated[str, "ETF ticker symbol, e.g. 513100; empty means list the largest premiums/discounts"] = "",
    top_n: Annotated[int, "How many ETFs to list when symbol is empty (max 50)"] = 10,
) -> str:
    """
    获取 ETF 场内价格相对 IOPV 的折溢价率（溢价率为正表示溢价买入）。
    跨境 / QDII ETF 常年溢价，溢价过高时买入会额外承担溢价回落风险。
    参数：
        symbol (str): ETF 代码，例如 513100；留空则列出折溢价绝对值最大的前 top_n 只。
        top_n (int): 留空 symbol 时返回的条数，默认 10。
    返回：
        str: 折溢价率表格 + 口径说明 + 高溢价告警。
    """
    return cap_tool_result(
        run_data_tool(
            "get_etf_premium_discount",
            symbol=symbol,
            top_n=top_n,
        )
    )


@tool
def get_tracking_error(
    symbol: Annotated[str, "Fund ticker symbol, e.g. 510300, 161725"],
    index_code: Annotated[str, "Optional tracked index code, e.g. 000300, 399997; empty means auto-detect"] = "",
    days: Annotated[int, "Lookback days, default 252, clamped to 20-1250"] = 252,
) -> str:
    """
    计算指数基金相对其跟踪指数的年化跟踪误差（TE）与跟踪偏离度（TD）。
    指数代码留空时按基金名称自动识别；海外指数（纳斯达克100、标普500）无 A 股行情数据源，无法计算。
    参数：
        symbol (str): 基金代码，例如 510300、161725。
        index_code (str): 可选，跟踪指数代码，例如 000300、399997。
        days (int): 回溯天数，默认 252。
    返回：
        str: 跟踪误差指标 + 口径说明；样本不足时明确说明不做结论。
    """
    return cap_tool_result(
        run_data_tool(
            "get_tracking_error",
            symbol=symbol,
            index_code=index_code,
            days=days,
        )
    )


@tool
def get_fx_rate(
    currency: Annotated[str, "Currency name, e.g. 美元, 港币, 日元"] = "美元",
    days: Annotated[int, "Lookback days, default 30, clamped to 5-90"] = 30,
) -> str:
    """
    获取人民币兑指定外币的中国银行牌价与区间变动（单位：人民币元 / 100 外币）。
    QDII 基金的人民币净值已包含汇率变动，汇率本身不是买卖 QDII 的择时依据。
    参数：
        currency (str): 外币名称，如 美元、欧元、日元、港币。
        days (int): 回溯天数，默认 30，限制在 5 到 90 之间。
    返回：
        str: 最新牌价 + 区间变动 + 口径说明。
    """
    return cap_tool_result(run_data_tool("get_fx_rate", currency=currency, days=days))
