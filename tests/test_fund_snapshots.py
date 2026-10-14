"""`fetch_fund_daily_snapshots` 的单元测试：打桩三张上游表，不联网。"""

from __future__ import annotations

import pandas as pd
import pytest

from ifa.dataflows import a_share_public_fund as pf


def _open_fund_daily() -> pd.DataFrame:
    """场外每日净值表：没有净值日期列（日期写在列名里），且「当天」列常常是空的。"""
    return pd.DataFrame(
        {
            "基金代码": ["161725", "110020"],
            "基金简称": ["招商中证白酒指数(LOF)A", "易方达沪深300ETF联接A"],
            "2026-10-14-单位净值": [None, None],
            "2026-10-13-单位净值": [0.5285, 1.2345],
            "日增长率": [None, None],
        }
    )


def _index_fund_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "基金代码": ["161725", "110020"],
            "基金名称": ["招商中证白酒指数(LOF)A", "易方达沪深300ETF联接A"],
            "单位净值": [0.5285, 1.2345],
            "日期": ["2026-10-14", "2026-10-14"],
            "日增长率": ["-0.99", "0.51"],
        }
    )


def _etf_table(growth: str = "---") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "基金代码": ["510300"],
            "基金简称": ["沪深300ETF华泰"],
            "2026-10-14-单位净值": [None],
            "2026-10-13-单位净值": [4.3479],
            "增长率": [growth],
            "市价": [4.294],
        }
    )


@pytest.fixture
def tables(monkeypatch) -> dict:
    """按上游函数名打桩 `_call_akshare_api`，并记录调用顺序（未打桩的调用直接失败）。"""
    calls: list[str] = []
    stub: dict = {"__calls__": calls}

    def fake_call(func, *args, **kwargs):
        key = getattr(func, "__name__", str(func))
        calls.append(key)
        if key not in stub:
            raise AssertionError(f"未打桩的上游调用: {key}")
        value = stub[key]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(pf, "_call_akshare_api", fake_call)
    return stub


def _stub_all(tables: dict, *, growth: str = "---", hist: pd.DataFrame | None = None) -> None:
    tables["fund_open_fund_daily_em"] = _open_fund_daily()
    tables["fund_info_index_em"] = _index_fund_table()
    tables["fund_etf_fund_daily_em"] = _etf_table(growth=growth)
    if hist is not None:
        tables["fund_etf_hist_em"] = hist


def test_open_fund_nav_date_comes_from_column_name(tables):
    _stub_all(tables)

    snapshots = pf.fetch_fund_daily_snapshots(["161725"])

    assert snapshots["161725"]["nav"] == 0.5285
    assert snapshots["161725"]["name"] == "招商中证白酒指数(LOF)A"


def test_index_table_fills_fresher_date_and_change(tables):
    _stub_all(tables)

    snapshots = pf.fetch_fund_daily_snapshots(["110020"])

    assert snapshots["110020"]["nav_date"] == "2026-10-14"
    assert snapshots["110020"]["change_pct"] == 0.51


def test_open_fund_keeps_previous_trade_date_when_today_is_empty(tables):
    """只有场外每日净值表有数据时，日期必须如实落在上一交易日，不能写成今天。"""
    tables["fund_open_fund_daily_em"] = _open_fund_daily()

    snapshots = pf.fetch_fund_daily_snapshots(["161725"])

    assert snapshots["161725"]["nav_date"] == "2026-10-13"
    assert snapshots["161725"]["change_pct"] is None


def test_etf_change_falls_back_to_daily_history(tables):
    _stub_all(tables, hist=pd.DataFrame({"日期": ["2026-10-14"], "涨跌幅": [0.42]}))

    snapshots = pf.fetch_fund_daily_snapshots(["510300"])

    assert snapshots["510300"]["nav"] == 4.3479
    assert snapshots["510300"]["price"] == 4.294
    assert snapshots["510300"]["change_pct"] == 0.42
    assert tables["__calls__"][-1] == "fund_etf_hist_em"


def test_etf_growth_rate_is_used_without_extra_request(tables):
    _stub_all(tables, growth="1.23")

    snapshots = pf.fetch_fund_daily_snapshots(["510300"])

    assert snapshots["510300"]["change_pct"] == 1.23
    assert "fund_etf_hist_em" not in tables["__calls__"]


def test_unknown_codes_are_omitted(tables):
    _stub_all(tables)

    snapshots = pf.fetch_fund_daily_snapshots(["161725", "999999"])

    assert set(snapshots) == {"161725"}


def test_failing_table_degrades_without_raising(tables):
    _stub_all(tables, hist=pd.DataFrame({"日期": ["2026-10-14"], "涨跌幅": [0.42]}))
    # 指数基金表只覆盖 110020，161725 的唯一来源是下面这张会挂掉的场外表
    tables["fund_info_index_em"] = _index_fund_table().iloc[0:0]
    tables["fund_open_fund_daily_em"] = RuntimeError("上游 502")

    snapshots = pf.fetch_fund_daily_snapshots(["161725", "510300"])

    # 场外表挂了：161725 缺数据但不抛异常，场内 ETF 仍然要拿到
    assert "161725" not in snapshots
    assert snapshots["510300"]["nav"] == 4.3479
    assert snapshots["510300"]["change_pct"] == 0.42


def test_missing_tokens_are_treated_as_missing(tables):
    tables["fund_open_fund_daily_em"] = pd.DataFrame(
        {
            "基金代码": ["161725"],
            "基金简称": ["招商中证白酒指数(LOF)A"],
            "2026-10-13-单位净值": ["---"],
        }
    )

    snapshots = pf.fetch_fund_daily_snapshots(["161725"])

    # 有名称仍然返回（名称对用户有用），但净值/日期为 None
    assert snapshots["161725"]["nav"] is None
    assert snapshots["161725"]["nav_date"] is None


def test_empty_codes_returns_empty(tables):
    assert pf.fetch_fund_daily_snapshots([]) == {}
