# web/pages/portfolio.py
"""组合配置建议页面。"""

import streamlit as st


def render_portfolio_page():
    st.title("💰 智能组合配置建议")

    st.subheader("风险偏好")
    risk_options = {
        "conservative": "🛡️ 保守型 — 追求资产保值，低波动",
        "moderate": "⚖️ 稳健型 — 追求增值与风险平衡",
        "aggressive": "🚀 积极型 — 追求较高收益",
        "growth": "🔥 成长型 — 追求高收益，高风险",
    }
    risk = st.radio("选择风险偏好", list(risk_options.keys()), format_func=lambda x: risk_options[x], index=1)

    investment_amount = st.number_input("投资金额（可选）", min_value=0, value=0, step=10000)

    if st.button("生成配置方案", type="primary", use_container_width=True):
        _run_portfolio(risk, investment_amount)


def _run_portfolio(risk_profile: str, amount: float):
    from datetime import datetime

    from ifa.default_config import build_runtime_config
    from ifa.llm_clients.factory import create_llm_client
    from ifa.graph.advisor_graph import AdvisorGraph

    with st.status("正在生成组合配置...", expanded=True) as status:
        st.write("🟡 初始化...")
        config = build_runtime_config()
        kwargs = _get_provider_kwargs(config)

        quick_llm = create_llm_client(
            provider=config["llm_provider"],
            model=config["quick_think_llm"],
            base_url=config.get("backend_url"),
            **kwargs,
        )
        deep_llm = create_llm_client(
            provider=config["llm_provider"],
            model=config["deep_think_llm"],
            base_url=config.get("backend_url"),
            **kwargs,
        )

        st.write("🟡 生成组合方案（可能需要 2-3 分钟）...")
        advisor = AdvisorGraph(
            quick_llm=quick_llm.get_llm(),
            deep_llm=deep_llm.get_llm(),
            config=config,
        )

        state = {
            "fund_codes": "",
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "mode": "portfolio",
            "asset_type": "",
            "screen_conditions": f"风险偏好: {risk_profile}",
            "risk_profile": risk_profile,
            "screen_results": "",
            "fund_analysis_report": "",
            "index_analysis_report": "",
            "portfolio_advice": "",
            "final_report": "",
            "messages": [],
        }

        try:
            final_state = advisor.run("portfolio", state)
            status.update(label="配置方案生成完成!", state="complete")
        except Exception as e:
            status.update(label="生成失败", state="error")
            st.error(f"生成失败: {e}")
            return

    report = final_state.get("final_report", "")
    if report:
        st.markdown(report)


def _get_provider_kwargs(config: dict) -> dict:
    kwargs = {}
    provider = config.get("llm_provider", "").lower()
    if provider == "google":
        t = config.get("google_thinking_level")
        if t:
            kwargs["thinking_level"] = t
    elif provider in ("openai", "azure"):
        e = config.get("openai_reasoning_effort")
        if e:
            kwargs["reasoning_effort"] = e
        if provider == "azure":
            av = config.get("azure_api_version")
            if av:
                kwargs["azure_api_version"] = av
    elif provider == "anthropic":
        e = config.get("anthropic_effort")
        if e:
            kwargs["effort"] = e
    timeout = config.get("timeout")
    if timeout is not None:
        kwargs["timeout"] = timeout
    return kwargs
