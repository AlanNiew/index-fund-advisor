# ifa/agents/utils.py
"""Agent 工具函数，精简自 tradingagents，移除个股相关 import。"""

import logging
import time

from langchain_core.messages import HumanMessage, RemoveMessage

from ifa.dataflows.asset_type import AssetType, detect_asset_type, get_asset_label

logger = logging.getLogger(__name__)


class AgentLLMError(Exception):
    """Agent 调用 LLM 时重试耗尽后抛出的异常。"""


#: 辩论历史进入 prompt 时的字符上限。
#: 辩论上下文逐轮增长，而每个辩手每轮都要重读整段历史——2026-10 实测 510300 的 deep
#: 运行 wall 30.4 分钟，辩论段独占 86%，上下文大小是主要成本。截断时保留**末尾**
#: （最新发言）：越新的反驳越决定下一轮该怎么接。
DEBATE_HISTORY_MAX_CHARS = 3000


def truncate_debate_history(text: str, max_chars: int = DEBATE_HISTORY_MAX_CHARS) -> str:
    """截断过长的辩论历史，保留最新发言。

    与 truncate_report 的方向相反：报告开头是结论（保留头部），辩论则越靠后的发言越
    重要（从头部丢弃）。只用于构造 prompt，state 里的全文不受影响。
    """
    if not text or len(text) <= max_chars:
        return text
    return "[... 较早的辩论发言已省略 ...]\n\n" + text[-max_chars:]


def _resolve_retries(retries: int | None) -> int:
    """确定重试次数：显式参数优先，否则读运行时配置 llm_max_retries。"""
    if retries is not None:
        return max(0, int(retries))

    from ifa.dataflows.config import get_config
    from ifa.default_config import DEFAULT_LLM_MAX_RETRIES

    configured = get_config().get("llm_max_retries")
    if isinstance(configured, int) and not isinstance(configured, bool) and configured >= 0:
        return configured
    return DEFAULT_LLM_MAX_RETRIES


def invoke_llm_safely(llm, prompt, retries: int | None = None, base_delay: float = 1.0):
    """带指数退避重试的 LLM 安全调用。

    retries: 重试次数（总尝试次数 = retries + 1）；None 时读配置 llm_max_retries。
    """
    retries = _resolve_retries(retries)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return llm.invoke(prompt)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "LLM 调用失败（第 %d/%d 次重试，%s），%.1f 秒后重试: %s",
                    attempt + 1,
                    retries,
                    type(exc).__name__,
                    delay,
                    exc,
                )
                time.sleep(delay)
            else:
                logger.error("LLM 调用在 %d 次重试后仍然失败: %s", retries, exc)
    raise AgentLLMError(f"LLM 调用失败，已重试 {retries} 次: {last_exc}") from last_exc


def invoke_chain_safely(chain, input_data, retries: int | None = None, base_delay: float = 1.0):
    """带指数退避重试的 LangChain 链安全调用。

    retries: 重试次数（总尝试次数 = retries + 1）；None 时读配置 llm_max_retries。
    """
    retries = _resolve_retries(retries)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return chain.invoke(input_data)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Chain 调用失败（第 %d/%d 次重试，%s），%.1f 秒后重试: %s",
                    attempt + 1,
                    retries,
                    type(exc).__name__,
                    delay,
                    exc,
                )
                time.sleep(delay)
            else:
                logger.error("Chain 调用在 %d 次重试后仍然失败: %s", retries, exc)
    raise AgentLLMError(f"Chain 调用失败，已重试 {retries} 次: {last_exc}") from last_exc


def _build_language_instruction(language: str, usage_label: str) -> str:
    """为指定语言与用途生成提示语。"""
    lang = (language or "").strip() or "English"
    if lang.lower() == "english":
        return ""
    return (
        f" Write all narrative text, section headings, bullet labels, and summaries in {lang}."
        f" Treat this as the selected {usage_label}."
        " Translate default English headings unless an explicit machine-readable token is required."
    )


def get_internal_language_instruction() -> str:
    """返回与当前内部语言匹配的提示语。"""
    return _build_language_instruction(get_internal_language(), "internal language")


def get_final_language_instruction() -> str:
    """返回与当前最终语言匹配的提示语。"""
    return _build_language_instruction(get_final_output_language(), "final output language")


def get_language_instruction() -> str:
    """兼容旧接口，返回当前最终语言匹配的提示语。"""
    return get_final_language_instruction()


def get_internal_language() -> str:
    """获取当前配置的内部语言。"""
    from ifa.dataflows.config import get_config

    return str(get_config().get("internal_language", "English")).strip()


def get_final_output_language() -> str:
    """获取当前配置的最终输出语言。"""
    from ifa.dataflows.config import get_config

    config = get_config()
    return str(config.get("final_output_language", config.get("output_language", "Chinese"))).strip()


def get_output_language() -> str:
    """兼容旧接口。"""
    return get_final_output_language()


def build_instrument_context(ticker: str) -> str:
    """描述精确的 A 股标的，根据资产类型自动调整描述文本。"""
    asset_type = detect_asset_type(ticker)
    label = get_asset_label(asset_type)

    type_hint = (
        f"The instrument to analyze is `{ticker}` (a {label['instrument_cn']}). "
        "Use this exact A-share ticker in every tool call, report, and recommendation, "
        "preserving the market suffix `.SH`, `.SZ`, or `.BJ`."
    )

    if asset_type in (AssetType.ETF, AssetType.INDEX):
        type_hint += (
            f" This is a {label['instrument_noun']}, not an individual stock. "
            "Use fund analysis and constituent analysis tools."
        )
    elif asset_type in (AssetType.OFFSHORE_FUND, AssetType.PUBLIC_FUND):
        type_hint += f" This is a {label['instrument_noun']}. Use public fund analysis tools."

    return type_hint


def create_msg_delete():
    """创建消息清理函数，用于 Agent 间的消息隔离。"""

    def delete_messages(state):
        messages = state["messages"]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]
        placeholder = HumanMessage(content="Continue")
        return {"messages": removal_operations + [placeholder]}

    return delete_messages
