# ifa/graph/signal_processing.py
"""信号处理模块 —— 从最终报告中提取标准化评级和置信度。"""

from typing import Any


class SignalProcessor:
    """处理投资决策信号，提取结构化评级。"""

    def __init__(self, quick_thinking_llm: Any):
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str) -> str:
        """从完整决策文本中提取标准化评级。

        参数:
            full_signal: 投资组合经理的完整决策文本

        返回:
            标准化评级: STRONG_BUY / BUY / HOLD / UNDERWEIGHT / SELL
        """
        from ifa.agents.utils import invoke_llm_safely

        messages = [
            (
                "system",
                "You are an efficient assistant that extracts the investment rating from fund analysis reports. "
                "Extract the rating as exactly one of: STRONG_BUY, BUY, HOLD, UNDERWEIGHT, SELL. "
                "Output only the single rating word, nothing else.",
            ),
            ("human", full_signal),
        ]
        result = invoke_llm_safely(self.quick_thinking_llm, messages)
        content = result.content if hasattr(result, "content") else str(result)
        return content.strip()

    def process_confidence(self, full_signal: str) -> str:
        """从决策文本中提取置信度。"""
        from ifa.agents.utils import invoke_llm_safely

        messages = [
            (
                "system",
                "You are an efficient assistant that extracts the confidence level from fund analysis reports. "
                "Extract the confidence as exactly one of: High, Medium, Low. "
                "Output only the single confidence word, nothing else.",
            ),
            ("human", full_signal),
        ]
        result = invoke_llm_safely(self.quick_thinking_llm, messages)
        content = result.content if hasattr(result, "content") else str(result)
        return content.strip()
