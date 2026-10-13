from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model


class NormalizedChatGoogleGenerativeAI(ChatGoogleGenerativeAI):
    """对 ChatGoogleGenerativeAI 输出做内容规范化封装。

    Gemini 3 模型可能返回分块内容，这里统一整理为字符串，
    便于后续链路稳定处理。
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


class GoogleClient(BaseLLMClient):
    """Google Gemini 模型客户端封装。"""

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
        返回配置好的 ChatGoogleGenerativeAI 实例。

        返回：
            Any: 配置完成的 ChatGoogleGenerativeAI 实例。
        """
        self.warn_if_unknown_model()
        llm_kwargs: dict[str, Any] = {"model": self.model}

        if self.base_url:
            llm_kwargs["base_url"] = self.base_url

        for key in ("timeout", "max_retries", "callbacks", "http_client", "http_async_client"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # 统一的 api_key 会映射为 google 专用的 google_api_key
        google_api_key = self.kwargs.get("api_key") or self.kwargs.get("google_api_key")
        if google_api_key:
            llm_kwargs["google_api_key"] = google_api_key

        # 按模型类型将 thinking_level 映射到对应接口参数
        # Gemini 3 Pro：支持 low、high
        # Gemini 3 Flash：支持 minimal、low、medium、high
        # Gemini 2.5：使用 thinking_budget（0=关闭，-1=动态）
        thinking_level = self.kwargs.get("thinking_level")
        if thinking_level:
            model_lower = self.model.lower()
            if "gemini-3" in model_lower:
                # Gemini 3 Pro 不支持 "minimal"，这里改用 "low"
                if "pro" in model_lower and thinking_level == "minimal":
                    thinking_level = "low"
                llm_kwargs["thinking_level"] = thinking_level
            else:
                # Gemini 2.5：映射到 thinking_budget
                llm_kwargs["thinking_budget"] = -1 if thinking_level == "high" else 0

        return NormalizedChatGoogleGenerativeAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """
        校验模型是否适用于 Google。

        返回：
            bool: 条件满足时返回 True，否则返回 False。
        """
        return validate_model("google", self.model)
