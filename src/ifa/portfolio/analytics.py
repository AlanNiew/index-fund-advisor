# ifa/portfolio/analytics.py
"""组合层数学分析 —— 相关性、协方差与风险贡献（代码计算，不靠 LLM 自述）。

组合建议的 prompt 一直要求 LLM "consider correlation"，但项目此前没有任何代码
真正计算过相关性、协方差或风险贡献，组合层的风险描述完全是 LLM 自述。本模块用
各基金的真实历史净值/收盘价序列（与回测共用同一取价层，口径一致），在共同交易日
上对齐后计算：

- 年化协方差矩阵与相关系数矩阵（日频收益 × 252，样本自由度 ddof=1）
- 组合年化波动率 sqrt(w' Σ w)
- 加权平均波动率 Σ w_i σ_i —— 「完全不看相关性」的对照基准
- 分散化比率 = 加权平均波动率 / 组合波动率（> 1 才说明相关性带来了分散化收益）
- 每只基金的风险贡献 RC_i = w_i (Σ w)_i / (w' Σ w)，以及「贡献占比 / 权重占比」

样本不足或取数失败时剔除该基金并在 notes 写明；有效基金不足 2 只返回 None。
绝不猜测、绝不把缺失当 0。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
DEFAULT_LOOKBACK_DAYS = 252
MIN_COMMON_OBSERVATIONS = 60

PriceFetcher = Callable[[str, str, str], Any]


def _default_price_fetcher(symbol: str, start_date: str, end_date: str) -> Any:
    """默认取价函数：复用回测的取价层，保证组合分析与回测/验证口径一致。"""
    from ifa.backtest.engine import _fetch_price_data

    return _fetch_price_data(symbol, start_date, end_date)


@dataclass
class PortfolioAnalytics:
    """组合数学分析结果（全部为历史已实现数据，不是预测）。"""

    fund_codes: list[str]
    weights: dict[str, float]
    price_bases: dict[str, str]
    start_date: str
    end_date: str
    observations: int
    annualized_vol_pct: float
    weighted_avg_vol_pct: float
    diversification_ratio: float
    avg_pairwise_correlation: float | None
    annualized_vol_pct_by_fund: dict[str, float]
    risk_contribution_pct: dict[str, float]
    risk_contribution_ratio: dict[str, float]
    correlation: list[list[float]]
    dropped: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好形式（日志/测试用）。"""
        return {
            "fund_codes": list(self.fund_codes),
            "weights": dict(self.weights),
            "price_bases": dict(self.price_bases),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "observations": self.observations,
            "annualized_vol_pct": self.annualized_vol_pct,
            "weighted_avg_vol_pct": self.weighted_avg_vol_pct,
            "diversification_ratio": self.diversification_ratio,
            "avg_pairwise_correlation": self.avg_pairwise_correlation,
            "annualized_vol_pct_by_fund": dict(self.annualized_vol_pct_by_fund),
            "risk_contribution_pct": dict(self.risk_contribution_pct),
            "risk_contribution_ratio": dict(self.risk_contribution_ratio),
            "correlation": [list(row) for row in self.correlation],
            "dropped": list(self.dropped),
            "notes": list(self.notes),
        }


def _close_series(df: pd.DataFrame) -> pd.Series | None:
    """从行情/净值表里取「收盘价或净值」序列（列名按数据源模糊匹配）。"""
    from ifa.backtest.engine import _find_column

    if df is None or getattr(df, "empty", True):
        return None
    value_col = _find_column(df, "close", "收盘", "收盘价", "累计净值", "单位净值", "净值")
    date_col = _find_column(df, "date", "日期", "净值日期", "时间")
    if value_col is None or date_col is None:
        return None
    series = pd.Series(
        pd.to_numeric(df[value_col], errors="coerce").to_numpy(),
        index=pd.to_datetime(df[date_col], errors="coerce"),
        name="close",
    )
    series = series[series.index.notna()]
    series = series.dropna()
    series = series[~series.index.duplicated(keep="last")].sort_index()
    if len(series) < 2:
        return None
    return series


def _fetch_close_series(
    code: str,
    start_date: str,
    end_date: str,
    fetcher: PriceFetcher,
) -> tuple[pd.Series | None, str]:
    """取一只基金的收盘/净值序列，附带价格口径说明；失败返回 (None, "")。"""
    try:
        df = fetcher(code, start_date, end_date)
    except Exception as exc:  # 数据源异常不能让整个组合分析中断
        logger.debug("组合分析取价失败 %s: %s", code, exc)
        return None, ""
    basis = ""
    try:
        basis = str(df.attrs.get("price_basis", "")) if df is not None else ""
    except Exception:
        basis = ""
    return _close_series(df), basis


def _align_returns(series_map: dict[str, pd.Series]) -> pd.DataFrame:
    """按共同交易日对齐后计算日收益率（任一基金缺失的交易日整行丢弃）。"""
    levels = pd.DataFrame(series_map)
    levels = levels.dropna(how="any")
    returns = levels.pct_change().dropna(how="any")
    return returns


def compute_analytics(
    returns: pd.DataFrame,
    weights: dict[str, float],
    *,
    price_bases: dict[str, str] | None = None,
    dropped: list[str] | None = None,
    notes: list[str] | None = None,
) -> PortfolioAnalytics | None:
    """纯计算：给定日收益矩阵与权重，算波动率/相关系数/风险贡献。

    不做任何取数，便于用合成矩阵单测。有效基金不足 2 只、权重合计 <= 0 或
    组合方差退化时返回 None。
    """
    codes = [str(c) for c in returns.columns]
    if len(codes) < 2 or len(returns) < 2:
        return None
    raw = np.array([float(weights.get(c, 0.0)) for c in codes], dtype=float)
    if raw.sum() <= 0:
        return None
    w = raw / raw.sum()

    values = returns.to_numpy(dtype=float)
    cov_daily = np.atleast_2d(np.cov(values, rowvar=False, ddof=1))
    cov = cov_daily * TRADING_DAYS_PER_YEAR
    vols = np.sqrt(np.diag(cov))
    if np.any(vols <= 0):
        return None

    port_var = float(w @ cov @ w)
    if not np.isfinite(port_var) or port_var <= 0:
        return None
    port_vol = float(np.sqrt(port_var))
    weighted_avg_vol = float(w @ vols)
    div_ratio = weighted_avg_vol / port_vol

    corr = cov / np.outer(vols, vols)
    corr = np.clip(corr, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    off_diag = corr[~np.eye(len(codes), dtype=bool)]
    avg_corr = float(np.mean(off_diag)) if off_diag.size and np.all(np.isfinite(off_diag)) else None

    marginal = cov @ w
    rc_share = w * marginal / port_var
    rc_ratio = np.divide(rc_share, w, out=np.zeros_like(rc_share), where=w > 0)

    start_date = str(returns.index[0])[:10]
    end_date = str(returns.index[-1])[:10]
    return PortfolioAnalytics(
        fund_codes=codes,
        weights={c: float(wi) for c, wi in zip(codes, w, strict=True)},
        price_bases=dict(price_bases or {}),
        start_date=start_date,
        end_date=end_date,
        observations=int(len(returns)),
        annualized_vol_pct=round(port_vol * 100, 2),
        weighted_avg_vol_pct=round(weighted_avg_vol * 100, 2),
        diversification_ratio=round(div_ratio, 3),
        avg_pairwise_correlation=None if avg_corr is None else round(avg_corr, 3),
        annualized_vol_pct_by_fund={c: round(float(v) * 100, 2) for c, v in zip(codes, vols, strict=True)},
        risk_contribution_pct={c: round(float(v) * 100, 2) for c, v in zip(codes, rc_share, strict=True)},
        risk_contribution_ratio={c: round(float(v), 3) for c, v in zip(codes, rc_ratio, strict=True)},
        correlation=[[round(float(x), 3) for x in row] for row in corr],
        dropped=list(dropped or []),
        notes=list(notes or []),
    )


def analyze_portfolio(
    weights: dict[str, float],
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    as_of: str | None = None,
    price_fetcher: PriceFetcher | None = None,
    min_observations: int = MIN_COMMON_OBSERVATIONS,
) -> PortfolioAnalytics | None:
    """按权重表取历史序列并计算组合数学指标；数据不足时返回 None。

    weights 是「基金代码 -> 权重（百分数或小数都行，内部归一化）」。
    """
    codes = [str(c) for c in weights if float(weights.get(c, 0.0)) > 0]
    if len(codes) < 2:
        return None
    fetcher = price_fetcher or _default_price_fetcher
    end_date = as_of or date.today().isoformat()
    try:
        end = date.fromisoformat(end_date)
    except ValueError:
        return None
    start_date = (end - timedelta(days=int(lookback_days * 1.6) + 10)).isoformat()

    dropped: list[str] = []
    notes: list[str] = []
    series_map: dict[str, pd.Series] = {}
    bases: dict[str, str] = {}
    for code in codes:
        series, basis = _fetch_close_series(code, start_date, end_date, fetcher)
        if series is None:
            dropped.append(code)
            continue
        series_map[code] = series
        if basis:
            bases[code] = basis
    if len(series_map) < 2:
        return None

    returns = _align_returns(series_map).tail(lookback_days)
    if len(returns) < min_observations:
        return None

    kept = {c: float(weights[c]) for c in returns.columns}
    zero_vol = [c for c in returns.columns if not float(returns[c].std(ddof=1)) > 0]
    if zero_vol:
        returns = returns.drop(columns=zero_vol)
        for c in zero_vol:
            dropped.append(c)
        notes.append("剔除波动率为 0 的基金：" + "、".join(zero_vol))
        if len(returns.columns) < 2:
            return None
        kept = {c: kept[c] for c in returns.columns}

    bases_used = sorted({bases.get(c, "未知口径") for c in returns.columns})
    notes.insert(
        0,
        f"样本区间 {str(returns.index[0])[:10]} ~ {str(returns.index[-1])[:10]}，"
        f"{len(returns)} 个共同交易日；日频收益、协方差按 {TRADING_DAYS_PER_YEAR} 个交易日年化、ddof=1",
    )
    notes.append("价格口径：" + "；".join(bases_used))
    notes.append("风险贡献为归一化占比 w_i(Σw)_i/(w'Σw)；比值 < 1 表示该基金的边际风险贡献低于其资金占比")
    notes.append("波动率与分散化比率基于历史已实现数据，不是收益预测")
    if dropped:
        notes.append("未纳入计算的基金（取数失败或样本不足）：" + "、".join(dropped))

    return compute_analytics(returns, kept, price_bases=bases, dropped=dropped, notes=notes)


def format_portfolio_analytics(analytics: PortfolioAnalytics) -> str:
    """渲染代码计算的组合分析块（与 WEIGHT CHECK 一样，是确定性输出）。"""
    lines: list[str] = []
    lines.append("## PORTFOLIO ANALYTICS（代码计算，非 LLM 自述）")
    lines.append("")
    lines.append(f"- 样本区间：{analytics.start_date} ~ {analytics.end_date}（{analytics.observations} 个共同交易日）")
    lines.append(f"- 组合年化波动率：**{analytics.annualized_vol_pct:.2f}%**")
    lines.append(f"- 加权平均波动率（忽略相关性）：{analytics.weighted_avg_vol_pct:.2f}%")
    ratio_note = "相关性确实降低了组合波动" if analytics.diversification_ratio > 1.0 else "分散化没有带来波动下降"
    lines.append(f"- 分散化比率：**{analytics.diversification_ratio:.3f}**（{ratio_note}）")
    if analytics.avg_pairwise_correlation is None:
        lines.append("- 平均两两相关系数：不可用（样本退化）")
    else:
        lines.append(f"- 平均两两相关系数：**{analytics.avg_pairwise_correlation:.3f}**")
    lines.append("")
    lines.append("| 基金 | 权重 | 年化波动率 | 风险贡献占比 | 贡献占比 / 权重占比 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for code in analytics.fund_codes:
        lines.append(
            f"| {code} | {analytics.weights.get(code, 0.0) * 100:.1f}% "
            f"| {analytics.annualized_vol_pct_by_fund.get(code, 0.0):.2f}% "
            f"| {analytics.risk_contribution_pct.get(code, 0.0):.2f}% "
            f"| {analytics.risk_contribution_ratio.get(code, 0.0):.3f} |"
        )
    lines.append("")
    lines.append("相关系数矩阵：")
    lines.append("")
    header = "| | " + " | ".join(analytics.fund_codes) + " |"
    lines.append(header)
    lines.append("| --- " * (len(analytics.fund_codes) + 1) + "|")
    for code, row in zip(analytics.fund_codes, analytics.correlation, strict=True):
        cells = " | ".join(f"{value:.3f}" for value in row)
        lines.append(f"| {code} | {cells} |")
    lines.append("")
    for note in analytics.notes:
        lines.append(f"- {note}")
    return "\n".join(lines)
