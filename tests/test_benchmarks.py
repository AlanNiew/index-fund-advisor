# tests/test_benchmarks.py
"""基准解析测试 —— 每只基金必须比「它自己该比的指数」。

原实现一律用沪深300 当基准（连纳指、标普、白酒基金也是），这里把基准变成
逐条可审计的对象：显式 override > 基金名称识别 > 回退沪深300（且必须写清原因）。
"""

from __future__ import annotations

import pytest

from ifa.backtest.benchmarks import (
    DEFAULT_BENCHMARK_CODE,
    BenchmarkSpec,
    detect_foreign_index,
    detect_index_name,
    resolve_benchmark,
)
from ifa.dataflows.a_share_macro import csindex_code


class TestDetectIndexName:
    @pytest.mark.parametrize(
        ("fund_name", "expected"),
        [
            ("易方达沪深300ETF联接A", "沪深300"),
            ("华夏上证50ETF", "上证50"),
            ("南方中证500ETF", "中证500"),
            ("招商中证白酒指数A", "中证白酒"),
            ("工银上证红利ETF", "上证红利"),
            ("中证红利指数基金", "中证红利"),
            ("国联安中证100指数A", "中证100"),
            ("天弘中证800指数A", "中证800"),
        ],
    )
    def test_known_index_names(self, fund_name, expected):
        assert detect_index_name(fund_name) == expected

    def test_longer_name_wins_over_its_prefix(self):
        """「中证1000」包含「中证100」子串，长度降序排序是真实踩过的坑。"""
        assert detect_index_name("华宝中证1000指数A") == "中证1000"
        assert detect_index_name("富国中证1000ETF") == "中证1000"

    @pytest.mark.parametrize("fund_name", ["", "   ", "华夏成长混合", None])
    def test_no_index_detected(self, fund_name):
        assert detect_index_name(fund_name) is None

    def test_foreign_index_is_not_a_domestic_index(self):
        assert detect_index_name("华夏纳斯达克100ETF") is None
        assert detect_index_name("博时标普500ETF") is None


class TestDetectForeignIndex:
    @pytest.mark.parametrize(
        ("fund_name", "expected"),
        [
            ("华夏纳斯达克100ETF", "纳斯达克100"),
            ("博时标普500ETF联接A", "标普500"),
            ("华夏恒生ETF", "恒生"),
            ("华安德国DAX30ETF", "德国DAX"),
        ],
    )
    def test_foreign_names(self, fund_name, expected):
        assert detect_foreign_index(fund_name) == expected

    @pytest.mark.parametrize("fund_name", ["", "华宝中证1000指数A", None])
    def test_domestic_names_are_not_foreign(self, fund_name):
        assert detect_foreign_index(fund_name) is None


class TestCsindexCodeAccessor:
    def test_known_names(self):
        assert csindex_code("沪深300") == "000300"
        assert csindex_code("中证白酒") == "399997"
        assert csindex_code("中证1000") == "000852"

    def test_whitespace_is_stripped(self):
        assert csindex_code("  沪深300  ") == "000300"

    @pytest.mark.parametrize("name", ["纳斯达克100", "不存在的指数", "", None])
    def test_unknown_names(self, name):
        assert csindex_code(name) is None


class TestResolveBenchmark:
    def test_explicit_override_wins(self):
        spec = resolve_benchmark("161725", "招商中证白酒指数A", overrides={"161725": "000905"})
        assert spec.source == "explicit"
        assert spec.code == "000905"
        assert spec.label == "000905"  # 未给名称时用代码兜底

    def test_explicit_override_with_label(self):
        spec = resolve_benchmark("161725", None, overrides={"161725": "000905:中证500"})
        assert spec.source == "explicit"
        assert spec.label == "中证500"

    def test_fund_name_detection(self):
        spec = resolve_benchmark("110020", "易方达沪深300ETF联接A")
        assert spec.source == "fund_name"
        assert spec.code == "000300"
        assert spec.label == "沪深300"

    def test_fund_name_detection_uses_real_codes(self):
        spec = resolve_benchmark("161725", "招商中证白酒指数A")
        assert (spec.code, spec.label) == ("399997", "中证白酒")

    def test_foreign_fund_falls_back_with_explanation(self):
        spec = resolve_benchmark("000834", "大成纳斯达克100ETF联接")
        assert spec.source == "default"
        assert spec.code == DEFAULT_BENCHMARK_CODE
        assert "纳斯达克100" in spec.note
        assert "沪深300" in spec.note

    def test_unknown_fund_falls_back_with_explanation(self):
        spec = resolve_benchmark("999999", "某某成长混合基金")
        assert spec.source == "default"
        assert "未识别到跟踪指数" in spec.note

    def test_missing_fund_name_falls_back(self):
        spec = resolve_benchmark("999999", None)
        assert spec.source == "default"
        assert spec.code == DEFAULT_BENCHMARK_CODE

    def test_override_for_other_fund_does_not_leak(self):
        spec = resolve_benchmark("110020", "易方达沪深300ETF联接A", overrides={"161725": "000905"})
        assert spec.source == "fund_name"
        assert spec.code == "000300"


class TestBenchmarkSpecDescribe:
    def test_explicit(self):
        spec = BenchmarkSpec(code="000905", label="中证500", source="explicit")
        assert spec.describe() == "中证500（000905，调用方指定）"

    def test_fund_name(self):
        spec = BenchmarkSpec(code="000300", label="沪深300", source="fund_name")
        assert spec.describe() == "沪深300（000300，按基金名称识别）"

    def test_default_includes_reason(self):
        spec = BenchmarkSpec(
            code="000300",
            label="沪深300",
            source="default",
            note="未识别到跟踪指数，以沪深300 代替",
        )
        assert spec.describe() == "沪深300（000300，回退：未识别到跟踪指数，以沪深300 代替）"

    def test_default_without_note_is_still_explained(self):
        spec = BenchmarkSpec(code="000300", label="沪深300", source="default")
        assert "回退：" in spec.describe()
