# web/pages/analysis.py
"""单只基金深度分析页面。"""

import streamlit as st


def render_analysis_page():
    st.title("🔍 单只基金深度分析")

    col1, col2 = st.columns([3, 1])
    with col1:
        fund_code = st.text_input("基金代码", placeholder="如 510300、159919、007540")
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        analysis_date = st.date_input("分析日期")

    if st.button("开始分析", type="primary", use_container_width=True):
        if not fund_code:
            st.error("请输入基金代码")
            return
        _run_deep_analysis(fund_code, str(analysis_date))


def _run_deep_analysis(fund_code: str, analysis_date: str):
    """执行深度分析。"""
    from ifa.common import build_advisor, build_state

    with st.status("正在执行分析...", expanded=True) as status:
        st.write("🟡 初始化 LLM 客户端...")
        advisor = build_advisor()

        st.write("🟡 执行分析（可能需要 1-2 分钟）...")
        state = build_state("deep", fund_codes=fund_code, analysis_date=analysis_date)
        try:
            final_state = advisor.run("deep", state)
            status.update(label="分析完成!", state="complete")
        except Exception as e:
            status.update(label="分析失败", state="error")
            st.error(f"分析失败: {e}")
            return

    report = final_state.get("final_report", "")
    if report:
        st.markdown(report)
        from ifa.common import save_report
        path = save_report(final_state)
        if path:
            st.caption(f"报告已保存: {path}")
    else:
        st.warning("分析完成但未生成报告")
