# ifa/dataflows/a_share_macro.py
"""宏观经济、市场情绪、行业估值数据获取实现（基于 AkShare）。"""
from __future__ import annotations

from datetime import datetime

import akshare as ak

from .a_share import (
    _call_akshare_api,
    _format_data_error,
    _round_numeric_frame,
)

# ---------------------------------------------------------------------------
#  P0 — 宏观经济指标映射
# ---------------------------------------------------------------------------

_MACRO_INDICATOR_MAP: dict[str, tuple[callable, str]] = {
    "CPI": (lambda: ak.macro_china_cpi_yearly, "China CPI Year-on-Year"),
    "PPI": (lambda: ak.macro_china_ppi_yearly, "China PPI Year-on-Year"),
    "PMI": (lambda: ak.macro_china_pmi_yearly, "China PMI"),
    "GDP": (lambda: ak.macro_china_gdp_yearly, "China GDP"),
    "LPR": (lambda: ak.macro_china_lpr, "China LPR (Loan Prime Rate)"),
    "SHIBOR": (lambda: ak.macro_china_shibor_all, "China SHIBOR (All Tenors)"),
    "MONEY_SUPPLY": (lambda: ak.macro_china_money_supply, "China Money Supply (M0/M1/M2)"),
}

# ---------------------------------------------------------------------------
#  P1 — 北向资金渠道映射
# ---------------------------------------------------------------------------

_NORTH_FLOW_SYMBOLS = ("沪股通", "深股通", "北向资金")

# ---------------------------------------------------------------------------
#  P2 — 市场估值指标映射
# ---------------------------------------------------------------------------

_VALUATION_INDICATOR_MAP: dict[str, tuple[callable, str, dict]] = {
    "上证PE": (lambda: ak.stock_market_pe_lg, "Shanghai Market PE", {"symbol": "上证"}),
    "深证PE": (lambda: ak.stock_market_pe_lg, "Shenzhen Market PE", {"symbol": "深证"}),
    "上证PB": (lambda: ak.stock_market_pb_lg, "Shanghai Market PB", {"symbol": "上证"}),
    "深证PB": (lambda: ak.stock_market_pb_lg, "Shenzhen Market PB", {"symbol": "深证"}),
    "沪深300PE": (lambda: ak.stock_index_pe_lg, "CSI 300 PE", {"symbol": "沪深300"}),
    "上证50PE": (lambda: ak.stock_index_pe_lg, "SSE 50 PE", {"symbol": "上证50"}),
    "中证500PE": (lambda: ak.stock_index_pe_lg, "CSI 500 PE", {"symbol": "中证500"}),
    "创业板PE": (lambda: ak.stock_index_pe_lg, "ChiNext PE", {"symbol": "创业板"}),
}

# ---------------------------------------------------------------------------
#  P0 — 宏观经济指标
# ---------------------------------------------------------------------------


def get_macro_indicator(indicator: str = "GDP") -> str:
    """
    获取宏观经济指标数据。

    参数：
        indicator: 指标类型，可选 CPI/PPI/PMI/GDP/LPR/SHIBOR/MONEY_SUPPLY。

    返回：
        str: 宏观指标 CSV 数据。
    """
    key = indicator.upper().strip()
    if key not in _MACRO_INDICATOR_MAP:
        available = ", ".join(_MACRO_INDICATOR_MAP.keys())
        return f"不支持的宏观指标「{indicator}」。可选值: {available}"

    factory, title = _MACRO_INDICATOR_MAP[key]
    try:
        api_func = factory()
        df = _call_akshare_api(api_func)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# {title}", exc)

    if df is None or df.empty:
        return f"未获取到 {title} 数据。"

    recent = df.tail(60)
    output = _round_numeric_frame(recent)
    header = f"# {title}\n# Records: {len(output)}\n\n"
    return header + output.to_csv(index=False)


# ---------------------------------------------------------------------------
#  P1 — 北向资金
# ---------------------------------------------------------------------------


def get_north_flow(symbol: str = "北向资金") -> str:
    """
    获取北向资金（沪股通/深股通）历史净流入数据。

    参数：
        symbol: 渠道类型，可选 沪股通/深股通/北向资金。

    返回：
        str: 北向资金 CSV 数据。
    """
    label = symbol if symbol in _NORTH_FLOW_SYMBOLS else "北向资金"
    title = f"Northbound Capital Flow ({label})"
    try:
        df = _call_akshare_api(ak.stock_hsgt_hist_em, symbol=label)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# {title}", exc)

    if df is None or df.empty:
        return f"未获取到 {title} 数据。"

    # 精选关键列，去除 NaN 较多的列
    preferred_cols = [
        "日期", "当日成交净买额", "买入成交额", "卖出成交额",
        "历史累计净买额", "当日资金流入",
    ]
    available_cols = [c for c in preferred_cols if c in df.columns]
    if not available_cols:
        available_cols = list(df.columns[:6])

    recent = df[available_cols].tail(60)
    output = _round_numeric_frame(recent)
    header = f"# {title}\n# Records: {len(output)}\n\n"
    return header + output.to_csv(index=False)


# ---------------------------------------------------------------------------
#  P1 — 大盘资金流向
# ---------------------------------------------------------------------------


def get_market_fund_flow() -> str:
    """
    获取大盘资金流向数据（主力/超大单/大单/中单/小单净流入）。

    返回：
        str: 大盘资金流向 CSV 数据。
    """
    title = "Market Fund Flow Overview"
    try:
        df = _call_akshare_api(ak.stock_market_fund_flow)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# {title}", exc)

    if df is None or df.empty:
        return "未获取到大盘资金流向数据。"

    # 精选关键列
    preferred_cols = [
        "日期", "上证-收盘价", "上证-涨跌幅",
        "主力净流入-净额", "主力净流入-净占比",
        "超大单净流入-净额", "大单净流入-净额",
        "小单净流入-净额",
    ]
    available_cols = [c for c in preferred_cols if c in df.columns]
    if not available_cols:
        available_cols = list(df.columns[:8])

    recent = df[available_cols].tail(60)
    output = _round_numeric_frame(recent)
    header = f"# {title}\n# Records: {len(output)}\n\n"
    return header + output.to_csv(index=False)


# ---------------------------------------------------------------------------
#  P1 — 融资融券
# ---------------------------------------------------------------------------


def get_margin_data() -> str:
    """
    获取上海市场融资融券余额数据。

    返回：
        str: 融资融券 CSV 数据。
    """
    title = "Margin Trading Data (SSE)"
    try:
        df = _call_akshare_api(ak.macro_china_market_margin_sh)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# {title}", exc)

    if df is None or df.empty:
        return "未获取到融资融券数据。"

    recent = df.tail(60)
    output = _round_numeric_frame(recent)
    header = f"# {title}\n# Records: {len(output)}\n\n"
    return header + output.to_csv(index=False)


# ---------------------------------------------------------------------------
#  P2 — 板块资金流向排名
# ---------------------------------------------------------------------------


def get_sector_fund_flow(
    indicator: str = "今日",
    sector_type: str = "行业资金流",
) -> str:
    """
    获取板块资金流向排名（按行业/概念/地区分类）。

    参数：
        indicator: 时间维度，可选 今日/3日/5日/10日。
        sector_type: 板块类型，可选 行业资金流/概念资金流/地区资金流。

    返回：
        str: 板块资金流向排名 CSV 数据。
    """
    title = f"Sector Fund Flow Rank ({indicator}, {sector_type})"
    try:
        df = _call_akshare_api(
            ak.stock_sector_fund_flow_rank,
            indicator=indicator,
            sector_type=sector_type,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# {title}", exc)

    if df is None or df.empty:
        return f"未获取到 {title} 数据。"

    output = _round_numeric_frame(df.head(50))
    header = f"# {title}\n# Records: {len(output)}\n\n"
    return header + output.to_csv(index=False)


# ---------------------------------------------------------------------------
#  P2 — 市场估值（PE/PB）
# ---------------------------------------------------------------------------


def get_market_valuation(indicator: str = "上证PE") -> str:
    """
    获取市场整体或主要指数的估值数据（PE/PB）。

    参数：
        indicator: 估值指标，可选 上证PE/深证PE/上证PB/深证PB/沪深300PE/上证50PE/中证500PE/创业板PE。

    返回：
        str: 市场估值 CSV 数据。
    """
    key = indicator.strip()
    if key not in _VALUATION_INDICATOR_MAP:
        available = ", ".join(_VALUATION_INDICATOR_MAP.keys())
        return f"不支持的估值指标「{indicator}」。可选值: {available}"

    factory, title, kwargs = _VALUATION_INDICATOR_MAP[key]
    try:
        api_func = factory()
        df = _call_akshare_api(api_func, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# {title}", exc)

    if df is None or df.empty:
        return f"未获取到 {title} 数据。"

    # 保留日期和估值相关列
    preferred_cols = [c for c in df.columns if any(
        kw in c for kw in ("日期", "指数", "市盈率", "市净率", "平均")
    )]
    if not preferred_cols:
        preferred_cols = list(df.columns[:5])

    recent = df[preferred_cols].tail(60)
    output = _round_numeric_frame(recent)
    header = f"# {title}\n# Records: {len(output)}\n\n"
    return header + output.to_csv(index=False)


# ---------------------------------------------------------------------------
#  指数综合估值分析
# ---------------------------------------------------------------------------

_INDEX_VALUATION_NAMES = frozenset({
    "沪深300", "上证50", "中证500", "中证1000", "上证红利", "深证100",
})

# 近 10 年约 2500 个交易日
_LOOKBACK_ROWS = 2500


def _valuation_label(pct: float) -> str:
    """根据百分位返回估值判断标签。"""
    if pct < 20:
        return "严重低估"
    if pct < 30:
        return "低估"
    if pct < 40:
        return "偏低"
    if pct < 60:
        return "合理"
    if pct < 70:
        return "偏高"
    if pct < 80:
        return "高估"
    return "严重高估"


def _compute_metric(series, label: str) -> str:
    """
    从 pandas Series 计算当前值、均值、百分位、估值判断。

    返回：
        str: Markdown 表格行。
    """
    if series.dropna().empty:
        return f"| {label} | 暂无数据 | - | - | - |"

    current = series.iloc[-1]
    mean_val = series.mean()
    pct = series.rank(pct=True).iloc[-1] * 100

    return (
        f"| {label} "
        f"| {current:.2f} "
        f"| {mean_val:.2f} "
        f"| {pct:.1f}% "
        f"| {_valuation_label(pct)} |"
    )


def get_index_valuation(index_name: str = "沪深300") -> str:
    """
    获取指数综合估值分析报告，包含 PE/PB/盈利率/股息率及历史百分位。

    参数：
        index_name: 指数名称，可选 沪深300/上证50/中证500/中证1000/上证红利/深证100。

    返回：
        str: 指数估值分析报告（Markdown 表格）。
    """
    name = index_name.strip()
    if name not in _INDEX_VALUATION_NAMES:
        available = ", ".join(sorted(_INDEX_VALUATION_NAMES))
        return f"不支持的指数「{index_name}」。可选值: {available}"

    # ── 拉取 PE 数据 ──
    pe_rows: list[str] = []
    try:
        pe_df = _call_akshare_api(ak.stock_index_pe_lg, symbol=name)
        if pe_df is not None and not pe_df.empty:
            pe_recent = pe_df.tail(_LOOKBACK_ROWS)
            date_str = str(pe_recent["日期"].iloc[-1])[:10]
            pe_rows.append(_compute_metric(pe_recent["滚动市盈率"], "滚动市盈率(PE-TTM)"))
            pe_rows.append(_compute_metric(pe_recent["静态市盈率"], "静态市盈率"))
            # 盈利率 = 1/PE × 100
            ey = 1 / pe_recent["滚动市盈率"] * 100
            pe_rows.append(_compute_metric(ey, "盈利率(EY=1/PE)"))
    except Exception:  # noqa: BLE001
        date_str = "N/A"

    # ── 拉取 PB 数据 ──
    pb_rows: list[str] = []
    try:
        pb_df = _call_akshare_api(ak.stock_index_pb_lg, symbol=name)
        if pb_df is not None and not pb_df.empty:
            pb_recent = pb_df.tail(_LOOKBACK_ROWS)
            pb_rows.append(_compute_metric(pb_recent["市净率"], "市净率(PB)"))
    except Exception:  # noqa: BLE001
        pass

    # ── 拉取 A 股股息率（市场参考） ──
    div_rows: list[str] = []
    try:
        div_df = _call_akshare_api(ak.stock_a_gxl_lg, symbol="上证A股")
        if div_df is not None and not div_df.empty:
            div_recent = div_df.tail(_LOOKBACK_ROWS)
            div_rows.append(_compute_metric(div_recent["股息率"], "A股股息率(参考)"))
    except Exception:  # noqa: BLE001
        pass

    if not pe_rows and not pb_rows:
        return f"未获取到「{name}」的估值数据。"

    # ── 汇总报告 ──
    lines = [
        f"# Index Valuation Analysis: {name} ({date_str})",
        "",
        "## 当前估值指标",
        "| 指标 | 当前值 | 近10年均值 | 历史百分位 | 估值判断 |",
        "|------|-------|-----------|-----------|---------|",
    ]
    lines.extend(pe_rows)
    lines.extend(pb_rows)
    lines.extend(div_rows)
    lines.extend([
        "",
        "## 估值百分位说明",
        f"- 百分位基于近10年(约{_LOOKBACK_ROWS}个交易日)数据计算",
        "- <30% 低估 | 30%-70% 合理 | >70% 高估",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  三种指数估值分析方法
# ---------------------------------------------------------------------------

# 每个指数适用的估值方法
_INDEX_METHODS: dict[str, dict[str, bool]] = {
    "沪深300": {"ey": True, "bogle_pe": True, "bogle_pb": True},
    "上证50": {"ey": True, "bogle_pe": True, "bogle_pb": True},
    "中证500": {"ey": False, "bogle_pe": True, "bogle_pb": True},
    "中证1000": {"ey": False, "bogle_pe": True, "bogle_pb": True},
    "上证红利": {"ey": True, "bogle_pe": True, "bogle_pb": True},
    "深证100": {"ey": True, "bogle_pe": True, "bogle_pb": True},
}

# 均值回归假设年限
_MEAN_REVERSION_YEARS = 3


def _get_bond_yield_10y() -> float | None:
    """获取最新的 10 年期国债收益率（百分比）。"""
    try:
        today = datetime.now().strftime("%Y%m%d")
        # 仅取最近 3 个月数据，避免大批量请求超时
        from datetime import timedelta  # noqa: E402

        three_months_ago = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        df = _call_akshare_api(
            ak.bond_china_yield, start_date=three_months_ago, end_date=today
        )
        gov = df[df["曲线名称"] == "中债国债收益率曲线"]
        if gov.empty:
            return None
        return float(gov["10年"].iloc[-1])
    except Exception:  # noqa: BLE001
        return None


def _calc_ey_signal(pe_ttm: float, bond_yield: float) -> list[str]:
    """
    盈利收益率法：EY = 1/PE × 100%。

    判断标准：
      EY > 国债收益率 × 2 → 买入
      EY < 国债收益率     → 卖出
      中间                 → 持有
    """
    ey = 1 / pe_ttm * 100 if pe_ttm > 0 else 0
    threshold_buy = bond_yield * 2
    threshold_sell = bond_yield

    if ey > threshold_buy:
        signal = "**买入（低估）**"
    elif ey < threshold_sell:
        signal = "**卖出（高估）**"
    else:
        signal = "**持有（合理）**"

    return [
        "## 方法一：盈利收益率法",
        "",
        "| 项目 | 数值 |",
        "|------|------|",
        f"| 盈利收益率(EY) | {ey:.2f}% |",
        f"| 10年期国债收益率 | {bond_yield:.2f}% |",
        f"| 国债收益率 × 2（买入线） | {threshold_buy:.2f}% |",
        f"| 国债收益率 × 1（卖出线） | {threshold_sell:.2f}% |",
        f"| **投资信号** | {signal} |",
    ]


def _calc_bogle_pe_signal(
    pe_ttm: float,
    pe_series: pd.Series,  # noqa: F821
    div_yield: float | None,
) -> list[str]:
    """
    博格公式（市盈率）：预期年化收益率 = 股息率 + 盈利增长率 + PE 变化率。

    - 股息率：来自市场数据
    - 盈利增长率：近 5 年 EPS 复合增长率（EPS = 指数点位 / PE）
    - PE 变化率：(中位数PE / 当前PE)^(1/N) - 1，N=3 年均值回归
    """
    N = _MEAN_REVERSION_YEARS

    # PE 均值回归贡献
    pe_median = pe_series.median()
    pe_change = (pe_median / pe_ttm) ** (1 / N) - 1 if pe_ttm > 0 else 0

    # EPS 增长率：从指数点位/PE 推算近 5 年复合增长
    eps_growth = 0.0
    eps_growth_label = "暂无数据"

    if len(pe_series) >= 1260:  # 约 5 年
        eps_now = 1 / pe_series.iloc[-1]  # 归一化 EPS
        eps_5y_ago = 1 / pe_series.iloc[-1260]
        if eps_5y_ago > 0 and eps_now > 0:
            eps_growth = (eps_now / eps_5y_ago) ** (1 / 5) - 1
            eps_growth_label = f"{eps_growth * 100:.2f}%"

    # 股息率
    div_label = f"{div_yield:.2f}%" if div_yield is not None else "暂无数据"
    div_val = div_yield / 100 if div_yield else 0

    expected = div_val + eps_growth + pe_change

    return [
        "## 方法二：博格公式（市盈率）",
        "",
        "| 项目 | 数值 |",
        "|------|------|",
        f"| 股息率(参考) | {div_label} |",
        f"| 近5年 EPS 年化增长率 | {eps_growth_label} |",
        f"| PE 中位数（10年） | {pe_median:.2f} |",
        f"| PE 均值回归贡献（{N}年） | {pe_change * 100:+.2f}% |",
        f"| **预期年化收益率** | **{expected * 100:.2f}%** |",
    ]


def _calc_bogle_pb_signal(
    pb: float,
    pe_ttm: float,
    pb_series: pd.Series,  # noqa: F821
) -> list[str]:
    """
    博格公式（市净率）：预期年化收益率 ≈ ROE + PB 变化率。

    - ROE ≈ PB / PE
    - PB 变化率 = (中位数PB / 当前PB)^(1/N) - 1，N=3
    """
    N = _MEAN_REVERSION_YEARS

    # ROE 近似
    roe = pb / pe_ttm if pe_ttm > 0 else 0

    # PB 均值回归贡献
    pb_median = pb_series.median()
    pb_change = (pb_median / pb) ** (1 / N) - 1 if pb > 0 else 0

    expected = roe + pb_change

    return [
        "## 方法三：博格公式（市净率）",
        "",
        "| 项目 | 数值 |",
        "|------|------|",
        f"| 近似 ROE（=PB/PE） | {roe * 100:.2f}% |",
        f"| PB 中位数（10年） | {pb_median:.2f} |",
        f"| PB 均值回归贡献（{N}年） | {pb_change * 100:+.2f}% |",
        f"| **预期年化收益率** | **{expected * 100:.2f}%** |",
    ]


def get_valuation_signal(index_name: str = "沪深300") -> str:
    """
    获取指数估值信号报告，使用三种方法（盈利收益率法、博格公式PE/PB）分析。

    参数：
        index_name: 指数名称，可选 沪深300/上证50/中证500/中证1000/上证红利/深证100。

    返回：
        str: 估值信号分析报告。
    """
    name = index_name.strip()
    if name not in _INDEX_METHODS:
        available = ", ".join(sorted(_INDEX_METHODS.keys()))
        return f"不支持的指数「{index_name}」。可选值: {available}"

    methods = _INDEX_METHODS[name]

    # ── 拉取 PE 数据 ──
    pe_ttm = 0.0
    date_str = "N/A"
    pe_series = None
    try:
        pe_df = _call_akshare_api(ak.stock_index_pe_lg, symbol=name)
        if pe_df is not None and not pe_df.empty:
            pe_recent = pe_df.tail(_LOOKBACK_ROWS)
            date_str = str(pe_recent["日期"].iloc[-1])[:10]
            pe_ttm = float(pe_recent["滚动市盈率"].iloc[-1])
            pe_series = pe_recent["滚动市盈率"]
    except Exception:  # noqa: BLE001
        pass

    # ── 拉取 PB 数据 ──
    pb = 0.0
    pb_series = None
    try:
        pb_df = _call_akshare_api(ak.stock_index_pb_lg, symbol=name)
        if pb_df is not None and not pb_df.empty:
            pb_recent = pb_df.tail(_LOOKBACK_ROWS)
            pb = float(pb_recent["市净率"].iloc[-1])
            pb_series = pb_recent["市净率"]
    except Exception:  # noqa: BLE001
        pass

    # ── 10 年期国债收益率 ──
    bond_yield = _get_bond_yield_10y()

    # ── 股息率（市场参考） ──
    div_yield = None
    try:
        div_df = _call_akshare_api(ak.stock_a_gxl_lg, symbol="上证A股")
        if div_df is not None and not div_df.empty:
            div_yield = float(div_df["股息率"].iloc[-1])
    except Exception:  # noqa: BLE001
        pass

    if pe_ttm <= 0 and pb <= 0:
        return f"未获取到「{name}」的估值数据。"

    # ── 汇总报告 ──
    roe_approx = pb / pe_ttm * 100 if pe_ttm > 0 else 0
    bond_label = f"{bond_yield:.2f}%" if bond_yield else "暂无数据"
    div_label = f"{div_yield:.2f}%" if div_yield else "暂无数据"

    lines = [
        f"# Valuation Signal Report: {name} ({date_str})",
        "",
        "## 指数概况",
        "",
        "| 项目 | 数值 |",
        "|------|------|",
        f"| 当前 PE-TTM | {pe_ttm:.2f} |",
        f"| 当前 PB | {pb:.2f} |",
        f"| 近似 ROE | {roe_approx:.2f}% |",
        f"| 10年期国债收益率 | {bond_label} |",
        f"| A股股息率(参考) | {div_label} |",
    ]

    # ── 方法一：盈利收益率法 ──
    if methods["ey"]:
        if bond_yield and pe_ttm > 0:
            lines.append("")
            lines.extend(_calc_ey_signal(pe_ttm, bond_yield))
        else:
            lines += ["", "## 方法一：盈利收益率法", "", "数据不足，无法计算。"]

    # ── 方法二：博格公式（PE） ──
    if methods["bogle_pe"] and pe_ttm > 0 and pe_series is not None:
        lines.append("")
        lines.extend(_calc_bogle_pe_signal(pe_ttm, pe_series, div_yield))

    # ── 方法三：博格公式（PB） ──
    if methods["bogle_pb"] and pb > 0 and pe_ttm > 0 and pb_series is not None:
        lines.append("")
        lines.extend(_calc_bogle_pb_signal(pb, pe_ttm, pb_series))

    # ── 综合判断 ──
    applicable = []
    if methods["ey"] and bond_yield and pe_ttm > 0:
        ey = 1 / pe_ttm * 100
        if ey > bond_yield * 2:
            applicable.append("盈利收益率法信号：买入（低估）")
        elif ey < bond_yield:
            applicable.append("盈利收益率法信号：卖出（高估）")
        else:
            applicable.append("盈利收益率法信号：持有（合理）")

    lines += ["", "## 综合判断"]
    if applicable:
        lines.extend(f"- {s}" for s in applicable)
    else:
        lines.append("- 数据不足，无法生成综合判断。")

    lines.append("")
    lines.append("---")
    lines.append("*注：盈利收益率法适用于盈利稳定的宽基指数（沪深300/上证50/红利等）；"
                 "博格公式PE版适用于大部分指数；博格公式PB版适用于资产驱动型指数。*")

    return "\n".join(lines)
