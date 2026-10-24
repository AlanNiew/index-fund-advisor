"""评级稳定化测试 —— 单次判断不直接改变生效评级。

背景（2026-10 服务器一周实证）：6 个交易日 × 5 只基金 = 30 次评级，25 个相邻日对里
11 次翻转（44%），其中 017641 每天 BUY/UNDERWEIGHT 交替。BUY 与 UNDERWEIGHT 在 5 级
词表里已相差 2 档，所以「跨档阈值」压不住这种振荡——必须靠「连续 N 次同向确认」。

本文件覆盖三块：纯函数判定（decide）、历史落盘（RatingHistoryStore）、以及
AdvisorGraph 的接入行为（状态写回、多基金跳过、stabilize=False）。
"""

import json

import pytest

from ifa.decisions import (
    DEFAULT_CONFIRM_RUNS,
    HistoryEntry,
    RatingHistoryStore,
    StabilityConfig,
    decide,
)

CFG = StabilityConfig(enabled=True, confirm_runs=2)


def _entry(date: str, raw: str, effective: str, **kwargs) -> HistoryEntry:
    return HistoryEntry(date=date, raw_rating=raw, effective_rating=effective, **kwargs)


class TestDecideStates:
    """decide() 的六种状态：initial / unchanged / pending / confirmed / red_line / invalid。"""

    def test_initial_without_history(self):
        decision = decide("BUY", "Medium", [], CFG, as_of_date="2026-10-20")
        assert decision.status == "initial"
        assert decision.effective_rating == "BUY"
        assert decision.confirm_runs == 2

    def test_unchanged_keeps_same_rating(self):
        history = [_entry("2026-10-20", "BUY", "BUY")]
        decision = decide("BUY", "Medium", history, CFG, as_of_date="2026-10-21")
        assert decision.status == "unchanged"
        assert decision.effective_rating == "BUY"
        assert decision.changed is False
        assert decision.held is False

    def test_single_flip_is_held_pending(self):
        """单次反向判断不生效——这正是 017641 每天翻转要被挡住的那一步。"""
        history = [_entry("2026-10-20", "BUY", "BUY")]
        decision = decide("UNDERWEIGHT", "Medium", history, CFG, as_of_date="2026-10-21")
        assert decision.status == "pending"
        assert decision.effective_rating == "BUY"
        assert decision.raw_rating == "UNDERWEIGHT"
        assert decision.held is True
        assert decision.pending_days == 1

    def test_second_consecutive_flip_confirms(self):
        history = [
            _entry("2026-10-20", "BUY", "BUY"),
            _entry("2026-10-21", "UNDERWEIGHT", "BUY", status="pending", pending_rating="UNDERWEIGHT"),
        ]
        decision = decide("UNDERWEIGHT", "Medium", history, CFG, as_of_date="2026-10-22")
        assert decision.status == "confirmed"
        assert decision.effective_rating == "UNDERWEIGHT"
        assert decision.changed is True
        assert decision.pending_days == 2

    def test_sell_is_red_line_and_takes_effect_immediately(self):
        history = [_entry("2026-10-20", "BUY", "BUY")]
        decision = decide("SELL", "Medium", history, CFG, as_of_date="2026-10-21")
        assert decision.status == "red_line"
        assert decision.effective_rating == "SELL"
        assert decision.changed is True

    def test_unknown_rating_is_passed_through_untouched(self):
        decision = decide("N/A", "Medium", [], CFG)
        assert decision.status == "invalid"
        assert decision.effective_rating == "N/A"
        assert decision.raw_rating == "N/A"

    def test_confirm_runs_one_lets_every_change_through(self):
        """confirm_runs=1 是回退到旧行为（单次判断即生效），用于对照。"""
        history = [_entry("2026-10-20", "BUY", "BUY")]
        decision = decide("UNDERWEIGHT", "Medium", history, StabilityConfig(confirm_runs=1), as_of_date="2026-10-21")
        assert decision.status == "confirmed"
        assert decision.effective_rating == "UNDERWEIGHT"


class TestAsOfDateFiltering:
    """历史记录按 as_of_date 过滤：同日重跑不能把自己算成「连续第二次」。"""

    def test_same_day_entries_are_ignored(self):
        history = [
            _entry("2026-10-20", "BUY", "BUY"),
            _entry("2026-10-21", "UNDERWEIGHT", "BUY", status="pending"),
        ]
        # 只看 2026-10-21 之前 → 当日那条不算，仍是 pending
        decision = decide("UNDERWEIGHT", "Medium", history, CFG, as_of_date="2026-10-21")
        assert decision.status == "pending"
        assert decision.effective_rating == "BUY"

    def test_without_as_of_date_history_is_used_verbatim(self):
        history = [
            _entry("2026-10-20", "BUY", "BUY"),
            _entry("2026-10-21", "UNDERWEIGHT", "BUY", status="pending"),
        ]
        decision = decide("UNDERWEIGHT", "Medium", history, CFG)
        assert decision.status == "confirmed"


class TestStabilityConfigFromConfig:
    """from_config 读扁平配置键，并对非法值做钳制而不是崩掉。"""

    def test_reads_documented_keys(self):
        cfg = StabilityConfig.from_config(
            {
                "rating_stability_enabled": "false",
                "rating_stability_confirm_runs": "3",
                "rating_stability_history_max_entries": "50",
            }
        )
        assert cfg.enabled is False
        assert cfg.confirm_runs == 3
        assert cfg.max_entries == 50

    def test_invalid_values_fall_back(self):
        cfg = StabilityConfig.from_config({"rating_stability_enabled": "maybe", "rating_stability_confirm_runs": "abc"})
        assert cfg.enabled is True
        assert cfg.confirm_runs == DEFAULT_CONFIRM_RUNS

    def test_confirm_runs_is_at_least_one(self):
        assert StabilityConfig.from_config({"rating_stability_confirm_runs": 0}).confirm_runs == 1
        assert StabilityConfig.from_config({"rating_stability_confirm_runs": -5}).confirm_runs == 1

    def test_empty_config_uses_defaults(self):
        cfg = StabilityConfig.from_config(None)
        assert cfg.enabled is True
        assert cfg.confirm_runs == DEFAULT_CONFIRM_RUNS


class TestHistoryStore:
    def test_append_then_load_roundtrip(self, tmp_path):
        store = RatingHistoryStore(tmp_path)
        assert store.enabled is True
        assert store.append("017641", _entry("2026-10-20", "BUY", "BUY")) is True
        entries = store.load("017641")
        assert len(entries) == 1
        assert entries[0].raw_rating == "BUY"
        assert store.last("017641").effective_rating == "BUY"

    def test_same_day_run_overwrites_instead_of_counting_twice(self, tmp_path):
        """同一天重跑两次不能被算成「连续两次同向」——这是最容易被忽略的正确性 bug。"""
        store = RatingHistoryStore(tmp_path)
        store.append("017641", _entry("2026-10-20", "BUY", "BUY"))
        store.append("017641", _entry("2026-10-20", "UNDERWEIGHT", "BUY", status="pending"))
        entries = store.load("017641")
        assert len(entries) == 1
        assert entries[0].raw_rating == "UNDERWEIGHT"

    def test_none_directory_disables_persistence(self):
        """与 memory_dir 同语义：未配置目录就不落盘，单元测试因此无副作用。"""
        store = RatingHistoryStore(None)
        assert store.enabled is False
        assert store.append("510300", _entry("2026-10-20", "BUY", "BUY")) is False
        assert store.load("510300") == []

    def test_corrupted_file_degrades_to_empty(self, tmp_path):
        store = RatingHistoryStore(tmp_path)
        path = store.path_for("510300")
        assert path is not None
        path.write_text("{not json", encoding="utf-8")
        assert store.load("510300") == []

    def test_max_entries_truncates_oldest(self, tmp_path):
        store = RatingHistoryStore(tmp_path, max_entries=3)
        for day in range(1, 6):
            store.append("510300", _entry(f"2026-10-0{day}", "BUY", "BUY"))
        entries = store.load("510300")
        assert len(entries) == 3
        assert [entry.date for entry in entries] == ["2026-10-03", "2026-10-04", "2026-10-05"]

    def test_fund_code_is_sanitised_into_filename(self, tmp_path):
        store = RatingHistoryStore(tmp_path)
        path = store.path_for("510300/../etc")
        assert path is not None
        assert path.parent == tmp_path
        assert path.name.endswith(".json")

    def test_payload_is_json_with_version(self, tmp_path):
        store = RatingHistoryStore(tmp_path)
        store.append("510300", _entry("2026-10-20", "BUY", "BUY"))
        payload = json.loads(store.path_for("510300").read_text(encoding="utf-8"))
        assert payload["fund_code"] == "510300"
        assert payload["entries"][0]["effective_rating"] == "BUY"
        assert "version" in payload


class TestHistoryEntryParsing:
    def test_from_dict_roundtrip(self):
        entry = _entry("2026-10-20", "BUY", "HOLD", confidence="High", status="pending")
        restored = HistoryEntry.from_dict(entry.to_dict())
        assert restored is not None
        assert restored == entry

    @pytest.mark.parametrize(
        "payload",
        [None, "not-a-dict", {"date": "2026-10-20"}, {"date": "2026-10-20", "raw_rating": "BUY"}],
    )
    def test_malformed_payload_returns_none(self, payload):
        assert HistoryEntry.from_dict(payload) is None


class TestAdvisorGraphStability:
    """AdvisorGraph 接入：生效评级写回 final_rating，原始评级保留在 final_rating_raw。"""

    @pytest.fixture()
    def advisor(self, tmp_path):
        from ifa.graph.advisor_graph import AdvisorGraph

        class _MockLLM:
            def invoke(self, *args, **kwargs):  # pragma: no cover - 不会被调用
                raise AssertionError("稳定化测试不应调用 LLM")

        return AdvisorGraph(
            quick_llm=_MockLLM(),
            deep_llm=_MockLLM(),
            config={
                "results_dir": str(tmp_path / "results"),
                "rating_history_dir": str(tmp_path / "ratings"),
                "rating_stability_confirm_runs": 2,
            },
        )

    @staticmethod
    def _state(day: str, rating: str, codes: str = "017641") -> dict:
        return {"fund_codes": codes, "analysis_date": day, "final_rating": rating, "final_confidence": "Medium"}

    def test_pending_flip_keeps_effective_rating(self, advisor):
        first = self._state("2026-10-20", "BUY")
        advisor._apply_rating_stability(first)
        assert first["final_rating"] == "BUY"
        assert first["final_rating_raw"] == "BUY"
        assert first["rating_stability"]["status"] == "initial"

        second = self._state("2026-10-21", "UNDERWEIGHT")
        advisor._apply_rating_stability(second)
        assert second["final_rating"] == "BUY"  # 生效不变
        assert second["final_rating_raw"] == "UNDERWEIGHT"  # 原始保留
        assert second["rating_stability"]["held"] is True

    def test_repeated_flip_eventually_confirmed(self, advisor):
        advisor._apply_rating_stability(self._state("2026-10-20", "BUY"))
        advisor._apply_rating_stability(self._state("2026-10-21", "UNDERWEIGHT"))
        third = self._state("2026-10-22", "UNDERWEIGHT")
        advisor._apply_rating_stability(third)
        assert third["final_rating"] == "UNDERWEIGHT"
        assert third["rating_stability"]["status"] == "confirmed"

    def test_stabilize_false_bypasses_gate(self, advisor):
        advisor._apply_rating_stability(self._state("2026-10-20", "BUY"))
        state = self._state("2026-10-21", "UNDERWEIGHT")
        advisor._apply_rating_stability(state, stabilize=False)
        assert state["final_rating"] == "UNDERWEIGHT"
        assert state["rating_stability"]["status"] == "disabled"
        assert state["rating_stability"]["label"] == "未稳定化"

    def test_multi_fund_analysis_is_skipped_not_guessed(self, advisor):
        state = self._state("2026-10-20", "BUY", codes="510300,159919")
        advisor._apply_rating_stability(state)
        assert state["final_rating"] == "BUY"
        assert state["rating_stability"]["status"] == "skipped"

    def test_missing_rating_leaves_state_untouched(self, advisor):
        state = {"fund_codes": "510300", "analysis_date": "2026-10-20"}
        advisor._apply_rating_stability(state)
        assert "rating_stability" not in state
        assert "final_rating_raw" not in state

    def test_history_is_persisted_only_when_enabled(self, advisor, tmp_path):
        advisor._apply_rating_stability(self._state("2026-10-20", "BUY"))
        path = tmp_path / "ratings" / "017641.json"
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["entries"][-1]["effective_rating"] == "BUY"


class TestGraphHelpers:
    def test_extract_single_fund_code(self):
        from ifa.graph.advisor_graph import _extract_single_fund_code

        assert _extract_single_fund_code("510300") == "510300"
        assert _extract_single_fund_code(" 510300 ") == "510300"
        assert _extract_single_fund_code("510300,159919") is None
        assert _extract_single_fund_code(["510300"]) == "510300"
        assert _extract_single_fund_code(["510300", "159919"]) is None
        assert _extract_single_fund_code(None) is None

    def test_passthrough_labels(self):
        from ifa.graph.advisor_graph import _stability_passthrough

        assert _stability_passthrough("BUY", "Medium", "disabled", "x")["label"] == "未稳定化"
        assert _stability_passthrough("BUY", "Medium", "skipped", "x")["label"] == "未稳定化（多基金）"
        assert _stability_passthrough("BUY", "Medium", "error", "x")["label"] == "未稳定化（判定失败）"


class TestLogStateCarriesStability:
    """日志必须同时留生效与原始评级，结算脚本才能做 A/B 对照。"""

    def test_log_entry_contains_both_ratings(self, tmp_path):
        from ifa.graph.advisor_graph import AdvisorGraph

        class _MockLLM:
            def invoke(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError("不应调用 LLM")

        advisor = AdvisorGraph(
            quick_llm=_MockLLM(),
            deep_llm=_MockLLM(),
            config={
                "results_dir": str(tmp_path),
                "rating_history_dir": str(tmp_path / "ratings"),
            },
        )
        state = {
            "fund_codes": "510300",
            "analysis_date": "2026-10-20",
            "mode": "deep",
            "final_report": "报告",
            "final_rating": "BUY",
            "final_confidence": "Medium",
            "final_rating_raw": "BUY",
            "rating_stability": {"status": "initial", "label": "首次记录"},
        }
        advisor._log_state(state)
        candidates = list((tmp_path / "logs" / "510300").glob("*.json"))
        assert candidates, "日志未落盘"
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
        assert payload["final_rating"] == "BUY"
        assert payload["final_rating_raw"] == "BUY"
        assert payload["rating_stability"]["status"] == "initial"
