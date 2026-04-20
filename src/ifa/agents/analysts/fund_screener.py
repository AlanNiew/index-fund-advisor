# ifa/agents/analysts/fund_screener.py
"""基金筛选器 —— 根据条件筛选并初步评估指数基金候选列表。"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from ifa.agents.tools.public_fund_tools import (
    get_etf_spot_data,
    get_fund_basic_info,
    get_fund_list,
    get_index_fund_filter,
    get_open_fund_rank,
)
from ifa.agents.utils import (
    get_internal_language_instruction,
    invoke_chain_safely,
)

_FUND_SCREENER_SYSTEM_MESSAGE = (
    "You are an A-share index fund screener. "
    "Your task is to screen and filter index funds based on user-specified conditions.\n\n"
    "Steps:\n"
    "1. Understand the user's screening criteria (index category, tracking method, size, etc.);\n"
    "2. Call `get_index_fund_filter` with appropriate parameters;\n"
    "3. Optionally call `get_fund_list` or `get_open_fund_rank` for supplementary data;\n"
    "4. Call `get_fund_basic_info` for top candidates to get size and fee details;\n"
    "5. Call `get_etf_spot_data` if ETF real-time data is needed.\n\n"
    "Output a ranked list of candidate funds with key metrics:\n"
    "- Fund code, name, type\n"
    "- Size (AUM)\n"
    "- Tracking error / expense ratio\n"
    "- Recent performance summary\n"
    "Limit to top 10-15 candidates unless the user specifies otherwise."
)


def create_fund_screener(llm):
    """创建并返回基金筛选器节点。"""

    def fund_screener_node(state):
        current_date = state["analysis_date"]

        tools = [
            get_fund_list,
            get_fund_basic_info,
            get_index_fund_filter,
            get_open_fund_rank,
            get_etf_spot_data,
        ]

        system_message = _FUND_SCREENER_SYSTEM_MESSAGE + get_internal_language_instruction()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant. Use the provided tools to screen funds."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}.",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)

        chain = prompt | llm.bind_tools(tools)
        result = invoke_chain_safely(chain, state["messages"])

        screen_results = ""
        if len(result.tool_calls) == 0:
            screen_results = result.content

        return {
            "messages": [result],
            "screen_results": screen_results,
        }

    return fund_screener_node
