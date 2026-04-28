"""历史记录页面 — 展示 results/ 目录下的历史分析报告。"""

import os
from datetime import datetime
from pathlib import Path

import streamlit as st


def render_history_page():
    st.title("📋 历史记录")

    results_dir = os.environ.get(
        "IFA_RESULTS_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "results"),
    )
    results_path = Path(results_dir)

    if not results_path.exists():
        st.info("暂无历史记录。运行分析后，报告将自动保存。")
        return

    md_files = sorted(results_path.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not md_files:
        st.info("暂无历史记录。运行分析后，报告将自动保存。")
        return

    st.caption(f"共 {len(md_files)} 份报告（存储于 {results_path}）")

    for md_file in md_files[:50]:
        fund_dir = md_file.parent.name
        mod_time = md_file.stat().st_mtime
        time_str = datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M")

        with st.expander(f"📄 {md_file.name} — {fund_dir} — {time_str}"):
            content = md_file.read_text(encoding="utf-8")
            if len(content) > 5000:
                st.markdown(content[:5000])
                st.caption(f"... (共 {len(content)} 字符)")
            else:
                st.markdown(content)
