"""Web 可视化图表组件 — 基于 Plotly。"""

from __future__ import annotations

from typing import Any


def render_equity_curve(equity_curve: list[dict[str, Any]], title: str = "净值曲线"):
    """渲染净值/权益曲线图。

    参数:
        equity_curve: [{"date": "2024-01-01", "value": 100000}, ...]
        title: 图表标题
    """
    import plotly.graph_objects as go
    import streamlit as st

    if not equity_curve or len(equity_curve) < 2:
        st.info("数据不足，无法绘制曲线")
        return

    dates = [p["date"] for p in equity_curve]
    values = [p["value"] for p in equity_curve]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=values,
            mode="lines",
            name="净值",
            line=dict(color="#2563eb", width=2),
            fill="tozeroy",
            fillcolor="rgba(37, 99, 235, 0.08)",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="净值 (¥)",
        height=400,
        margin=dict(l=60, r=20, t=50, b=40),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_monthly_returns_bar(monthly_returns: list[dict[str, Any]]):
    """渲染月度收益柱状图。

    参数:
        monthly_returns: [{"month": "2024-01", "return_pct": 2.5}, ...]
    """
    import plotly.graph_objects as go
    import streamlit as st

    if not monthly_returns:
        st.info("无月度收益数据")
        return

    months = [m["month"] for m in monthly_returns]
    returns = [m["return_pct"] for m in monthly_returns]
    colors = ["#16a34a" if r >= 0 else "#dc2626" for r in returns]

    fig = go.Figure(go.Bar(x=months, y=returns, marker_color=colors, name="月度收益"))
    fig.update_layout(
        title="月度收益率",
        xaxis_title="月份",
        yaxis_title="收益率 (%)",
        height=350,
        margin=dict(l=60, r=20, t=50, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_backtest_metrics(result: dict[str, Any]):
    """渲染回测关键指标卡片。

    参数:
        result: BacktestResult 的 to_dict() 输出
    """
    import streamlit as st

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总收益率", f"{result.get('total_return_pct', 0):+.2f}%")
    col2.metric("年化收益率", f"{result.get('annualized_return_pct', 0):+.2f}%")
    col3.metric("最大回撤", f"{result.get('max_drawdown_pct', 0):.2f}%")
    col4.metric("Sharpe 比率", f"{result.get('sharpe_ratio', 0):.2f}")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("初始投入", f"¥{result.get('initial_value', 0):,.0f}")
    col6.metric("期末价值", f"¥{result.get('final_value', 0):,.2f}")
    col7.metric("年化波动率", f"{result.get('volatility_pct', 0):.2f}%")
    col8.metric("交易天数", f"{result.get('trading_days', 0)}")
