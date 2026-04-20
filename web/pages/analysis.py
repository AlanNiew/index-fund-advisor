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
    from datetime import datetime

    from ifa.default_config import build_runtime_config
    from ifa.llm_clients.factory import create_llm_client
    from ifa.graph.advisor_graph import AdvisorGraph

    with st.status("正在执行分析...", expanded=True) as status:
        st.write("🟡 初始化 LLM 客户端...")

        config = build_runtime_config()
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

        st.write("🟡 构建分析图...")
        advisor = AdvisorGraph(
            quick_llm=quick_llm.get_llm(),
            deep_llm=deep_llm.get_llm(),
            config=config,
        )

        state = {
            "fund_codes": fund_code,
            "analysis_date": analysis_date or datetime.now().strftime("%Y-%m-%d"),
            "mode": "deep",
            "asset_type": "",
            "screen_conditions": "",
            "risk_profile": "",
            "screen_results": "",
            "fund_analysis_report": "",
            "index_analysis_report": "",
            "portfolio_advice": "",
            "final_report": "",
            "messages": [],
        }

        st.write("🟡 执行分析（可能需要 1-2 分钟）...")
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
    else:
        st.warning("分析完成但未生成报告")
