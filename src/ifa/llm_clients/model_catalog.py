"""Shared model catalog for CLI selections and validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

ModelOption = tuple[str, str]
ProviderModeOptions = dict[str, dict[str, list[ModelOption]]]

_CUSTOM_CATALOG_PATH = Path(os.environ.get("IFA_MODEL_CATALOG", ""))


def _load_custom_catalog() -> ProviderModeOptions | None:
    """从环境变量 IFA_MODEL_CATALOG 指向的 JSON 文件加载自定义模型目录。"""
    if not _CUSTOM_CATALOG_PATH.exists():
        return None
    try:
        data = json.loads(_CUSTOM_CATALOG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


MODEL_OPTIONS: ProviderModeOptions = {
    "openai": {
        "quick": [
            ("GPT-5.4 Mini - Fast, strong coding and tool use", "gpt-5.4-mini"),
            ("GPT-5.4 Nano - Cheapest, high-volume tasks", "gpt-5.4-nano"),
            ("GPT-5.4 - Latest frontier, 1M context", "gpt-5.4"),
            ("GPT-4.1 - Smartest non-reasoning model", "gpt-4.1"),
        ],
        "deep": [
            ("GPT-5.4 - Latest frontier, 1M context", "gpt-5.4"),
            ("GPT-5.2 - Strong reasoning, cost-effective", "gpt-5.2"),
            ("GPT-5.4 Mini - Fast, strong coding and tool use", "gpt-5.4-mini"),
            ("GPT-5.4 Pro - Most capable, expensive ($30/$180 per 1M tokens)", "gpt-5.4-pro"),
        ],
    },
    "anthropic": {
        "quick": [
            ("Claude Sonnet 4.6 - Best speed and intelligence balance", "claude-sonnet-4-6"),
            ("Claude Haiku 4.5 - Fast, near-instant responses", "claude-haiku-4-5"),
            ("Claude Sonnet 4.5 - Agents and coding", "claude-sonnet-4-5"),
        ],
        "deep": [
            ("Claude Opus 4.6 - Most intelligent, agents and coding", "claude-opus-4-6"),
            ("Claude Opus 4.5 - Premium, max intelligence", "claude-opus-4-5"),
            ("Claude Sonnet 4.6 - Best speed and intelligence balance", "claude-sonnet-4-6"),
            ("Claude Sonnet 4.5 - Agents and coding", "claude-sonnet-4-5"),
        ],
    },
    "google": {
        "quick": [
            ("Gemini 3 Flash - Next-gen fast", "gemini-3-flash-preview"),
            ("Gemini 2.5 Flash - Balanced, stable", "gemini-2.5-flash"),
            ("Gemini 3.1 Flash Lite - Most cost-efficient", "gemini-3.1-flash-lite-preview"),
            ("Gemini 2.5 Flash Lite - Fast, low-cost", "gemini-2.5-flash-lite"),
        ],
        "deep": [
            ("Gemini 3.1 Pro - Reasoning-first, complex workflows", "gemini-3.1-pro-preview"),
            ("Gemini 3 Flash - Next-gen fast", "gemini-3-flash-preview"),
            ("Gemini 2.5 Pro - Stable pro model", "gemini-2.5-pro"),
            ("Gemini 2.5 Flash - Balanced, stable", "gemini-2.5-flash"),
        ],
    },
    "xai": {
        "quick": [
            ("Grok 4.1 Fast (Non-Reasoning) - Speed optimized, 2M ctx", "grok-4-1-fast-non-reasoning"),
            ("Grok 4 Fast (Non-Reasoning) - Speed optimized", "grok-4-fast-non-reasoning"),
            ("Grok 4.1 Fast (Reasoning) - High-performance, 2M ctx", "grok-4-1-fast-reasoning"),
        ],
        "deep": [
            ("Grok 4 - Flagship model", "grok-4-0709"),
            ("Grok 4.1 Fast (Reasoning) - High-performance, 2M ctx", "grok-4-1-fast-reasoning"),
            ("Grok 4 Fast (Reasoning) - High-performance", "grok-4-fast-reasoning"),
            ("Grok 4.1 Fast (Non-Reasoning) - Speed optimized, 2M ctx", "grok-4-1-fast-non-reasoning"),
        ],
    },
    "openrouter": {
        "quick": [
            ("NVIDIA Nemotron 3 Nano 30B (free)", "nvidia/nemotron-3-nano-30b-a3b:free"),
            ("Z.AI GLM 4.5 Air (free)", "z-ai/glm-4.5-air:free"),
        ],
        "deep": [
            ("Z.AI GLM 4.5 Air (free)", "z-ai/glm-4.5-air:free"),
            ("NVIDIA Nemotron 3 Nano 30B (free)", "nvidia/nemotron-3-nano-30b-a3b:free"),
        ],
    },
    "ollama": {
        "quick": [
            ("Qwen3:latest (8B, local)", "qwen3:latest"),
            ("GPT-OSS:latest (20B, local)", "gpt-oss:latest"),
            ("GLM-4.7-Flash:latest (30B, local)", "glm-4.7-flash:latest"),
        ],
        "deep": [
            ("GLM-4.7-Flash:latest (30B, local)", "glm-4.7-flash:latest"),
            ("GPT-OSS:latest (20B, local)", "gpt-oss:latest"),
            ("Qwen3:latest (8B, local)", "qwen3:latest"),
        ],
    },
    "qwen": {
        "quick": [
            ("Qwen qwen3.5-plus", "qwen3.5-plus"),
        ],
        "deep": [
            ("Qwen qwen3.5-plus", "qwen3.5-plus"),
        ],
    },
    "zhipu": {
        "quick": [
            ("GLM-5 Turbo - Fast, cost-effective", "glm-5-turbo"),
        ],
        "deep": [
            ("GLM-5.2 - Most capable", "glm-5.2"),
            ("GLM-5.1 - Advanced reasoning", "glm-5.1"),
            ("GLM-5 Turbo - Fast, cost-effective", "glm-5-turbo"),
        ],
    },
    "deepseek": {
        "quick": [
            ("DeepSeek Chat - Fast, cost-effective", "deepseek-v4-flash"),
        ],
        "deep": [
            ("DeepSeek Reasoner - Advanced reasoning", "deepseek-v4-pro"),
            ("DeepSeek Chat - Fast, cost-effective", "deepseek-v4-flash"),
        ],
    },
}


def get_model_options(provider: str, mode: str) -> list[ModelOption]:
    """
    返回指定提供方和选择模式对应的模型选项。

    优先使用自定义目录（IFA_MODEL_CATALOG 环境变量），回退到内置目录。

    参数：
        provider: 模型提供方名称。
        mode: 当前查询对应的选择模式。

    返回：
        List[ModelOption]: 当前查询结果。
    """
    catalog = _load_custom_catalog() or MODEL_OPTIONS
    return catalog[provider.lower()][mode]


def get_known_models() -> dict[str, list[str]]:
    """
    根据共享 CLI 目录构建已知模型名称集合。

    返回：
        Dict[str, List[str]]: 当前查询结果。
    """
    return {
        provider: sorted({value for options in mode_options.values() for _, value in options})
        for provider, mode_options in MODEL_OPTIONS.items()
    }
