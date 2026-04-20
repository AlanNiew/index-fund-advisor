"""基于 BM25 的金融情景记忆模块（从 tradingagents 复制，无修改）。"""

import re

from rank_bm25 import BM25Okapi


class FinancialSituationMemory:
    """使用 BM25 存储与检索金融情景记忆。"""

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.documents: list[str] = []
        self.recommendations: list[str] = []
        self.bm25 = None

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"\b\w+\b", text.lower())
        return tokens

    def _rebuild_index(self):
        if self.documents:
            tokenized_docs = [self._tokenize(doc) for doc in self.documents]
            self.bm25 = BM25Okapi(tokenized_docs)
        else:
            self.bm25 = None

    def add_situations(self, situations_and_advice: list[tuple[str, str]]):
        for situation, recommendation in situations_and_advice:
            self.documents.append(situation)
            self.recommendations.append(recommendation)
        self._rebuild_index()

    def get_memories(self, current_situation: str, n_matches: int = 1) -> list[dict]:
        if not self.documents or self.bm25 is None:
            return []
        query_tokens = self._tokenize(current_situation)
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
