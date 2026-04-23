"""LLM 客户端测试 — 工厂函数、模型校验、模型目录、内容规范化。"""

from unittest.mock import MagicMock

import pytest

from ifa.llm_clients.base_client import normalize_content
from ifa.llm_clients.factory import create_llm_client
from ifa.llm_clients.model_catalog import get_known_models, get_model_options
from ifa.llm_clients.validators import validate_model

# ════════════════════════════════════════════
#  工厂函数
# ════════════════════════════════════════════


class TestCreateLLMClient:
    """create_llm_client 工厂函数测试。"""

    def test_unsupported_provider_raises(self):
        """不支持的提供方抛出 ValueError。"""
        with pytest.raises(ValueError, match="Unsupported"):
            create_llm_client("unknown_provider", "model-x")

    def test_openai_provider(self):
        """OpenAI 提供方返回 OpenAIClient 实例。"""
        from ifa.llm_clients.openai_client import OpenAIClient

        client = create_llm_client("openai", "gpt-4.1", base_url="http://localhost:8000")
        assert isinstance(client, OpenAIClient)
        assert client.model == "gpt-4.1"

    def test_azure_provider(self):
        """Azure 提供方返回 AzureClient 实例。"""
        from ifa.llm_clients.azure_client import AzureClient

        client = create_llm_client("azure", "gpt-4.1")
        assert isinstance(client, AzureClient)

    def test_anthropic_provider(self):
        """Anthropic 提供方返回 AnthropicClient 实例。"""
        from ifa.llm_clients.anthropic_client import AnthropicClient

        client = create_llm_client("anthropic", "claude-sonnet-4-6")
        assert isinstance(client, AnthropicClient)

    def test_provider_case_insensitive(self):
        """提供方名称不区分大小写。"""
        client = create_llm_client("OpenAI", "gpt-4.1")
        assert client.model == "gpt-4.1"


# ════════════════════════════════════════════
#  模型校验
# ════════════════════════════════════════════


class TestValidateModel:
    """validate_model 校验逻辑测试。"""

    def test_valid_openai_model(self):
        """OpenAI 已知模型返回 True。"""
        assert validate_model("openai", "gpt-5.4") is True

    def test_invalid_openai_model(self):
        """OpenAI 未知模型返回 False。"""
        assert validate_model("openai", "gpt-999") is False

    def test_ollama_always_valid(self):
        """Ollama 本地模型始终返回 True。"""
        assert validate_model("ollama", "any-model-name") is True

    def test_openrouter_always_valid(self):
        """OpenRouter 始终返回 True。"""
        assert validate_model("openrouter", "any/model") is True

    def test_unknown_provider_valid(self):
        """未知 provider 始终返回 True（不做限制）。"""
        assert validate_model("some_new_provider", "any-model") is True


# ════════════════════════════════════════════
#  模型目录
# ════════════════════════════════════════════


class TestModelCatalog:
    """模型目录结构测试。"""

    def test_get_model_options_structure(self):
        """get_model_options 返回正确结构的列表。"""
        options = get_model_options("openai", "quick")
        assert isinstance(options, list)
        assert len(options) > 0
        # 每个选项是 (描述, 模型ID) 元组
        for label, model_id in options:
            assert isinstance(label, str)
            assert isinstance(model_id, str)

    def test_get_model_options_invalid_provider(self):
        """不存在的 provider 抛出 KeyError。"""
        with pytest.raises(KeyError):
            get_model_options("nonexistent", "quick")

    def test_get_known_models_non_empty(self):
        """get_known_models 返回非空字典。"""
        models = get_known_models()
        assert isinstance(models, dict)
        assert len(models) > 0
        # 每个提供方的模型列表非空
        for _provider, model_list in models.items():
            assert isinstance(model_list, list)
            assert len(model_list) > 0


# ════════════════════════════════════════════
#  normalize_content
# ════════════════════════════════════════════


class TestNormalizeContent:
    """normalize_content 响应规范化测试。"""

    def test_string_content_unchanged(self):
        """字符串内容保持不变。"""
        response = MagicMock()
        response.content = "Hello world"
        result = normalize_content(response)
        assert result.content == "Hello world"

    def test_list_text_blocks_joined(self):
        """多个文本块用换行拼接。"""
        response = MagicMock()
        response.content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result = normalize_content(response)
        assert result.content == "Hello\nWorld"

    def test_list_with_string_items(self):
        """列表中混合字符串项。"""
        response = MagicMock()
        response.content = ["Line1", "Line2"]
        result = normalize_content(response)
        assert result.content == "Line1\nLine2"

    def test_list_with_non_text_dicts_filtered(self):
        """非 text 类型的 dict 项被过滤为空字符串。"""
        response = MagicMock()
        response.content = [
            {"type": "image", "url": "http://x"},
            {"type": "text", "text": "visible"},
        ]
        result = normalize_content(response)
        assert "visible" in result.content
