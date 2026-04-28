# ifa/agents/tools/macro_tools.py
"""宏观经济、市场情绪、行业估值 LangChain @tool 工具定义。"""

from typing import Annotated

from langchain_core.tools import tool

from ifa.data_tools.api import run_data_tool
from ifa.dataflows.data_cleaning import cap_tool_result

# ── P0 — 宏观经济指标 ──────────────────────────────────────────


@tool
def get_macro_indicator(
    indicator: Annotated[
        str,
        "Macro indicator type: CPI/PPI/PMI/GDP/LPR/SHIBOR/MONEY_SUPPLY",
    ] = "GDP",
) -> str:
    """
    获取宏观经济指标数据。包括 CPI（消费者价格指数）、PPI（生产者价格指数）、
    PMI（采购经理指数）、GDP（国内生产总值）、LPR（贷款市场报价利率）、
    SHIBOR（上海银行间同业拆放利率）、MONEY_SUPPLY（货币供应量 M0/M1/M2）。
    参数：
        indicator (str): 宏观指标类型，默认 GDP。
    返回：
        str: 宏观指标 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_macro_indicator", indicator=indicator))


# ── P1 — 市场资金与情绪 ──────────────────────────────────────────


@tool
def get_north_flow(
    symbol: Annotated[
        str,
        "Northbound channel: 沪股通/深股通/北向资金",
    ] = "北向资金",
) -> str:
    """
    获取北向资金（沪股通/深股通）历史净流入数据，包括当日成交净买额、
    买入/卖出成交额、历史累计净买额等。
    参数：
        symbol (str): 渠道类型，默认 北向资金。
    返回：
        str: 北向资金 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_north_flow", symbol=symbol))


@tool
def get_market_fund_flow() -> str:
    """
    获取大盘资金流向概览，包括主力净流入、超大单/大单/中单/小单资金流向。
    返回：
        str: 大盘资金流向 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_market_fund_flow"))


@tool
def get_margin_data() -> str:
    """
    获取上海市场融资融券余额数据，包括融资买入额、融资余额、
    融券卖出量、融券余额、融资融券余额。
    返回：
        str: 融资融券 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_margin_data"))


# ── P2 — 板块资金与行业估值 ──────────────────────────────────────


@tool
def get_sector_fund_flow(
    indicator: Annotated[
        str,
        "Time period: 今日/3日/5日/10日",
    ] = "今日",
    sector_type: Annotated[
        str,
        "Sector type: 行业资金流/概念资金流/地区资金流",
    ] = "行业资金流",
) -> str:
    """
    获取板块资金流向排名，可按行业、概念、地区分类，查看今日/3日/5日/10日资金流向。
    参数：
        indicator (str): 时间维度，默认 今日。
        sector_type (str): 板块类型，默认 行业资金流。
    返回：
        str: 板块资金流向排名 CSV 数据。
    """
    return cap_tool_result(
        run_data_tool(
            "get_sector_fund_flow",
            indicator=indicator,
            sector_type=sector_type,
        )
    )


@tool
def get_market_valuation(
    indicator: Annotated[
        str,
        "Valuation indicator: 上证PE/深证PE/上证PB/深证PB/沪深300PE/上证50PE/中证500PE/创业板PE",
    ] = "上证PE",
) -> str:
    """
    获取市场整体或主要指数的估值数据（市盈率 PE / 市净率 PB）。
    支持上证、深证大盘估值以及沪深300、上证50、中证500、创业板等主要指数。
    参数：
        indicator (str): 估值指标，默认 上证PE。
    返回：
        str: 市场估值 CSV 数据。
    """
    return cap_tool_result(run_data_tool("get_market_valuation", indicator=indicator))


@tool
def get_index_valuation(
    index_name: Annotated[
        str,
        "Index name: 沪深300/上证50/中证500/中证1000/上证红利/深证100",
    ] = "沪深300",
) -> str:
    """
    获取指数综合估值分析报告，包含滚动/静态市盈率(PE)、市净率(PB)、
    盈利率(EY=1/PE)和A股股息率，并计算各指标近10年历史百分位及估值判断。
    参数：
        index_name (str): 指数名称，默认 沪深300。
    返回：
        str: 指数估值分析报告（含百分位和估值判断）。
    """
    return cap_tool_result(run_data_tool("get_index_valuation", index_name=index_name))


@tool
def get_valuation_signal(
    index_name: Annotated[
        str,
        "Index name: 沪深300/上证50/中证500/中证1000/上证红利/深证100",
    ] = "沪深300",
) -> str:
    """
    使用三种估值方法分析指数投资信号：
    1) 盈利收益率法（适合宽基/红利指数）— 对比 EY 与国债收益率，给出买/卖/持信号
    2) 博格公式PE版 — 预期收益率 = 股息率 + EPS增长 + PE均值回归
    3) 博格公式PB版 — 预期收益率 ≈ ROE + PB均值回归
    自动根据指数类型选择适用方法，生成综合投资判断。
    参数：
        index_name (str): 指数名称，默认 沪深300。
    返回：
        str: 估值信号分析报告（含三种方法的投资信号）。
    """
    return cap_tool_result(run_data_tool("get_valuation_signal", index_name=index_name))
