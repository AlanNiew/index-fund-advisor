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
    """执行组合配置分析。"""
    from ifa.common import build_advisor, build_state

    with st.status("正在生成组合配置...", expanded=True) as status:
        st.write("🟡 初始化...")
        advisor = build_advisor()

        st.write("🟡 生成组合方案（可能需要 2-3 分钟）...")
        state = build_state("portfolio", risk_profile=risk_profile, screen_conditions=f"风险偏好: {risk_profile}")
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
        from ifa.common import save_report

        path = save_report(final_state)
        if path:
            st.caption(f"报告已保存: {path}")
