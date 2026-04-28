# web/pages/screen.py
"""筛选对比页面。"""

import streamlit as st


def render_screen_page():
    st.title("📊 指数基金筛选对比")

    st.subheader("筛选条件")
    tab_structured, tab_natural = st.tabs(["结构化筛选", "自然语言"])

    with tab_structured:
        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox("指数类别", ["全部", "沪深指数", "行业主题", "大盘指数", "中盘指数", "小盘指数"])
        with col2:
            method = st.selectbox("跟踪方式", ["全部", "被动指数型", "增强指数型"])
        top_n = st.slider("返回数量", 5, 30, 10)

    with tab_natural:
        natural_query = st.text_area("输入自然语言条件", placeholder="如：帮我筛选规模大于10亿的沪深300被动指数基金")

    if st.button("开始筛选", type="primary", use_container_width=True):
        conditions = natural_query or f"类别: {category}, 跟踪方式: {method}, 前 {top_n} 只"
        _run_screen(conditions)


def _run_screen(conditions: str):
    """执行筛选分析。"""
    from ifa.common import build_advisor, build_state

    with st.status("正在执行筛选...", expanded=True) as status:
        st.write("🟡 初始化...")
        advisor = build_advisor()

        st.write("🟡 筛选中...")
        state = build_state("screen", screen_conditions=conditions)
        try:
            final_state = advisor.run("screen", state)
            status.update(label="筛选完成!", state="complete")
        except Exception as e:
            status.update(label="筛选失败", state="error")
            st.error(f"筛选失败: {e}")
            return

    report = final_state.get("final_report", "")
    if report:
        st.markdown(report)
        from ifa.common import save_report

        path = save_report(final_state)
        if path:
            st.caption(f"报告已保存: {path}")
