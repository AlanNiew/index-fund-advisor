# ifa/backtest/engine.py
"""简易回测引擎 —— 基于买入-持有策略的历史收益回测。

支持 ETF/指数基金的定投和一次性投资回测，
计算年化收益、最大回撤、Sharpe 等关键指标。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ifa.dataflows.data_cleaning import clean_dataframe

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """回测结果。"""

    symbol: str
    start_date: str
    end_date: str
    initial_value: float
    final_value: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    volatility_pct: float
    trading_days: int
    monthly_returns: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


def _parse_raw_to_dataframe(raw) -> pd.DataFrame | None:
    """将原始数据（CSV 字符串或 DataFrame）解析为 DataFrame。

    数据工具返回的 CSV 字符串通常带 ``#`` 开头的元信息行（如
    ``# ETF price data for ...``），必须跳过，否则 pandas 会把注释
    内容误解析为数据行。
    """
    if isinstance(raw, str) and "暂无数据" in raw:
        return None
    if isinstance(raw, str):
        from io import StringIO

        return pd.read_csv(StringIO(raw), comment="#")
    if isinstance(raw, pd.DataFrame):
        return raw.copy()
    return None


def _fetch_etf_index_data(
    symbol: str,
    start_date: str,
    end_date: str,
    asset_type,
) -> pd.DataFrame | None:
    """获取 ETF/指数价格数据。"""
    from ifa.dataflows.a_share_index_fund import get_etf_data, get_index_data

    raw = (
        get_etf_data(symbol, start_date, end_date)
        if asset_type.name == "ETF"
        else get_index_data(symbol, start_date, end_date)
    )

    df = _parse_raw_to_dataframe(raw)
    if df is None:
        return None

    date_col = _find_column(df, "date", "日期", "trade_date")
    close_col = _find_column(df, "close", "收盘", "close_price")
    if date_col is None or close_col is None:
        return None

    df = df[[date_col, close_col]].copy()
    df.columns = ["date", "close"]
    df = clean_dataframe(df, context=f"回测 {symbol}")
    if df.empty:
        return None

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    return df


def _fetch_fund_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """获取公募基金/场外基金净值数据。"""
    from ifa.dataflows.a_share_public_fund import get_fund_history_nav

    raw = get_fund_history_nav(symbol)
    df = _parse_raw_to_dataframe(raw)
    if df is None:
        return None

    date_col = _find_column(df, "净值日期", "date", "日期")
    close_col = _find_column(df, "单位净值", "nav", "close")
    if date_col is None or close_col is None:
        return None

    df = df[[date_col, close_col]].copy()
    df.columns = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"])

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _fetch_price_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """获取历史价格数据。"""
    from ifa.dataflows.asset_type import AssetType, detect_asset_type

    try:
        asset_type = detect_asset_type(symbol)
    except Exception:
        asset_type = AssetType.ETF

    if asset_type in (AssetType.ETF, AssetType.INDEX):
        return _fetch_etf_index_data(symbol, start_date, end_date, asset_type)

    if asset_type in (AssetType.PUBLIC_FUND, AssetType.OFFSHORE_FUND):
        return _fetch_fund_data(symbol, start_date, end_date)

    return None


def _find_column(df: pd.DataFrame, *candidates: str) -> str | None:
    """按候选名查找列。"""
    for col in df.columns:
        col_lower = col.lower().strip()
        for c in candidates:
            if col_lower == c.lower() or c.lower() in col_lower:
                return str(col)
    return None


def _calc_max_drawdown(prices: pd.Series) -> float:
    """计算最大回撤（百分比）。"""
    cummax = prices.cummax()
    drawdown = (prices - cummax) / cummax * 100
    return float(drawdown.min())


def _calc_sharpe(daily_returns: pd.Series, risk_free_rate: float = 0.02) -> float:
    """计算年化 Sharpe 比率。"""
    if daily_returns.std() == 0:
        return 0.0
    excess = daily_returns - risk_free_rate / 252
    return float(excess.mean() / daily_returns.std() * np.sqrt(252))


def _calc_monthly_returns(df: pd.DataFrame) -> list[dict[str, Any]]:
    """计算月度收益。"""
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month")["close"].agg(["first", "last"])
    monthly["return_pct"] = (monthly["last"] / monthly["first"] - 1) * 100
    return [{"month": str(m), "return_pct": round(r, 2)} for m, r in monthly["return_pct"].items()]


def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_investment: float = 100000.0,
) -> BacktestResult:
    """执行买入-持有策略的回测。

    参数:
        symbol: 基金/ETF/指数代码
        start_date: 回测起始日期 YYYY-MM-DD
        end_date: 回测结束日期 YYYY-MM-DD
        initial_investment: 初始投资金额

    返回:
        BacktestResult 包含完整的回测指标
    """
    empty_result = BacktestResult(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_value=initial_investment,
        final_value=initial_investment,
        total_return_pct=0,
        annualized_return_pct=0,
        max_drawdown_pct=0,
        sharpe_ratio=0,
        volatility_pct=0,
        trading_days=0,
    )

    try:
        df = _fetch_price_data(symbol, start_date, end_date)
    except Exception as e:
        logger.warning("回测数据获取失败 (%s): %s", symbol, e)
        empty_result.error = f"数据获取失败: {e}"
        return empty_result

    if df is None or len(df) < 2:
        empty_result.error = "数据不足（少于 2 个交易日）"
        return empty_result

    prices = df["close"]
    initial_price = float(prices.iloc[0])
    final_price = float(prices.iloc[-1])

    # 总收益
    total_return = (final_price / initial_price - 1) * 100

    # 年化收益
    days = len(df)
    years = days / 252
    annualized = ((final_price / initial_price) ** (1 / max(years, 0.01)) - 1) * 100 if years > 0 else 0

    # 日收益率
    daily_returns = prices.pct_change().dropna()

    # 波动率
    volatility = float(daily_returns.std() * np.sqrt(252) * 100)

    # 最大回撤
    max_dd = _calc_max_drawdown(prices)

    # Sharpe
    sharpe = _calc_sharpe(daily_returns)

    # 月度收益
    monthly = _calc_monthly_returns(df)

    # 净值曲线（采样到最多 120 个点）
    step = max(1, len(df) // 120)
    sampled = df.iloc[::step]
    equity = [
        {
            "date": str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"]),
            "value": round(initial_investment * row["close"] / initial_price, 2),
        }
        for _, row in sampled.iterrows()
    ]

    return BacktestResult(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_value=initial_investment,
        final_value=round(initial_investment * final_price / initial_price, 2),
        total_return_pct=round(total_return, 2),
        annualized_return_pct=round(annualized, 2),
        max_drawdown_pct=round(max_dd, 2),
        sharpe_ratio=round(sharpe, 2),
        volatility_pct=round(volatility, 2),
        trading_days=days,
        monthly_returns=monthly,
        equity_curve=equity,
    )


def format_backtest_report(result: BacktestResult) -> str:
    """将回测结果格式化为 Markdown 报告。"""
    if result.error:
        return f"## 回测报告 — {result.symbol}\n\n⚠️ {result.error}"

    lines = [
        f"## 回测报告 — {result.symbol}",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 回测区间 | {result.start_date} ~ {result.end_date} |",
        f"| 交易天数 | {result.trading_days} |",
        f"| 初始投入 | ¥{result.initial_value:,.0f} |",
        f"| 期末价值 | ¥{result.final_value:,.2f} |",
        f"| 总收益率 | {result.total_return_pct:+.2f}% |",
        f"| 年化收益率 | {result.annualized_return_pct:+.2f}% |",
        f"| 最大回撤 | {result.max_drawdown_pct:.2f}% |",
        f"| Sharpe 比率 | {result.sharpe_ratio:.2f} |",
        f"| 年化波动率 | {result.volatility_pct:.2f}% |",
        "",
    ]

    if result.monthly_returns:
        lines.append("### 月度收益")
        lines.append("")
        lines.append("| 月份 | 收益率 |")
        lines.append("|------|--------|")
        for m in result.monthly_returns[-12:]:  # 最近 12 个月
            lines.append(f"| {m['month']} | {m['return_pct']:+.2f}% |")

    return "\n".join(lines)
