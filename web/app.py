# web/app.py
"""IFA Streamlit Web 界面入口。"""

import os
import sys

import streamlit as st

from ifa.env_loader import load_env_files

# 确保项目根目录和 src 目录都在 sys.path 中
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
sys.path.insert(0, _PROJECT_ROOT)

# 加载 .env 文件（CLI 入口 cli/main.py 也会加载，但 Streamlit 子进程需要单独加载；
# load_env_files 同时覆盖用户配置目录，便于不在项目目录里启动时也能读到 Key）
load_env_files()

st.set_page_config(
    page_title="IFA - 指数基金分析",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 侧边栏导航 ──
st.sidebar.title("IFA 指数基金分析")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "功能导航",
    ["🏠 首页", "🔍 基金分析", "📊 筛选对比", "💰 组合配置", "📋 历史记录"],
)

if page == "🏠 首页":
    st.title("IFA - AI 驱动的指数基金分析工具")
    st.markdown("""
    ### 功能介绍

    - **单只基金深度分析**：输入基金代码，获取全面的基金分析报告
    - **筛选对比**：按条件筛选指数基金，多维度对比分析
    - **组合配置建议**：基于风险偏好，推荐指数基金组合方案

    ### 使用方式
    1. 在左侧导航选择功能
    2. 输入分析参数
    3. 点击开始分析
    """)

elif page == "🔍 基金分析":
    from web.views.analysis import render_analysis_page

    render_analysis_page()

elif page == "📊 筛选对比":
    from web.views.screen import render_screen_page

    render_screen_page()

elif page == "💰 组合配置":
    from web.views.portfolio import render_portfolio_page

    render_portfolio_page()

elif page == "📋 历史记录":
    from web.views.history import render_history_page

    render_history_page()
