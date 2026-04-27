# ifa/agents/managers/report_generator.py
"""报告生成器 —— 综合各阶段分析结果，生成格式化的最终报告。"""

from ifa.agents.utils import (
    get_final_language_instruction,
    invoke_llm_safely,
)

_REPORT_GENERATOR_PROMPT = """You are a report generator for index fund analysis. Your task is to
synthesize all analysis results into a well-structured, professional Markdown report.

## Analysis Mode: {mode}
## Fund Code(s): {fund_codes}
## Analysis Date: {analysis_date}

## Fund Analysis Report:
{fund_analysis_report}

## Index/Constituent Analysis Report:
{index_analysis_report}

## Portfolio Advice:
{portfolio_advice}

## Screening Results:
{screen_results}

## Research Debate Judgment:
{debate_judgment}

Generate a comprehensive final report in Markdown format with the following structure:

# 指数基金分析报告

## 基金概览
- Basic fund information summary

## 业绩分析
- Performance metrics and peer comparison

## 风险评估
- Risk metrics and drawdown analysis

## 持仓分析
- Holdings and sector allocation (if applicable)

## 成分股分析
- Constituent stock analysis (if applicable, for ETF/index funds)

## 投资建议
- Final recommendation: BUY / HOLD / REDEEM
- Confidence level
- Key reasons

## 风险提示
- Important risk factors to consider

---
*报告生成日期: {analysis_date}*
*本报告由 AI 分析生成，仅供参考，不构成投资建议。*
{language_instruction}"""


def _extract_debate_judgment(state: dict) -> str:
    """从状态中提取辩论裁决结果，整合基金辩论和风险辩论的裁决。"""
    parts = []

    # 基金研究辩论裁决
    fund_debate = state.get("fund_debate_state", {})
    if isinstance(fund_debate, dict):
        judge_decision = fund_debate.get("judge_decision", "")
        if judge_decision:
            parts.append(f"### Fund Research Debate Decision\n{judge_decision}")

    # 风险辩论裁决
    risk_debate = state.get("risk_debate_state", {})
    if isinstance(risk_debate, dict):
        judge_decision = risk_debate.get("judge_decision", "")
        if judge_decision:
            parts.append(f"### Risk Debate Decision\n{judge_decision}")

    return "\n\n".join(parts) if parts else "无"


def create_report_generator(llm):
    """创建并返回报告生成器节点。"""

    def report_generator_node(state) -> dict:
        mode = state.get("mode", "deep")
        fund_codes = state.get("fund_codes", "")
        analysis_date = state.get("analysis_date", "")
        fund_analysis = state.get("fund_analysis_report", "")
        index_analysis = state.get("index_analysis_report", "")
        portfolio_advice = state.get("portfolio_advice", "")
        screen_results = state.get("screen_results", "")

        # 提取辩论裁决结果
        debate_judgment = _extract_debate_judgment(state)

        language_instruction = get_final_language_instruction()

        prompt = _REPORT_GENERATOR_PROMPT.format(
            mode=mode,
            fund_codes=fund_codes,
            analysis_date=analysis_date,
            fund_analysis_report=fund_analysis or "无",
            index_analysis_report=index_analysis or "无",
            portfolio_advice=portfolio_advice or "无",
            screen_results=screen_results or "无",
            debate_judgment=debate_judgment,
            language_instruction=language_instruction,
        )

        response = invoke_llm_safely(llm, prompt)

        return {
            "messages": [response],
            "final_report": response.content,
        }

    return report_generator_node
