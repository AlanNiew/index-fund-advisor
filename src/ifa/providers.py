# ifa/providers.py
"""LLM 提供方清单 —— 基础地址、API Key 环境变量、展示名的单一事实来源。

为什么放在包顶层（而不是 `ifa/llm_clients/providers.py`）：
`ifa.default_config` 需要在不导入任何 LLM 依赖的前提下做提供方校验与 backend_url
归一化（`ifa config` / `ifa search` / `ifa info` 都不该为了读一个配置项就把
langchain 全套拉起来）。而 `ifa.llm_clients.__init__` 会 re-export
`create_llm_client`，导入它的任何子模块都会连带导入 factory → langchain_openai。
因此这张表必须待在零依赖的位置，由 `default_config` 与 `llm_clients` 共同引用。
"""

from __future__ import annotations

from typing import NamedTuple


class ProviderSpec(NamedTuple):
    """一个 LLM 提供方的静态描述。

    base_url 为 None 表示「没有内置端点」：要么由 SDK 默认值决定（openai/anthropic/
    google/azure），要么必须由用户显式配置（custom）。
    """

    base_url: str | None
    api_key_env: str | None
    label: str


#: 全部受支持的提供方。`custom` 是兜底入口：任何 OpenAI 兼容端点都可用它接入
#: （自建网关、公司内网、vLLM / Ollama / one-api 等），端点与 Key 由用户配置。
PROVIDER_CONFIG: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(None, "OPENAI_API_KEY", "OpenAI"),
    "anthropic": ProviderSpec(None, "ANTHROPIC_API_KEY", "Anthropic Claude"),
    "google": ProviderSpec(None, "GOOGLE_API_KEY", "Google Gemini"),
    "azure": ProviderSpec(None, "AZURE_OPENAI_API_KEY", "Azure OpenAI"),
    "deepseek": ProviderSpec("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "DeepSeek 官方"),
    "qwen": ProviderSpec("https://coding.dashscope.aliyuncs.com/v1", "QWEN_API_KEY", "通义千问（DashScope）"),
    "zhipu": ProviderSpec("https://open.bigmodel.cn/api/coding/paas/v4", "ZHIPUAI_API_KEY", "智谱 GLM"),
    "xai": ProviderSpec("https://api.x.ai/v1", "XAI_API_KEY", "xAI Grok"),
    "openrouter": ProviderSpec("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OpenRouter"),
    "ollama": ProviderSpec("http://localhost:11434/v1", None, "本地 Ollama（无需 Key）"),
    "opencode": ProviderSpec("https://opencode.ai/inference/go/v1", "OPENCODE_API_KEY", "OpenCode Go"),
    "custom": ProviderSpec(None, "IFA_CUSTOM_API_KEY", "自定义（任意 OpenAI 兼容端点）"),
}

#: 走 OpenAI 兼容协议（/chat/completions）的提供方；其余各有专用客户端。
OPENAI_COMPATIBLE_PROVIDERS = frozenset(
    {"openai", "ollama", "openrouter", "qwen", "zhipu", "deepseek", "opencode", "custom"}
)


def default_base_url(provider: str) -> str | None:
    """提供方的内置端点；未知提供方或没有内置端点时返回 None。"""
    spec = PROVIDER_CONFIG.get(provider.strip().lower())
    return spec.base_url if spec else None


def api_key_env(provider: str) -> str | None:
    """提供方读取 API Key 的环境变量名；无需 Key 时为 None。"""
    spec = PROVIDER_CONFIG.get(provider.strip().lower())
    return spec.api_key_env if spec else None


def provider_label(provider: str) -> str:
    """面向用户的展示名；未知提供方原样返回。"""
    spec = PROVIDER_CONFIG.get(provider.strip().lower())
    return spec.label if spec else provider


def canonical_base_urls() -> set[str]:
    """所有内置端点 —— 用于识别「配置里残留了别的提供方的地址」。"""
    return {spec.base_url for spec in PROVIDER_CONFIG.values() if spec.base_url}
