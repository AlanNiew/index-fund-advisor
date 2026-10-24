"""评级历史落盘 —— 稳定化要「记得上次生效的是什么」。

存储形态：每只基金一个 JSON 文件（`{dir}/{fund_code}.json`），内容为按时间升序的
记录列表。用原子写（tmp → replace），进程被 kill 也不会留下半截文件。

两个刻意的设计：

- **directory 为 None 即不落盘**。与 `FinancialSituationMemory` 的 memory_dir 语义
  一致：单元测试拿到的极简 config 没有目录，于是它们仍然无副作用。
- **同一天重复跑覆盖当天那条**，不是追加。否则「连跑两次」会被算成「连续两次同向」，
  一天的证据就能让评级改口，稳定化也就白做了。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ifa.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

_PERSIST_VERSION = 1
_UNSAFE_FILENAME = re.compile(r"[^0-9A-Za-z_.-]+")


@dataclass(frozen=True)
class HistoryEntry:
    """一次分析的评级记录（既有原始判断，也有当时生效的评级）。"""

    date: str
    raw_rating: str
    effective_rating: str
    confidence: str = ""
    status: str = ""
    reason: str = ""
    pending_rating: str = ""
    recorded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "raw_rating": self.raw_rating,
            "effective_rating": self.effective_rating,
            "confidence": self.confidence,
            "status": self.status,
            "reason": self.reason,
            "pending_rating": self.pending_rating,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> HistoryEntry | None:
        """宽容解析：字段缺失或类型不对就返回 None，由调用方跳过这一条。"""
        if not isinstance(payload, dict):
            return None
        date = str(payload.get("date") or "").strip()
        raw_rating = str(payload.get("raw_rating") or "").strip()
        effective_rating = str(payload.get("effective_rating") or "").strip()
        if not date or not raw_rating or not effective_rating:
            return None
        return cls(
            date=date,
            raw_rating=raw_rating,
            effective_rating=effective_rating,
            confidence=str(payload.get("confidence") or ""),
            status=str(payload.get("status") or ""),
            reason=str(payload.get("reason") or ""),
            pending_rating=str(payload.get("pending_rating") or ""),
            recorded_at=str(payload.get("recorded_at") or ""),
        )


class RatingHistoryStore:
    """按基金代码读写评级历史。读失败一律当「没有历史」，绝不让稳定化层炸掉主流程。"""

    def __init__(self, directory: str | Path | None, *, max_entries: int = 120) -> None:
        self._directory = Path(directory) if directory else None
        self._max_entries = max(2, int(max_entries))
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path | None:
        return self._directory

    @property
    def enabled(self) -> bool:
        return self._directory is not None

    def path_for(self, fund_code: str) -> Path | None:
        if self._directory is None:
            return None
        safe = _UNSAFE_FILENAME.sub("_", str(fund_code).strip()) or "unknown"
        return self._directory / f"{safe}.json"

    def load(self, fund_code: str) -> list[HistoryEntry]:
        path = self.path_for(fund_code)
        if path is None or not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # 损坏的文件不该阻断分析
            logger.warning("评级历史读取失败，按无历史处理: %s (%s)", path, exc)
            return []
        records = payload.get("entries") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            return []
        entries = [entry for entry in (HistoryEntry.from_dict(item) for item in records) if entry is not None]
        entries.sort(key=lambda entry: entry.date)
        return entries[-self._max_entries :]

    def last(self, fund_code: str) -> HistoryEntry | None:
        entries = self.load(fund_code)
        return entries[-1] if entries else None

    def append(self, fund_code: str, entry: HistoryEntry) -> bool:
        """写入一条记录，返回是否真的落盘了（未配置目录时为 False）。

        同一天重复调用会替换当天那条（见模块 docstring）。
        """
        path = self.path_for(fund_code)
        if path is None:
            return False
        with self._lock:
            entries = self.load(fund_code)
            if entries and entries[-1].date == entry.date:
                entries[-1] = entry
            else:
                entries.append(entry)
                entries.sort(key=lambda item: item.date)
            entries = entries[-self._max_entries :]
            payload = {
                "version": _PERSIST_VERSION,
                "fund_code": str(fund_code),
                "updated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
                "entries": [item.to_dict() for item in entries],
            }
            try:
                atomic_write_json(path, payload)
            except Exception as exc:
                logger.warning("评级历史写入失败（不影响本次分析）: %s (%s)", path, exc)
                return False
            return True

    def clear(self, fund_code: str) -> bool:
        """删除某只基金的历史（测试与人工重置用）。返回是否删掉了文件。"""
        path = self.path_for(fund_code)
        if path is None:
            return False
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            except Exception as exc:
                logger.warning("评级历史删除失败: %s (%s)", path, exc)
                return False
            return True
