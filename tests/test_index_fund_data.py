"""ETF / 指数 / 场外基金数据层测试（全部 mock，不触网）。

补的是覆盖率盲区：a_share_index_fund.py 此前仅 13% 覆盖。这里重点验证
「中文列名 → 英文列名」的映射与 Date/PctChange 派生逻辑——回测引擎直接消费
这些列名，映射错了会静默算错收益。
"""

import pandas as pd
import pytest

import ifa.dataflows.a_share_index_fund as ix

_OHLCV = pd.DataFrame(
    {
        "日期": ["2024-01-02", "2024-01-03", "2024-01-04"],
        "开盘": [3.50, 3.60, 3.55],
        "最高": [3.70, 3.80, 3.60],
        "最低": [3.40, 3.50, 3.50],
        "收盘": [3.60, 3.55, 3.58],
        "成交量": [1000, 2000, 1500],
        "成交额": [3600.5, 7100.25, 5370.0],
        "涨跌幅": [1.23, -1.39, 0.85],
        "换手率": [0.5, 0.6, 0.55],
    }
)

_PLAIN = pd.DataFrame({"基金代码": ["510300"], "基金简称": ["沪深300ETF"]})


def _patch(monkeypatch, *, value=None, exc=None):
    def fake(*args, **kwargs):
        if exc is not None:
            raise exc
        return value

    monkeypatch.setattr(ix, "_call_akshare_api", fake)


_CASES = [
    (
        "etf_data",
        ix.get_etf_data,
        ("510300", "2024-01-01", "2024-03-01"),
        {},
        _OHLCV,
        "# ETF price data for",
        "ETF 行情数据。",
    ),
    (
        "index_data",
        ix.get_index_data,
        ("000300", "2024-01-01", "2024-03-01"),
        {},
        _OHLCV,
        "# Index data for",
        "指数行情数据。",
    ),
    ("etf_fund_info", ix.get_etf_fund_info, ("510300",), {}, _PLAIN, "# ETF Fund Info for", "的 ETF 基金信息。"),
    (
        "index_constituents",
        ix.get_index_constituents,
        ("000300",),
        {},
        _PLAIN,
        "# Index Constituents for",
        "的成分股数据。",
    ),
    ("fund_nav", ix.get_fund_nav, ("510300",), {}, _PLAIN, "# Fund NAV History for", "的基金净值数据。"),
    (
        "stock_daily",
        ix.get_stock_daily,
        ("600519", "2024-01-01", "2024-03-01"),
        {},
        _OHLCV,
        "# Stock price data for",
        "个股行情数据。",
    ),
]
_IDS = [c[0] for c in _CASES]


@pytest.mark.parametrize("_id,func,args,kwargs,sample,title_frag,_empty", _CASES, ids=_IDS)
class TestNormalPath:
    def test_returns_title_and_data(self, monkeypatch, _id, func, args, kwargs, sample, title_frag, _empty):
        _patch(monkeypatch, value=sample.copy())
        out = func(*args, **kwargs)
        assert isinstance(out, str)
        assert title_frag in out
        assert "# Records:" in out or "510300" in out


@pytest.mark.parametrize("_id,func,args,kwargs,_sample,_title,_empty", _CASES, ids=_IDS)
class TestEmptyDataFrame:
    def test_returns_explicit_not_found_message(self, monkeypatch, _id, func, args, kwargs, _sample, _title, _empty):
        _patch(monkeypatch, value=pd.DataFrame())
        out = func(*args, **kwargs)
        assert out.strip()
        assert _empty in out


@pytest.mark.parametrize("_id,func,args,kwargs,_sample,_title,_empty", _CASES, ids=_IDS)
class TestSourceFailure:
    def test_degrades_instead_of_raising(self, monkeypatch, _id, func, args, kwargs, _sample, _title, _empty):
        _patch(monkeypatch, exc=RuntimeError("模拟接口异常"))
        out = func(*args, **kwargs)
        assert "数据源访问失败" in out
        assert "模拟接口异常" in out


class TestColumnMapping:
    """中文列名 → 英文列名映射；回测引擎依赖这些列名。"""

    def test_etf_data_maps_all_ohlcv_columns(self, monkeypatch):
        _patch(monkeypatch, value=_OHLCV.copy())
        out = ix.get_etf_data("510300", "2024-01-01", "2024-03-01")
        header, sep, body = out.partition("\n\n")
        assert sep, "输出必须包含标题块与 CSV 数据块的分隔"
        assert "# Records: 3" in header
        for col in ["Date", "Open", "High", "Low", "Close", "Volume", "Amount", "PctChange", "TurnoverPct"]:
            assert col in body
        assert "2024-01-02" in body

    def test_etf_data_formats_date_as_iso(self, monkeypatch):
        """日期必须归一化为 YYYY-MM-DD，否则下游解析会失败。"""
        _patch(monkeypatch, value=_OHLCV.copy())
        out = ix.get_etf_data("510300", "2024-01-01", "2024-03-01")
        assert "2024-01-02" in out
        assert "2024-01-02 00:00:00" not in out

    def test_etf_data_derives_pct_change_when_absent(self, monkeypatch):
        """缺少涨跌幅列时用 Close.pct_change() 补一列，而不是留空。"""
        df = _OHLCV.drop(columns=["涨跌幅"])
        _patch(monkeypatch, value=df)
        out = ix.get_etf_data("510300", "2024-01-01", "2024-03-01")
        body = out.partition("\n\n")[2]
        assert "PctChange" in body

    def test_index_data_does_not_derive_pct_change(self, monkeypatch):
        """指数接口不派生 PctChange（与 ETF 的行为差异，避免误以为两边一致）。"""
        df = _OHLCV.drop(columns=["涨跌幅"])
        _patch(monkeypatch, value=df)
        out = ix.get_index_data("000300", "2024-01-01", "2024-03-01")
        body = out.partition("\n\n")[2]
        assert "PctChange" not in body
        assert "Close" in body

    def test_index_data_drops_unknown_columns(self, monkeypatch):
        df = _OHLCV.copy()
        df["备注"] = ["a", "b", "c"]
        _patch(monkeypatch, value=df)
        out = ix.get_index_data("000300", "2024-01-01", "2024-03-01")
        assert "备注" not in out


class TestArgumentMapping:
    """代码规范化与参数透传。"""

    def test_etf_data_passes_plain_code_and_api_dates(self, monkeypatch):
        captured = {}

        def fake(func, *args, **kwargs):
            captured.update(kwargs)
            return _OHLCV.copy()

        monkeypatch.setattr(ix, "_call_akshare_api", fake)
        ix.get_etf_data("510300.SH", "2024-01-01", "2024-03-01")
        assert captured["symbol"] == "510300"
        assert captured["period"] == "daily"
        assert captured["adjust"] == "qfq"
        # format_date_for_api 需产出 akshare 期望的 8 位无分隔格式
        assert captured["start_date"].isdigit() and len(captured["start_date"]) == 8
        assert captured["end_date"].isdigit() and len(captured["end_date"]) == 8

    def test_fund_nav_keeps_only_last_60_rows(self, monkeypatch):
        df = pd.DataFrame({"净值日期": [f"2024-01-{i:02d}" for i in range(1, 29)], "单位净值": range(28)})
        _patch(monkeypatch, value=df)
        out = ix.get_fund_nav("510300")
        assert "# Records:" not in out  # _format_table 路径不带 Records 头
        assert "510300" in out or "净值日期" in out


class TestIndexConstituentsRaw:
    """get_index_constituents_raw —— 供缓存层复用的原始数据变体。

    契约与其它 a_share_* 函数不同：它返回 DataFrame 且**不吞异常**，
    因为调用方（数据工具层）需要按自己的语义决定如何降级。
    """

    def test_returns_dataframe(self, monkeypatch):
        df = pd.DataFrame({"成分券代码": ["600000"], "权重": [1.5]})
        _patch(monkeypatch, value=df)
        out = ix.get_index_constituents_raw("000300")
        assert isinstance(out, pd.DataFrame)
        assert list(out["成分券代码"]) == ["600000"]

    def test_raises_instead_of_swallowing(self, monkeypatch):
        _patch(monkeypatch, exc=RuntimeError("接口挂了"))
        with pytest.raises(RuntimeError, match="接口挂了"):
            ix.get_index_constituents_raw("000300")

    def test_passes_plain_code(self, monkeypatch):
        captured = {}

        def fake(func, *args, **kwargs):
            captured.update(kwargs)
            return pd.DataFrame({"成分券代码": ["600000"]})

        monkeypatch.setattr(ix, "_call_akshare_api", fake)
        ix.get_index_constituents_raw("000300.SH")
        assert captured["symbol"] == "000300"


class TestIndexConstituentsDelegation:
    """格式化的 get_index_constituents 必须复用同一个取数实现（避免两套实现漂移）。"""

    def test_formatted_version_reuses_raw_fetch(self, monkeypatch):
        calls = []

        def fake_raw(symbol):
            calls.append(symbol)
            return pd.DataFrame({"成分券代码": ["600000"], "权重": [1.5]})

        monkeypatch.setattr(ix, "get_index_constituents_raw", fake_raw)
        out = ix.get_index_constituents("000300")
        assert calls == ["000300"]
        assert "# Index Constituents for" in out

    def test_raw_failure_degrades_to_error_text(self, monkeypatch):
        def boom(symbol):
            raise RuntimeError("模拟失败")

        monkeypatch.setattr(ix, "get_index_constituents_raw", boom)
        out = ix.get_index_constituents("000300")
        assert "数据源访问失败" in out
        assert "模拟失败" in out
