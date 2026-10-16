# ifa/backtest/engine.py
"""简易回测引擎 —— 买入-持有（一次性投资）策略的历史收益回测。

计算年化收益、最大回撤、Sharpe 等关键指标，并把「价格口径」与「投资者口径」
（扣掉申购费/赎回费/佣金后真正拿到手的收益）同时给出。

**不支持定投** —— 原 docstring 声称「支持定投和一次性投资」，但实现里只有一次性买入，
这是句假话，已删除。定投需要现金流加权（money-weighted）收益率，不是这套指标能表达的。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ifa.backtest.fees import FeeAssumptions, resolve_fees
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
    # —— 口径（P1 回测口径修正新增）——
    #: 价格序列是什么口径（累计净值 / 前复权价 / 指数价格），见 _price_basis_label
    price_basis: str = ""
    #: Sharpe 用的无风险利率（年化 %）及其来源
    risk_free_rate_pct: float = 2.0
    risk_free_source: str = "默认值 2%"
    #: 投资者口径：扣掉申购费/赎回费/佣金后真正拿到手的期末价值与收益
    net_final_value: float = 0.0
    net_total_return_pct: float = 0.0
    net_annualized_return_pct: float = 0.0
    #: 费用拖累（价格口径收益 − 投资者口径收益，百分点）
    fee_impact_pct: float = 0.0
    #: 本次用到的费用假设（含 describe 一行说明与 notes 列表）
    fee_assumptions: dict[str, Any] = field(default_factory=dict)
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
        from ifa.dataflows.a_share import DATA_SOURCE_ERROR_MARKER

        if DATA_SOURCE_ERROR_MARKER in raw:
            # 取数失败会被数据层格式化成带标记的文本。若直接交给 pandas，会得到 0 行，
            # 调用方就会把「数据源挂了」误报成「数据不足（少于 2 个交易日）」。
            detail = raw.split(DATA_SOURCE_ERROR_MARKER, 1)[1].strip()
            raise ValueError(detail[:300] or "数据源访问失败")

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


def _nav_frame(raw_df: pd.DataFrame | None, column: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    """把净值原始表裁剪成 date/close 两列的窗口数据（不足 2 行返回 None）。"""
    if raw_df is None or raw_df.empty:
        return None
    date_col = _find_column(raw_df, "净值日期", "date", "日期")
    close_col = _find_column(raw_df, column, "nav", "close")
    if date_col is None or close_col is None:
        return None
    picked = raw_df[[date_col, close_col]].copy()
    picked.columns = ["date", "close"]
    picked["date"] = pd.to_datetime(picked["date"], errors="coerce")
    picked["close"] = pd.to_numeric(picked["close"], errors="coerce")
    picked = picked.dropna(subset=["date", "close"])
    picked = picked[(picked["date"] >= start) & (picked["date"] <= end)]
    picked = picked.sort_values("date").reset_index(drop=True)
    if len(picked) < 2:
        return None
    return picked


def _nav_series_of(frame: pd.DataFrame | None) -> pd.Series | None:
    """把 date/close 帧转成以日期为索引的序列（供折算检测用）。"""
    if frame is None:
        return None
    return pd.Series(frame["close"].to_numpy(), index=pd.DatetimeIndex(frame["date"].to_numpy()))


def _fetch_fund_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """获取公募基金/场外基金的收益可比序列（完整历史）。

    三个必须避开的坑：

    1. **单位净值 != 收益**。分红除权日单位净值会向下跳空，直接拿单位净值算收益会把
       分红记成亏损。累计净值把分红再投计入，才是投资者真实收益口径。
    2. **份额折算之后累计净值也不可比**。份额折算会把单位净值重置为 1.0，而累计净值
       继续累计，两者比值一步跳变，此后累计净值不再与收益率可比 —— 用它算收益会把
       真实亏损算小。实测 161725 在 2017/2019/2020/2024/2026 五次折算后，同一区间
       累计净值口径 -25.91%，而含折算还原的口径约 -59.61%。判据见
       a_share_index_fund.cum_nav_is_comparable（比值单日跳变 < 5% 才算可比）。
    3. get_fund_history_nav 这个 Agent 工具取的是 tail(120) —— 只有半年，
       回测三年会静默截断成半年。所以这里用 fetch_fund_nav_series（完整历史）。

    折算不可比时退到 ETF/LOF 前复权收盘价（分红与份额折算都已还原），再退到单位净值，
    并把实际口径写进 df.attrs["price_basis"]，报告里可见。
    """
    from ifa.dataflows.a_share_index_fund import _etf_price_series, cum_nav_is_comparable
    from ifa.dataflows.a_share_public_fund import fetch_fund_nav_series

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    cum_raw = fetch_fund_nav_series(symbol, "累计净值走势")
    cum = _nav_frame(cum_raw, "累计净值", start, end)
    try:
        unit_raw = fetch_fund_nav_series(symbol, "单位净值走势")
    except Exception as exc:  # noqa: BLE001
        logger.debug("单位净值取数失败，仅用于折算检测，忽略 (%s): %s", symbol, exc)
        unit_raw = None
    unit = _nav_frame(unit_raw, "单位净值", start, end)

    if cum is not None and cum_nav_is_comparable(_nav_series_of(unit), _nav_series_of(cum)):
        cum.attrs["price_basis"] = "基金累计净值（分红再投已计入）"
        return cum

    if cum is not None:
        price_series, price_basis = _etf_price_series(symbol, start_date, end_date)
        if price_series is not None and len(price_series) >= 2:
            frame = price_series.rename("close").reset_index()
            frame.columns = ["date", "close"]
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
            if len(frame) >= 2:
                frame.attrs["price_basis"] = f"{price_basis}（原累计净值口径受份额折算影响，已改用前复权价）"
                return frame
        if unit is not None:
            unit.attrs["price_basis"] = "基金单位净值（发生过份额折算，累计净值不可比；分红未计入，收益被低估）"
            return unit
        return None

    if unit is not None:
        unit.attrs["price_basis"] = "基金单位净值（**未计分红**，收益被低估）"
        return unit
    return None


def _price_basis_label(asset_type_name: str) -> str:
    """价格序列的口径说明（进报告，避免读者误以为都是「含分红的总收益」）。"""
    if asset_type_name == "ETF":
        return "ETF 前复权收盘价（分红已还原）"
    if asset_type_name in ("PUBLIC_FUND", "OFFSHORE_FUND"):
        return "基金净值（口径见下）"
    if asset_type_name == "INDEX":
        return "指数收盘价（价格指数，**不含分红**）"
    return "收盘价"


def _fetch_price_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """获取历史价格数据，并在 df.attrs 上标注资产类型与价格口径。

    用 attrs 而不是返回元组：run_backtest 的既有测试会 monkeypatch 这个函数，
    保持「三参数 → DataFrame|None」的签名不变最省事。
    """
    from ifa.dataflows.asset_type import AssetType, detect_asset_type

    try:
        asset_type = detect_asset_type(symbol)
    except Exception:
        asset_type = AssetType.ETF

    if asset_type in (AssetType.ETF, AssetType.INDEX):
        df = _fetch_etf_index_data(symbol, start_date, end_date, asset_type)
    elif asset_type in (AssetType.PUBLIC_FUND, AssetType.OFFSHORE_FUND):
        df = _fetch_fund_data(symbol, start_date, end_date)
    else:
        # 兜底：部分 ETF 联接 / LOF 会被资产类型判定误分类成股票（实测 000834 被判为 STOCK），
        # 直接返回 None 会得到「0 个交易日」的空回测，所以再按基金净值取一次。
        df = _fetch_fund_data(symbol, start_date, end_date)

    if df is None:
        return None
    df.attrs["asset_type"] = asset_type.name
    df.attrs.setdefault("price_basis", _price_basis_label(asset_type.name))
    return df


def _find_column(df: pd.DataFrame, *candidates: str) -> str | None:
    """按候选名做「大小写不敏感 + 子串包含」的模糊查找。

    注意：这与 `ifa.dataflows.a_share_common.find_column`（精确匹配列名）语义不同，
    是刻意保留的差异——行情/净值列名在不同数据源间存在后缀差异（「收盘」vs「收盘价」），
    精确匹配会漏。不要为了「消除重复」把两者合并，那会让回测静默取不到价格列。
    """
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


#: 国债收益率取不到时退回去的无风险利率（年化 %）—— 与旧硬编码值一致，但会标注来源。
DEFAULT_RISK_FREE_PCT = 2.0
_RISK_FREE_CACHE: tuple[float, str] | None = None


def resolve_risk_free_rate() -> tuple[float, str]:
    """无风险利率（年化 %）+ 来源说明。

    与估值模块同源：中债 10 年期国债收益率。取不到时退回 2% 并在报告里标注 ——
    Sharpe 的分子对无风险利率高度敏感，来源必须可见。此前这里硬编码 2%，而同一系统的
    ERP 用的是真实国债利率，两个口径互相打架。
    """
    global _RISK_FREE_CACHE
    if _RISK_FREE_CACHE is not None:
        return _RISK_FREE_CACHE
    value: float | None = None
    try:
        from ifa.dataflows.a_share_macro import _get_bond_yield_10y

        value = _get_bond_yield_10y()
    except Exception as exc:  # noqa: BLE001
        logger.debug("无风险利率取数失败: %s", exc)
    if value is not None and 0 < value < 15:
        _RISK_FREE_CACHE = (float(value), "中债10年期国债收益率")
    else:
        _RISK_FREE_CACHE = (DEFAULT_RISK_FREE_PCT, "默认值 2%（国债收益率取数失败）")
    return _RISK_FREE_CACHE


def _holding_days(df: pd.DataFrame) -> int:
    """回测区间实际持有的自然日数（用于挑赎回费率档位）。"""
    try:
        return max(0, int((df["date"].iloc[-1] - df["date"].iloc[0]).days))
    except Exception:  # noqa: BLE001
        return 0


def _safe_resolve_fees(
    symbol: str,
    asset_type_name: str,
    holding_days: int,
    include_fees: bool,
    commission_pct: float | None,
) -> FeeAssumptions:
    """解析费用假设；任何异常都退化为「不收费 + 明确标注」，不让回测挂掉。"""
    if not include_fees:
        return FeeAssumptions(
            applies=False,
            holding_days=holding_days,
            source="disabled",
            notes=("调用方显式关闭了费用（include_fees=False），收益为价格口径的乐观值",),
        )
    try:
        return resolve_fees(symbol, asset_type_name, holding_days, commission_pct=commission_pct)
    except Exception as exc:  # noqa: BLE001
        logger.warning("费率解析失败 (%s): %s", symbol, exc)
        return FeeAssumptions(
            applies=False,
            holding_days=holding_days,
            source="error",
            notes=(f"费率解析失败（{exc}），本次未计交易成本，收益偏乐观",),
        )


def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_investment: float = 100000.0,
    *,
    include_fees: bool = True,
    commission_pct: float | None = None,
) -> BacktestResult:
    """执行**买入-持有**（一次性投资）策略的回测。

    参数:
        symbol: 基金/ETF/指数代码
        start_date: 回测起始日期 YYYY-MM-DD
        end_date: 回测结束日期 YYYY-MM-DD
        initial_investment: 初始投资金额
        include_fees: 是否计入申购费/赎回费/券商佣金（默认计入）
        commission_pct: 场内 ETF 单边券商佣金（%），None 表示用默认万 3

    返回:
        BacktestResult 包含完整的回测指标

    口径说明（这是本函数最容易读错的地方）:
        * total_return_pct / final_value 是**价格口径**（不含申赎费），与指数基准同口径，
          适合做超额收益比较；
        * net_* 字段是**投资者口径**（扣掉申购费/赎回费/佣金后真正拿到手的），
          报告里两个都给，差额即 fee_impact_pct；
        * 净值/复权价本身**已扣除**管理费与托管费，绝不能再扣一次（那是重复计费）。
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
        net_final_value=initial_investment,
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

    asset_type_name = str(df.attrs.get("asset_type") or "ETF")
    price_basis = str(df.attrs.get("price_basis") or _price_basis_label(asset_type_name))
    risk_free_pct, risk_free_source = resolve_risk_free_rate()

    # 总收益（价格口径）
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

    # Sharpe —— 无风险利率用真实 10Y 国债（取不到才退回 2%，来源进报告）
    sharpe = _calc_sharpe(daily_returns, risk_free_pct / 100)

    # 月度收益
    monthly = _calc_monthly_returns(df)

    # —— 交易成本：只有申购费/赎回费/佣金落在净值之外 ——
    holding_days = _holding_days(df)
    fees = _safe_resolve_fees(symbol, asset_type_name, holding_days, include_fees, commission_pct)
    entry_factor = 1 - fees.entry_pct / 100 if fees.applies else 1.0
    exit_factor = 1 - fees.exit_pct / 100 if fees.applies else 1.0
    invested = initial_investment * entry_factor
    gross_final = invested * final_price / initial_price
    net_final = gross_final * exit_factor
    net_total_return = (net_final / initial_investment - 1) * 100 if initial_investment else 0.0
    if years > 0 and initial_investment > 0 and net_final > 0:
        net_annualized = ((net_final / initial_investment) ** (1 / max(years, 0.01)) - 1) * 100
    else:
        net_annualized = 0.0

    # 净值曲线（持仓市值：已计入买入成本，未扣赎回费 —— 卖出费只发生在最后一天）
    step = max(1, len(df) // 120)
    sampled = df.iloc[::step]
    equity = [
        {
            "date": str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"]),
            "value": round(invested * row["close"] / initial_price, 2),
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
        price_basis=price_basis,
        risk_free_rate_pct=round(risk_free_pct, 4),
        risk_free_source=risk_free_source,
        net_final_value=round(net_final, 2),
        net_total_return_pct=round(net_total_return, 2),
        net_annualized_return_pct=round(net_annualized, 2),
        fee_impact_pct=round(total_return - net_total_return, 2),
        fee_assumptions=fees.as_dict() | {"describe": fees.describe()},
        monthly_returns=monthly,
        equity_curve=equity,
    )


def _format_cost_section(result: BacktestResult) -> list[str]:
    """「交易成本口径」小节：把价格口径与投资者口径的差额摆到明面上。"""
    if not result.fee_assumptions:
        return []
    describe = str(result.fee_assumptions.get("describe") or "")
    notes = list(result.fee_assumptions.get("notes") or [])
    lines = [
        "### 交易成本口径",
        "",
        f"- 价格口径（未计申赎费）总收益：{result.total_return_pct:+.2f}%",
        f"- 投资者口径（计费后）总收益：**{result.net_total_return_pct:+.2f}%**",
        f"- 投资者口径期末价值：¥{result.net_final_value:,.2f}",
        f"- 投资者口径年化收益：{result.net_annualized_return_pct:+.2f}%",
        f"- 费用拖累：{result.fee_impact_pct:.2f} 个百分点",
        f"- 费用假设：{describe}",
    ]
    for note in notes:
        lines.append(f"- 说明：{note}")
    lines.append("- 管理费/托管费**已包含在净值中**，未重复扣除。")
    lines.append("")
    return lines


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
        f"| 价格口径 | {result.price_basis or '—'} |",
        f"| 无风险利率 | {result.risk_free_rate_pct:.2f}%（{result.risk_free_source}） |",
        "",
    ]

    lines.extend(_format_cost_section(result))

    if result.monthly_returns:
        lines.append("### 月度收益")
        lines.append("")
        lines.append("| 月份 | 收益率 |")
        lines.append("|------|--------|")
        for m in result.monthly_returns[-12:]:  # 最近 12 个月
            lines.append(f"| {m['month']} | {m['return_pct']:+.2f}% |")

    return "\n".join(lines)
