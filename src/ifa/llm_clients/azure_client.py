import os
from typing import Any

from langchain_core.messages import AIMessage
from langchain_openai import AzureChatOpenAI
from openai import BadRequestError

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model


class NormalizedAzureChatOpenAI(AzureChatOpenAI):
    """对 AzureChatOpenAI 输出做内容规范化与内容过滤容错封装。"""

    content_filter_max_retries: int = 2
    content_filter_skip_message: str = "Skipped due to Azure content policy filter."

    def _extract_error_payload(self, exc: BadRequestError) -> str:
        """
        提取异常中可用于判断内容过滤的文本。

        参数：
            exc: Azure OpenAI 返回的请求异常。

        返回：
            str: 展平后的错误文本。
        """
        parts = [str(exc)]

        body = getattr(exc, "body", None)
        if body is not None:
            parts.append(str(body))

        response = getattr(exc, "response", None)
        if response is not None:
            try:
                parts.append(str(response.json()))
            except Exception:
                parts.append(str(response))

        return "\n".join(part for part in parts if part)

    def _is_content_filter_error(self, exc: BadRequestError) -> bool:
        """
        判断异常是否为 Azure 内容过滤错误。

        参数：
            exc: Azure OpenAI 返回的请求异常。

        返回：
            bool: 命中过滤时返回 True，否则返回 False。
        """
        payload = self._extract_error_payload(exc)
        markers = (
            "content_filter",
            "ResponsibleAIPolicyViolation",
            "content management policy",
        )
        return any(marker in payload for marker in markers)

    def _build_skip_response(self) -> AIMessage:
        """
        构造内容过滤后的跳过响应。

        返回：
            AIMessage: 用于替代异常中断的占位响应。
        """
        return AIMessage(content=self.content_filter_skip_message)

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
        max_attempts = max(1, int(getattr(self, "content_filter_max_retries", 0)) + 1)

        for attempt in range(max_attempts):
            try:
                return normalize_content(super().invoke(input, config, **kwargs))
            except BadRequestError as exc:
                if not self._is_content_filter_error(exc):
                    raise
                if attempt == max_attempts - 1:
                    return normalize_content(self._build_skip_response())

        return normalize_content(self._build_skip_response())


class AzureClient(BaseLLMClient):
    """Azure OpenAI 模型客户端封装。"""

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        """
        初始化对象。

        参数：
            model: Azure OpenAI deployment 名称。
            base_url: Azure OpenAI endpoint。
            kwargs: 透传给底层可调用对象的关键字参数。

        返回：
            None: 无返回值。
        """
        super().__init__(model, base_url, **kwargs)
        self.provider = "azure"

    def get_llm(self) -> Any:
        """
        返回配置好的 AzureChatOpenAI 实例。

        返回：
            Any: 配置完成的 AzureChatOpenAI 实例。
        """
        self.warn_if_unknown_model()
        llm_kwargs = {
            "azure_deployment": self.model,
        }

        azure_endpoint = self.base_url
        if azure_endpoint:
            llm_kwargs["azure_endpoint"] = azure_endpoint

        api_key = self.kwargs.get("api_key") or os.environ.get("AZURE_API_KEY")
        if not api_key:
            raise RuntimeError("未检测到 Azure API Key，请设置环境变量 AZURE_API_KEY。")
        if api_key:
            llm_kwargs["api_key"] = api_key

        api_version = self.kwargs.get("azure_api_version") or self.kwargs.get("api_version")
        if api_version:
            llm_kwargs["api_version"] = api_version

        for key in (
            "timeout",
            "max_retries",
            "reasoning_effort",
            "callbacks",
            "http_client",
            "http_async_client",
            "use_responses_api",
        ):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        llm = NormalizedAzureChatOpenAI(**llm_kwargs)
        llm.content_filter_max_retries = int(self.kwargs.get("content_filter_max_retries", 2))
        llm.content_filter_skip_message = self.kwargs.get(
            "content_filter_skip_message",
            "Skipped due to Azure content policy filter.",
        )
        return llm

    def validate_model(self) -> bool:
        """
        校验模型是否适用于 Azure OpenAI。

        返回：
            bool: 条件满足时返回 True，否则返回 False。
        """
        return validate_model("azure", self.model)
