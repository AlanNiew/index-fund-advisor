"""公募基金数据层测试 —— 格式化、空值降级、异常降级（全部 mock，不触网）。

补的是覆盖率盲区：a_share_public_fund.py 此前仅 11% 覆盖，而它是全部基金结论的
输入源。此前已发生过估值 NaN、股息率语义、历史净值截断这类数据解析问题。

三个维度覆盖每个函数：
  1. 正常返回 → 标题 + 数据行都在
  2. 空 DataFrame → 返回「未找到/未获取」提示而非空串
  3. akshare 抛异常 → 返回错误文本而非把异常抛给上层 Agent
"""

import pandas as pd
import pytest

import ifa.dataflows.a_share_public_fund as pf

# 覆盖所有分支需要的列：编号、名称、类型（用于 preferred_cols）、数值列（用于四舍五入）
_SAMPLE = pd.DataFrame(
    {
        "基金代码": ["510300", "159919"],
        "基金简称": ["沪深300ETF", "沪深300ETF易方达"],
        "基金类型": ["指数型", "指数型"],
        "单位净值": [4.123456, 3.987654],
    }
)


def _patch(monkeypatch, *, value=None, exc=None):
    """替换模块内的取数函数；exc 优先于 value。

    同时替换 _fetch_etf_daily_row：get_fund_basic_info 对 ETF 代码走的是场内
    行情表而非蛋卷，若不替换就会真的触网。替换件必须复刻真实契约——查不到
    返回 None（而不是空 DataFrame），否则空值分支测不到。
    """

    def fake(*args, **kwargs):
        if exc is not None:
            raise exc
        return value

    def fake_row(plain):
        if exc is not None:
            raise exc
        if value is None or not isinstance(value, pd.DataFrame) or value.empty:
            return None
        return value

    monkeypatch.setattr(pf, "_call_akshare_api", fake)
    monkeypatch.setattr(pf, "_fetch_etf_daily_row", fake_row)


# (id, 函数, 位置参数, 关键字参数, 标题片段, 空值提示片段)
_CASES = [
    ("fund_list", pf.get_fund_list, (), {}, "# All Public Funds List", "未获取到基金列表数据。"),
    # 510300 是场内 ETF：这条用例走的是场内行情表分支，空值提示也随之不同
    ("fund_basic_info", pf.get_fund_basic_info, ("510300",), {}, "# Fund Basic Info for", "的 ETF 行情记录"),
    ("open_fund_rank", pf.get_open_fund_rank, ("全部",), {}, "# Open Fund Rank (全部)", "的开放式基金排行数据。"),
    (
        "fund_stock_holdings",
        pf.get_fund_stock_holdings,
        ("510300",),
        {},
        "# Fund Stock Holdings for",
        "的股票持仓数据。",
    ),
    ("fund_bond_holdings", pf.get_fund_bond_holdings, ("510300",), {}, "# Fund Bond Holdings for", "的债券持仓数据。"),
    (
        "fund_industry_allocation",
        pf.get_fund_industry_allocation,
        ("510300",),
        {},
        "# Fund Industry Allocation for",
        "的行业配置数据。",
    ),
    ("fund_risk_analysis", pf.get_fund_risk_analysis, ("510300",), {}, "# Fund Risk Analysis for", "的风险分析数据。"),
    ("fund_achievement", pf.get_fund_achievement, ("510300",), {}, "# Fund Achievement for", "的业绩数据。"),
    ("etf_spot_data", pf.get_etf_spot_data, (), {}, "# ETF Spot Data", "未获取到 ETF 实时行情数据。"),
    ("fund_history_nav", pf.get_fund_history_nav, ("510300",), {}, "# Fund 单位净值走势 for", "数据。"),
    (
        "fund_value_estimation",
        pf.get_fund_value_estimation,
        ("全部",),
        {},
        "# Fund Value Estimation (全部)",
        "的净值估算数据。",
    ),
    ("fund_dividend", pf.get_fund_dividend, ("2024",), {}, "# Fund Dividend Data (2024)", "年的基金分红数据。"),
    ("fund_purchase_status", pf.get_fund_purchase_status, (), {}, "# Fund Purchase Status", "未获取到基金申购状态数据。"),
    ("fund_fee", pf.get_fund_fee, ("510300",), {"indicator": "申购费率"}, "# Fund 申购费率 for", "数据。"),
    ("index_fund_filter", pf.get_index_fund_filter, (), {}, "# Index Fund Filter (全部/全部)", "的指数基金数据。"),
    ("money_fund_daily", pf.get_money_fund_daily, (), {}, "# Money Fund Daily", "未获取到货币基金实时数据。"),
    (
        "fund_profit_probability",
        pf.get_fund_profit_probability,
        ("510300",),
        {},
        "# Fund Profit Probability for",
        "的盈利概率数据。",
    ),
    (
        "fund_asset_allocation",
        pf.get_fund_asset_allocation,
        ("510300",),
        {},
        "# Fund Asset Allocation for",
        "的资产配置数据。",
    ),
    ("etf_intraday", pf.get_etf_intraday, ("510300",), {"period": "5"}, "# ETF Intraday for", "分钟分时数据。"),
    ("lof_spot_data", pf.get_lof_spot_data, (), {}, "# LOF Spot Data", "未获取到 LOF 实时行情数据。"),
]
_IDS = [c[0] for c in _CASES]


@pytest.mark.parametrize("_id,func,args,kwargs,title_frag,_empty_frag", _CASES, ids=_IDS)
class TestNormalPath:
    def test_returns_title_and_data(self, monkeypatch, _id, func, args, kwargs, title_frag, _empty_frag):
        _patch(monkeypatch, value=_SAMPLE.copy())
        out = func(*args, **kwargs)
        assert isinstance(out, str)
        assert title_frag in out
        assert "510300" in out  # 数据行确实被渲染


@pytest.mark.parametrize("_id,func,args,kwargs,_title_frag,empty_frag", _CASES, ids=_IDS)
class TestEmptyDataFrame:
    def test_returns_explicit_not_found_message(self, monkeypatch, _id, func, args, kwargs, _title_frag, empty_frag):
        _patch(monkeypatch, value=pd.DataFrame())
        out = func(*args, **kwargs)
        assert isinstance(out, str)
        assert out.strip(), "空数据不应返回空字符串"
        assert empty_frag in out


@pytest.mark.parametrize("_id,func,args,kwargs,_title_frag,_empty_frag", _CASES, ids=_IDS)
class TestSourceFailure:
    def test_degrades_instead_of_raising(self, monkeypatch, _id, func, args, kwargs, _title_frag, _empty_frag):
        _patch(monkeypatch, exc=RuntimeError("模拟网络失败"))
        out = func(*args, **kwargs)
        assert isinstance(out, str)
        assert "数据源访问失败" in out
        assert "RuntimeError" in out
        assert "模拟网络失败" in out

    def test_none_return_is_treated_as_empty(self, monkeypatch, _id, func, args, kwargs, _title_frag, _empty_frag):
        """_call_akshare_api 返回 None（部分 akshare 接口会这样）不能触发 AttributeError。"""
        _patch(monkeypatch, value=None)
        out = func(*args, **kwargs)
        assert isinstance(out, str)
        assert out.strip()


class TestFundListSpecifics:
    """get_fund_list 的列选择与行数上限逻辑。"""

    def test_prefers_known_columns(self, monkeypatch):
        df = pd.DataFrame(_SAMPLE)
        df["多余列"] = ["x", "y"]
        _patch(monkeypatch, value=df)
        out = pf.get_fund_list()
        assert "多余列" not in out  # preferred_cols 命中时只保留 3 列

    def test_falls_back_to_first_four_columns(self, monkeypatch):
        """没有 preferred_cols 时退化为前 4 列，而不是返回空表。"""
        df = pd.DataFrame({f"列{i}": ["a", "b"] for i in range(6)})
        _patch(monkeypatch, value=df)
        out = pf.get_fund_list()
        assert "# Total: 2 funds (showing top 30)" in out
        assert "列3" in out
        assert "列4" not in out

    def test_caps_rows_at_30(self, monkeypatch):
        """超过 30 只时必须截断，否则会撑爆 LLM 上下文。"""
        df = pd.DataFrame({"基金代码": [f"{i:06d}" for i in range(200)]})
        _patch(monkeypatch, value=df)
        out = pf.get_fund_list()
        assert "# Total: 200 funds (showing top 30)" in out
        assert "000029" in out
        assert "000030" not in out


class TestHistoryNavSpecifics:
    """get_fund_history_nav 的 tail(120) 截断 —— 这是评级验证器只支持 ETF 的根因。"""

    def test_keeps_only_last_120_rows(self, monkeypatch):
        """300 行 → tail(120) 取第 180~299 行，_format_table 再 head(10) 取其中前 10 行。

        即输出应含第 180 行（净值 1180），且完全不含第 0 行（净值 1000）——
        若没做 tail(120)，head(10) 会显示 1000~1009。
        """
        df = pd.DataFrame(
            {
                "净值日期": [f"2024-{(i % 12) + 1:02d}-01" for i in range(300)],
                "单位净值": [1000 + i for i in range(300)],
            }
        )
        _patch(monkeypatch, value=df)
        out = pf.get_fund_history_nav("510300")
        assert "1180" in out  # tail(120) 后的首行
        assert "1000" not in out  # 未截断时会出现的首行

    def test_passes_plain_code_and_indicator(self, monkeypatch):
        captured = {}

        def fake(func, *args, **kwargs):
            captured.update(kwargs)
            return _SAMPLE.copy()

        monkeypatch.setattr(pf, "_call_akshare_api", fake)
        pf.get_fund_history_nav("510300.SH", indicator="累计净值走势")
        assert captured["symbol"] == "510300"
        assert captured["indicator"] == "累计净值走势"


class TestReportDateHandling:
    """持仓/配置接口的日期参数传递。"""

    def test_stock_holdings_truncates_date_to_year(self, monkeypatch):
        captured = {}

        def fake(func, *args, **kwargs):
            captured.update(kwargs)
            return _SAMPLE.copy()

        monkeypatch.setattr(pf, "_call_akshare_api", fake)
        pf.get_fund_stock_holdings("510300", date="2024-06-30")
        assert captured["date"] == "2024"

    def test_asset_allocation_strips_dashes(self, monkeypatch):
        captured = {}

        def fake(func, *args, **kwargs):
            captured.update(kwargs)
            return _SAMPLE.copy()

        monkeypatch.setattr(pf, "_call_akshare_api", fake)
        pf.get_fund_asset_allocation("510300", date="2024-06-30")
        assert captured["date"] == "20240630"


class TestFundBasicInfoRouting:
    """ETF 与场外基金走不同数据源。

    蛋卷（fund_individual_basic_info_xq）只有场外基金库：对 510300 这类场内
    ETF 直接返回无 data 键的响应 → KeyError: 'data'。故 ETF 必须走场内行情表。
    """

    def test_etf_routes_to_quote_table_not_danjuan(self, monkeypatch):
        calls = {"row": [], "ak": []}

        def fake_row(plain):
            calls["row"].append(plain)
            return _SAMPLE.copy()

        def fake_ak(func, *args, **kwargs):
            calls["ak"].append(getattr(func, "__name__", str(func)))
            return _SAMPLE.copy()

        monkeypatch.setattr(pf, "_fetch_etf_daily_row", fake_row)
        monkeypatch.setattr(pf, "_call_akshare_api", fake_ak)
        out = pf.get_fund_basic_info("510300")
        assert calls["row"] == ["510300"]
        assert calls["ak"] == []  # 不得再打蛋卷
        assert "基金简称" in out
        assert "沪深300ETF" in out

    def test_etf_not_found_reports_why(self, monkeypatch):
        monkeypatch.setattr(pf, "_fetch_etf_daily_row", lambda plain: None)
        out = pf.get_fund_basic_info("510300")
        assert "未找到" in out
        assert "ETF 行情记录" in out

    def test_etf_source_failure_degrades_to_text(self, monkeypatch):
        def boom(plain):
            raise RuntimeError("模拟失败")

        monkeypatch.setattr(pf, "_fetch_etf_daily_row", boom)
        out = pf.get_fund_basic_info("510300")
        assert "数据源访问失败" in out
        assert "模拟失败" in out

    def test_offshore_still_uses_danjuan(self, monkeypatch):
        calls = {"ak": [], "row": []}

        def fake_ak(func, *args, **kwargs):
            calls["ak"].append(getattr(func, "__name__", str(func)))
            return _SAMPLE.copy()

        def fake_row(plain):
            calls["row"].append(plain)
            return _SAMPLE.copy()

        monkeypatch.setattr(pf, "_call_akshare_api", fake_ak)
        monkeypatch.setattr(pf, "_fetch_etf_daily_row", fake_row)
        out = pf.get_fund_basic_info("000051")
        assert calls["ak"] == ["fund_individual_basic_info_xq"]
        assert calls["row"] == []
        assert "# Fund Basic Info for" in out
