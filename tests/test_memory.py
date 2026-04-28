"""金融情景记忆模块测试 — BM25 存储与检索、中文分词、FIFO 淘汰。"""

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
        """默认最大条数为 100。"""
        mem = FinancialSituationMemory("default")
        assert mem._max_situations == 100

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
