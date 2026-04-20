import warnings
from abc import ABC, abstractmethod
from typing import Any


def normalize_content(response):
    """
    将 LLM 响应内容规范化为普通字符串。

    参数：
        response: 需要规范化或检查的模型响应对象。

    返回：
        Any: 规范化后的响应对象。
    """
    content = response.content
    if isinstance(content, list):
        texts = [
            item.get("text", "")
            if isinstance(item, dict) and item.get("type") == "text"
            else item
            if isinstance(item, str)
            else ""
            for item in content
        ]
        response.content = "\n".join(t for t in texts if t)
    return response


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

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
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs

    def get_provider_name(self) -> str:
        """
        返回告警信息中使用的提供方名称。

        返回：
            str: 当前查询结果。
        """
        provider = getattr(self, "provider", None)
        if provider:
            return str(provider)
        return self.__class__.__name__.removesuffix("Client").lower()

    def warn_if_unknown_model(self) -> None:
        """
        当模型不在该提供方的已知列表中时发出告警。

        返回：
            None: 无返回值。
        """
        if self.validate_model():
            return

        warnings.warn(
            (
                f"Model '{self.model}' is not in the known model list for "
                f"provider '{self.get_provider_name()}'. Continuing anyway."
            ),
            RuntimeWarning,
            stacklevel=2,
        )

    @abstractmethod
    def get_llm(self) -> Any:
        """
        返回配置好的 LLM 实例。

        返回：
            Any: 当前查询结果。
        """
        pass

    @abstractmethod
    def validate_model(self) -> bool:
        """
        校验该客户端是否支持当前模型。

        返回：
            bool: 条件满足时返回 True，否则返回 False。
        """
        pass
