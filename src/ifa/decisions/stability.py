"""评级稳定化规则（纯函数，无 IO）。

规则只有一条主线和两个例外：

- **主线**：原始评级与当前生效评级不同时，要求「连续 `confirm_runs` 次分析都给出
  同一个原始评级」才生效；未达门槛则维持生效评级，并记录「待确认 N/M」。
- **例外 1（硬红线）**：落到 SELL 立即生效 —— 风险事件不该排队等第二次确认。
  固态红线列表可通过 `StabilityConfig.red_line_ratings` 覆盖。
- **例外 2（首次）**：没有历史时直接采用原始评级（否则新基金永远发不出评级）。

为什么不是「跨档阈值」：BUY 与 UNDERWEIGHT 在 5 级词表里已相差 2 档，阈值方案对
逐日交替完全无效；连续确认才真正消除单日噪声。

稳定性只用「原始评级序列」判定，不看置信度 —— 实测 30 次评级里 29 次是 Medium，
置信度目前没有区分度（P-C 待做），拿它做闸门等于没有闸门。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ifa.decisions.history import HistoryEntry

logger = logging.getLogger(__name__)

# 看多程度：数字越大越看多。只用于展示「跨了几档」，不参与稳定化判定。
RATING_RANK: dict[str, int] = {"STRONG_BUY": 4, "BUY": 3, "HOLD": 2, "UNDERWEIGHT": 1, "SELL": 0}

DEFAULT_CONFIRM_RUNS = 2
DEFAULT_MAX_ENTRIES = 120

#: 不排队、立即生效的评级（风险优先）。
RED_LINE_RATINGS: frozenset[str] = frozenset({"SELL"})

STATUS_INITIAL = "initial"
STATUS_UNCHANGED = "unchanged"
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_RED_LINE = "red_line"
STATUS_INVALID = "invalid"

_KNOWN_RATINGS = frozenset(RATING_RANK)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class StabilityConfig:
    """稳定化开关与参数，从扁平 runtime config 构造。"""

    enabled: bool = True
    confirm_runs: int = DEFAULT_CONFIRM_RUNS
    red_line_ratings: frozenset[str] = RED_LINE_RATINGS
    max_entries: int = DEFAULT_MAX_ENTRIES

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None = None) -> StabilityConfig:
        cfg: Mapping[str, Any] = config or {}
        return cls(
            enabled=_as_bool(cfg.get("rating_stability_enabled"), True),
            confirm_runs=max(1, _as_int(cfg.get("rating_stability_confirm_runs"), DEFAULT_CONFIRM_RUNS)),
            max_entries=max(2, _as_int(cfg.get("rating_stability_history_max_entries"), DEFAULT_MAX_ENTRIES)),
        )


@dataclass(frozen=True)
class StabilityDecision:
    """一次稳定化判定的完整结果：既有交付用的生效评级，也有审计用的原始评级。"""

    raw_rating: str
    effective_rating: str
    confidence: str = ""
    status: str = STATUS_INITIAL
    reason: str = ""
    previous_rating: str = ""
    pending_rating: str = ""
    pending_days: int = 0
    confirm_runs: int = DEFAULT_CONFIRM_RUNS
    history_days: int = 0

    @property
    def changed(self) -> bool:
        """生效评级相对上一次生效评级是否真的变了（首次记录不算变更）。"""
        return bool(self.previous_rating) and self.effective_rating != self.previous_rating

    @property
    def held(self) -> bool:
        """本次原始判断被稳定化闸门挡住了（交付评级 != 原始评级）。"""
        return self.effective_rating != self.raw_rating

    @property
    def is_valid(self) -> bool:
        return self.status != STATUS_INVALID

    @property
    def label(self) -> str:
        """给汇总表/邮件用的短标签。"""
        if self.status == STATUS_INVALID:
            return "评级缺失"
        if self.status == STATUS_RED_LINE:
            return f"红线生效 {self.previous_rating or '-'}→{self.raw_rating}"
        if self.status == STATUS_CONFIRMED:
            return f"确认变更 {self.previous_rating or '-'}→{self.raw_rating}（连续 {self.pending_days} 次）"
        if self.status == STATUS_PENDING:
            return f"维持 {self.effective_rating}（原始 {self.raw_rating}，待确认 {self.pending_days}/{self.confirm_runs}）"
        if self.status == STATUS_INITIAL:
            return "首次记录"
        return "维持不变"

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_rating": self.raw_rating,
            "effective_rating": self.effective_rating,
            "confidence": self.confidence,
            "status": self.status,
            "reason": self.reason,
            "previous_rating": self.previous_rating,
            "pending_rating": self.pending_rating,
            "pending_days": self.pending_days,
            "confirm_runs": self.confirm_runs,
            "history_days": self.history_days,
            "changed": self.changed,
            "held": self.held,
            "label": self.label,
        }


def _decision_for_invalid(raw_rating: str, confidence: str, history_days: int) -> StabilityDecision:
    return StabilityDecision(
        raw_rating=raw_rating,
        effective_rating=raw_rating,
        confidence=confidence,
        status=STATUS_INVALID,
        reason="原始评级无法识别，原样透传（不改写、不猜测）",
        history_days=history_days,
    )


def decide(
    raw_rating: str,
    confidence: str = "",
    history: Sequence[HistoryEntry] | None = None,
    config: StabilityConfig | None = None,
    *,
    as_of_date: str | None = None,
) -> StabilityDecision:
    """按稳定化规则算出本次生效评级。

    `as_of_date` 给定时只用更早的记录推断历史状态，因此同一天重跑不会把自己算进
    「连续确认」的次数里（这是稳定性判定的关键正确性条件）。
    """
    cfg = config or StabilityConfig()
    entries = list(history or [])
    if as_of_date:
        entries = [entry for entry in entries if entry.date < as_of_date]

    raw = str(raw_rating or "").strip()
    confidence_text = str(confidence or "").strip()

    if raw not in _KNOWN_RATINGS:
        return _decision_for_invalid(raw, confidence_text, len(entries))

    if not entries:
        return StabilityDecision(
            raw_rating=raw,
            effective_rating=raw,
            confidence=confidence_text,
            status=STATUS_INITIAL,
            reason="无历史记录，直接采用原始评级",
            confirm_runs=cfg.confirm_runs,
        )

    last = entries[-1]
    previous = last.effective_rating if last.effective_rating in _KNOWN_RATINGS else raw

    if raw == previous:
        return StabilityDecision(
            raw_rating=raw,
            effective_rating=previous,
            confidence=confidence_text,
            status=STATUS_UNCHANGED,
            reason="与上次生效评级一致",
            previous_rating=previous,
            confirm_runs=cfg.confirm_runs,
            history_days=len(entries),
        )

    if raw in cfg.red_line_ratings:
        return StabilityDecision(
            raw_rating=raw,
            effective_rating=raw,
            confidence=confidence_text,
            status=STATUS_RED_LINE,
            reason=f"{raw} 属硬红线，跳过连续确认立即生效",
            previous_rating=previous,
            pending_rating=raw,
            pending_days=1,
            confirm_runs=cfg.confirm_runs,
            history_days=len(entries),
        )

    streak = 0
    for entry in reversed(entries):
        if entry.raw_rating != raw:
            break
        streak += 1
    pending_days = streak + 1

    if pending_days >= cfg.confirm_runs:
        return StabilityDecision(
            raw_rating=raw,
            effective_rating=raw,
            confidence=confidence_text,
            status=STATUS_CONFIRMED,
            reason=f"原始评级连续 {pending_days} 次为 {raw}，达到确认门槛（{cfg.confirm_runs} 次）",
            previous_rating=previous,
            pending_rating=raw,
            pending_days=pending_days,
            confirm_runs=cfg.confirm_runs,
            history_days=len(entries),
        )

    return StabilityDecision(
        raw_rating=raw,
        effective_rating=previous,
        confidence=confidence_text,
        status=STATUS_PENDING,
        reason=(
            f"原始评级 {raw} 与生效评级 {previous} 不同，连续第 {pending_days}/{cfg.confirm_runs} 次，"
            "未达变更门槛，维持生效评级"
        ),
        previous_rating=previous,
        pending_rating=raw,
        pending_days=pending_days,
        confirm_runs=cfg.confirm_runs,
        history_days=len(entries),
    )
