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
    from datetime import datetime

    from ifa.default_config import build_runtime_config
    from ifa.llm_clients.factory import create_llm_client
    from ifa.graph.advisor_graph import AdvisorGraph

    with st.status("正在执行筛选...", expanded=True) as status:
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

        st.write("🟡 筛选中...")
        advisor = AdvisorGraph(
            quick_llm=quick_llm.get_llm(),
            deep_llm=deep_llm.get_llm(),
            config=config,
        )

        state = {
            "fund_codes": "",
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "mode": "screen",
            "asset_type": "",
            "screen_conditions": conditions,
            "risk_profile": "",
            "screen_results": "",
            "fund_analysis_report": "",
            "index_analysis_report": "",
            "portfolio_advice": "",
            "final_report": "",
            "messages": [],
        }

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
