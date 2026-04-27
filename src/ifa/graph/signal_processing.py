# ifa/graph/signal_processing.py
"""信号处理模块 —— 从最终报告中提取标准化评级和置信度。"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 合法值常量
_VALID_RATINGS = frozenset({"STRONG_BUY", "BUY", "HOLD", "UNDERWEIGHT", "SELL"})
_VALID_CONFIDENCES = frozenset({"High", "Medium", "Low"})

# 模糊匹配映射（小写 → 标准值）
_RATING_ALIASES: dict[str, str] = {
    "strong buy": "STRONG_BUY",
    "strongbuy": "STRONG_BUY",
    "strong_buy": "STRONG_BUY",
    "buy": "BUY",
    "hold": "HOLD",
    "underweight": "UNDERWEIGHT",
    "sell": "SELL",
    "strong sell": "SELL",
    "strongsell": "SELL",
}

_CONFIDENCE_ALIASES: dict[str, str] = {
    "high": "High",
    "medium": "Medium",
    "moderate": "Medium",
    "low": "Low",
}


class SignalProcessor:
    """处理投资决策信号，提取结构化评级。"""

    def __init__(self, quick_thinking_llm: Any):
        self.quick_thinking_llm = quick_thinking_llm

    @staticmethod
    def _normalize_rating(raw: str) -> str:
        """将原始评级字符串规范化为合法评级，失败时 fallback 到 HOLD。"""
        cleaned = raw.strip()
        # 精确匹配
        if cleaned in _VALID_RATINGS:
            return cleaned
        # 模糊匹配
        lowered = cleaned.lower().replace("-", " ").replace("_", " ").strip()
        if lowered in _RATING_ALIASES:
            return _RATING_ALIASES[lowered]
        # 包含匹配（处理 LLM 返回多余文本的情况）
        for rating in _VALID_RATINGS:
            if rating.lower() in lowered:
                return rating
        logger.warning("无法识别的评级 '%s'，fallback 到 HOLD", raw)
        return "HOLD"

    @staticmethod
    def _normalize_confidence(raw: str) -> str:
        """将原始置信度字符串规范化，失败时 fallback 到 Medium。"""
        cleaned = raw.strip()
        # 精确匹配
        if cleaned in _VALID_CONFIDENCES:
            return cleaned
        # 模糊匹配
        lowered = cleaned.lower().strip()
        if lowered in _CONFIDENCE_ALIASES:
            return _CONFIDENCE_ALIASES[lowered]
        # 包含匹配
        for conf in _VALID_CONFIDENCES:
            if conf.lower() in lowered:
                return conf
        logger.warning("无法识别的置信度 '%s'，fallback 到 Medium", raw)
        return "Medium"

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
        return self._normalize_rating(content.strip())

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
        return self._normalize_confidence(content.strip())
