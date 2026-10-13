"""成分股工具测试 —— 与数据工具层的接线、缓存往返后的代码规范化、降级路径。

背景（本次修复的两个问题）：
  1. 三个工具此前直连 akShare，绕过了 CachedDataToolExecutor，而它们正是
     网络请求最密集的工具；
  2. get_constituent_performance 把个股行情路由到 `get_stock_data`，但该方法
     从未注册进 VENDOR_METHODS，route_to_vendor 必然抛 ValueError 并被吞掉，
     于是对全部 10 只股票**恒定**返回「数据获取失败」。
"""

import io

import pandas as pd

import ifa.agents.tools.constituent_tools as ct

_CONSTITUENTS = pd.DataFrame(
    {
        "日期": ["20240102"] * 12,
        "指数代码": ["000300"] * 12,
        "成分券代码": [f"60000{i}" for i in range(12)],
        "成分券名称": [f"股票{i}" for i in range(12)],
        "权重": [float(10 - i * 0.5) for i in range(12)],
    }
)
_SECTORED = _CONSTITUENTS.assign(行业=["银行", "白酒"] * 6)

_STOCK_DAILY = (
    "# Stock price data for 600000.SH from 2024-01-01 to 2024-02-01\n# Records: 2\n\n"
    "Date,Open,High,Low,Close,Volume,Amount,PctChange,TurnoverPct\n"
    "2024-01-02,10.0,10.5,9.9,10.2,100,1020.0,1.0,0.5\n"
    "2024-01-03,10.2,10.4,10.1,10.3,200,2060.0,0.98,0.6\n"
)


def _cached_copy(df: pd.DataFrame) -> pd.DataFrame:
    """模拟缓存层的 CSV 往返：纯数字列被推断成整数，前导零丢失。"""
    return pd.read_csv(io.StringIO(df.to_csv(index=False)))


def _patch(monkeypatch, *, constituents=None, stock=None, exc=None, recorder=None):
    """替换模块内的 run_data_tool，按工具名分发。"""
    daily = stock if stock is not None else _STOCK_DAILY

    def fake(tool_name, **params):
        if recorder is not None:
            recorder.append((tool_name, params))
        if exc is not None:
            raise exc
        if tool_name == "get_index_constituents_raw":
            return constituents
        if tool_name == "get_stock_daily":
            return daily
        raise AssertionError(f"未预期的数据工具: {tool_name}")

    monkeypatch.setattr(ct, "run_data_tool", fake)


class TestDataToolRouting:
    """三个工具都必须经数据工具层取数（否则拿不到缓存/快照）。"""

    def test_overview_routes_through_data_tool(self, monkeypatch):
        rec = []
        _patch(monkeypatch, constituents=_CONSTITUENTS.copy(), recorder=rec)
        ct.get_constituent_overview.invoke({"symbol": "000300"})
        assert [name for name, _ in rec] == ["get_index_constituents_raw"]

    def test_performance_uses_registered_stock_tool(self, monkeypatch):
        """个股行情必须走已注册的 get_stock_daily，而不是此前未注册的 get_stock_data。"""
        rec = []
        _patch(monkeypatch, constituents=_CONSTITUENTS.copy(), recorder=rec)
        out = ct.get_constituent_performance.invoke({"symbol": "000300", "look_back_days": 30})

        tools_used = {name for name, _ in rec}
        assert "get_stock_daily" in tools_used
        assert "get_stock_data" not in tools_used
        assert "数据获取失败" not in out
        assert "# Records: 2" in out

    def test_three_tools_share_one_constituent_fetch(self, monkeypatch):
        rec = []
        _patch(monkeypatch, constituents=_CONSTITUENTS.copy(), recorder=rec)
        ct.get_constituent_overview.invoke({"symbol": "000300"})
        ct.get_constituent_sector_distribution.invoke({"symbol": "000300"})
        ct.get_constituent_performance.invoke({"symbol": "000300", "look_back_days": 30})

        constituent_calls = [n for n, _ in rec if n == "get_index_constituents_raw"]
        assert len(constituent_calls) == 3  # 同参数 → 由数据工具层的缓存去重

    def test_performance_fetches_each_top_holding(self, monkeypatch):
        rec = []
        _patch(monkeypatch, constituents=_CONSTITUENTS.copy(), recorder=rec)
        ct.get_constituent_performance.invoke({"symbol": "000300", "look_back_days": 30})
        stock_calls = [p for n, p in rec if n == "get_stock_daily"]
        assert len(stock_calls) == 10  # 只取前 10 大权重股


class TestStockCodeNormalization:
    """成分股代码必须保持 6 位 —— 缓存 CSV 往返会丢前导零。"""

    def test_fresh_dataframe_passes_six_digit_codes(self, monkeypatch):
        rec = []
        _patch(monkeypatch, constituents=_CONSTITUENTS.copy(), recorder=rec)
        ct.get_constituent_performance.invoke({"symbol": "000300", "look_back_days": 30})
        codes = [p["symbol"] for n, p in rec if n == "get_stock_daily"]
        assert len(codes) == 10
        assert all(len(code) == 6 for code in codes)

    def test_cached_dataframe_keeps_leading_zeros(self, monkeypatch):
        """命中缓存时 DataFrame 由 CSV 读回，代码列已变成整数 —— 仍须补零。"""
        cached = _cached_copy(_CONSTITUENTS)
        assert cached["成分券代码"].dtype.kind in "iu"  # 前提：前导零确实已丢失

        rec = []
        _patch(monkeypatch, constituents=cached, recorder=rec)
        ct.get_constituent_performance.invoke({"symbol": "000300", "look_back_days": 30})
        codes = [p["symbol"] for n, p in rec if n == "get_stock_daily"]
        assert all(len(code) == 6 for code in codes)
        assert all(".0" not in code for code in codes)


class TestDegradation:
    """异常与空数据必须降级为可读文本，不能把异常抛给上层 Agent。"""

    def test_source_failure_degrades(self, monkeypatch):
        _patch(monkeypatch, exc=RuntimeError("模拟接口超时"))
        out = ct.get_constituent_overview.invoke({"symbol": "000300"})
        assert "数据源访问失败" in out
        assert "模拟接口超时" in out

    def test_empty_constituents_degrades(self, monkeypatch):
        _patch(monkeypatch, constituents=pd.DataFrame())
        assert "未找到" in ct.get_constituent_overview.invoke({"symbol": "000300"})
        assert "未找到" in ct.get_constituent_performance.invoke({"symbol": "000300"})

    def test_single_stock_failure_is_isolated(self, monkeypatch):
        """单只个股取数失败只影响那一行，不应拖垮整份输出。"""

        def fake(tool_name, **params):
            if tool_name == "get_index_constituents_raw":
                return _CONSTITUENTS.copy()
            if params["symbol"] == "600003":
                raise RuntimeError("该股停牌")
            return _STOCK_DAILY

        monkeypatch.setattr(ct, "run_data_tool", fake)
        out = ct.get_constituent_performance.invoke({"symbol": "000300", "look_back_days": 30})
        assert out.count("数据获取失败") == 1
        assert out.count("# Records: 2") == 9

    def test_missing_code_column_is_reported(self, monkeypatch):
        df = _CONSTITUENTS.drop(columns=["成分券代码"])
        _patch(monkeypatch, constituents=df)
        out = ct.get_constituent_performance.invoke({"symbol": "000300"})
        assert "未找到代码字段" in out

    def test_missing_industry_column_is_reported(self, monkeypatch):
        _patch(monkeypatch, constituents=_CONSTITUENTS.copy())
        out = ct.get_constituent_sector_distribution.invoke({"symbol": "000300"})
        assert "未找到行业分类字段" in out


class TestOffshoreFundShortCircuit:
    """场外基金没有成分股，必须在取数前短路返回，且不触网。"""

    def test_all_three_short_circuit(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ct, "run_data_tool", lambda *a, **k: calls.append(a))

        for tool_fn in (
            ct.get_constituent_overview,
            ct.get_constituent_sector_distribution,
            ct.get_constituent_performance,
        ):
            out = tool_fn.invoke({"symbol": "110011"})
            assert "场外基金" in out

        assert calls == []


class TestSectorDistribution:
    """行业分布聚合逻辑。"""

    def test_aggregates_counts_and_weights(self, monkeypatch):
        _patch(monkeypatch, constituents=_SECTORED.copy())
        out = ct.get_constituent_sector_distribution.invoke({"symbol": "000300"})
        assert "行业" in out
        assert "成分股数量" in out
        assert "权重合计(%)" in out

    def test_weights_column_present(self, monkeypatch):
        _patch(monkeypatch, constituents=_SECTORED.copy())
        out = ct.get_constituent_sector_distribution.invoke({"symbol": "000300"})
        # 6 只银行 + 6 只白酒，占比各 50%
        assert "50.0" in out


class TestOverviewSelection:
    """权重股概览的排序与截断。"""

    def test_top_ten_by_weight(self, monkeypatch):
        _patch(monkeypatch, constituents=_CONSTITUENTS.copy())  # 12 行，权重递减
        out = ct.get_constituent_overview.invoke({"symbol": "000300"})
        assert "Top 10 Constituents" in out
        assert "股票0" in out  # 权重最高
        assert "股票11" not in out  # 被截断
