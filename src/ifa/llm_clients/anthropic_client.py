from typing import Any

from langchain_anthropic import ChatAnthropic

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

_PASSTHROUGH_KWARGS = (
    "timeout",
    "max_retries",
    "api_key",
    "max_tokens",
    "callbacks",
    "http_client",
    "http_async_client",
    "effort",
)


class NormalizedChatAnthropic(ChatAnthropic):
    """对 ChatAnthropic 输出做内容规范化封装。

    Claude 在开启扩展思考或工具调用时，可能返回分块内容；
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


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude 模型客户端封装。"""

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        """
        初始化对象。

        参数：
            model: 模型标识。
            base_url: 基础接口地址。
            kwargs: 透传给底层可调用对象的关键字参数。

        返回：
            None: 无返回值。
        """
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """
        返回配置好的 ChatAnthropic 实例。

        返回：
            Any: 配置完成的 ChatAnthropic 实例。
        """
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        if self.base_url:
            llm_kwargs["base_url"] = self.base_url

        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        return NormalizedChatAnthropic(**llm_kwargs)

    def validate_model(self) -> bool:
        """
        校验模型是否适用于 Anthropic。

        返回：
            bool: 条件满足时返回 True，否则返回 False。
        """
        return validate_model("anthropic", self.model)
