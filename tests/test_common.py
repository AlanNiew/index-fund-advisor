"""公共模块测试 — get_provider_kwargs, build_state, save_report。"""

import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from ifa.common import (
    _atomic_write_json,
    _atomic_write_text,
    build_state,
    get_provider_kwargs,
    save_report,
)

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
        """文件名格式正确 — 基金代码作为目录，日期+模式+request_id 作为文件名。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "final_report": "report",
                "mode": "deep",
                "analysis_date": "2024-06-01",
                "fund_codes": "510300,159919",
                "request_id": "a1b2c3d4e5f6",
            }
            with patch("ifa.default_config.build_runtime_config") as mock_config:
                mock_config.return_value = {"results_dir": tmpdir}
                filepath = save_report(state)

            # 基金代码在目录路径中
            assert "510300_159919" in filepath
            # 日期+模式+request_id[:8] 在文件名中
            filename = os.path.basename(filepath)
            assert filename == "2024-06-01_deep_a1b2c3d4.md"

    def test_concurrent_writes_no_overwrite(self):
        """同基金同日同模式并发写入不互相覆盖 — 每个请求落独立文件。

        验证 request_id 后缀方案:5 线程并发调 save_report,各自带不同 request_id,
        join 后应有 5 个文件,内容各自完整。
        """
        N = 5
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = []
            paths = {}

            def worker(tid):
                try:
                    # 前 8 位必须各不相同(request_id[:8] 作为文件名后缀)
                    state = {
                        "final_report": f"# 报告 {tid}",
                        "mode": "deep",
                        "analysis_date": "2024-06-01",
                        "fund_codes": "510300",
                        "request_id": f"{tid:08x}abcd5678",
                    }
                    with patch("ifa.default_config.build_runtime_config") as mock_config:
                        mock_config.return_value = {"results_dir": tmpdir}
                        paths[tid] = save_report(state)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert errors == [], f"并发写入出错: {errors}"
            # 5 个不同路径
            assert len(set(paths.values())) == N, "并发写入产生重复路径,说明 request_id 后缀未生效"
            # 每个文件都存在且内容完整可读
            for tid, p in paths.items():
                assert os.path.exists(p), f"文件丢失: {p}"
                with open(p, encoding="utf-8") as f:
                    content = f.read()
                assert f"报告 {tid}" in content, f"文件内容不匹配: {p}"


# ════════════════════════════════════════════
#  _atomic_write_text / _atomic_write_json
# ════════════════════════════════════════════


class TestAtomicWrite:
    """原子写 helper 测试。"""

    def test_atomic_write_text_creates_file(self):
        """原子写文本正常落盘。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "f.txt"
            _atomic_write_text(path, "hello")
            assert path.read_text(encoding="utf-8") == "hello"
            # tmp 文件已清理
            assert not (path.with_suffix(".txt.tmp")).exists()

    def test_atomic_write_json_creates_file(self):
        """原子写 JSON 正常落盘且可解析。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data.json"
            _atomic_write_json(path, {"a": 1, "b": "中文"})
            loaded = json.loads(path.read_text(encoding="utf-8"))
            assert loaded == {"a": 1, "b": "中文"}

    def test_atomic_write_text_preserves_old_on_replace_failure(self):
        """replace 失败时,旧文件不被截断(降级直写会覆盖,但内容是新的而非空)。

        重点验证:tmp 写入失败后不会留下截断的旧文件。我们让 replace 抛异常,
        断言兜底直写后文件内容完整(非空)。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "f.txt"
            # 预置旧内容
            path.write_text("OLD_CONTENT", encoding="utf-8")

            # mock Path.replace 抛异常,触发兜底
            original_replace = Path.replace

            def failing_replace(self, target):
                raise OSError("mocked replace failure")

            with patch.object(Path, "replace", failing_replace):
                _atomic_write_text(path, "NEW_CONTENT")

            # 兜底直写成功,内容是新的(非空,非截断)
            assert path.read_text(encoding="utf-8") == "NEW_CONTENT"
            # tmp 已清理
            assert not path.with_suffix(".txt.tmp").exists()
            # 恢复(避免影响后续测试)
            Path.replace = original_replace
