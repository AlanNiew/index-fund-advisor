"""金融情景记忆模块测试 — BM25 存储与检索、中文分词、FIFO 淘汰、落盘持久化。"""

import json
import subprocess
import sys
from pathlib import Path

from ifa.agents.memory import FinancialSituationMemory


class TestFinancialSituationMemory:
    """FinancialSituationMemory 增删查测试。"""

    def test_add_and_retrieve(self):
        """添加情景后可检索到匹配记忆。"""
        mem = FinancialSituationMemory("test")
        mem.add_situations(
            [
                ("市场大涨，沪深300涨幅超过3%", "建议持有宽基ETF"),
                ("市场大跌，恐慌情绪蔓延", "建议分批建仓"),
            ]
        )

        results = mem.get_memories("市场大幅上涨", n_matches=1)
        assert len(results) == 1
        assert "沪深300" in results[0]["matched_situation"]
        assert "similarity_score" in results[0]

    def test_empty_memory_returns_empty(self):
        """空记忆检索返回空列表。"""
        mem = FinancialSituationMemory("empty")
        assert mem.get_memories("任何查询") == []

    def test_clear_empties_memory(self):
        """clear() 后检索为空。"""
        mem = FinancialSituationMemory("test")
        mem.add_situations([("情景A", "建议A")])
        assert len(mem.get_memories("情景A")) == 1

        mem.clear()
        assert mem.get_memories("情景A") == []
        assert mem.documents == []
        assert mem.bm25 is None

    def test_relevance_ranking(self):
        """多匹配时按相关性排序。"""
        mem = FinancialSituationMemory("rank")
        mem.add_situations(
            [
                ("市场上涨，蓝筹股领涨", "建议持有蓝筹"),
                ("市场下跌，科技股暴跌", "建议回避科技"),
                ("蓝筹股大幅上涨，金融板块强势", "关注金融ETF"),
            ]
        )

        results = mem.get_memories("蓝筹股上涨", n_matches=3)
        assert len(results) == 3
        # 第一个结果应该与查询最相关
        assert "蓝筹" in results[0]["matched_situation"]

    def test_multiple_matches(self):
        """请求多条匹配时返回对应数量。"""
        mem = FinancialSituationMemory("multi")
        mem.add_situations(
            [
                ("情景1", "建议1"),
                ("情景2", "建议2"),
                ("情景3", "建议3"),
            ]
        )

        results = mem.get_memories("情景", n_matches=2)
        assert len(results) == 2
        # 所有结果都有完整的字段
        for r in results:
            assert "matched_situation" in r
            assert "recommendation" in r
            assert "similarity_score" in r


class TestChineseTokenization:
    """中文分词测试。"""

    def test_tokenize_chinese_chars(self):
        """中文字符按字拆分。"""
        tokens = FinancialSituationMemory._tokenize("沪深300")
        # 沪、深各为独立 token，300 为英文 token
        assert "沪" in tokens
        assert "深" in tokens
        assert "300" in tokens

    def test_tokenize_english_preserved(self):
        """英文单词保留为完整 token。"""
        tokens = FinancialSituationMemory._tokenize("ETF index fund")
        assert "etf" in tokens
        assert "index" in tokens
        assert "fund" in tokens

    def test_tokenize_mixed_content(self):
        """中英混合内容正确分词。"""
        tokens = FinancialSituationMemory._tokenize("沪深300 ETF基金")
        # 沪深为中文单字，300为数字token，ETF为英文token，基金为中文单字
        assert "沪" in tokens
        assert "深" in tokens
        assert "300" in tokens
        assert "etf" in tokens
        assert "基" in tokens
        assert "金" in tokens

    def test_tokenize_empty_string(self):
        """空字符串返回空列表。"""
        assert FinancialSituationMemory._tokenize("") == []

    def test_chinese_retrieval_quality(self):
        """中文检索应能匹配到相关记忆。"""
        mem = FinancialSituationMemory("chinese_test")
        mem.add_situations(
            [
                ("沪深300指数基金近期涨幅较大，估值偏高", "建议减仓"),
                ("中证500指数处于历史低位，估值合理", "建议逢低买入"),
                ("国债收益率下行，债券基金表现优异", "建议配置债基"),
            ]
        )

        # 查询应匹配到沪深300相关的记忆
        results = mem.get_memories("沪深300估值", n_matches=1)
        assert len(results) == 1
        assert "沪深300" in results[0]["matched_situation"]

    def test_chinese_vs_english_query(self):
        """中文查询和中文记忆匹配优于英文。"""
        mem = FinancialSituationMemory("lang_test")
        mem.add_situations(
            [
                ("宽基指数ETF波动率低，适合定投", "推荐定投"),
                ("科技股近期回调较大，注意风险", "建议观望"),
            ]
        )

        results = mem.get_memories("宽基指数波动率", n_matches=1)
        assert len(results) == 1
        assert "宽基" in results[0]["matched_situation"]


class TestFIFOEviction:
    """FIFO 淘汰机制测试。"""

    def test_default_max_situations(self):
        """默认最大条数为 1000（见 memory.py 注释：覆盖率 vs 内存权衡）。"""
        mem = FinancialSituationMemory("default")
        assert mem._max_situations == 1000

    def test_custom_max_situations(self):
        """自定义最大条数。"""
        mem = FinancialSituationMemory("custom", {"max_situations": 5})
        assert mem._max_situations == 5

    def test_fifo_eviction(self):
        """超出上限时淘汰最旧条目。"""
        mem = FinancialSituationMemory("fifo", {"max_situations": 3})
        mem.add_situations(
            [
                ("情景1", "建议1"),
                ("情景2", "建议2"),
                ("情景3", "建议3"),
            ]
        )
        assert len(mem.documents) == 3

        # 添加第 4 条，应淘汰第 1 条
        mem.add_situations([("情景4", "建议4")])
        assert len(mem.documents) == 3
        assert "情景1" not in mem.documents
        assert "情景4" in mem.documents

    def test_fifo_maintains_order(self):
        """FIFO 保持插入顺序。"""
        mem = FinancialSituationMemory("order", {"max_situations": 2})
        mem.add_situations(
            [
                ("A", "a"),
                ("B", "b"),
                ("C", "c"),
            ]
        )
        assert mem.documents == ["B", "C"]
        assert mem.recommendations == ["b", "c"]


class TestPersistence:
    """记忆落盘测试 —— 修复「记忆只在内存、进程退出即丢失」。"""

    def test_no_memory_dir_disables_persistence(self):
        """未提供 memory_dir 时不落盘、不创建文件（保持单元测试无副作用）。"""
        mem = FinancialSituationMemory("nopersist", {"max_situations": 10})
        assert mem._path is None
        mem.add_situations([("情景A", "建议A")])
        # add_situations 不应因缺少落盘路径而报错，内存仍生效
        assert mem.documents == ["情景A"]

    def test_persist_and_reload(self, tmp_path):
        """add_situations 后写盘，新实例可载入并正常检索。"""
        cfg = {"memory_dir": str(tmp_path)}
        mem = FinancialSituationMemory("bull_memory", cfg)
        mem.add_situations([("市场大涨，沪深300涨幅超过3%", "建议持有"), ("市场大跌，恐慌情绪蔓延", "建议分批建仓")])

        assert (tmp_path / "bull_memory.json").exists()

        reloaded = FinancialSituationMemory("bull_memory", cfg)
        assert reloaded.documents == ["市场大涨，沪深300涨幅超过3%", "市场大跌，恐慌情绪蔓延"]
        assert reloaded.recommendations == ["建议持有", "建议分批建仓"]
        # 载入后索引按需重建，检索立即可用
        results = reloaded.get_memories("市场大幅上涨", n_matches=1)
        assert len(results) == 1
        assert "沪深300" in results[0]["matched_situation"]

    def test_reload_applies_fifo_cap(self, tmp_path):
        """文件来自上限更大的旧配置时，载入即按当前上限淘汰最旧条目。"""
        cfg = {"memory_dir": str(tmp_path)}
        writer = FinancialSituationMemory("capped", {**cfg, "max_situations": 10})
        writer.add_situations([(f"情景{i}", f"建议{i}") for i in range(10)])

        reloaded = FinancialSituationMemory("capped", {**cfg, "max_situations": 3})
        assert reloaded.documents == ["情景7", "情景8", "情景9"]

    def test_corrupt_file_degrades_to_empty(self, tmp_path):
        """损坏 JSON 降级为空记忆，不抛异常。"""
        (tmp_path / "broken.json").write_text("{ 这不是合法 JSON", encoding="utf-8")
        mem = FinancialSituationMemory("broken", {"memory_dir": str(tmp_path)})
        assert mem.documents == []
        assert mem.get_memories("任意查询") == []

    def test_malformed_entries_are_skipped(self, tmp_path):
        """逐条校验：缺字段/类型错误的条目被跳过，其余正常载入。"""
        payload = {
            "version": 1,
            "entries": [
                {"situation": "合法情景", "recommendation": "合法建议"},
                {"situation": "缺推荐"},
                "不是字典",
                {"situation": 1, "recommendation": 2},
            ],
        }
        (tmp_path / "partial.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        mem = FinancialSituationMemory("partial", {"memory_dir": str(tmp_path)})
        assert mem.documents == ["合法情景"]
        assert mem.recommendations == ["合法建议"]

    def test_non_dict_payload_degrades_to_empty(self, tmp_path):
        """顶层不是对象（如数组）时同样降级为空。"""
        (tmp_path / "array.json").write_text("[1, 2, 3]", encoding="utf-8")
        mem = FinancialSituationMemory("array", {"memory_dir": str(tmp_path)})
        assert mem.documents == []

    def test_persist_leaves_no_tmp_residue(self, tmp_path):
        """原子写不留下 .tmp 残留文件。"""
        mem = FinancialSituationMemory("atomic", {"memory_dir": str(tmp_path)})
        mem.add_situations([("情景", "建议")])
        assert sorted(p.name for p in tmp_path.iterdir()) == ["atomic.json"]

    def test_clear_removes_file(self, tmp_path):
        """clear() 默认删除落盘文件，避免下次启动读回旧记忆。"""
        cfg = {"memory_dir": str(tmp_path)}
        mem = FinancialSituationMemory("clearable", cfg)
        mem.add_situations([("情景", "建议")])
        assert (tmp_path / "clearable.json").exists()

        mem.clear()
        assert not (tmp_path / "clearable.json").exists()
        assert FinancialSituationMemory("clearable", cfg).documents == []

    def test_clear_without_persist_keeps_file(self, tmp_path):
        """clear(persist=False) 只清内存，保留磁盘文件。"""
        cfg = {"memory_dir": str(tmp_path)}
        mem = FinancialSituationMemory("keepfile", cfg)
        mem.add_situations([("情景", "建议")])
        mem.clear(persist=False)

        assert mem.documents == []
        assert (tmp_path / "keepfile.json").exists()

    def test_fifo_eviction_persists(self, tmp_path):
        """淘汰结果同步落盘，而不是只在内存里一致。"""
        cfg = {"memory_dir": str(tmp_path), "max_situations": 2}
        mem = FinancialSituationMemory("evict", cfg)
        mem.add_situations([("A", "a"), ("B", "b"), ("C", "c")])
        assert FinancialSituationMemory("evict", cfg).documents == ["B", "C"]

    def test_cross_process_reload(self, tmp_path):
        """真实的跨会话复用：子进程写入，父进程载入。

        这是本次修复要保证的核心行为——此前记忆只存在于内存，进程退出即蒸发，
        正常分析流程中 get_memories() 恒为空。
        """
        project_root = Path(__file__).resolve().parents[1]
        script = (
            "from ifa.agents.memory import FinancialSituationMemory\n"
            f"m = FinancialSituationMemory('cross', {{'memory_dir': {str(tmp_path)!r}}})\n"
            "m.add_situations([('跨进程情景', '跨进程建议')])\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr

        mem = FinancialSituationMemory("cross", {"memory_dir": str(tmp_path)})
        assert mem.documents == ["跨进程情景"]
        assert mem.recommendations == ["跨进程建议"]
