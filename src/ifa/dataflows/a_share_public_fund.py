# ifa/dataflows/a_share_public_fund.py
"""公募基金（股票型/混合型/债券型/货币型/QDII/FOF 等）数据获取实现（基于 AkShare）。"""

from __future__ import annotations

import akshare as ak

from .a_share import (
    _call_akshare_api,
    _format_data_error,
    _format_table,
    _round_numeric_frame,
)
from .a_share_common import safe_display_symbol, safe_plain_code

# ── 1. 全部基金列表 ─────────────────────────────────────────────


def get_fund_list() -> str:
    """
    获取全部公募基金列表（代码/名称/类型）。

    返回：
        str: 基金列表 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_name_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# All Public Funds List", exc)

    if df is None or df.empty:
        return "未获取到基金列表数据。"

    # 选取核心列，避免数据过大
    preferred_cols = ["基金代码", "基金简称", "基金类型"]
    available_cols = [c for c in preferred_cols if c in df.columns]
    if not available_cols:
        available_cols = list(df.columns[:4])

    selected = df[available_cols].copy()
    # 限制行数，避免返回全部 2 万+ 基金撑爆 LLM 上下文
    total = len(selected)
    sample = selected.head(30)
    header = f"# All Public Funds List\n# Total: {total} funds (showing top 30)\n\n"
    return header + str(sample.to_csv(index=False))


# ── 2. 基金基本信息 ─────────────────────────────────────────────


def get_fund_basic_info(symbol: str) -> str:
    """
    获取基金基本信息（规模/经理/评级/成立日期等）。

    参数：
        symbol: 基金代码（如 000001）。

    返回：
        str: 基金基本信息文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_individual_basic_info_xq,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Basic Info for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的基金基本信息。"

    return f"# Fund Basic Info for {display}\n\n{df.to_csv(index=False)}"


# ── 3. 开放式基金排行 ──────────────────────────────────────────


def get_open_fund_rank(symbol: str = "") -> str:
    """
    获取开放式基金排行（多时间维度收益率）。

    参数：
        symbol: 基金类型筛选，如 "全部"、"股票型"、"混合型"、"债券型"、"指数型"、"QDII" 等。

    返回：
        str: 基金排行 CSV 数据。
    """
    filter_label = symbol if symbol else "全部"
    try:
        df = _call_akshare_api(
            ak.fund_open_fund_rank_em,
            symbol=filter_label,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Open Fund Rank ({filter_label})", exc)

    if df is None or df.empty:
        return f"未找到类型为「{filter_label}」的开放式基金排行数据。"

    # 取前 50 条避免数据过大
    output = _round_numeric_frame(df.head(50))
    header = f"# Open Fund Rank ({filter_label})\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ── 4. 基金股票持仓 ────────────────────────────────────────────


def get_fund_stock_holdings(symbol: str, date: str = "") -> str:
    """
    获取基金股票持仓明细。

    参数：
        symbol: 基金代码（如 000001）。
        date: 报告期，格式 YYYY 或 YYYY-MM-DD。为空时取最新。

    返回：
        str: 股票持仓 CSV 数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    report_date = date[:4] if date else ""

    try:
        df = _call_akshare_api(
            ak.fund_portfolio_hold_em,
            symbol=plain,
            date=report_date,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Stock Holdings for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的股票持仓数据。"

    header = f"# Fund Stock Holdings for {display} ({report_date or 'latest'})\n# Records: {len(df)}\n\n"
    # 保留前 20 行（按持仓比例排序，前 20 = 十大重仓股，最有价值）
    return header + str(df.head(20).to_csv(index=False))


# ── 5. 基金债券持仓 ────────────────────────────────────────────


def get_fund_bond_holdings(symbol: str, date: str = "") -> str:
    """
    获取基金债券持仓明细。

    参数：
        symbol: 基金代码（如 000001）。
        date: 报告期，格式 YYYY 或 YYYY-MM-DD。为空时取最新。

    返回：
        str: 债券持仓 CSV 数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    report_date = date[:4] if date else ""

    try:
        df = _call_akshare_api(
            ak.fund_portfolio_bond_hold_em,
            symbol=plain,
            date=report_date,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Bond Holdings for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的债券持仓数据。"

    header = f"# Fund Bond Holdings for {display} ({report_date or 'latest'})\n# Records: {len(df)}\n\n"
    # 保留前 20 行（前 20 = 主要债券持仓）
    return header + str(df.head(20).to_csv(index=False))


# ── 6. 行业配置 ────────────────────────────────────────────────


def get_fund_industry_allocation(symbol: str, date: str = "") -> str:
    """
    获取基金行业配置。

    参数：
        symbol: 基金代码（如 000001）。
        date: 报告期，格式 YYYY 或 YYYY-MM-DD。为空时取最新。

    返回：
        str: 行业配置 CSV 数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    report_date = date[:4] if date else ""

    try:
        df = _call_akshare_api(
            ak.fund_portfolio_industry_allocation_em,
            symbol=plain,
            date=report_date,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Industry Allocation for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的行业配置数据。"

    return _format_table(df, f"# Fund Industry Allocation for {display} ({report_date or 'latest'})", rows=30)


# ── 7. 风险分析 ────────────────────────────────────────────────


def get_fund_risk_analysis(symbol: str) -> str:
    """
    获取基金风险分析（波动率/夏普比率/最大回撤等）。

    参数：
        symbol: 基金代码（如 000001）。

    返回：
        str: 风险分析文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_individual_analysis_xq,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Risk Analysis for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的风险分析数据。"

    return f"# Fund Risk Analysis for {display}\n\n{df.to_csv(index=False)}"


# ── 8. 基金业绩 ────────────────────────────────────────────────


def get_fund_achievement(symbol: str) -> str:
    """
    获取基金业绩（年度/阶段收益 + 同类排名）。

    参数：
        symbol: 基金代码（如 000001）。

    返回：
        str: 业绩数据文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_individual_achievement_xq,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Achievement for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的业绩数据。"

    return f"# Fund Achievement for {display}\n\n{df.to_csv(index=False)}"


# ── 9. ETF 实时行情 ────────────────────────────────────────────


def get_etf_spot_data() -> str:
    """
    获取 ETF 实时行情（折价率/资金流向等）。

    返回：
        str: ETF 实时行情 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_etf_spot_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# ETF Spot Data", exc)

    if df is None or df.empty:
        return "未获取到 ETF 实时行情数据。"

    # 取前 100 条避免数据过大
    output = _round_numeric_frame(df.head(100))
    header = f"# ETF Spot Data\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ── 10. 基金历史净值 / 累计收益率 / 排名走势 ──────────────────


def get_fund_history_nav(symbol: str, indicator: str = "单位净值走势") -> str:
    """
    获取基金历史净值走势、累计收益率走势或同类排名走势。

    参数：
        symbol: 基金代码（如 000001）。
        indicator: 指标类型，可选 "单位净值走势"、"累计净值走势"、"累计收益率走势"、"同类排名走势"。

    返回：
        str: 历史数据 CSV 文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_open_fund_info_em,
            symbol=plain,
            indicator=indicator,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund {indicator} for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的「{indicator}」数据。"

    # 取最近 120 条数据避免过大
    recent = df.tail(120)
    return _format_table(recent, f"# Fund {indicator} for {display}")


# ─────────────────────────────────────────────────────────────
# Phase 2：增强接口
# ─────────────────────────────────────────────────────────────


# ── 11. 净值估算 ────────────────────────────────────────────────


def get_fund_value_estimation(symbol: str = "") -> str:
    """
    获取基金净值估算数据（盘中实时估值）。

    参数：
        symbol: 基金类型筛选，如 "全部"、"股票型"、"混合型"、"债券型"、"指数型"、"QDII" 等。

    返回：
        str: 净值估算 CSV 数据。
    """
    filter_label = symbol if symbol else "全部"
    try:
        df = _call_akshare_api(ak.fund_value_estimation_em, symbol=filter_label)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Value Estimation ({filter_label})", exc)

    if df is None or df.empty:
        return f"未找到类型为「{filter_label}」的净值估算数据。"

    # 取前 20 条
    output = _round_numeric_frame(df.head(20))
    header = f"# Fund Value Estimation ({filter_label})\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ── 12. 基金分红数据 ────────────────────────────────────────────


def get_fund_dividend(year: str = "") -> str:
    """
    获取基金分红数据。

    参数：
        year: 年份，如 "2025"。为空时取最新。

    返回：
        str: 基金分红 CSV 数据。
    """
    year_label = year if year else "latest"
    try:
        df = _call_akshare_api(ak.fund_fh_em, year=year)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Dividend Data ({year_label})", exc)

    if df is None or df.empty:
        return f"未找到 {year_label} 年的基金分红数据。"

    output = _round_numeric_frame(df.head(100))
    header = f"# Fund Dividend Data ({year_label})\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ── 13. 基金申购状态 ────────────────────────────────────────────


def get_fund_purchase_status() -> str:
    """
    获取全部基金申购/赎回状态。

    返回：
        str: 申购状态 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_purchase_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# Fund Purchase Status", exc)

    if df is None or df.empty:
        return "未获取到基金申购状态数据。"

    return _format_table(df.head(50), "# Fund Purchase Status")


# ── 14. 基金交易费率 ────────────────────────────────────────────


def get_fund_fee(symbol: str, indicator: str = "申购费率") -> str:
    """
    获取基金交易费率信息。

    参数：
        symbol: 基金代码（如 015641）。
        indicator: 费率类型，可选 "交易状态"/"申购与赎回金额"/"运作费用"/"认购费率（前端）"/"申购费率"/"赎回费率"。

    返回：
        str: 费率信息文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_fee_em,
            symbol=plain,
            indicator=indicator,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Fee for {display} ({indicator})", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的「{indicator}」数据。"

    return f"# Fund {indicator} for {display}\n\n{df.to_csv(index=False)}"


# ── 15. 指数型基金筛选 ─────────────────────────────────────────


def get_index_fund_filter(symbol: str = "", indicator: str = "") -> str:
    """
    获取指数型基金列表及筛选数据。

    参数：
        symbol: 指数分类，如 "全部"/"沪深指数"/"行业主题"/"大盘指数"/"中盘指数"/"小盘指数"。
        indicator: 跟踪方式，如 "全部"/"被动指数型"/"增强指数型"。

    返回：
        str: 指数基金列表 CSV 数据。
    """
    filter_label = symbol if symbol else "全部"
    indicator_label = indicator if indicator else "全部"
    try:
        df = _call_akshare_api(
            ak.fund_info_index_em,
            symbol=filter_label,
            indicator=indicator_label,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Index Fund Filter ({filter_label}/{indicator_label})", exc)

    if df is None or df.empty:
        return f"未找到分类为「{filter_label}」、跟踪方式为「{indicator_label}」的指数基金数据。"

    output = _round_numeric_frame(df.head(50))
    header = f"# Index Fund Filter ({filter_label}/{indicator_label})\n# Records: {len(output)}\n\n"
    return header + str(output.to_csv(index=False))


# ─────────────────────────────────────────────────────────────
# Phase 3：补充接口
# ─────────────────────────────────────────────────────────────


# ── 16. 货币基金实时数据 ──────────────────────────────────────────


def get_money_fund_daily() -> str:
    """
    获取货币基金实时数据（万份收益/7日年化等）。

    返回：
        str: 货币基金 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_money_fund_daily_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# Money Fund Daily", exc)

    if df is None or df.empty:
        return "未获取到货币基金实时数据。"

    return _format_table(df, "# Money Fund Daily", rows=50)


# ── 17. 盈利概率 ────────────────────────────────────────────────


def get_fund_profit_probability(symbol: str) -> str:
    """
    获取基金盈利概率（历史任意时点买入持有满 X 时间的盈利概率和平均收益）。

    参数：
        symbol: 基金代码（如 000001）。

    返回：
        str: 盈利概率数据文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_individual_profit_probability_xq,
            symbol=plain,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Profit Probability for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的盈利概率数据。"

    return f"# Fund Profit Probability for {display}\n\n{df.to_csv(index=False)}"


# ── 18. 资产配置比例 ────────────────────────────────────────────


def get_fund_asset_allocation(symbol: str, date: str = "") -> str:
    """
    获取基金大类资产配置比例（股票/债券/现金等）。

    参数：
        symbol: 基金代码（如 002804）。
        date: 报告期，格式 YYYYMMDD（如 20231231）。为空时取最新。

    返回：
        str: 资产配置比例文本。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    report_date = date.replace("-", "") if date else ""
    try:
        df = _call_akshare_api(
            ak.fund_individual_detail_hold_xq,
            symbol=plain,
            date=report_date,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# Fund Asset Allocation for {display}", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的资产配置数据。"

    return f"# Fund Asset Allocation for {display} ({report_date or 'latest'})\n\n{df.to_csv(index=False)}"


# ── 19. ETF 分时行情 ────────────────────────────────────────────


def get_etf_intraday(
    symbol: str,
    period: str = "5",
    start_date: str = "",
    end_date: str = "",
    adjust: str = "",
) -> str:
    """
    获取 ETF 分时行情数据（分钟级 K 线）。

    参数：
        symbol: ETF 代码（如 513500）。
        period: K 线周期，可选 "1"/"5"/"15"/"30"/"60"。
        start_date: 开始日期时间，格式 "YYYY-MM-DD HH:MM:SS"。
        end_date: 结束日期时间，格式 "YYYY-MM-DD HH:MM:SS"。
        adjust: 复权方式，"" 不复权/"qfq" 前复权/"hfq" 后复权。

    返回：
        str: 分时行情 CSV 数据。
    """
    display = safe_display_symbol(symbol)
    plain = safe_plain_code(symbol)
    try:
        df = _call_akshare_api(
            ak.fund_etf_hist_min_em,
            symbol=plain,
            period=period,
            start_date=start_date or "1979-09-01 09:32:00",
            end_date=end_date or "2222-01-01 09:32:00",
            adjust=adjust,
        )
    except Exception as exc:  # noqa: BLE001
        return _format_data_error(f"# ETF Intraday for {display} ({period}min)", exc)

    if df is None or df.empty:
        return f"未找到 {display} 的 {period} 分钟分时数据。"

    # 取最近 240 条
    recent = df.tail(240)
    return _format_table(recent, f"# ETF Intraday for {display} ({period}min)")


# ── 20. LOF 实时行情 ────────────────────────────────────────────


def get_lof_spot_data() -> str:
    """
    获取 LOF 基金实时行情数据。

    返回：
        str: LOF 实时行情 CSV 数据。
    """
    try:
        df = _call_akshare_api(ak.fund_lof_spot_em)
    except Exception as exc:  # noqa: BLE001
        return _format_data_error("# LOF Spot Data", exc)

    if df is None or df.empty:
        return "未获取到 LOF 实时行情数据。"

    return _format_table(df, "# LOF Spot Data", rows=50)
