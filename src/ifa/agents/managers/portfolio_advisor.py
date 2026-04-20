# ifa/agents/managers/portfolio_advisor.py
"""组合配置顾问 —— 基于风险偏好和资产配置理论推荐指数基金组合方案。"""

from ifa.agents.utils import (
    get_final_language_instruction,
    get_internal_language_instruction,
    invoke_llm_safely,
)
from ifa.portfolio.models import RISK_PROFILES
from ifa.portfolio.strategies import STRATEGY_DESCRIPTIONS

_PORTFOLIO_ADVISOR_PROMPT = """You are a professional index fund portfolio advisor for A-share (A股) market.
Your role is to create an optimized index fund portfolio based on the user's risk profile.

## User Risk Profile: {risk_profile}
{profile_details}

## Available Asset Allocation Strategies:
{strategies}

## Instructions:
1. Based on the risk profile, determine the optimal asset class allocation
   (broad-based index, mid/small cap, sector thematic, bond, money market, QDII);
2. For each asset class, identify the best index fund candidates using screening criteria;
3. Consider diversification, correlation, and risk-adjusted returns;
4. Specify exact allocation percentages that sum to 100%;
5. Provide clear reasoning for each allocation decision.

## Fund Analysis Results (from Fund Analyst):
{fund_analysis_report}

## Screening Results (from Fund Screener):
{screen_results}

Output format - start with "PORTFOLIO ADVICE:" followed by:
- ASSET ALLOCATION: Category weights (e.g., 宽基指数 50%, 债券 20%, ...)
- FUND SELECTIONS: For each category, the recommended fund code, name, and weight
- RATIONALE: Why this allocation suits the {risk_profile} profile
- RISK ASSESSMENT: Expected return range, volatility level, max drawdown estimate
- REBALANCE GUIDANCE: When and how to rebalance
{language_instruction}"""


def create_portfolio_advisor(llm, memory=None):
    """创建并返回组合配置顾问节点。"""

    def portfolio_advisor_node(state) -> dict:
        risk_profile = state.get("risk_profile", "moderate")
        fund_analysis = state.get("fund_analysis_report", "")
        screen_results = state.get("screen_results", "")

        # 获取风险偏好模板
        profile = RISK_PROFILES.get(risk_profile, RISK_PROFILES["moderate"])
        profile_details = (
            f"Allocation template: {profile.allocation_template}\n"
            f"Max single fund weight: {profile.max_single_fund_pct * 100}%\n"
            f"Min bond weight: {profile.min_bond_pct * 100}%\n"
            f"Max international weight: {profile.max_international_pct * 100}%"
        )

        # 获取策略描述
        strategy_text = "\n".join(
            f"- **{s['name']}**: {s['description']}"
            for s in STRATEGY_DESCRIPTIONS.values()
        )

        language_instruction = (
            get_internal_language_instruction() + get_final_language_instruction()
        )

        prompt = _PORTFOLIO_ADVISOR_PROMPT.format(
            risk_profile=risk_profile,
            profile_details=profile_details,
            strategies=strategy_text,
            fund_analysis_report=fund_analysis or "Not available yet",
            screen_results=screen_results or "Not available yet",
            language_instruction=language_instruction,
        )

        response = invoke_llm_safely(llm, prompt)

        return {
            "messages": [response],
            "portfolio_advice": response.content,
        }

    return portfolio_advisor_node
