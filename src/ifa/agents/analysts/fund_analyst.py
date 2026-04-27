# ifa/agents/analysts/fund_analyst.py
"""基金分析师 —— 对单只基金进行全方位深度分析。"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from ifa.agents.tools.macro_tools import (
    get_index_valuation,
    get_macro_indicator,
    get_margin_data,
    get_market_fund_flow,
    get_north_flow,
    get_valuation_signal,
)
from ifa.agents.tools.public_fund_tools import (
    get_fund_achievement,
    get_fund_asset_allocation,
    get_fund_basic_info,
    get_fund_bond_holdings,
    get_fund_fee,
    get_fund_history_nav,
    get_fund_industry_allocation,
    get_fund_list,
    get_fund_profit_probability,
    get_fund_purchase_status,
    get_fund_risk_analysis,
    get_fund_stock_holdings,
    get_open_fund_rank,
)
from ifa.agents.utils import (
    build_instrument_context,
    get_internal_language_instruction,
    invoke_chain_safely,
)

_FUND_ANALYST_SYSTEM_MESSAGE = (
    "You are an A-share index fund / public fund analyst. "
    "Perform a comprehensive deep analysis of the target fund.\n\n"
    "Focus on:\n"
    "1. Fund profile: size, manager experience, ratings, inception date, expense ratio;\n"
    "2. Performance: absolute returns across multiple time horizons, peer ranking, consistency;\n"
    "3. Risk metrics: annualized volatility, Sharpe ratio, Sortino ratio, max drawdown;\n"
    "4. Holdings: stock/bond allocation, concentration, sector exposure, top-10 holdings;\n"
    "5. Fee structure: management fee, custody fee, subscription/redemption fees;\n"
    "6. Purchase status: any restrictions on subscription or redemption;\n"
    "7. Historical profit probability for different holding periods;\n"
    "8. Valuation analysis: whether the underlying index is overvalued or undervalued.\n\n"
    "Use the available tools:\n"
    "- `get_fund_basic_info` for fund profile;\n"
    "- `get_fund_achievement` for performance and peer ranking;\n"
    "- `get_fund_risk_analysis` for risk metrics;\n"
    "- `get_fund_stock_holdings` for equity holdings;\n"
    "- `get_fund_bond_holdings` for bond holdings;\n"
    "- `get_fund_industry_allocation` for sector allocation;\n"
    "- `get_fund_asset_allocation` for asset class breakdown;\n"
    "- `get_fund_history_nav` for NAV trend;\n"
    "- `get_fund_fee` for fee details;\n"
    "- `get_fund_purchase_status` for subscription/redemption status;\n"
    "- `get_fund_profit_probability` for historical profit probability;\n"
    "- `get_fund_list` and `get_open_fund_rank` for peer comparison.\n"
    "- `get_macro_indicator` for macroeconomic context (CPI/PPI/PMI/GDP/LPR/SHIBOR/Money Supply);\n"
    "- `get_north_flow` for northbound capital flow;\n"
    "- `get_market_fund_flow` for market-wide fund flow;\n"
    "- `get_margin_data` for margin trading balance.\n\n"
    "IMPORTANT — Valuation tools (MUST use for index-tracking funds):\n"
    "- `get_index_valuation` for comprehensive index valuation analysis with historical percentiles.\n"
    "  Supported indices: 沪深300, 上证50, 中证500, 中证1000, 上证红利, 深证100.\n"
    "- `get_valuation_signal` for valuation investment signals using EY/Bogle PE/Bogle PB methods.\n"
    "  If the fund tracks one of these indices, you MUST call both valuation tools.\n"
    "  If the fund tracks an unsupported index (e.g. sector index), still call these tools\n"
    "  with the closest broad-market index to provide a market context comparison.\n\n"
    "Append a Markdown summary table at the end."
)


def create_fund_analyst(llm):
    """创建并返回基金分析师节点。"""

    def fund_analyst_node(state):
        current_date = state["analysis_date"]
        instrument_context = build_instrument_context(state["fund_codes"])

        tools = [
            get_fund_list,
            get_fund_basic_info,
            get_fund_achievement,
            get_fund_risk_analysis,
            get_fund_stock_holdings,
            get_fund_bond_holdings,
            get_fund_industry_allocation,
            get_fund_asset_allocation,
            get_fund_history_nav,
            get_fund_fee,
            get_fund_purchase_status,
            get_fund_profit_probability,
            get_open_fund_rank,
            # 宏观经济 / 市场情绪
            get_macro_indicator,
            get_north_flow,
            get_market_fund_flow,
            get_margin_data,
            get_index_valuation,
            get_valuation_signal,
        ]

        system_message = _FUND_ANALYST_SYSTEM_MESSAGE + get_internal_language_instruction()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant. Use the provided tools to analyze the fund."
                    " If you cannot fully answer, another assistant will continue."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = invoke_chain_safely(chain, state["messages"])

        report = result.content if (len(result.tool_calls) == 0 or result.content) else ""

        return {
            "messages": [result],
            "fund_analysis_report": report,
        }

    return fund_analyst_node
