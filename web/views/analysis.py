"""单只基金深度分析页面（含回测图表）。"""

import streamlit as st


@st.cache_resource
def _get_advisor():
    """缓存 AdvisorGraph 实例，避免每次分析都重建 LLM 客户端。"""
    from ifa.common import build_advisor

    return build_advisor()


def render_analysis_page():
    st.title("单只基金深度分析")

    col1, col2 = st.columns([3, 1])
    with col1:
        fund_code = st.text_input("基金代码", placeholder="如 510300、159919、007540")
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        analysis_date = st.date_input("分析日期")

    with st.expander("回测参数（可选）"):
        bt_col1, bt_col2 = st.columns(2)
        with bt_col1:
            bt_enabled = st.checkbox("同时运行回测")
        with bt_col2:
            bt_months = st.selectbox("回测时长", [3, 6, 12, 24], index=2, format_func=lambda x: f"{x} 个月")
        bt_amount = st.number_input("初始金额", min_value=1000, value=100000, step=10000)

    if st.button("开始分析", type="primary", use_container_width=True):
        if not fund_code:
            st.error("请输入基金代码")
            return
        _run_deep_analysis(fund_code, str(analysis_date), bt_enabled, bt_months, bt_amount)


def _run_deep_analysis(fund_code: str, analysis_date: str, bt_enabled: bool, bt_months: int, bt_amount: float):
    """执行深度分析（可选回测）。"""
    from ifa.common import build_state

    advisor = _get_advisor()

    with st.status("正在执行分析...", expanded=True) as status:
        st.write("执行分析（可能需要 1-2 分钟）...")
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

    # 回测部分
    if bt_enabled:
        st.markdown("---")
        st.subheader("历史回测")

        import dataclasses
        from datetime import datetime, timedelta

        from ifa.backtest.engine import format_backtest_report, run_backtest

        end_dt = datetime.strptime(analysis_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=bt_months * 31)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = analysis_date

        with st.spinner(f"正在回测 {start_date} ~ {end_date} ..."):
            result = run_backtest(fund_code, start_date, end_date, bt_amount)

        from web.views.charts import render_backtest_metrics, render_equity_curve, render_monthly_returns_bar

        render_backtest_metrics(dataclasses.asdict(result))

        tab_curve, tab_monthly, tab_detail = st.tabs(["净值曲线", "月度收益", "详细报告"])
        with tab_curve:
            render_equity_curve(result.equity_curve, f"{fund_code} 净值曲线")
        with tab_monthly:
            render_monthly_returns_bar(result.monthly_returns)
        with tab_detail:
            st.markdown(format_backtest_report(result))
