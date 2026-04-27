"""基于 BM25 的金融情景记忆模块。

改进自 tradingagents 原始版本：
- 中文分词：每个汉字作为独立 token，英文保留原 ``\\w+`` 模式
- 条目上限：FIFO 淘汰最旧条目，防止无界增长
"""

import re

from rank_bm25 import BM25Okapi

# 默认最大记忆条数
_DEFAULT_MAX_SITUATIONS = 100

# CJK 统一汉字范围（包含扩展 A 区）
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# 英文 token
_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


class FinancialSituationMemory:
    """使用 BM25 存储与检索金融情景记忆。

    参数:
        name: 记忆实例名称
        config: 可选配置字典，支持:
            - max_situations: 最大记忆条数（默认 100）
    """

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self._config = config or {}
        self._max_situations = self._config.get("max_situations", _DEFAULT_MAX_SITUATIONS)
        self.documents: list[str] = []
        self.recommendations: list[str] = []
        self.bm25 = None

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中英混合分词：中文按字拆分，英文按词拆分。

        将 "沪深300指数基金波动率较低" 拆分为
        ['沪', '深', '300', '指', '数', '基', '金', '波', '动', '率', '较', '低']
        """
        tokens: list[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if _CJK_RE.match(ch):
                # 中文字符：每个字作为独立 token
                tokens.append(ch)
                i += 1
            else:
                # 非中文：尝试匹配连续的英文/数字
                rest = text[i:]
                m = _WORD_RE.match(rest)
                if m:
                    tokens.append(m.group().lower())
                    i += m.end()
                else:
                    i += 1
        return tokens

    def _rebuild_index(self):
        if self.documents:
            tokenized_docs = [self._tokenize(doc) for doc in self.documents]
            self.bm25 = BM25Okapi(tokenized_docs)
        else:
            self.bm25 = None

    def add_situations(self, situations_and_advice: list[tuple[str, str]]):
        """添加情景记忆，超出上限时 FIFO 淘汰最旧条目。"""
        for situation, recommendation in situations_and_advice:
            self.documents.append(situation)
            self.recommendations.append(recommendation)

        # FIFO 淘汰超出上限的旧条目
        while len(self.documents) > self._max_situations:
            self.documents.pop(0)
            self.recommendations.pop(0)

        self._rebuild_index()

    def get_memories(self, current_situation: str, n_matches: int = 1) -> list[dict]:
        """根据当前情景检索最相似的历史记忆。"""
        if not self.documents or self.bm25 is None:
            return []
        query_tokens = self._tokenize(current_situation)
        if not query_tokens:
            return []
        scores = self.bm25.get_scores(query_tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_matches]
        results = []
        max_score = max(scores) if max(scores) > 0 else 1
        for idx in top_indices:
            normalized_score = scores[idx] / max_score if max_score > 0 else 0
            results.append(
                {
                    "matched_situation": self.documents[idx],
                    "recommendation": self.recommendations[idx],
                    "similarity_score": normalized_score,
                }
            )
        return results

    def clear(self):
        self.documents = []
        self.recommendations = []
        self.bm25 = None
