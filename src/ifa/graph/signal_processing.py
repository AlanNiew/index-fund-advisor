# ifa/graph/signal_processing.py
"""信号处理模块 —— 从最终报告中提取标准化评级和置信度。"""

import logging
import re
from collections.abc import Callable
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


# ── 确定性解析（优先于 LLM 抽取）──────────────────────────────────────────
# 管理层与报告生成器被要求输出机器可读的 `Rating: X` / `Confidence: Y` 行。
# 先做正则解析有两个好处：不额外花一次 LLM 调用；不会把报告里的词表菜单
# （如「BUY / HOLD / REDEEM」或「STRONG_BUY / BUY / HOLD / ...」）误当成结论。

_RATING_TOKEN_MAP: dict[str, str] = {
    "strongbuy": "STRONG_BUY",
    "strong buy": "STRONG_BUY",
    "strongsell": "SELL",
    "strong sell": "SELL",
    "buy": "BUY",
    "hold": "HOLD",
    "underweight": "UNDERWEIGHT",
    "sell": "SELL",
}

# 中文整值写法：只认「整个取值就是评级词」的情况，避免「不建议买入」这类反例
_RATING_CN_VALUES: dict[str, str] = {
    "强烈买入": "STRONG_BUY",
    "增持": "BUY",
    "买入": "BUY",
    "持有": "HOLD",
    "减持": "UNDERWEIGHT",
    "卖出": "SELL",
    "强烈卖出": "SELL",
}

_CONFIDENCE_CN_VALUES: dict[str, str] = {
    "高": "High",
    "较高": "High",
    "中": "Medium",
    "中等": "Medium",
    "低": "Low",
    "较低": "Low",
}

_RATING_EN_RE = re.compile(r"(strong\s*buy|strong\s*sell|buy|hold|underweight|sell)", re.IGNORECASE)
_CONFIDENCE_EN_RE = re.compile(r"(high|medium|moderate|low)", re.IGNORECASE)

_RATING_LINE_RE = re.compile(
    r"^[ \t>*_#\-•]*(?:final[ \t]+)?(?:rating|recommendation|评级|投资评级)"
    r"[ \t*_]*[:：][ \t*_`]*(?P<value>[^\n]+?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_CONFIDENCE_LINE_RE = re.compile(
    r"^[ \t>*_#\-•]*(?:final[ \t]+)?(?:confidence|置信度)"
    r"[ \t*_]*[:：][ \t*_`]*(?P<value>[^\n]+?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

_STRIP_CHARS = "*_#:：,;，；.、（）()[]【】<>《》 "


def _clean_value(value: str) -> str:
    """去掉取值里的 Markdown 强调符与首尾标点，便于整值比对。"""
    return value.strip().strip(_STRIP_CHARS).strip()


def _strict_rating(raw: str) -> str | None:
    """严格解析评级；无法唯一确定时返回 None（不做猜测）。"""
    cleaned = _clean_value(raw)
    if not cleaned:
        return None
    if cleaned in _VALID_RATINGS:
        return cleaned
    lowered = re.sub(r"\s+", " ", cleaned.lower().replace("-", " ").replace("_", " ")).strip()
    if lowered in _RATING_ALIASES:
        return _RATING_ALIASES[lowered]
    if cleaned in _RATING_CN_VALUES:
        return _RATING_CN_VALUES[cleaned]
    found = {_RATING_TOKEN_MAP[re.sub(r"\s+", " ", m.group(1).lower())] for m in _RATING_EN_RE.finditer(cleaned)}
    if len(found) == 1:
        return next(iter(found))
    return None


def _strict_confidence(raw: str) -> str | None:
    """严格解析置信度；无法唯一确定时返回 None（不做猜测）。"""
    cleaned = _clean_value(raw)
    if not cleaned:
        return None
    if cleaned in _VALID_CONFIDENCES:
        return cleaned
    lowered = cleaned.lower().strip()
    if lowered in _CONFIDENCE_ALIASES:
        return _CONFIDENCE_ALIASES[lowered]
    if cleaned in _CONFIDENCE_CN_VALUES:
        return _CONFIDENCE_CN_VALUES[cleaned]
    found = {m.group(1).lower() for m in _CONFIDENCE_EN_RE.finditer(cleaned)}
    if len(found) == 1:
        return _CONFIDENCE_ALIASES[next(iter(found))]
    return None


def _last_valid_match(pattern: re.Pattern[str], text: str, parser: Callable[[str], str | None]) -> str | None:
    """从后往前取第一个能唯一解析的取值行（结论通常在文本末尾）。"""
    for match in reversed(list(pattern.finditer(text))):
        parsed = parser(match.group("value"))
        if parsed:
            return parsed
    return None


def parse_decision_signals(text: str) -> tuple[str | None, str | None]:
    """确定性解析决策文本里的 `Rating:` / `Confidence:` 行。

    参数:
        text: 管理层裁决（judge_decision）或最终报告文本。

    返回:
        (rating, confidence)；任一无法唯一确定时为 None，由调用方决定是否回落 LLM 抽取。
    """
    if not text or not isinstance(text, str):
        return None, None
    return (
        _last_valid_match(_RATING_LINE_RE, text, _strict_rating),
        _last_valid_match(_CONFIDENCE_LINE_RE, text, _strict_confidence),
    )


class SignalProcessor:
    """处理投资决策信号，提取结构化评级。"""

    def __init__(self, quick_thinking_llm: Any):
        self.quick_thinking_llm = quick_thinking_llm

    @staticmethod
    def _normalize_rating(raw: str) -> str:
        """将原始评级字符串规范化为合法评级，失败时 fallback 到 HOLD。"""
        strict = _strict_rating(raw)
        if strict:
            return strict
        # 包含匹配兜底（处理 LLM 返回多余文本的情况，如 "buying"）
        lowered = raw.strip().lower().replace("-", " ").replace("_", " ").strip()
        for rating in sorted(_VALID_RATINGS):
            if rating.lower() in lowered:
                return rating
        logger.warning("无法识别的评级 '%s'，fallback 到 HOLD", raw)
        return "HOLD"

    @staticmethod
    def _normalize_confidence(raw: str) -> str:
        """将原始置信度字符串规范化，失败时 fallback 到 Medium。"""
        strict = _strict_confidence(raw)
        if strict:
            return strict
        # 包含匹配兜底
        lowered = raw.strip().lower().strip()
        for conf in sorted(_VALID_CONFIDENCES):
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
