"""IFA — AI 驱动的中国指数基金分析工具。"""

from ifa.common import build_advisor, build_state, save_report
from ifa.graph.advisor_graph import AdvisorGraph

__all__ = [
    "AdvisorGraph",
    "build_advisor",
    "build_state",
    "save_report",
]
