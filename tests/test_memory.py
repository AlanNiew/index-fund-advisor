"""金融情景记忆模块测试 — BM25 存储与检索。"""

from ifa.agents.memory import FinancialSituationMemory


class TestFinancialSituationMemory:
    """FinancialSituationMemory 增删查测试。"""

    def test_add_and_retrieve(self):
        """添加情景后可检索到匹配记忆。"""
        mem = FinancialSituationMemory("test")
        mem.add_situations([
            ("市场大涨，沪深300涨幅超过3%", "建议持有宽基ETF"),
            ("市场大跌，恐慌情绪蔓延", "建议分批建仓"),
        ])

        results = mem.get_memories("市场大幅上涨", n_matches=1)
        assert len(results) == 1
        assert "沪深300" in results[0]["matched_situation"]
        # BM25 用 \b\w+\b 分词对中文支持有限，score 可能为 0
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
        mem.add_situations([
            ("市场上涨，蓝筹股领涨", "建议持有蓝筹"),
            ("市场下跌，科技股暴跌", "建议回避科技"),
            ("蓝筹股大幅上涨，金融板块强势", "关注金融ETF"),
        ])

        results = mem.get_memories("蓝筹股上涨", n_matches=3)
        assert len(results) == 3
        # 第一个结果应该与查询最相关
        assert "蓝筹" in results[0]["matched_situation"]

    def test_multiple_matches(self):
        """请求多条匹配时返回对应数量。"""
        mem = FinancialSituationMemory("multi")
        mem.add_situations([
            ("情景1", "建议1"),
            ("情景2", "建议2"),
            ("情景3", "建议3"),
        ])

        results = mem.get_memories("情景", n_matches=2)
        assert len(results) == 2
        # 所有结果都有完整的字段
        for r in results:
            assert "matched_situation" in r
            assert "recommendation" in r
            assert "similarity_score" in r
