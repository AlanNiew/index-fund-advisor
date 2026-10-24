"""评级结算测试 —— 从已落盘日志算「生效 vs 原始」两条口径，零 LLM。

重点覆盖三件容易出错的事：
1. 日志扫描要能跳过坏日志、并对同一 (基金, 日期, 模式) 的多份日志去重；
2. 未到期的前瞻收益**不进入统计**（不能把「最近 5 天涨幅」当成 60 日收益）；
3. 两条口径必须共用同一批价格——否则「稳定化前后的差异」里混进了取数差异。
"""

import json
import os

import pytest

from ifa.backtest import settlement
from ifa.backtest.settlement import (
    ForwardReturnProvider,
    LoggedRating,
    compute_stability_summary,
    format_settlement_report,
    scan_rating_logs,
    settle_logged_ratings,
    write_settlement,
)


def _write_log(
    root,
    *,
    code="510300",
    date="2026-01-05",
    mode="deep",
    rating="BUY",
    raw_rating=None,
    error="",
    stability=None,
    suffix="abc",
    name=None,
):
    """按 AdvisorGraph._log_state 的真实结构写一份日志。"""
    directory = root / "logs" / code
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "fund_codes": code,
        "analysis_date": date,
        "mode": mode,
        "asset_type": "etf",
        "final_rating": rating,
        "final_confidence": "Medium",
        "final_report": "报告全文",
        "error": error,
    }
    if raw_rating is not None:
        payload["final_rating_raw"] = raw_rating
    if stability is not None:
        payload["rating_stability"] = stability
    path = directory / (name or f"{date}_{mode}_{suffix}.json")
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestScanRatingLogs:
    def test_reads_rating_and_date(self, tmp_path):
        _write_log(tmp_path, rating="BUY", raw_rating="HOLD")
        scan = scan_rating_logs(tmp_path)
        assert scan.files == 1
        assert len(scan.entries) == 1
        entry = scan.entries[0]
        assert entry.fund_code == "510300"
        assert entry.analysis_date == "2026-01-05"
        assert entry.rating == "BUY"
        assert entry.raw_rating == "HOLD"

    def test_raw_rating_falls_back_to_effective(self, tmp_path):
        _write_log(tmp_path, rating="BUY")
        entry = scan_rating_logs(tmp_path).entries[0]
        assert entry.raw_rating == "BUY"

    def test_skips_error_logs(self, tmp_path):
        _write_log(tmp_path, error="LLM timeout")
        scan = scan_rating_logs(tmp_path)
        assert scan.entries == []
        assert len(scan.skipped) == 1

    def test_skips_invalid_rating(self, tmp_path):
        _write_log(tmp_path, rating="N/A")
        scan = scan_rating_logs(tmp_path)
        assert scan.entries == []
        assert "评级" in scan.skipped[0]["reason"]

    def test_skips_broken_json(self, tmp_path):
        directory = tmp_path / "logs" / "510300"
        directory.mkdir(parents=True)
        (directory / "broken.json").write_text("{oops", encoding="utf-8")
        scan = scan_rating_logs(tmp_path)
        assert scan.entries == []
        assert len(scan.skipped) == 1

    def test_date_falls_back_to_filename_prefix(self, tmp_path):
        directory = tmp_path / "logs" / "510300"
        directory.mkdir(parents=True)
        payload = {"fund_codes": "510300", "mode": "deep", "final_rating": "BUY"}
        (directory / "2026-01-06_deep_xyz.json").write_text(json.dumps(payload), encoding="utf-8")
        scan = scan_rating_logs(tmp_path)
        assert scan.entries[0].analysis_date == "2026-01-06"

    def test_duplicate_same_day_keeps_newest_mtime(self, tmp_path):
        old = _write_log(tmp_path, rating="BUY", suffix="old")
        new = _write_log(tmp_path, rating="UNDERWEIGHT", suffix="new")
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_700_000_100, 1_700_000_100))
        scan = scan_rating_logs(tmp_path)
        assert scan.duplicates == 1
        assert len(scan.entries) == 1
        assert scan.entries[0].rating == "UNDERWEIGHT"

    def test_since_until_filters(self, tmp_path):
        _write_log(tmp_path, date="2026-01-05")
        _write_log(tmp_path, date="2026-02-05")
        assert len(scan_rating_logs(tmp_path, since="2026-02-01").entries) == 1
        assert len(scan_rating_logs(tmp_path, until="2026-01-31").entries) == 1

    def test_modes_filter(self, tmp_path):
        _write_log(tmp_path, mode="deep", date="2026-01-05")
        _write_log(tmp_path, mode="deep_simple", date="2026-01-06")
        assert len(scan_rating_logs(tmp_path, modes=["deep_simple"]).entries) == 1


def _logged(code, date, rating, raw_rating, stability_status="unchanged") -> LoggedRating:
    return LoggedRating(
        fund_code=code,
        analysis_date=date,
        rating=rating,
        raw_rating=raw_rating,
        confidence="Medium",
        mode="deep",
        stability_status=stability_status,
        source=f"{code}.json",
    )


class TestStabilitySummary:
    def test_counts_effective_vs_raw_changes(self):
        entries = [
            _logged("017641", "2026-10-20", "BUY", "BUY"),
            _logged("017641", "2026-10-21", "BUY", "UNDERWEIGHT", "pending"),
            _logged("017641", "2026-10-22", "BUY", "BUY"),
        ]
        summary = compute_stability_summary(entries)
        assert summary.raw_changes == 2
        assert summary.effective_changes == 0
        assert summary.held_days == 1

    def test_churn_reduction_is_none_without_raw_churn(self):
        entries = [_logged("510300", "2026-10-20", "BUY", "BUY")]
        summary = compute_stability_summary(entries)
        assert summary.raw_changes == 0
        assert summary.effective_churn_reduction is None

    def test_status_counts_include_unknown_for_old_logs(self):
        entries = [_logged("510300", "2026-10-20", "BUY", "BUY", stability_status="")]
        summary = compute_stability_summary(entries)
        assert summary.status_counts.get("unknown") == 1

    def test_empty_input(self):
        summary = compute_stability_summary([])
        assert summary.funds == []
        assert summary.total_days == 0


class _FakeBacktest:
    def __init__(self, total_return_pct, trading_days):
        self.total_return_pct = total_return_pct
        self.trading_days = trading_days
        self.error = ""


class TestForwardReturnProvider:
    @pytest.fixture(autouse=True)
    def _patch(self, monkeypatch):
        self.calls = []

        def fake_run_backtest(code, start, end):  # noqa: ANN001
            self.calls.append((code, start, end))
            return _FakeBacktest(total_return_pct=5.0, trading_days=60)

        monkeypatch.setattr(settlement, "run_backtest", fake_run_backtest)
        monkeypatch.setattr(settlement, "benchmark_return", lambda code, date, horizon: 2.0)

    def test_matured_result_is_cached(self, tmp_path):
        provider = ForwardReturnProvider(tmp_path / "cache.json")
        first = provider.fund_return("510300", "2026-01-05", 60)
        second = provider.fund_return("510300", "2026-01-05", 60)
        assert first.matured is True
        assert first.value == 5.0
        assert second.value == 5.0
        assert provider.remote_fetches == 1
        assert provider.cache_hits == 1
        assert len(self.calls) == 1

    def test_cache_survives_reload(self, tmp_path):
        cache = tmp_path / "cache.json"
        provider = ForwardReturnProvider(cache)
        provider.fund_return("510300", "2026-01-05", 60)
        assert provider.save() is True
        assert cache.exists()
        provider = ForwardReturnProvider(cache)
        result = provider.fund_return("510300", "2026-01-05", 60)
        assert provider.cache_hits == 1
        assert result.value == 5.0

    def test_immature_result_is_not_cached(self, tmp_path, monkeypatch):
        def fake_run_backtest(code, start, end):  # noqa: ANN001
            return _FakeBacktest(total_return_pct=1.0, trading_days=5)

        monkeypatch.setattr(settlement, "run_backtest", fake_run_backtest)
        provider = ForwardReturnProvider(tmp_path / "cache.json")
        provider.fund_return("510300", "2026-10-20", 60)
        provider.fund_return("510300", "2026-10-20", 60)
        assert provider.remote_fetches == 2
        assert provider.cache_hits == 0

    def test_backtest_error_is_reported_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            settlement, "run_backtest", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network down"))
        )
        result = ForwardReturnProvider(None).fund_return("510300", "2026-01-05", 60)
        assert result.ok is False
        assert "network down" in result.error


class TestSettleEndToEnd:
    @pytest.fixture(autouse=True)
    def _patch(self, monkeypatch):
        """价格由假回测提供；基准与基金名称也打桩，避免任何网络调用。"""
        monkeypatch.setattr(
            settlement,
            "run_backtest",
            lambda code, start, end: _FakeBacktest(total_return_pct=8.0, trading_days=25),
        )
        monkeypatch.setattr(settlement, "benchmark_return", lambda code, date, horizon: 3.0)
        monkeypatch.setattr(settlement, "lookup_fund_names", lambda codes: {})

    def _seed(self, root):
        # 生效评级 BUY 一路不变，原始评级在 BUY/UNDERWEIGHT 之间翻转
        _write_log(root, date="2026-01-05", rating="BUY", raw_rating="BUY", stability={"status": "initial"})
        _write_log(root, date="2026-01-06", rating="BUY", raw_rating="UNDERWEIGHT", stability={"status": "pending"})
        _write_log(root, date="2026-01-07", rating="BUY", raw_rating="BUY", stability={"status": "unchanged"})

    def test_two_arms_share_prices(self, tmp_path):
        self._seed(tmp_path)
        result = settle_logged_ratings(tmp_path, hold_days=20, horizons=[20], use_cache=False)
        assert result.entries_n == 3
        assert result.effective.total == 3
        assert result.raw.total == 3
        # 两条口径共用一个 provider：每条日志只取一次基金收益 + 一次基准收益，
        # 第二条口径（原始评级）全部命中缓存 —— 若各取一套，这里会是 12 而不是 6。
        assert result.remote_fetches == 6
        assert result.cache_hits == 6
        assert result.stability.effective_changes == 0
        assert result.stability.raw_changes == 2

    def test_comparison_exposes_delta(self, tmp_path):
        self._seed(tmp_path)
        result = settle_logged_ratings(tmp_path, hold_days=20, horizons=[20], use_cache=False)
        comparison = result.comparison()
        assert set(comparison) >= {"hold_days", "effective", "raw", "delta"}

    def test_immature_horizon_is_excluded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            settlement,
            "run_backtest",
            lambda code, start, end: _FakeBacktest(total_return_pct=1.0, trading_days=5),
        )
        self._seed(tmp_path)
        result = settle_logged_ratings(tmp_path, hold_days=60, horizons=[60], use_cache=False)
        assert result.immature_n > 0
        assert result.matured_counts == {}

    def test_empty_results_dir_warns(self, tmp_path):
        result = settle_logged_ratings(tmp_path / "empty", use_cache=False)
        assert result.entries_n == 0
        assert any("日志" in warning for warning in result.warnings)

    def test_no_stability_data_warns(self, tmp_path):
        """稳定化上线前的日志没有 rating_stability，报告必须点明而不是假装有。"""
        _write_log(tmp_path, date="2026-01-05", rating="BUY")
        result = settle_logged_ratings(tmp_path, hold_days=20, horizons=[20], use_cache=False)
        assert any("稳定化" in warning for warning in result.warnings)


class TestReport:
    def _result(self, tmp_path):
        _write_log(tmp_path, date="2026-01-05", rating="BUY", raw_rating="BUY")
        return settle_logged_ratings(tmp_path, hold_days=20, horizons=[20], use_cache=False)

    def test_report_contains_both_arms_and_honesty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            settlement,
            "run_backtest",
            lambda code, start, end: _FakeBacktest(total_return_pct=8.0, trading_days=25),
        )
        monkeypatch.setattr(settlement, "benchmark_return", lambda code, date, horizon: 3.0)
        monkeypatch.setattr(settlement, "lookup_fund_names", lambda codes: {})
        report = format_settlement_report(self._result(tmp_path))
        assert "智识诚实声明" in report
        assert "生效评级 vs 原始评级" in report
        assert "评级稳定性" in report
        assert "不证明它变好或变坏" in report

    def test_write_settlement_creates_json_and_markdown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            settlement,
            "run_backtest",
            lambda code, start, end: _FakeBacktest(total_return_pct=8.0, trading_days=25),
        )
        monkeypatch.setattr(settlement, "benchmark_return", lambda code, date, horizon: 3.0)
        monkeypatch.setattr(settlement, "lookup_fund_names", lambda codes: {})
        result = self._result(tmp_path)
        json_path, md_path = write_settlement(result, tmp_path / "out")
        assert json_path.exists() and md_path.exists()
        assert json_path.name.startswith("settled_")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert "effective" in payload and "raw" in payload and "stability" in payload
        assert "comparison" in payload
