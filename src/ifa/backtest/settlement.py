# ifa/backtest/settlement.py
"""评级结算 —— 把「已经产出的评级」与「事后实际收益」对上账，不重跑 LLM。

与 `rating_validator` 的分工：validator 会**重新跑一遍历史分析**（每次几十次 LLM 调用、
几十分钟），适合偶尔做一次大样本校验；settlement 直接读 `results/logs/` 里已经落盘的
分析日志（每个日志都带 analysis_date 与 final_rating），只补取价格数据，因此
**零 LLM 成本**，可以每周甚至每天跑，用来回答一个具体问题：

    「稳定化之后的评级，是变准了，还是只是变钝了？」

为此结算必须同时维护两条口径（这也是本模块存在的核心原因）：

- **生效评级**（effective）—— 用户实际看到的那个评级；
- **原始评级**（raw）—— 当日辩论的原始结论。

两条口径用同一批到期的前瞻收益统计，差异才可归因于「稳定化」；只报一条会被
Steelman 成「稳定化有效」或「稳定化有害」的单方面证据。样本量小、多视界多重比较
的告诫沿用 validator 的智识诚实原则，见 `format_settlement_report` 的显式提示。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ifa.atomic_io import atomic_write_json, atomic_write_text
from ifa.backtest.benchmarks import resolve_benchmark
from ifa.backtest.engine import run_backtest
from ifa.backtest.rating_stats import RATING_ORDER, ordered_horizons
from ifa.backtest.rating_validator import (
    RatingRecord,
    RatingValidationResult,
    add_trading_days,
    benchmark_return,
    compute_statistics,
    format_validation_report,
    lookup_fund_names,
)

__all__ = [
    "DEFAULT_HOLD_DAYS",
    "ForwardReturnProvider",
    "FundStability",
    "HorizonReturn",
    "LogScan",
    "LoggedRating",
    "SettlementResult",
    "StabilitySummary",
    "compute_stability_summary",
    "format_settlement_report",
    "scan_rating_logs",
    "settle_logged_ratings",
    "write_settlement",
]

logger = logging.getLogger(__name__)

DEFAULT_HOLD_DAYS = 60
_DEFAULT_CACHE_NAME = "forward_returns.json"
_VALID_RATINGS = frozenset(RATING_ORDER)


# ── 1. 读日志 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LoggedRating:
    """从一份分析日志里抽出来的一条评级。"""

    fund_code: str
    analysis_date: str
    rating: str  # 生效评级
    raw_rating: str  # 原始评级（P-A 之前的历史日志里等于 rating）
    confidence: str
    mode: str
    stability_status: str  # initial/unchanged/pending/confirmed/red_line/""（老日志）
    source: str  # 日志文件路径

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "analysis_date": self.analysis_date,
            "rating": self.rating,
            "raw_rating": self.raw_rating,
            "confidence": self.confidence,
            "mode": self.mode,
            "stability_status": self.stability_status,
            "source": self.source,
        }


@dataclass
class LogScan:
    """扫描结果 —— 有效记录 + 被跳过的文件及原因（跳过必须可解释，不能静默丢样本）。"""

    entries: list[LoggedRating] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    files: int = 0
    duplicates: int = 0


def _first_code(value: Any) -> str:
    if isinstance(value, str):
        for part in value.replace("/", ",").split(","):
            if part.strip():
                return part.strip()
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            if str(item).strip():
                return str(item).strip()
    return ""


def _date_from_name(path: Path) -> str:
    head = path.name.split("_", 1)[0]
    if len(head) == 10 and head[4] == "-" and head[7] == "-":
        return head
    return ""


def _stability_status(payload: Mapping[str, Any]) -> str:
    block = payload.get("rating_stability")
    if isinstance(block, dict):
        return str(block.get("status") or "")
    return ""


def scan_rating_logs(
    results_dir: str | Path,
    *,
    modes: Sequence[str] | None = None,
    since: str | None = None,
    until: str | None = None,
) -> LogScan:
    """扫描 `{results_dir}/logs/**/*.json`，抽出所有可用评级。

    同一 (基金, 日期, 模式) 若有多份日志（重跑过），保留修改时间最新的一份，
    否则重跑会产生重复样本，把命中率算成「那天我们跑了三次」。
    """
    scan = LogScan()
    root = Path(results_dir) / "logs"
    if not root.is_dir():
        return scan

    chosen: dict[tuple[str, str, str], tuple[float, Path, LoggedRating]] = {}
    for path in sorted(root.rglob("*.json")):
        scan.files += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            scan.skipped.append({"path": str(path), "reason": f"JSON 解析失败: {exc!s:.80s}"})
            continue
        if not isinstance(payload, dict):
            scan.skipped.append({"path": str(path), "reason": "日志不是 JSON 对象"})
            continue
        if str(payload.get("error") or "").strip():
            scan.skipped.append({"path": str(path), "reason": f"当次分析失败: {str(payload.get('error'))[:60]}"})
            continue

        code = _first_code(payload.get("fund_codes"))
        if not code:
            scan.skipped.append({"path": str(path), "reason": "缺少 fund_codes"})
            continue
        analysis_date = str(payload.get("analysis_date") or "").strip() or _date_from_name(path)
        if not analysis_date:
            scan.skipped.append({"path": str(path), "reason": "缺少 analysis_date"})
            continue
        mode = str(payload.get("mode") or "").strip()
        if modes and mode not in set(modes):
            continue

        rating = str(payload.get("final_rating") or "").strip().upper()
        if rating not in _VALID_RATINGS:
            scan.skipped.append({"path": str(path), "reason": f"评级不可识别: {rating or '(空)'}"})
            continue
        raw_rating = str(payload.get("final_rating_raw") or "").strip().upper() or rating
        if raw_rating not in _VALID_RATINGS:
            raw_rating = rating
        if since and analysis_date < since:
            continue
        if until and analysis_date > until:
            continue

        entry = LoggedRating(
            fund_code=code,
            analysis_date=analysis_date,
            rating=rating,
            raw_rating=raw_rating,
            confidence=str(payload.get("final_confidence") or ""),
            mode=mode,
            stability_status=_stability_status(payload),
            source=str(path),
        )
        key = (code, analysis_date, mode)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        previous = chosen.get(key)
        if previous is None:
            chosen[key] = (mtime, path, entry)
        else:
            scan.duplicates += 1
            if mtime >= previous[0]:
                chosen[key] = (mtime, path, entry)

    scan.entries = sorted(
        (item[2] for item in chosen.values()),
        key=lambda item: (item.fund_code, item.analysis_date, item.mode),
    )
    return scan


# ── 2. 稳定化自身的度量（不依赖价格数据）────────────────────────────────


@dataclass(frozen=True)
class FundStability:
    """单只基金的评级稳定性：生效评级改了几次 vs 原始评级改了几次。"""

    fund_code: str
    days: int
    effective_changes: int
    raw_changes: int
    held_days: int  # 生效评级 != 原始评级 的天数（被闸门挡住）
    confirmed_days: int
    pending_days: int
    red_line_days: int
    first_date: str
    last_date: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "days": self.days,
            "effective_changes": self.effective_changes,
            "raw_changes": self.raw_changes,
            "held_days": self.held_days,
            "confirmed_days": self.confirmed_days,
            "pending_days": self.pending_days,
            "red_line_days": self.red_line_days,
            "first_date": self.first_date,
            "last_date": self.last_date,
        }


@dataclass
class StabilitySummary:
    """全样本的稳定性汇总。`effective_churn_reduction` 是最直观的那个数。"""

    funds: list[FundStability] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    total_days: int = 0
    invalid_days: int = 0

    @property
    def effective_changes(self) -> int:
        return sum(item.effective_changes for item in self.funds)

    @property
    def raw_changes(self) -> int:
        return sum(item.raw_changes for item in self.funds)

    @property
    def held_days(self) -> int:
        return sum(item.held_days for item in self.funds)

    @property
    def effective_churn_reduction(self) -> float | None:
        """(原始变更数 - 生效变更数) / 原始变更数；原始无变更时为 None（不是 0）。"""
        raw = self.raw_changes
        if raw <= 0:
            return None
        return (raw - self.effective_changes) / raw

    def to_dict(self) -> dict[str, Any]:
        return {
            "funds": [item.to_dict() for item in self.funds],
            "status_counts": dict(self.status_counts),
            "total_days": self.total_days,
            "invalid_days": self.invalid_days,
            "effective_changes": self.effective_changes,
            "raw_changes": self.raw_changes,
            "held_days": self.held_days,
            "effective_churn_reduction": self.effective_churn_reduction,
        }


def _count_changes(ratings: Sequence[str]) -> int:
    return sum(1 for previous, current in zip(ratings, ratings[1:], strict=False) if previous != current)


def compute_stability_summary(entries: Iterable[LoggedRating]) -> StabilitySummary:
    """按基金统计评级变更次数 —— 不需要任何价格数据，纯日志就能算。"""
    summary = StabilitySummary()
    grouped: dict[str, list[LoggedRating]] = {}
    for entry in entries:
        if entry.rating not in _VALID_RATINGS:
            summary.invalid_days += 1
            continue
        grouped.setdefault(entry.fund_code, []).append(entry)
        key = entry.stability_status or "unknown"
        summary.status_counts[key] = summary.status_counts.get(key, 0) + 1
        summary.total_days += 1

    for code, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda item: item.analysis_date)
        effective = [item.rating for item in ordered]
        raw = [item.raw_rating for item in ordered]
        summary.funds.append(
            FundStability(
                fund_code=code,
                days=len(ordered),
                effective_changes=_count_changes(effective),
                raw_changes=_count_changes(raw),
                held_days=sum(1 for item in ordered if item.rating != item.raw_rating),
                confirmed_days=sum(1 for item in ordered if item.stability_status == "confirmed"),
                pending_days=sum(1 for item in ordered if item.stability_status == "pending"),
                red_line_days=sum(1 for item in ordered if item.stability_status == "red_line"),
                first_date=ordered[0].analysis_date,
                last_date=ordered[-1].analysis_date,
            )
        )
    return summary


# ── 3. 前瞻收益取数（带磁盘缓存）────────────────────────────────────────


@dataclass(frozen=True)
class HorizonReturn:
    """某个视界上的前瞻收益。`matured=False` 表示数据还没走满这些交易日。"""

    value: float | None = None
    matured: bool = False
    trading_days: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None


class ForwardReturnProvider:
    """取「某基金/基准在某日之后 N 个交易日」的收益，并缓存到磁盘。

    缓存只存**已到期**的结果：未到期是随时间变化的状态，缓存下来会让下次运行
    永远读到昨天的「还没到期」。
    """

    def __init__(self, cache_path: str | Path | None = None, *, use_cache: bool = True) -> None:
        self._cache_path = Path(cache_path) if (cache_path and use_cache) else None
        self._cache: dict[str, dict[str, Any]] = self._load_cache()
        self._dirty = False
        self.cache_hits = 0
        self.remote_fetches = 0

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if self._cache_path is None or not self._cache_path.exists():
            return {}
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("前瞻收益缓存读取失败，忽略: %s (%s)", self._cache_path, exc)
            return {}
        data = payload.get("entries") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else {}

    def save(self) -> bool:
        if self._cache_path is None or not self._dirty:
            return False
        try:
            atomic_write_json(
                self._cache_path,
                {
                    "version": 1,
                    "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "entries": self._cache,
                },
            )
        except Exception as exc:
            logger.warning("前瞻收益缓存写入失败: %s (%s)", self._cache_path, exc)
            return False
        self._dirty = False
        return True

    def fund_return(self, code: str, date: str, horizon: int) -> HorizonReturn:
        key = f"fund|{code}|{date}|{horizon}"
        cached = self._cache.get(key)
        if isinstance(cached, dict) and cached.get("matured"):
            self.cache_hits += 1
            return HorizonReturn(
                value=cached.get("value"),
                matured=True,
                trading_days=int(cached.get("trading_days") or horizon),
            )
        end_date = add_trading_days(date, horizon)
        self.remote_fetches += 1
        try:
            backtest = run_backtest(code, date, end_date)
        except Exception as exc:
            return HorizonReturn(error=f"收益获取异常: {exc!s:.80s}")
        if backtest.error:
            return HorizonReturn(error=f"收益数据: {backtest.error[:80]}")
        matured = backtest.trading_days >= horizon
        if matured:
            self._cache[key] = {
                "value": backtest.total_return_pct,
                "matured": True,
                "trading_days": backtest.trading_days,
                "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._dirty = True
        return HorizonReturn(
            value=backtest.total_return_pct,
            matured=matured,
            trading_days=backtest.trading_days,
        )

    def bench_return(self, code: str, date: str, horizon: int) -> float | None:
        key = f"bench|{code}|{date}|{horizon}"
        if key in self._cache:
            self.cache_hits += 1
            value = self._cache[key].get("value")
            return None if value is None else float(value)
        self.remote_fetches += 1
        value = benchmark_return(code, date, horizon)
        if value is not None:
            self._cache[key] = {
                "value": value,
                "matured": True,
                "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._dirty = True
        return value


# ── 4. 结算 ────────────────────────────────────────────────────────────


@dataclass
class SettlementResult:
    """一次结算的全部产出：两条口径的统计 + 稳定性度量 + 元信息。"""

    generated_at: str
    results_dir: str
    hold_days: int
    horizons: tuple[int, ...]
    entries: list[LoggedRating]
    effective: RatingValidationResult
    raw: RatingValidationResult
    stability: StabilitySummary
    log_files: int = 0
    duplicates: int = 0
    skipped_logs: list[dict[str, str]] = field(default_factory=list)
    matured_counts: dict[int, int] = field(default_factory=dict)
    immature_n: int = 0
    cache_hits: int = 0
    remote_fetches: int = 0
    fund_names_source: str = "none"
    warnings: list[str] = field(default_factory=list)

    @property
    def entries_n(self) -> int:
        return len(self.entries)

    def arm_metrics(self, result: RatingValidationResult) -> dict[str, Any]:
        """扁平化一个口径的主视界指标（报告与 JSON 共用）。"""
        primary = next((item for item in result.horizons if item.hold_days == self.hold_days), None)
        if primary is None:
            return {"total": result.total, "valid": result.valid, "skipped": result.skipped}
        return {
            "total": result.total,
            "valid": result.valid,
            "skipped": result.skipped,
            "bullish_n": primary.bullish_n,
            "bearish_n": primary.bearish_n,
            "bullish_hit_rate": primary.bullish_hit_rate,
            "bearish_hit_rate": primary.bearish_hit_rate,
            "bullish_excess_hit_rate": primary.bullish_excess_hit_rate,
            "bearish_excess_hit_rate": primary.bearish_excess_hit_rate,
            "mean_excess_pct": primary.mean_excess_pct,
            "median_excess_pct": primary.median_excess_pct,
            "rank_ic": primary.rank_ic,
            "rank_ic_n": primary.rank_ic_n,
            "monotonicity": primary.monotonicity,
            "hold_n": primary.hold_n,
            "confidence_spread": primary.confidence_spread,
            "excess_n": primary.excess_n,
            "excess_p": primary.excess_p,
        }

    def comparison(self) -> dict[str, Any]:
        """两条口径的并排对照 + 差值（差值才是「稳定化」可归因的效果）。"""
        effective = self.arm_metrics(self.effective)
        raw = self.arm_metrics(self.raw)
        deltas: dict[str, float | None] = {}
        for key in (
            "bullish_hit_rate",
            "bearish_hit_rate",
            "bullish_excess_hit_rate",
            "bearish_excess_hit_rate",
            "mean_excess_pct",
            "rank_ic",
            "monotonicity",
        ):
            left, right = effective.get(key), raw.get(key)
            deltas[key] = None if left is None or right is None else float(left) - float(right)
        return {"hold_days": self.hold_days, "effective": effective, "raw": raw, "delta": deltas}

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "results_dir": self.results_dir,
            "hold_days": self.hold_days,
            "horizons": list(self.horizons),
            "log_files": self.log_files,
            "duplicates": self.duplicates,
            "skipped_logs": self.skipped_logs,
            "matured_counts": {str(key): value for key, value in sorted(self.matured_counts.items())},
            "immature_n": self.immature_n,
            "cache_hits": self.cache_hits,
            "remote_fetches": self.remote_fetches,
            "fund_names_source": self.fund_names_source,
            "warnings": self.warnings,
            "stability": self.stability.to_dict(),
            "comparison": self.comparison(),
            "entries": [entry.to_dict() for entry in self.entries],
            "effective": {
                "total": self.effective.total,
                "valid": self.effective.valid,
                "skipped": self.effective.skipped,
                "warnings": list(self.effective.warnings),
                "benchmark_labels": list(self.effective.benchmark_labels),
                "benchmark_fallback_n": self.effective.benchmark_fallback_n,
                "horizons": [item.to_dict() for item in self.effective.horizons],
            },
            "raw": {
                "total": self.raw.total,
                "valid": self.raw.valid,
                "skipped": self.raw.skipped,
                "warnings": list(self.raw.warnings),
                "horizons": [item.to_dict() for item in self.raw.horizons],
            },
        }


def _record_dict(record: RatingRecord) -> dict[str, Any]:
    return {
        "fund_code": record.fund_code,
        "analysis_date": record.analysis_date,
        "rating": record.rating,
        "confidence": record.confidence,
        "forward_return_pct": record.forward_return_pct,
        "benchmark_return_pct": record.benchmark_return_pct,
        "excess_return_pct": record.excess_return_pct,
        "hold_days": record.hold_days,
        "fetch_error": record.fetch_error,
        "returns_by_horizon": {str(key): value for key, value in record.returns_by_horizon.items()},
        "benchmark_by_horizon": {str(key): value for key, value in record.benchmark_by_horizon.items()},
        "excess_by_horizon": {str(key): value for key, value in record.excess_by_horizon.items()},
        "horizon_errors": {str(key): value for key, value in record.horizon_errors.items()},
        "benchmark_code": record.benchmark_code,
        "benchmark_label": record.benchmark_label,
        "benchmark_source": record.benchmark_source,
    }


def _build_arm(
    entries: Sequence[LoggedRating],
    *,
    rating_of: str,
    hold_days: int,
    horizons: Sequence[int],
    provider: ForwardReturnProvider,
    fund_names: Mapping[str, str],
    benchmark_overrides: dict[str, str] | None,
    matured_counts: dict[int, int],
    immature: set[str],
) -> RatingValidationResult:
    """为一套评级口径构造 RatingRecord 并统计。

    两条口径共享同一次取数（收益与评级无关），所以价格数据只取一遍。
    """
    records: list[RatingRecord] = []
    for entry in entries:
        spec = resolve_benchmark(entry.fund_code, fund_names.get(entry.fund_code), overrides=benchmark_overrides)
        raw_rating = entry.raw_rating if rating_of == "raw" else entry.rating
        record = RatingRecord(
            fund_code=entry.fund_code,
            analysis_date=entry.analysis_date,
            rating=raw_rating,
            confidence=entry.confidence,
            benchmark_code=spec.code,
            benchmark_label=spec.label,
            benchmark_source=spec.source,
        )
        primary_hold: int | None = None
        for horizon in horizons:
            outcome = provider.fund_return(entry.fund_code, entry.analysis_date, horizon)
            if outcome.value is None:
                record.horizon_errors[horizon] = outcome.error or "收益数据缺失"
                continue
            if not outcome.matured:
                # 未到期不能进统计：否则「最近 5 天的涨幅」会被当成「60 日收益」
                immature.add(f"{entry.fund_code}|{entry.analysis_date}|{horizon}")
                record.horizon_errors[horizon] = f"未到期（仅 {outcome.trading_days}/{horizon} 个交易日）"
                continue
            value = float(outcome.value)
            record.returns_by_horizon[horizon] = value
            matured_counts[horizon] = matured_counts.get(horizon, 0) + 1
            if horizon == hold_days:
                primary_hold = outcome.trading_days
            bench = provider.bench_return(spec.code, entry.analysis_date, horizon)
            if bench is not None:
                record.benchmark_by_horizon[horizon] = bench
                record.excess_by_horizon[horizon] = value - bench

        if hold_days in record.returns_by_horizon:
            record.forward_return_pct = record.returns_by_horizon[hold_days]
            record.hold_days = primary_hold or 0
        if hold_days in record.benchmark_by_horizon:
            record.benchmark_return_pct = record.benchmark_by_horizon[hold_days]
        if hold_days in record.excess_by_horizon:
            record.excess_return_pct = record.excess_by_horizon[hold_days]
        if not record.returns_by_horizon:
            record.fetch_error = next(iter(record.horizon_errors.values()), "收益数据缺失")
        records.append(record)

    return compute_statistics(records, hold_days, horizons=horizons)


def settle_logged_ratings(
    results_dir: str | Path = "results",
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    horizons: Sequence[int] | None = None,
    modes: Sequence[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    fund_names: Mapping[str, str] | None = None,
    benchmark_overrides: dict[str, str] | None = None,
    provider: ForwardReturnProvider | None = None,
    cache_path: str | Path | None = None,
    use_cache: bool = True,
) -> SettlementResult:
    """读日志 → 逐视界补取前瞻收益 → 生效/原始两条口径统计 + 稳定性度量。

    零 LLM 调用；唯一的网络成本是价格数据（有磁盘缓存，重复运行几乎免费）。
    """
    stat_horizons = ordered_horizons(horizons, hold_days)
    scan = scan_rating_logs(results_dir, modes=modes, since=since, until=until)

    names_source = "provided"
    names: dict[str, str] = dict(fund_names or {})
    if not names:
        codes = sorted({entry.fund_code for entry in scan.entries})
        names = lookup_fund_names(codes) if codes else {}
        names_source = "remote" if names else "none"

    returns = provider or ForwardReturnProvider(cache_path, use_cache=use_cache)
    matured_counts: dict[int, int] = {}
    immature: set[str] = set()

    effective = _build_arm(
        scan.entries,
        rating_of="effective",
        hold_days=hold_days,
        horizons=stat_horizons,
        provider=returns,
        fund_names=names,
        benchmark_overrides=benchmark_overrides,
        matured_counts=matured_counts,
        immature=immature,
    )
    raw = _build_arm(
        scan.entries,
        rating_of="raw",
        hold_days=hold_days,
        horizons=stat_horizons,
        provider=returns,
        fund_names=names,
        benchmark_overrides=benchmark_overrides,
        matured_counts={},
        immature=immature,
    )
    returns.save()

    stability = compute_stability_summary(scan.entries)
    warnings: list[str] = []
    if not scan.entries:
        warnings.append("没有找到可用分析日志，先跑几天 ifa 分析再结算")
    if stability.raw_changes and stability.effective_changes == stability.raw_changes:
        warnings.append("原始评级与生效评级变更次数相同：稳定化在本批样本上没有起作用（或样本内无待确认变更）")
    if any(entry.stability_status == "" for entry in scan.entries):
        warnings.append("部分日志产生于稳定化上线之前（无 rating_stability 字段），其生效评级即原始评级")

    return SettlementResult(
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        results_dir=str(results_dir),
        hold_days=hold_days,
        horizons=stat_horizons,
        entries=list(scan.entries),
        effective=effective,
        raw=raw,
        stability=stability,
        log_files=scan.files,
        duplicates=scan.duplicates,
        skipped_logs=scan.skipped,
        matured_counts=matured_counts,
        immature_n=len(immature),
        cache_hits=returns.cache_hits,
        remote_fetches=returns.remote_fetches,
        fund_names_source=names_source,
        warnings=warnings,
    )


# ── 5. 报告 ────────────────────────────────────────────────────────────


def _fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.2%}"


def _fmt_signed(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:+.{digits}f}"


def _delta_text(value: float | None, *, pct: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.2%}" if pct else f"{value:+.3f}"


def _compare_rows(result: SettlementResult) -> list[str]:
    comparison = result.comparison()
    effective = comparison["effective"]
    raw = comparison["raw"]
    deltas = comparison["delta"]
    specs = (
        ("看涨命中率（绝对）", "bullish_hit_rate", True),
        ("看跌命中率（绝对）", "bearish_hit_rate", True),
        ("看涨超额命中率", "bullish_excess_hit_rate", True),
        ("看跌超额命中率", "bearish_excess_hit_rate", True),
        ("平均超额（%）", "mean_excess_pct", False),
        ("rank IC", "rank_ic", False),
        ("单调性", "monotonicity", False),
    )
    lines = ["| 指标 | 生效评级 | 原始评级 | 差值（生效-原始） |", "|------|---------|---------|------------------|"]
    for label, key, as_pct in specs:
        left = effective.get(key)
        right = raw.get(key)
        left_text = _fmt_ratio(left) if as_pct else _fmt_signed(left)
        right_text = _fmt_ratio(right) if as_pct else _fmt_signed(right)
        lines.append(f"| {label} | {left_text} | {right_text} | {_delta_text(deltas.get(key), pct=as_pct)} |")
    lines.append(f"| 有效样本 | {effective.get('valid', 0)} | {raw.get('valid', 0)} | — |")
    return lines


def _stability_rows(result: SettlementResult) -> list[str]:
    stability = result.stability
    lines = [
        "| 基金 | 天数 | 生效变更 | 原始变更 | 被挡住 | 确认变更 | 待确认 | 红线 | 区间 |",
        "|------|------|---------|---------|-------|---------|-------|------|------|",
    ]
    for item in stability.funds:
        lines.append(
            f"| {item.fund_code} | {item.days} | {item.effective_changes} | {item.raw_changes} | "
            f"{item.held_days} | {item.confirmed_days} | {item.pending_days} | {item.red_line_days} | "
            f"{item.first_date} ~ {item.last_date} |"
        )
    if not stability.funds:
        lines.append("| — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — |")
    return lines


def format_settlement_report(result: SettlementResult) -> str:
    """把结算结果格式化为 Markdown（两条口径并排 + 稳定性 + 各自明细）。"""
    comparison = result.comparison()
    lines: list[str] = [
        "【评级结算报告 · 智识诚实声明】",
        "本报告基于「已经产出的评级 + 事后价格」，不重新运行 LLM。样本量有限、存在幸存者偏差：",
        "样本 < 30 时任何「命中率更高」的结论都不成立；多视界/多指标属多重比较，只有主视界可当确认性结论。",
        "生效评级与原始评级的差异只说明「稳定化改变了什么」，不证明它变好或变坏。",
        "过往表现不代表未来结果，本报告不构成投资建议。",
        "",
        "---",
        "",
        "# 评级结算报告（来自已有分析日志）",
        "",
        f"**结算时间**: {result.generated_at}  ",
        f"**数据来源**: `{result.results_dir}/logs/`（{result.log_files} 份日志，去重 {result.duplicates} 份）  ",
        f"**样本**: {result.entries_n} 条评级  ",
        f"**主视界**: {result.hold_days} 个交易日；同时统计 "
        f"{' / '.join(str(item) for item in result.horizons)} 个交易日  ",
        "**到期情况**: "
        + "、".join(f"+{k} 日 {v} 条" for k, v in sorted(result.matured_counts.items()))
        + (f"；未到期 {result.immature_n} 条（不进入统计）" if result.immature_n else ""),
        f"**取数**: 价格请求 {result.remote_fetches} 次，缓存命中 {result.cache_hits} 次；"
        f"基金名称来源 {result.fund_names_source}",
        "",
    ]

    if result.warnings:
        lines.append("## 需要留意")
        lines.extend(f"- {warning}" for warning in result.warnings)
        lines.append("")

    lines.append(f"## 一、生效评级 vs 原始评级（主视界 {result.hold_days} 交易日）")
    lines.append("")
    lines.extend(_compare_rows(result))
    lines.append("")
    churn = result.stability.effective_churn_reduction
    lines.append(
        f"**评级变更**: 生效 {result.stability.effective_changes} 次 / 原始 {result.stability.raw_changes} 次"
        + (f"（减少 {churn:.0%}）" if churn is not None else "")
        + f"；被稳定化闸门挡住的原始变更 {result.stability.held_days} 条。"
    )
    if comparison["delta"]["bullish_excess_hit_rate"] is not None:
        lines.append(
            "生效评级的看涨超额命中率相对原始评级 "
            f"{_delta_text(comparison['delta']['bullish_excess_hit_rate'], pct=True)} —— "
            "样本不足时这一差值就是噪声，不要据此调整参数。"
        )
    lines.append("")

    lines.append("## 二、评级稳定性（纯日志口径，与价格无关）")
    lines.append("")
    lines.extend(_stability_rows(result))
    lines.append("")
    if result.stability.status_counts:
        counts = "、".join(f"{key} {value}" for key, value in sorted(result.stability.status_counts.items()))
        lines.append(f"状态分布: {counts}（unknown = 稳定化上线前的日志）")
        lines.append("")

    lines.append("## 三、生效评级明细")
    lines.append("")
    lines.append(_strip_arm_header(format_validation_report(result.effective), "生效评级（用户实际看到的口径）"))
    lines.append("")
    lines.append("## 四、原始评级明细")
    lines.append("")
    lines.append(_strip_arm_header(format_validation_report(result.raw), "原始评级（当日辩论的原始结论）"))
    lines.append("")
    if result.skipped_logs:
        lines.append(f"## 五、被跳过的日志（{len(result.skipped_logs)} 份）")
        lines.append("")
        for item in result.skipped_logs[:50]:
            lines.append(f"- `{item['path']}`: {item['reason']}")
        if len(result.skipped_logs) > 50:
            lines.append(f"- ……另有 {len(result.skipped_logs) - 50} 份省略")
        lines.append("")
    return "\n".join(lines)


def _strip_arm_header(report: str, title: str) -> str:
    """去掉单口径报告自带的声明与一级标题，避免在同一份文档里重复。"""
    body = report
    if "---" in body:
        body = body.split("---", 1)[1]
    body = body.replace("# 评级验证报告", f"### {title}", 1)
    return body.strip()


def write_settlement(result: SettlementResult, output_dir: str | Path) -> tuple[Path, Path]:
    """写出 JSON + Markdown 两份结算结果，返回两者路径。"""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = result.generated_at[:10] or datetime.now().strftime("%Y-%m-%d")
    json_path = directory / f"settled_{stamp}.json"
    md_path = directory / f"settled_{stamp}.md"
    atomic_write_json(json_path, result.to_dict())
    atomic_write_text(md_path, format_settlement_report(result))
    return json_path, md_path
