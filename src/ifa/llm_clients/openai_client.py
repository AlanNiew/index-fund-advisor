import logging
import os
import uuid
from typing import Any

from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr

from ifa.providers import PROVIDER_CONFIG

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

logger = logging.getLogger(__name__)


class NormalizedChatOpenAI(ChatOpenAI):
    """对 ChatOpenAI 输出做内容规范化封装。

    Responses API 可能返回分块内容（如 reasoning、text 等），
    这里统一整理为字符串，便于后续链路稳定处理。
    """

    def invoke(self, input, config=None, **kwargs):
        """
        执行模型调用。

        参数：
            input: 输入内容。
            config: 运行时配置映射。
            kwargs: 透传给底层可调用对象的关键字参数。

        返回：
            Any: 规范化后的模型响应。
        """
        return normalize_content(super().invoke(input, config, **kwargs))

    # OpenCode Go 在思考模式下要求把历史 assistant 消息的 reasoning_content 原样回传，
    # 而 langchain_openai 在两个方向上都会丢弃该字段（_convert_message_to_dict 不输出、
    # _convert_dict_to_message 不提取）——只能在这里显式保留。默认关闭：
    # DeepSeek 官方 API 的规则相反（回传 reasoning_content 会 400），绝不能全局打开。
    _preserve_reasoning_content: bool = PrivateAttr(default=False)

    def _create_chat_result(self, response: Any, generation_info: dict | None = None) -> ChatResult:
        """
        构建调用结果，并保留网关返回的 reasoning_content。

        参数：
            response: 原始响应（dict 或 SDK 对象）。
            generation_info: 附加生成信息。

        返回：
            ChatResult: 标准化后的调用结果。
        """
        result = super()._create_chat_result(response, generation_info)
        if not self._preserve_reasoning_content:
            return result
        try:
            choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
            for choice, generations in zip(choices or [], result.generations, strict=False):
                reasoning = _extract_reasoning_content(choice)
                if not reasoning:
                    continue
                # generations 一般是单条 ChatGeneration，n>1 时才会是列表
                for generation in generations if isinstance(generations, list) else [generations]:
                    message = getattr(generation, "message", None)
                    if message is not None:
                        message.additional_kwargs.setdefault("reasoning_content", reasoning)
        except Exception:  # 保护层：提取失败不得影响正常返回
            logger.debug("提取 reasoning_content 失败", exc_info=True)
        return result

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        """
        构造请求体，并按需回传历史 assistant 消息的 reasoning_content。

        参数：
            input_: 本次调用的输入。
            stop: 停止词。
            kwargs: 其余透传参数。

        返回：
            dict: 请求体。
        """
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if not self._preserve_reasoning_content:
            return payload
        try:
            messages = self._convert_input(input_).to_messages()
            converted = payload.get("messages")
            if not isinstance(converted, list) or len(converted) != len(messages):
                return payload
            for message, out in zip(messages, converted, strict=False):
                if not isinstance(out, dict) or out.get("role") != "assistant":
                    continue
                reasoning = getattr(message, "additional_kwargs", {}).get("reasoning_content")
                if isinstance(reasoning, str) and reasoning:
                    out["reasoning_content"] = reasoning
        except Exception:  # 保护层：回传失败不得影响正常请求
            logger.debug("回传 reasoning_content 失败", exc_info=True)
        return payload


def _extract_reasoning_content(choice: Any) -> str | None:
    """从一条 choice 中取出 reasoning_content（兼容 dict 与 SDK 对象两种形态）。"""
    message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)
    if isinstance(message, dict):
        value = message.get("reasoning_content")
    elif message is None:
        value = None
    else:
        value = getattr(message, "reasoning_content", None)
        if not value:
            extra = getattr(message, "model_extra", None)
            value = extra.get("reasoning_content") if isinstance(extra, dict) else None
    return value if isinstance(value, str) and value else None


# 将用户配置中的 kwargs 透传给 ChatOpenAI
_PASSTHROUGH_KWARGS = (
    "timeout",
    "max_retries",
    "reasoning_effort",
    "api_key",
    "callbacks",
    "http_client",
    "http_async_client",
    "default_headers",
)

# OpenCode Go：订阅制聚合端点，走 OpenAI 兼容协议（Chat Completions）。
# 该服务明确要求客户端「自报身份」并携带稳定会话 ID（文档 "Where can I use it?"）：
#   - 用通用 SDK 名（如 openai-python）发请求会被视为非典型客户端；
#   - x-opencode-session 用于服务端优化路由与提示缓存。
# 因此 opencode 提供方会额外注入 default_headers，见 OpenAIClient.get_llm()。
_OPENCODE_BASE_URL = "https://opencode.ai/inference/go/v1"
_OPENCODE_API_KEY_ENV = "OPENCODE_API_KEY"
# 与 pyproject.toml 的 version 保持一致（tests/test_llm_clients.py 会校验二者一致）。
_OPENCODE_USER_AGENT = "index-fund-advisor/0.1.0"
# 进程级会话 ID：一次 ifa 运行内的全部 LLM 调用（各 Agent、各轮辩论）共享同一会话，
# 这正是该头部想表达的「同一个对话」。可用环境变量 OPENCODE_SESSION_ID 覆盖
# （例如由外层编排器为每次真实对话注入不同 ID）。
_OPENCODE_SESSION_ID = uuid.uuid4().hex


def _opencode_session_id() -> str:
    """返回本次会话标识，供 OpenCode Go 优化路由与提示缓存。"""
    return os.environ.get("OPENCODE_SESSION_ID") or _OPENCODE_SESSION_ID


# 各提供方的基础地址与 API Key 环境变量：单一事实来源在 ifa/providers.py
# （default_config 也要用它做 backend_url 归一化，而它不能导入 langchain）。
_PROVIDER_CONFIG = PROVIDER_CONFIG


class OpenAIClient(BaseLLMClient):
    """面向 OpenAI、Ollama、OpenRouter、xAI、OpenCode Go 及自定义端点的客户端封装。

    原生 OpenAI 模型默认使用 /v1/responses，以支持统一的 reasoning_effort
    与工具调用行为；兼容提供方（含 opencode 与 custom）继续使用标准
    Chat Completions 接口。
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        provider: str = "openai",
        **kwargs,
    ):
        """
        初始化对象。

        参数：
            model: 模型标识。
            base_url: 基础接口地址。
            provider: 模型提供方名称。
            kwargs: 透传给底层可调用对象的关键字参数。

        返回：
            None: 无返回值。
        """
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """
        返回配置好的 ChatOpenAI 实例。

        返回：
            Any: 配置完成的 ChatOpenAI 实例。
        """
        self.warn_if_unknown_model()
        llm_kwargs: dict[str, Any] = {"model": self.model}

        # 提供方专属的基础地址与鉴权参数。
        # 显式配置的 base_url（self.base_url）优先于内置端点：企业内网代理、自建网关上
        # 复用同一提供方协议时可直接覆盖。provider="custom" 没有内置端点，必须显式给。
        spec = _PROVIDER_CONFIG.get(self.provider)
        base_url = self.base_url or (spec.base_url if spec else None)
        if base_url:
            llm_kwargs["base_url"] = base_url

        if self.provider == "custom" and not base_url:
            raise ValueError(
                "llm_provider='custom' 必须提供 backend_url（自定义端点的 OpenAI 兼容地址，"
                "形如 https://your-gateway/v1）。设置方式：ifa config backend_url <url>，"
                "或环境变量 IFA_BACKEND_URL。"
            )

        if spec is not None and spec.api_key_env:
            api_key = os.environ.get(spec.api_key_env)
            if api_key:
                llm_kwargs["api_key"] = api_key
        elif spec is not None:
            # 本地 Ollama 不校验 Key，但底层 SDK 要求非空值
            llm_kwargs["api_key"] = "ollama"

        # 继续透传用户提供的 kwargs
        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # 原生 OpenAI：使用 Responses API，以在不同模型家族间保持一致行为
        # 第三方兼容提供方则继续使用 Chat Completions。
        if self.provider == "openai":
            llm_kwargs["use_responses_api"] = True

        # OpenCode Go 要求客户端自报身份并携带稳定会话 ID：缺失时服务端会按通用
        # SDK 客户端处理，且无法为同一对话复用路由与提示缓存。
        # 用户显式传入的 default_headers 优先级最高（可覆盖 User-Agent）。
        if self.provider == "opencode":
            headers: dict[str, str] = {"User-Agent": _OPENCODE_USER_AGENT}
            user_headers = self.kwargs.get("default_headers")
            if isinstance(user_headers, dict):
                headers.update(user_headers)
            headers["x-opencode-session"] = self.kwargs.get("opencode_session_id") or _opencode_session_id()
            llm_kwargs["default_headers"] = headers

        llm = NormalizedChatOpenAI(**llm_kwargs)

        # OpenCode Go 在思考模式下要求回传历史 assistant 消息的 reasoning_content，
        # 缺失时上游会以 400 拒绝整个请求（间歇出现：是否进思考模式由上游按请求决定）。
        # 只对 opencode 打开——DeepSeek 官方 API 的规则相反。
        if self.provider == "opencode":
            llm._preserve_reasoning_content = True

        return llm

    def validate_model(self) -> bool:
        """
        校验模型是否适用于当前提供方。

        返回：
            bool: 条件满足时返回 True，否则返回 False。
        """
        return validate_model(self.provider, self.model)
