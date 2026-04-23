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
