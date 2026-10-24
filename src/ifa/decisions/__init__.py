"""决策层（decisions）— 在报告生成之后、交付之前对评级做稳定化。

背景：日频多 Agent 辩论输出的评级在相邻交易日之间会来回翻转（实测 6 个交易日、
5 只基金，25 个相邻日对里有 11 次翻转）。评级若每次都跟着单日辩论结果改口，
「判断」就退化成了「采样」。本包用一条最小规则把它拉回判断：

1. 新评级必须**连续 N 次分析**（默认 2）同向出现才生效，否则维持上次生效评级；
2. **硬红线**（落到 SELL）跳过确认立即生效 —— 风险事件不该等第二次确认；
3. 生效评级与原始评级都保留，供结算脚本对照「稳定化是变准了还是变钝了」。

之所以不用「跨 2 档才允许改」的阈值方案：BUY 与 UNDERWEIGHT 在 5 级词表里本就
相差 2 档，阈值方案压不住每日交替，只有连续确认能做到。
"""

from ifa.decisions.history import HistoryEntry, RatingHistoryStore
from ifa.decisions.stability import (
    DEFAULT_CONFIRM_RUNS,
    DEFAULT_MAX_ENTRIES,
    RATING_RANK,
    RED_LINE_RATINGS,
    StabilityConfig,
    StabilityDecision,
    decide,
)

__all__ = [
    "DEFAULT_CONFIRM_RUNS",
    "DEFAULT_MAX_ENTRIES",
    "RATING_RANK",
    "RED_LINE_RATINGS",
    "HistoryEntry",
    "RatingHistoryStore",
    "StabilityConfig",
    "StabilityDecision",
    "decide",
]
