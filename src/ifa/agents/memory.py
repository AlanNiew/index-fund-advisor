"""基于 BM25 的金融情景记忆模块。

改进自 tradingagents 原始版本：
- 中文分词：每个汉字作为独立 token，英文保留原 ``\\w+`` 模式
- 条目上限：FIFO 淘汰最旧条目，防止无界增长
- 落盘持久化：配置提供 `memory_dir` 时，记忆写入 `<memory_dir>/<name>.json`，
  进程重启后自动载入。这是让 `Reflector` 积累的经验真正跨会话复用的关键——
  此前记忆只存在于内存，正常分析流程中永远是空的（见 graph/reflection.py）。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

from rank_bm25 import BM25Okapi

from ifa.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# 默认最大记忆条数
# 说明：BM25 情景记忆按相似度检索历史决策，不是按标的穷举。
# 100 条在 A 股 5000+ 基金、多牛熊周期下覆盖率不足，会把短期噪声编码成「经验」。
# 提到 1000 以平衡覆盖率与内存（每条仅存字符串，内存开销可忽略）。
# 真正的瓶颈不是上限而是反思信号质量——见 graph/reflection.py 的注释。
_DEFAULT_MAX_SITUATIONS = 1000

# 落盘格式版本号（未来格式变更时用于迁移）
_PERSIST_VERSION = 1

# CJK 统一汉字范围（包含扩展 A 区）
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# 英文 token
_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


class FinancialSituationMemory:
    """使用 BM25 存储与检索金融情景记忆。

    参数:
        name: 记忆实例名称（同时作为落盘文件名）
        config: 可选配置字典，支持:
            - max_situations: 最大记忆条数（默认 1000）
            - memory_dir: 落盘目录。**不提供则不落盘**（单元测试因此保持无副作用）；
              生产路径由 DEFAULT_CONFIG 提供 `local_data/memory`。

    持久化语义:
        - `add_situations()` 后立即原子写盘（写失败只告警，不阻塞分析）
        - 载入时对损坏/缺字段的文件降级为空记忆，绝不抛异常
        - `clear()` 默认同时删除落盘文件，避免下次启动把旧记忆读回来
    """

    def __init__(self, name: str, config: dict | None = None):
        self.name = name
        self._config = config or {}
        self._max_situations = self._config.get("max_situations", _DEFAULT_MAX_SITUATIONS)
        self.documents: list[str] = []
        self.recommendations: list[str] = []
        self.bm25: BM25Okapi | None = None
        self._index_dirty = False
        self._lock = threading.Lock()

        memory_dir = self._config.get("memory_dir")
        self._path: Path | None = Path(memory_dir) / f"{name}.json" if memory_dir else None
        self._load()

    # ════════════════════════════════════════════
    #  持久化
    # ════════════════════════════════════════════

    def _load(self) -> None:
        """从磁盘载入历史记忆。

        损坏、缺字段、权限不足等任何异常都降级为空记忆：记忆是增强项，
        没有理由让一份坏 JSON 阻断整条分析流程。
        """
        if self._path is None or not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            entries = payload.get("entries", []) if isinstance(payload, dict) else []
            if not isinstance(entries, list):
                raise ValueError("entries 字段不是列表")

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                situation = entry.get("situation")
                recommendation = entry.get("recommendation")
                if isinstance(situation, str) and isinstance(recommendation, str):
                    self.documents.append(situation)
                    self.recommendations.append(recommendation)

            # 文件可能来自 max_situations 更大的旧配置，载入时同样执行淘汰
            self._evict_overflow()
            self._index_dirty = True
            logger.debug("已载入记忆 %s：%d 条（%s）", self.name, len(self.documents), self._path)
        except Exception as e:  # noqa: BLE001
            logger.warning("记忆载入失败，按空记忆继续（%s）：%s", self._path, e)
            self.documents = []
            self.recommendations = []

    def _persist(self) -> None:
        """原子写盘。失败只记录告警——记忆是增强项，不能拖垮分析流程。"""
        if self._path is None:
            return
        try:
            with self._lock:
                payload = {
                    "version": _PERSIST_VERSION,
                    "name": self.name,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "max_situations": self._max_situations,
                    "entries": [
                        {"situation": situation, "recommendation": recommendation}
                        for situation, recommendation in zip(self.documents, self.recommendations, strict=False)
                    ],
                }
            atomic_write_json(self._path, payload)
        except Exception as e:  # noqa: BLE001
            logger.warning("记忆持久化失败（%s）：%s", self._path, e)

    # ════════════════════════════════════════════
    #  分词与检索
    # ════════════════════════════════════════════

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

    def _ensure_index(self):
        """惰性重建 BM25 索引，仅在标记为脏时才执行。"""
        if not self._index_dirty:
            return
        self._rebuild_index()
        self._index_dirty = False

    def _evict_overflow(self) -> None:
        """FIFO 淘汰超出上限的最旧条目。"""
        while len(self.documents) > self._max_situations:
            self.documents.pop(0)
            self.recommendations.pop(0)

    def add_situations(self, situations_and_advice: list[tuple[str, str]]):
        """添加情景记忆，超出上限时 FIFO 淘汰最旧条目，并落盘。"""
        if not situations_and_advice:
            return
        with self._lock:
            for situation, recommendation in situations_and_advice:
                self.documents.append(situation)
                self.recommendations.append(recommendation)
            self._evict_overflow()
            self._index_dirty = True
        self._persist()

    def get_memories(self, current_situation: str, n_matches: int = 1) -> list[dict]:
        """根据当前情景检索最相似的历史记忆。"""
        with self._lock:
            self._ensure_index()
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

    def clear(self, persist: bool = True) -> None:
        """清空记忆。

        参数:
            persist: 为 True（默认）时同时删除落盘文件，避免下次启动又把旧记忆读回来。
        """
        with self._lock:
            self.documents = []
            self.recommendations = []
            self.bm25 = None
            self._index_dirty = False

        if persist and self._path is not None:
            try:
                self._path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("记忆文件删除失败（%s）：%s", self._path, e)
