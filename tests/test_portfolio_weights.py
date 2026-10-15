"""组合权重解析与校验测试 —— LLM 自述的权重必须被代码算一遍。

覆盖：类别/基金权重解析（中英标点、加粗、重复代码）、合计容差、单基金上限、
债券下限、QDII 上限、不可行场景（基金数 × 上限 < 100%）、以及 portfolio_advisor
节点的接线（违规文本会在 portfolio_advice 里追加 WEIGHT CHECK）。
"""

from ifa.agents.managers.portfolio_advisor import create_portfolio_advisor
from ifa.portfolio.models import RISK_PROFILES
from ifa.portfolio.weights import (
    format_weight_check,
    parse_category_weights,
    parse_fund_weights,
    rebalance_fund_weights,
    validate_portfolio_weights,
)

MODERATE = RISK_PROFILES["moderate"]
GROWTH = RISK_PROFILES["growth"]


def _advice(categories: str, funds: str, tail: str = "- RATIONALE: 测试用\n- RISK ASSESSMENT: 无\n") -> str:
    return f"PORTFOLIO ADVICE:\n- ASSET ALLOCATION: {categories}\n- FUND SELECTIONS: {funds}\n{tail}"


class _MockLLM:
    """按预设文本返回的 Mock LLM。"""

    def __init__(self, content: str) -> None:
        self._content = content

    def invoke(self, *args, **kwargs):
        content = self._content

        class _Response:
            pass

        response = _Response()
        response.content = content
        return response


class TestParseCategoryWeights:
    def test_parses_comma_separated_categories(self):
        weights = parse_category_weights(_advice("宽基指数 45%, 债券 25%, QDII 30%", "510300 (100%)"))
        assert weights == {"宽基指数": 45.0, "债券": 25.0, "QDII": 30.0}

    def test_parses_cjk_separators_and_bold(self):
        text = _advice("- **宽基指数**: 50%、中证500指数 20%、货币基金 30%", "510300 (100%)")
        assert parse_category_weights(text) == {"宽基指数": 50.0, "中证500指数": 20.0, "货币基金": 30.0}

    def test_ignores_total_row(self):
        text = _advice("宽基指数 60%, 债券 40%\n- 合计: 100%", "510300 (100%)")
        weights = parse_category_weights(text)
        assert "合计" not in weights
        assert weights == {"宽基指数": 60.0, "债券": 40.0}

    def test_subtotal_line_does_not_inflate_last_code(self):
        # 真实报告的复述行：「行业 512760 + 512010 = 10%」里的 10% 是这一组合计，不是 512010 的仓位
        text = _advice("宽基指数 100%", "512760 (5%), 512010 (5%)\n行业 512760 + 512010 = 10%\n中盘 510500 = 15%\n")
        weights = parse_fund_weights(text)
        assert weights == {"512760": 5.0, "512010": 5.0, "510500": 15.0}

    def test_parses_markdown_table_categories(self):
        categories = (
            "\n| 资产类别 | 目标权重 | 角色 |\n|---|---:|---|\n"
            "| 宽基指数 | 45% | 核心底仓 |\n| 中盘指数 | 15% | 核心弹性 |\n"
            "| 债券 | 25% | 防御压舱 |\n| 行业主题 | 10% | 卫星增强 |\n"
            "| QDII | 5% | 跨市场分散 |\n| 合计 | 100% | 股债比约 75/25 |\n"
        )
        weights = parse_category_weights(_advice(categories, "510300 (100%)"))
        assert weights == {"宽基指数": 45.0, "中盘指数": 15.0, "债券": 25.0, "行业主题": 10.0, "QDII": 5.0}

    def test_returns_empty_when_section_missing(self):
        assert parse_category_weights("PORTFOLIO ADVICE: 无权重") == {}

    def test_stops_at_next_section(self):
        # RATIONALE 里的百分比不能被当成类别权重
        text = _advice("宽基指数 100%", "510300 (100%)", tail="- RATIONALE: 建议 债券 50% 上限\n")
        assert parse_category_weights(text) == {"宽基指数": 100.0}


class TestParseFundWeights:
    def test_parses_code_then_percentage(self):
        weights = parse_fund_weights(_advice("宽基指数 100%", "510300 沪深300ETF (30%), 110020 (20%)"))
        assert weights == {"510300": 30.0, "110020": 20.0}

    def test_parses_percentage_before_code(self):
        weights = parse_fund_weights(_advice("宽基指数 100%", "30% 510300、20% 110020"))
        assert weights == {"510300": 30.0, "110020": 20.0}

    def test_duplicate_mentions_take_max_not_sum(self):
        # 明细之后常有「小计」行复述同一批代码，累加会造出 200% 的假违规
        weights = parse_fund_weights(_advice("宽基指数 100%", "510300 (20%), 510300 (20%)"))
        assert weights == {"510300": 20.0}

    def test_parses_markdown_table_rows(self):
        # 真实 2026-10-14 组合报告就是 markdown 表格 + 一行小计复述
        funds = (
            "| 排名 | 基金代码 | 基金名称 | 类型 | 配置权重 |\n"
            "|---|---:|---|---:|---:|\n"
            "| 1 | 510300 | 沪深300ETF华泰 | 指数型-股票 | 20% |\n"
            "| 2 | 511010 | 国债ETF国泰 | 指数型-固收 | 25% |\n"
            "| 3 | 510500 | 中证500ETF南方 | 指数型-股票 | 15% |\n"
            "| 4 | 510880 | 红利ETF华泰柏瑞 | 指数型-股票 | 15% |\n"
            "| 5 | 510050 | 上证50ETF华夏 | 指数型-股票 | 10% |\n"
            "| 6 | 512760 | 芯片ETF国泰 | 指数型-股票 | 5% |\n"
            "| 7 | 512010 | 医药ETF易方达 | 指数型-股票 | 5% |\n"
            "| 8 | 513500 | 标普500ETF博时 | 指数型-海外股票 | 5% |\n\n"
            "宽基小计：510300（20%）+ 510880（15%）+ 510050（10%）= 45%；中盘 510500 = 15%\n"
        )
        weights = parse_fund_weights(_advice("宽基指数 100%", funds))
        assert weights == {
            "510300": 20.0,
            "511010": 25.0,
            "510500": 15.0,
            "510880": 15.0,
            "510050": 10.0,
            "512760": 5.0,
            "512010": 5.0,
            "513500": 5.0,
        }
        assert abs(sum(weights.values()) - 100) < 1e-9

    def test_ignores_non_six_digit_numbers(self):
        weights = parse_fund_weights(_advice("宽基指数 100%", "51030 (30%), 2024 (70%)"))
        assert weights == {}


class TestValidatePortfolioWeights:
    def test_compliant_advice_passes(self):
        text = _advice(
            "宽基指数 50%, 债券 30%, QDII 20%",
            "510300 (30%), 110020 (30%), 000834 (20%), 017641 (20%)",
        )
        report = validate_portfolio_weights(text, MODERATE)
        assert report.ok, report.issues
        assert report.corrected_categories == {}
        assert report.corrected_funds == {}
        assert format_weight_check(report, MODERATE) is None

    def test_sum_mismatch_is_reported_and_corrected(self):
        text = _advice("宽基指数 60%, 债券 20%, QDII 15%", "510300 (30%), 110020 (30%), 000834 (40%)")
        report = validate_portfolio_weights(text, MODERATE)
        assert not report.ok
        assert any("合计 95.0%" in issue for issue in report.issues)
        assert abs(sum(report.corrected_categories.values()) - 100) < 1e-6
        assert abs(sum(report.corrected_funds.values()) - 100) < 1e-6

    def test_single_fund_over_cap_is_capped(self):
        text = _advice("宽基指数 100%", "510300 (40%), 110020 (20%), 000834 (20%), 017641 (20%)")
        report = validate_portfolio_weights(text, MODERATE)
        assert any("单基金权重超过上限 30%" in issue for issue in report.issues)
        assert report.corrected_funds["510300"] == 30.0
        assert abs(sum(report.corrected_funds.values()) - 100) < 1e-6
        assert all(value <= 30.0 + 1e-9 for value in report.corrected_funds.values())

    def test_bond_floor_is_lifted(self):
        text = _advice("宽基指数 80%, 债券 5%, QDII 15%", "510300 (50%), 110020 (50%)")
        report = validate_portfolio_weights(text, MODERATE)
        assert any("低于该风险偏好的下限 15%" in issue for issue in report.issues)
        assert report.corrected_categories["债券"] >= 15.0 - 1e-9
        assert abs(sum(report.corrected_categories.values()) - 100) < 1e-6

    def test_bond_floor_without_bond_category_is_reported(self):
        text = _advice("宽基指数 70%, QDII 30%", "510300 (50%), 110020 (50%)")
        report = validate_portfolio_weights(text, MODERATE)
        assert any("没有债券类" in issue for issue in report.issues)

    def test_international_cap_is_enforced(self):
        text = _advice("宽基指数 60%, 债券 20%, QDII 30%", "510300 (50%), 110020 (50%)")
        report = validate_portfolio_weights(text, MODERATE)
        assert any("超过该风险偏好的上限 20%" in issue for issue in report.issues)
        assert report.corrected_categories["QDII"] <= 20.0 + 1e-9
        assert abs(sum(report.corrected_categories.values()) - 100) < 1e-6

    def test_unparseable_advice_is_reported(self):
        report = validate_portfolio_weights("PORTFOLIO ADVICE: 无任何权重", MODERATE)
        assert not report.ok
        assert any("未能从组合建议里解析出任何权重" in issue for issue in report.issues)

    def test_infeasible_fund_count_is_reported(self):
        text = _advice("宽基指数 100%", "510300 (50%), 110020 (50%)")
        report = validate_portfolio_weights(text, GROWTH)
        assert any("凑不满 100%" in issue for issue in report.issues)
        assert any("顶到上限 20%" in issue for issue in report.issues)

    def test_rebalance_fund_weights_returns_issue_on_empty_input(self):
        corrected, issues = rebalance_fund_weights({}, MODERATE)
        assert corrected == {}
        assert issues == ["没有解析到单基金权重"]


class TestFormatWeightCheck:
    def test_renders_issues_corrections_and_constraints(self):
        text = _advice("宽基指数 80%, 债券 5%, QDII 15%", "510300 (60%), 110020 (40%)")
        report = validate_portfolio_weights(text, MODERATE)
        rendered = format_weight_check(report, MODERATE)
        assert rendered is not None
        assert "## WEIGHT CHECK（代码校验，非 LLM 自述）" in rendered
        assert "发现的问题:" in rendered
        assert "按约束重排后的资产类别权重" in rendered
        assert "按约束重排后的单基金权重" in rendered
        assert "约束（moderate）: 单基金 ≤ 30%、债券 ≥ 15%、海外/QDII ≤ 20%" in rendered
        assert "⚠" in rendered


class TestPortfolioAdvisorNodeIntegration:
    def test_violating_advice_gets_weight_check_appendix(self):
        advice = _advice("宽基指数 80%, 债券 5%, QDII 15%", "510300 (60%), 110020 (40%)")
        node = create_portfolio_advisor(_MockLLM(advice))
        result = node({"risk_profile": "moderate"})
        assert result["portfolio_advice"].startswith(advice)
        assert "## WEIGHT CHECK" in result["portfolio_advice"]
        assert len(result["messages"]) == 1

    def test_compliant_advice_is_left_untouched(self):
        advice = _advice(
            "宽基指数 50%, 债券 30%, QDII 20%",
            "510300 (30%), 110020 (30%), 000834 (20%), 017641 (20%)",
        )
        node = create_portfolio_advisor(_MockLLM(advice))
        result = node({"risk_profile": "moderate"})
        assert result["portfolio_advice"] == advice

    def test_prompt_requests_machine_readable_weights(self):
        captured: list[str] = []

        class _CapturingLLM:
            def invoke(self, prompt, *args, **kwargs):
                captured.append(prompt)

                class _Response:
                    content = _advice("宽基指数 100%", "510300 (100%)")

                return _Response()

        create_portfolio_advisor(_CapturingLLM())({"risk_profile": "moderate"})
        assert "machine-readable" in captured[0]
        assert "Max single fund weight: 30.0%" in captured[0]
