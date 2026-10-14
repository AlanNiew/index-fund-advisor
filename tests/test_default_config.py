"""默认配置与校验测试 —— 供应商白名单、路径键、辩论轮数默认值、延迟预算。

这些是「配置层说一套、代码做一套」最容易发生的地方：
  - tushare 曾在白名单里但没有实现，配置它会被静默忽略；
  - AdvisorGraph 的辩论轮数兜底值曾与 DEFAULT_CONFIG 不一致（前者 1、后者 2）；
  - 超时/重试这类延迟预算必须有单一事实来源，且默认值要能对应上实测证据。
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
        """默认 1 轮：2026-10 实测辩论段独占 30.4 分钟运行的 86%。"""
        assert dc.DEFAULT_MAX_DEBATE_ROUNDS == 1
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
        """路径键不写入用户配置文件，否则换机器/换目录后会读到过期绝对路径。"""
        import json

        target = tmp_path / "config.json"
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", target)

        dc.save_last_config({**dc.DEFAULT_CONFIG, "llm_provider": "openai"})
        stored = json.loads(target.read_text(encoding="utf-8"))

        assert stored["llm_provider"] == "openai"
        for key in dc._PATH_KEYS:
            assert key not in stored, f"{key} 不应被持久化"

    def test_save_last_config_leaves_no_tmp_file(self, tmp_path, monkeypatch):
        target = tmp_path / "config.json"
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", target)
        dc.save_last_config({**dc.DEFAULT_CONFIG, "llm_provider": "openai"})
        assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json"]


class TestDefaultProviderWiring:
    """默认提供方与模型目录必须对得上。

    历史上 `backend_url` 长期残留着上一个提供方的地址（指向智谱而 provider 是 deepseek），
    这类「配置说一套、代码做一套」的漂移只有测试能挡住。
    """

    def test_default_provider_is_opencode(self):
        """项目默认走 OpenCode Go 聚合端点。"""
        assert dc.DEFAULT_CONFIG["llm_provider"] == "opencode"

    def test_default_models_exist_in_catalog(self):
        """默认模型必须真的在该提供方的模型目录里，否则 CLI 永远选不到它们。"""
        from ifa.llm_clients.model_catalog import get_known_models

        provider = dc.DEFAULT_CONFIG["llm_provider"]
        known = get_known_models().get(provider, [])
        assert known, f"提供方 {provider} 没有模型目录"

        for key in ("deep_think_llm", "quick_think_llm"):
            assert dc.DEFAULT_CONFIG[key] in known, f"{key}={dc.DEFAULT_CONFIG[key]} 不在 {provider} 的模型目录中"

    def test_backend_url_matches_default_provider(self):
        """backend_url 不得残留其他提供方的地址（内置提供方以 _PROVIDER_CONFIG 为准）。"""
        from ifa.llm_clients.openai_client import _PROVIDER_CONFIG

        provider = dc.DEFAULT_CONFIG["llm_provider"]
        assert dc.DEFAULT_CONFIG["backend_url"] == _PROVIDER_CONFIG[provider][0]


class TestEnvOverrides:
    """环境变量覆盖：env > 用户配置文件 > DEFAULT_CONFIG。

    这是「不动任何文件就换模型」的唯一入口，容器 / CI / 第三方集成全靠它。
    """

    def test_env_beats_config_file(self, monkeypatch):
        monkeypatch.setattr(dc, "load_last_config", lambda: {"llm_provider": "openai", "timeout": 60})
        monkeypatch.setenv("IFA_LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("IFA_TIMEOUT", "30")

        config = dc.build_runtime_config()

        assert config["llm_provider"] == "deepseek"
        assert config["timeout"] == 30

    def test_env_overrides_models(self, monkeypatch):
        monkeypatch.setattr(dc, "load_last_config", lambda: {})
        monkeypatch.setenv("IFA_DEEP_LLM", "deepseek-chat")
        monkeypatch.setenv("IFA_QUICK_LLM", "deepseek-chat")

        config = dc.build_runtime_config()

        assert config["deep_think_llm"] == "deepseek-chat"
        assert config["quick_think_llm"] == "deepseek-chat"

    def test_blank_env_is_ignored(self, monkeypatch):
        """空串/空白等于「没设」，不能把配置清成空字符串。"""
        monkeypatch.setattr(dc, "load_last_config", lambda: {})
        monkeypatch.setenv("IFA_LLM_PROVIDER", "   ")

        assert dc.build_runtime_config()["llm_provider"] == dc.DEFAULT_CONFIG["llm_provider"]

    def test_invalid_timeout_env_raises(self, monkeypatch):
        monkeypatch.setattr(dc, "load_last_config", lambda: {})
        monkeypatch.setenv("IFA_TIMEOUT", "abc")

        with pytest.raises(ValueError, match="timeout"):
            dc.build_runtime_config()


class TestUserConfigFile:
    """用户配置文件（JSON）读写 —— `ifa config` 的落盘层。

    历史缺陷：旧实现只把配置 pformat 成 Python 字面量写进包目录里的 last_config.py，
    包目录通常不可写（site-packages 只读），于是「设置」形同虚设。
    """

    def test_set_and_unset_roundtrip(self, tmp_path, monkeypatch):
        import json

        target = tmp_path / "config.json"
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", target)

        assert dc.set_user_config("llm_provider", "deepseek") == "deepseek"
        assert json.loads(target.read_text(encoding="utf-8")) == {"llm_provider": "deepseek"}
        assert dc.load_last_config() == {"llm_provider": "deepseek"}

        assert dc.unset_user_config("llm_provider") is True
        assert dc.load_last_config() == {}
        assert not target.exists()

    def test_set_coerces_types(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", tmp_path / "config.json")

        assert dc.set_user_config("timeout", "45") == 45
        assert dc.set_user_config("enable_debate", "false") is False

        stored = dc.load_last_config()
        assert stored["timeout"] == 45
        assert stored["enable_debate"] is False

    def test_unknown_key_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", tmp_path / "config.json")

        with pytest.raises(ValueError, match="未知配置项"):
            dc.set_user_config("no_such_key", "1")

    def test_path_keys_are_not_configurable(self, tmp_path, monkeypatch):
        """路径键由项目位置现场推导，写进配置文件换机器就失效。"""
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", tmp_path / "config.json")

        assert "memory_dir" not in dc.CONFIGURABLE_KEYS
        with pytest.raises(ValueError, match="未知配置项"):
            dc.set_user_config("memory_dir", "/tmp/x")

    def test_corrupt_config_file_degrades(self, tmp_path, monkeypatch):
        """损坏的配置文件只能降级为默认值，不能让每个命令都崩。"""
        target = tmp_path / "config.json"
        target.write_text("{ this is not json", encoding="utf-8")
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", target)

        assert dc.load_last_config() == {}

    def test_legacy_python_config_still_read(self, tmp_path, monkeypatch):
        """老用户升级前写下的 last_config.py 必须仍能被读到（只读兼容）。"""
        legacy = tmp_path / "last_config.py"
        legacy.write_text("LAST_CONFIG = {'llm_provider': 'zhipu'}\n", encoding="utf-8")
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(dc, "LEGACY_LAST_CONFIG_PATH", legacy)

        assert dc.load_last_config() == {"llm_provider": "zhipu"}

    def test_runtime_config_uses_user_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc, "LAST_CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(dc, "LEGACY_LAST_CONFIG_PATH", tmp_path / "nonexistent.py")

        dc.set_user_config("llm_provider", "deepseek")
        dc.set_user_config("deep_think_llm", "deepseek-chat")
        dc.set_user_config("quick_think_llm", "deepseek-chat")
        config = dc.build_runtime_config()

        assert config["llm_provider"] == "deepseek"
        # 换提供方后端点必须跟着走，而不是留着上一个提供方的地址
        assert config["backend_url"] == "https://api.deepseek.com/v1"


class TestBackendUrlNormalization:
    """backend_url 不得残留别的提供方的端点（历史漂移：provider=deepseek 却指向智谱）。"""

    def test_stale_other_provider_url_is_replaced(self, monkeypatch):
        monkeypatch.setattr(
            dc,
            "load_last_config",
            lambda: {"llm_provider": "deepseek", "backend_url": "https://open.bigmodel.cn/api/coding/paas/v4"},
        )

        assert dc.build_runtime_config()["backend_url"] == "https://api.deepseek.com/v1"

    def test_custom_url_is_preserved(self, monkeypatch):
        """用户自己的地址不是「别家端点」，必须原样保留。"""
        monkeypatch.setattr(
            dc,
            "load_last_config",
            lambda: {"llm_provider": "custom", "backend_url": "https://gateway.internal/v1"},
        )

        assert dc.build_runtime_config()["backend_url"] == "https://gateway.internal/v1"

    def test_default_provider_url_is_preserved(self, monkeypatch):
        monkeypatch.setattr(dc, "load_last_config", lambda: {})

        assert dc.build_runtime_config()["backend_url"] == dc.DEFAULT_CONFIG["backend_url"]


class TestProviderValidation:
    """提供方白名单 —— 配置了却不生效的选项比报错更糟。"""

    def test_unknown_provider_rejected_with_options(self):
        with pytest.raises(ValueError, match="不是已知提供方"):
            dc.validate_config({"timeout": 180, "llm_provider": "no-such-vendor"})

    def test_custom_requires_backend_url(self):
        with pytest.raises(ValueError, match="backend_url"):
            dc.validate_config({"timeout": 180, "llm_provider": "custom", "backend_url": ""})

    def test_custom_with_backend_url_accepted(self):
        dc.validate_config({"timeout": 180, "llm_provider": "custom", "backend_url": "https://x/v1"})

    def test_every_provider_has_label(self):
        from ifa.providers import PROVIDER_CONFIG, provider_label

        assert PROVIDER_CONFIG
        for name in PROVIDER_CONFIG:
            assert provider_label(name), f"{name} 没有展示名"


class TestLatencyBudget:
    """超时/重试的默认值与分档：quick 档收紧、deep 档单独放宽。"""

    def test_timeout_tiers(self):
        assert dc.DEFAULT_CONFIG["timeout"] == dc.DEFAULT_LLM_TIMEOUT == 120
        assert dc.DEFAULT_CONFIG["deep_timeout"] == dc.DEFAULT_DEEP_TIMEOUT == 180
        assert dc.DEFAULT_LLM_TIMEOUT < dc.DEFAULT_DEEP_TIMEOUT

    def test_retry_default(self):
        assert dc.DEFAULT_CONFIG["llm_max_retries"] == dc.DEFAULT_LLM_MAX_RETRIES == 2

    def test_new_keys_are_configurable(self):
        """新增的延迟预算键必须真能被 ifa config / 环境变量覆盖，否则只是摆设。"""
        for key in ("deep_timeout", "llm_max_retries"):
            assert key in dc.CONFIGURABLE_KEYS
        assert dc._coerce_config_value("llm_max_retries", "4") == 4
        assert ("IFA_DEEP_TIMEOUT", "deep_timeout") in dc._ENV_OVERRIDES
        assert ("IFA_LLM_MAX_RETRIES", "llm_max_retries") in dc._ENV_OVERRIDES

    def test_rejects_bad_latency_values(self):
        with pytest.raises(ValueError, match="deep_timeout"):
            dc.validate_config({"llm_provider": "deepseek", "deep_timeout": 0})
        with pytest.raises(ValueError, match="llm_max_retries"):
            dc.validate_config({"llm_provider": "deepseek", "llm_max_retries": -1})

    def test_env_overrides_latency_budget(self, monkeypatch):
        monkeypatch.setattr(dc, "load_last_config", lambda: {})
        monkeypatch.setenv("IFA_TIMEOUT", "45")
        monkeypatch.setenv("IFA_DEEP_TIMEOUT", "300")
        monkeypatch.setenv("IFA_LLM_MAX_RETRIES", "1")

        config = dc.build_runtime_config()

        assert config["timeout"] == 45
        assert config["deep_timeout"] == 300
        assert config["llm_max_retries"] == 1
