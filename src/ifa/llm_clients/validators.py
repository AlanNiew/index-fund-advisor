"""各提供方的模型名称校验器。"""

from .model_catalog import get_known_models

VALID_MODELS = {
    provider: models for provider, models in get_known_models().items() if provider not in ("ollama", "openrouter")
}


def validate_model(provider: str, model: str) -> bool:
    """
    检查模型名称是否适用于指定提供方。

    参数：
        provider: 模型提供方名称。
        model: 模型标识。

    返回：
        bool: 条件满足时返回 True，否则返回 False。
    """
    provider_lower = provider.lower()

    # 模型清单由用户/服务端决定，本地无从校验的提供方一律放行
    # （custom 是任意 OpenAI 兼容端点，模型名当然不在内置目录里）。
    if provider_lower in ("ollama", "openrouter", "azure", "custom"):
        return True

    if provider_lower not in VALID_MODELS:
        return True

    return model in VALID_MODELS[provider_lower]
