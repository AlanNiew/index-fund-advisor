"""公共模块测试 — get_provider_kwargs, build_state, save_report。"""

import os
import tempfile
from unittest.mock import patch

from ifa.common import build_state, get_provider_kwargs, save_report

# ════════════════════════════════════════════
#  get_provider_kwargs
# ════════════════════════════════════════════


class TestGetProviderKwargs:
    """get_provider_kwargs 提供方参数转换测试。"""

    def test_google_thinking_level(self):
        """Google 提供方提取 thinking_level。"""
        config = {"llm_provider": "google", "google_thinking_level": "high"}
        kwargs = get_provider_kwargs(config)
        assert kwargs["thinking_level"] == "high"

    def test_google_no_thinking(self):
        """Google 无 thinking 配置时不包含该键。"""
        config = {"llm_provider": "google"}
        kwargs = get_provider_kwargs(config)
        assert "thinking_level" not in kwargs

    def test_openai_reasoning_effort(self):
        """OpenAI 提取 reasoning_effort。"""
        config = {"llm_provider": "openai", "openai_reasoning_effort": "high"}
        kwargs = get_provider_kwargs(config)
        assert kwargs["reasoning_effort"] == "high"

    def test_azure_api_version(self):
        """Azure 提取 api_version。"""
        config = {
            "llm_provider": "azure",
            "azure_api_version": "2024-02-15-preview",
        }
        kwargs = get_provider_kwargs(config)
        assert kwargs["azure_api_version"] == "2024-02-15-preview"

    def test_anthropic_effort(self):
        """Anthropic 提取 effort。"""
        config = {"llm_provider": "anthropic", "anthropic_effort": "extended"}
        kwargs = get_provider_kwargs(config)
        assert kwargs["effort"] == "extended"

    def test_timeout_always_included(self):
        """timeout 在任何 provider 下都会被传递。"""
        config = {"llm_provider": "openai", "timeout": 120}
        kwargs = get_provider_kwargs(config)
        assert kwargs["timeout"] == 120

    def test_empty_config_returns_empty(self):
        """空配置返回空字典。"""
        kwargs = get_provider_kwargs({})
        assert kwargs == {}


# ════════════════════════════════════════════
#  build_state
# ════════════════════════════════════════════


class TestBuildState:
    """build_state 状态构建测试。"""

    def test_build_state_deep_mode(self):
        """deep 模式构建正确的状态字典。"""
        state = build_state("deep", fund_codes="510300", analysis_date="2024-01-15")
        assert state["fund_codes"] == "510300"
        assert state["analysis_date"] == "2024-01-15"
        assert state["mode"] == "deep"

    def test_build_state_defaults(self):
        """未提供 fund_codes 时使用空字符串默认值。"""
        state = build_state("screen")
        assert state["fund_codes"] == ""
        assert state["mode"] == "screen"


# ════════════════════════════════════════════
#  save_report
# ════════════════════════════════════════════


class TestSaveReport:
    """save_report 报告保存测试。"""

    def test_no_report_returns_none(self):
        """无报告时返回 None。"""
        assert save_report({}) is None
        assert save_report({"final_report": ""}) is None

    def test_saves_report_to_file(self):
        """有报告时保存到文件并返回绝对路径。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "final_report": "# 测试报告\n这是测试内容",
                "mode": "deep",
                "analysis_date": "2024-06-01",
                "fund_codes": "510300",
            }
            with patch("ifa.default_config.build_runtime_config") as mock_config:
                mock_config.return_value = {"results_dir": tmpdir}
                filepath = save_report(state)

            assert filepath is not None
            assert os.path.isabs(filepath)
            assert os.path.exists(filepath)
            with open(filepath, encoding="utf-8") as f:
                assert "测试报告" in f.read()

    def test_filename_format(self):
        """文件名格式正确 — 基金代码作为目录，日期和模式作为文件名。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "final_report": "report",
                "mode": "deep",
                "analysis_date": "2024-06-01",
                "fund_codes": "510300,159919",
            }
            with patch("ifa.default_config.build_runtime_config") as mock_config:
                mock_config.return_value = {"results_dir": tmpdir}
                filepath = save_report(state)

            # 基金代码在目录路径中
            assert "510300_159919" in filepath
            # 日期和模式在文件名中
            filename = os.path.basename(filepath)
            assert filename == "2024-06-01_deep.md"
