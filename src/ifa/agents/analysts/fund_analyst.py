# ifa/agents/analysts/fund_analyst.py
"""基金分析师 —— 对单只基金进行全方位深度分析。"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

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
    "7. Historical profit probability for different holding periods.\n\n"
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
    "- `get_fund_list` and `get_open_fund_rank` for peer comparison.\n\n"
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

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "fund_analysis_report": report,
        }

    return fund_analyst_node
