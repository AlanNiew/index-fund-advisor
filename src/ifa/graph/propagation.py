# ifa/graph/propagation.py
"""状态初始化与传播模块 —— 管理图执行的初始状态和传播参数。"""

from typing import Any

from ifa.agents.types import FundDebateState, RiskDebateState


class Propagator:
    """管理 IFA 工作流的状态初始化和图传播参数。"""

    def __init__(self, max_recur_limit: int = 150):
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        fund_codes: str = "",
        analysis_date: str = "",
        mode: str = "deep",
        screen_conditions: str = "",
        risk_profile: str = "",
    ) -> dict[str, Any]:
        """创建图执行的初始状态。

        参数:
            fund_codes: 目标基金代码（逗号分隔）
            analysis_date: 分析日期
            mode: 分析模式 (deep/screen/portfolio)
            screen_conditions: 筛选条件
            risk_profile: 风险偏好
        """
        from langchain_core.messages import HumanMessage

        if mode == "deep" and fund_codes:
            init_content = f"请对基金 {fund_codes} 进行深度分析。"
        elif mode == "screen" and screen_conditions:
            init_content = f"请按以下条件筛选指数基金：{screen_conditions}"
        elif mode == "portfolio":
            risk = risk_profile or "moderate"
            init_content = f"请根据风险偏好（{risk}）生成指数基金组合配置建议。"
        else:
            init_content = "请开始分析。"

        return {
            "messages": [HumanMessage(content=init_content)],
            "fund_codes": fund_codes,
            "analysis_date": analysis_date,
            "mode": mode,
            "asset_type": "",
            "screen_conditions": screen_conditions,
            "risk_profile": risk_profile,
            "screen_results": "",
            "fund_analysis_report": "",
            "index_analysis_report": "",
            "portfolio_advice": "",
            "fund_debate_state": FundDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "final_report": "",
            "final_rating": "",
            "final_confidence": "",
        }

    def get_graph_args(self, callbacks: list | None = None) -> dict[str, Any]:
        """获取图执行参数。"""
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
