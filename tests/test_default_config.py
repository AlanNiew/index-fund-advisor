"""默认配置与校验测试 —— 供应商白名单、路径键、辩论轮数默认值。

这些是「配置层说一套、代码做一套」最容易发生的地方：
  - tushare 曾在白名单里但没有实现，配置它会被静默忽略；
  - AdvisorGraph 的辩论轮数兜底值曾是 1，而 DEFAULT_CONFIG 是 2。
"""

import pytest

import ifa.default_config as dc


class TestValidateConfig:
    """validate_config 的合法性校验。"""

    def test_rejects_vendor_without_implementation(self):
        """没有实现的供应商必须报错，而不是被静默回退到 akshare。"""
        with pytest.raises(ValueError, match="tushare"):
            dc.validate_config(
                {
                    "timeout": 180,
                    "llm_provider": "deepseek",
                    "data_vendors": {"public_fund": "tushare"},
                }
            )

    def test_accepts_akshare(self):
        dc.validate_config(
            {
                "timeout": 180,
                "llm_provider": "deepseek",
                "data_vendors": {"public_fund": "akshare"},
            }
        )

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError, match="timeout"):
            dc.validate_config({"timeout": 0, "llm_provider": "deepseek"})

    def test_rejects_blank_provider(self):
        with pytest.raises(ValueError, match="llm_provider"):
            dc.validate_config({"timeout": 180, "llm_provider": "   "})

    def test_known_vendors_lists_only_implemented_ones(self):
        """白名单必须与 VENDOR_METHODS 的实际实现保持一致。"""
        from ifa.dataflows.interface import VENDOR_METHODS

        implemented = set()
        for methods in VENDOR_METHODS.values():
            implemented.update(methods.keys())

        assert implemented == dc._KNOWN_DATA_VENDORS


class TestDebateRoundDefaults:
    """辩论轮数的单一事实来源。"""

    def test_default_config_matches_constants(self):
        assert dc.DEFAULT_CONFIG["max_debate_rounds"] == dc.DEFAULT_MAX_DEBATE_ROUNDS
        assert dc.DEFAULT_CONFIG["max_risk_discuss_rounds"] == dc.DEFAULT_MAX_RISK_DISCUSS_ROUNDS

    def test_documented_defaults(self):
        """CLAUDE.md 声明默认 2 轮，这里固定住。"""
        assert dc.DEFAULT_MAX_DEBATE_ROUNDS == 2
        assert dc.DEFAULT_MAX_RISK_DISCUSS_ROUNDS == 2

    def test_advisor_graph_fallback_matches(self):
        """config 缺键时，图里实际生效的轮数必须与 DEFAULT_CONFIG 一致。

        此前 AdvisorGraph 硬编码兜底 1，配置不完整时辩论轮数会静默减半。
        """
        from ifa.graph.advisor_graph import AdvisorGraph

        class MockLLM:
            def invoke(self, *a, **kw):
                class R:
                    content = "mock"

                return R

        advisor = AdvisorGraph(quick_llm=MockLLM(), deep_llm=MockLLM(), config={})
        assert advisor.conditional_logic.max_debate_rounds == dc.DEFAULT_MAX_DEBATE_ROUNDS
        assert advisor.conditional_logic.max_risk_discuss_rounds == dc.DEFAULT_MAX_RISK_DISCUSS_ROUNDS


class TestRuntimePaths:
    """运行时配置的路径键行为。"""

    def test_memory_dir_present_and_is_a_path_key(self, monkeypatch):
        monkeypatch.setattr(dc, "load_last_config", lambda: {})
        config = dc.build_runtime_config()
        assert config["memory_dir"].replace("\\", "/").endswith("memory")
        assert "memory_dir" in dc._PATH_KEYS

    def test_save_last_config_strips_path_keys(self, tmp_path, monkeypatch):
        """路径键不写入 last_config.py，否则换机器/换目录后会读到过期绝对路径。"""
        target = tmp_path / "last_config.py"
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", target)

        dc.save_last_config({**dc.DEFAULT_CONFIG, "llm_provider": "openai"})
        content = target.read_text(encoding="utf-8")

        assert "'llm_provider'" in content
        for key in dc._PATH_KEYS:
            assert f"'{key}'" not in content, f"{key} 不应被持久化"

    def test_save_last_config_leaves_no_tmp_file(self, tmp_path, monkeypatch):
        target = tmp_path / "last_config.py"
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", target)
        dc.save_last_config({**dc.DEFAULT_CONFIG, "llm_provider": "openai"})
        assert sorted(p.name for p in tmp_path.iterdir()) == ["last_config.py"]
