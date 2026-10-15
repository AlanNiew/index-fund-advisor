"""信号处理模块测试 — SignalProcessor 提取标准化评级和置信度。"""

from unittest.mock import MagicMock

from ifa.graph.signal_processing import SignalProcessor


class TestSignalProcessor:
    """SignalProcessor 信号提取测试。"""

    def _make_mock_llm(self, content: str):
        """创建返回指定内容的 mock LLM。"""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = content
        mock_llm.invoke.return_value = mock_response
        return mock_llm

    def test_extract_rating(self):
        """从决策文本中提取标准化评级。"""
        mock_llm = self._make_mock_llm("BUY")
        processor = SignalProcessor(mock_llm)

        result = processor.process_signal("We recommend buying this fund due to strong fundamentals.")
        assert result == "BUY"
        mock_llm.invoke.assert_called_once()

    def test_extract_rating_strips_whitespace(self):
        """提取结果去除首尾空白。"""
        mock_llm = self._make_mock_llm("  STRONG_BUY  \n")
        processor = SignalProcessor(mock_llm)

        result = processor.process_signal("Very bullish on this ETF")
        assert result == "STRONG_BUY"

    def test_extract_confidence(self):
        """从决策文本中提取置信度。"""
        mock_llm = self._make_mock_llm("High")
        processor = SignalProcessor(mock_llm)

        result = processor.process_confidence("We are very confident in this analysis.")
        assert result == "High"

    def test_extract_confidence_strips_whitespace(self):
        """置信度提取结果去除首尾空白。"""
        mock_llm = self._make_mock_llm("\tMedium\n")
        processor = SignalProcessor(mock_llm)

        result = processor.process_confidence("Moderate confidence level")
        assert result == "Medium"

    def test_process_signal_handles_no_content_attr(self):
        """LLM 响应无 content 属性时降级为 str()。"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = "HOLD"  # 无 .content 属性

        processor = SignalProcessor(mock_llm)
        result = processor.process_signal("Neutral outlook")
        assert result == "HOLD"

    # ── 评级规范化校验测试 ──

    def test_normalize_rating_exact_match(self):
        """精确匹配所有合法评级。"""
        for rating in ("STRONG_BUY", "BUY", "HOLD", "UNDERWEIGHT", "SELL"):
            assert SignalProcessor._normalize_rating(rating) == rating

    def test_normalize_rating_fuzzy_strong_buy(self):
        """模糊匹配 'strong buy' → STRONG_BUY。"""
        assert SignalProcessor._normalize_rating("strong buy") == "STRONG_BUY"

    def test_normalize_rating_fuzzy_with_extra_text(self):
        """包含多余文本时仍能提取评级。"""
        assert SignalProcessor._normalize_rating("I think the rating is BUY for this fund") == "BUY"

    def test_normalize_rating_fallback_hold(self):
        """完全无法识别时 fallback 到 HOLD。"""
        assert SignalProcessor._normalize_rating("不确定") == "HOLD"

    def test_normalize_confidence_exact_match(self):
        """精确匹配所有合法置信度。"""
        for conf in ("High", "Medium", "Low"):
            assert SignalProcessor._normalize_confidence(conf) == conf

    def test_normalize_confidence_fuzzy_moderate(self):
        """模糊匹配 'moderate' → Medium。"""
        assert SignalProcessor._normalize_confidence("moderate") == "Medium"

    def test_normalize_confidence_fallback_medium(self):
        """完全无法识别时 fallback 到 Medium。"""
        assert SignalProcessor._normalize_confidence("未知") == "Medium"

    def test_process_signal_fuzzy_rating_integration(self):
        """process_signal 整体测试：LLM 返回非标准格式时仍能规范化。"""
        mock_llm = self._make_mock_llm("The rating is SELL")
        processor = SignalProcessor(mock_llm)
        result = processor.process_signal("Bearish outlook")
        assert result == "SELL"

    def test_process_confidence_fuzzy_integration(self):
        """process_confidence 整体测试：LLM 返回非标准格式时仍能规范化。"""
        mock_llm = self._make_mock_llm("low confidence")
        processor = SignalProcessor(mock_llm)
        result = processor.process_confidence("Uncertain analysis")
        assert result == "Low"

class TestParseDecisionSignals:
    """确定性解析管理层裁决/报告里的机器可读 Rating:/Confidence: 行（零 LLM 调用）。"""

    def test_parses_plain_machine_lines(self):
        from ifa.graph.signal_processing import parse_decision_signals

        assert parse_decision_signals("RATING: BUY\nCONFIDENCE: High") == ("BUY", "High")

    def test_parses_markdown_bold_labels(self):
        from ifa.graph.signal_processing import parse_decision_signals

        text = "**Rating**: STRONG_BUY\n**Confidence**: Low"
        assert parse_decision_signals(text) == ("STRONG_BUY", "Low")

    def test_last_occurrence_wins_over_menu_echo(self):
        """prompt 里的词表菜单会被回显；结论行在末尾，应取末尾那一行。"""
        from ifa.graph.signal_processing import parse_decision_signals

        text = (
            "1. **Rating**: State one of STRONG_BUY / BUY / HOLD / UNDERWEIGHT / SELL.\n"
            "2. **Confidence**: High / Medium / Low.\n"
            "RATING: SELL\nCONFIDENCE: Medium"
        )
        assert parse_decision_signals(text) == ("SELL", "Medium")

    def test_menu_with_multiple_ratings_is_not_guessed(self):
        from ifa.graph.signal_processing import parse_decision_signals

        assert parse_decision_signals("Rating: BUY / HOLD / SELL") == (None, None)

    def test_unknown_word_is_not_guessed(self):
        """REDEEM 不在 5 级词表里 —— 不能靠猜，交给上层回落 LLM 抽取。"""
        from ifa.graph.signal_processing import parse_decision_signals

        assert parse_decision_signals("Rating: REDEEM") == (None, None)
        assert parse_decision_signals("Rating: REDEEM\nConfidence: Medium") == (None, "Medium")

    def test_chinese_labels_and_values(self):
        from ifa.graph.signal_processing import parse_decision_signals

        assert parse_decision_signals("评级：买入\n置信度：较高") == ("BUY", "High")

    def test_negated_chinese_sentence_is_not_guessed(self):
        """「不建议买入」不是评级结论，整值匹配不上就不猜。"""
        from ifa.graph.signal_processing import parse_decision_signals

        assert parse_decision_signals("评级：不建议买入") == (None, None)

    def test_inline_trailing_comment_is_tolerated(self):
        from ifa.graph.signal_processing import parse_decision_signals

        text = "- **Rating**: BUY — 估值处于低位\n- **Confidence**: Medium（中等）"
        assert parse_decision_signals(text) == ("BUY", "Medium")

    def test_empty_or_non_string_input(self):
        from ifa.graph.signal_processing import parse_decision_signals

        assert parse_decision_signals("") == (None, None)
        assert parse_decision_signals(None) == (None, None)  # type: ignore[arg-type]
