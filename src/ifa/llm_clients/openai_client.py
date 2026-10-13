import os
import uuid
from typing import Any

from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model


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


# 各提供方的基础地址与 API Key 环境变量
_PROVIDER_CONFIG = {
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
    "qwen": ("https://coding.dashscope.aliyuncs.com/v1", "QWEN_API_KEY"),
    "zhipu": ("https://open.bigmodel.cn/api/coding/paas/v4", "ZHIPUAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "opencode": (_OPENCODE_BASE_URL, _OPENCODE_API_KEY_ENV),
}


class OpenAIClient(BaseLLMClient):
    """面向 OpenAI、Ollama、OpenRouter、xAI 与 OpenCode Go 的客户端封装。

    原生 OpenAI 模型默认使用 `/v1/responses`，以支持统一的
    `reasoning_effort` 与工具调用行为；兼容提供方（含 opencode）
    继续使用标准 Chat Completions 接口。
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

        # 提供方专属的基础地址与鉴权参数
        if self.provider in _PROVIDER_CONFIG:
            base_url, api_key_env = _PROVIDER_CONFIG[self.provider]
            llm_kwargs["base_url"] = base_url
            if api_key_env:
                api_key = os.environ.get(api_key_env)
                if api_key:
                    llm_kwargs["api_key"] = api_key
            else:
                llm_kwargs["api_key"] = "ollama"
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

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

        return NormalizedChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """
        校验模型是否适用于当前提供方。

        返回：
            bool: 条件满足时返回 True，否则返回 False。
        """
        return validate_model(self.provider, self.model)
