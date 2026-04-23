# ifa/agents/analysts/index_analyst.py
"""成分股/指数分析师 —— 分析 ETF/指数的成分股和行业分布。"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from ifa.agents.tools.constituent_tools import (
    get_constituent_overview,
    get_constituent_performance,
    get_constituent_sector_distribution,
)
from ifa.agents.tools.etf_index_tools import get_etf_fund_info
from ifa.agents.tools.macro_tools import (
    get_index_valuation,
    get_macro_indicator,
    get_market_fund_flow,
    get_market_valuation,
    get_north_flow,
    get_sector_fund_flow,
    get_valuation_signal,
)
from ifa.agents.utils import (
    build_instrument_context,
    get_internal_language_instruction,
    invoke_chain_safely,
)

_INDEX_ANALYST_SYSTEM_MESSAGE = (
    "You are an A-share index/ETF constituent analyst. "
    "Analyze the weight distribution, sector allocation, and performance "
    "of the top constituent stocks in the target index or ETF fund.\n\n"
    "Focus on:\n"
    "1. Top-10 heavy-weight stocks' recent performance and trend;\n"
    "2. Sector concentration risk and industry rotation signals;\n"
    "3. Whether leading constituents support or drag the index/ETF;\n"
    "4. Style exposure (large-cap vs small-cap, growth vs value);\n"
    "5. Fund profile data (size, expense ratio, tracking index) if available.\n\n"
    "Use the available tools:\n"
    "- `get_constituent_overview` for top-weight stocks summary;\n"
    "- `get_constituent_sector_distribution` for industry breakdown;\n"
    "- `get_constituent_performance` for recent price action of key stocks;\n"
    "- `get_etf_fund_info` for fund profile data.\n"
    "- `get_macro_indicator` for macro environment context;\n"
    "- `get_north_flow` for northbound capital flow;\n"
    "- `get_market_fund_flow` for market-wide fund flow;\n"
    "- `get_sector_fund_flow` for sector capital flow ranking;\n"
    "- `get_market_valuation` for market/index PE/PB valuation.\n"
    "- `get_index_valuation` for comprehensive index valuation analysis with historical percentiles.\n"
    "- `get_valuation_signal` for valuation investment signals using EY/Bogle PE/Bogle PB methods.\n\n"
    "Append a Markdown table at the end."
)


def create_index_analyst(llm):
    """创建并返回成分股分析师节点。"""

    def index_analyst_node(state):
        current_date = state["analysis_date"]
        instrument_context = build_instrument_context(state["fund_codes"])

        tools = [
            get_constituent_overview,
            get_constituent_sector_distribution,
            get_constituent_performance,
            get_etf_fund_info,
            # 宏观经济 / 市场情绪 / 行业估值
            get_macro_indicator,
            get_north_flow,
            get_market_fund_flow,
            get_sector_fund_flow,
            get_market_valuation,
            get_index_valuation,
            get_valuation_signal,
        ]

        system_message = _INDEX_ANALYST_SYSTEM_MESSAGE + get_internal_language_instruction()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant. Use the provided tools to analyze the index/ETF."
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
            "index_analysis_report": report,
        }

    return index_analyst_node
