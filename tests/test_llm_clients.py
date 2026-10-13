"""LLM 客户端测试 — 工厂函数、模型校验、模型目录、内容规范化、OpenCode Go 接入。"""

import re
from pathlib import Path
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

    def test_deepseek_provider(self):
        """DeepSeek 提供方返回 OpenAIClient 实例。"""
        from ifa.llm_clients.openai_client import OpenAIClient

        client = create_llm_client("deepseek", "deepseek-chat")
        assert isinstance(client, OpenAIClient)
        assert client.provider == "deepseek"

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

    def test_valid_deepseek_model(self):
        """DeepSeek 已知模型返回 True。"""
        assert validate_model("deepseek", "deepseek-chat") is True
        assert validate_model("deepseek", "deepseek-reasoner") is True

    def test_invalid_deepseek_model(self):
        """DeepSeek 未知模型返回 False。"""
        assert validate_model("deepseek", "deepseek-999") is False

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


# ════════════════════════════════════════════
#  OpenCode Go 端点接入
# ════════════════════════════════════════════


class TestOpenCodeProvider:
    """OpenCode Go（opencode）提供方的接入契约。

    该端点对客户端有两条额外要求：自报身份的 User-Agent、以及稳定会话 ID。
    把它们固定成测试，是因为删掉它们不会报任何错——只会悄悄失去路由与提示缓存优化。
    """

    def test_factory_returns_openai_client(self):
        """工厂把 opencode 映射到 OpenAIClient。"""
        from ifa.llm_clients.openai_client import OpenAIClient

        client = create_llm_client("opencode", "deepseek-v4.1-flash")
        assert isinstance(client, OpenAIClient)
        assert client.provider == "opencode"

    def test_uses_opencode_gateway_base_url(self, monkeypatch):
        """base_url 指向 OpenCode Go 网关，API Key 取自 OPENCODE_API_KEY。"""
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-test-key")

        llm = create_llm_client("opencode", "deepseek-v4.1-flash").get_llm()

        assert llm.openai_api_base == "https://opencode.ai/inference/go/v1"
        assert llm.model_name == "deepseek-v4.1-flash"
        assert llm.openai_api_key.get_secret_value() == "sk-test-key"

    def test_sends_self_identifying_user_agent_and_session(self, monkeypatch):
        """请求必须带上自有 User-Agent 与会话头。"""
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-test-key")
        monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)

        headers = create_llm_client("opencode", "deepseek-v4-pro").get_llm().default_headers

        assert headers["User-Agent"].startswith("index-fund-advisor/")
        assert headers["x-opencode-session"]

    def test_user_agent_tracks_package_version(self):
        """User-Agent 里的版本号必须与 pyproject.toml 一致，否则会无声漂移。"""
        from ifa.llm_clients.openai_client import _OPENCODE_USER_AGENT

        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
        assert match is not None

        assert f"index-fund-advisor/{match.group(1)}" == _OPENCODE_USER_AGENT

    def test_session_id_stable_within_process(self, monkeypatch):
        """一次 ifa 运行内的所有 LLM 调用共享同一会话——这正是该头部的用途。"""
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-test-key")
        monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)

        first = create_llm_client("opencode", "deepseek-v4-pro").get_llm()
        second = create_llm_client("opencode", "deepseek-v4.1-flash").get_llm()

        assert first.default_headers["x-opencode-session"] == second.default_headers["x-opencode-session"]

    def test_session_id_env_override(self, monkeypatch):
        """OPENCODE_SESSION_ID 可覆盖进程默认会话。"""
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-test-key")
        monkeypatch.setenv("OPENCODE_SESSION_ID", "conversation-42")

        headers = create_llm_client("opencode", "deepseek-v4-pro").get_llm().default_headers

        assert headers["x-opencode-session"] == "conversation-42"

    def test_session_id_kwarg_wins_over_env(self, monkeypatch):
        """显式 kwarg 优先级高于环境变量。"""
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-test-key")
        monkeypatch.setenv("OPENCODE_SESSION_ID", "from-env")

        llm = create_llm_client("opencode", "deepseek-v4-pro", opencode_session_id="from-kwarg").get_llm()

        assert llm.default_headers["x-opencode-session"] == "from-kwarg"

    def test_user_headers_merge_with_required_ones(self, monkeypatch):
        """用户自定义 header 被保留，但我们要求的会话头不会被顶掉。"""
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-test-key")
        monkeypatch.setenv("OPENCODE_SESSION_ID", "conv-1")

        llm = create_llm_client(
            "opencode",
            "deepseek-v4-pro",
            default_headers={"X-Trace": "abc", "User-Agent": "custom/2.0"},
        ).get_llm()

        assert llm.default_headers["X-Trace"] == "abc"
        assert llm.default_headers["User-Agent"] == "custom/2.0"
        assert llm.default_headers["x-opencode-session"] == "conv-1"

    def test_other_providers_get_no_opencode_headers(self, monkeypatch):
        """会话头只应出现在 opencode 上，不能泄漏到其他提供方。"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")

        assert create_llm_client("deepseek", "deepseek-chat").get_llm().default_headers is None


class TestOpenCodeModelCatalog:
    """OpenCode Go 的模型目录与校验。"""

    def test_catalog_lists_gateway_models(self):
        quick = [model for _, model in get_model_options("opencode", "quick")]
        deep = [model for _, model in get_model_options("opencode", "deep")]

        assert "deepseek-v4.1-flash" in quick
        assert "deepseek-v4-pro" in deep

    def test_validate_model_accepts_gateway_ids(self):
        assert validate_model("opencode", "deepseek-v4.1-flash") is True
        assert validate_model("opencode", "deepseek-v4-pro") is True

    def test_validate_model_rejects_foreign_ids(self):
        assert validate_model("opencode", "gpt-999") is False
