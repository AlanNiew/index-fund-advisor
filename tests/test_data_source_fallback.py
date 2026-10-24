"""行情源回退测试（全部 mock，不触网）。

背景：2026-10 实测东财行情域名（push2his / push2 / push2delay）对华为云机房 IP
在 TLS 握手后直接断连，而同一台机器上腾讯、新浪行情接口正常，本机（家宽 IP）
访问东财正常。ETF/指数取数因此改为「东财优先 + 备用源回退」。

这里验证的是回退契约本身：
- 东财正常时绝不触达备用源（不额外增加失败面的延迟）；
- 东财失败时用备用源顶上，且输出必须标明来源（否则使用者无法判断数据口径）；
- 备用源也失败时必须把两段原因都报出来（不能把「数据源全挂」误报成「查无数据」）；
- 东财正常但确实无数据时，仍保持「未找到」语义。
"""

from types import SimpleNamespace

import akshare as ak
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
    }
)

# 腾讯前复权日线的原始列（date/open/close/high/low/amount），含一行区间外数据
_TX = pd.DataFrame(
    {
        "date": ["2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04"],
        "open": [3.40, 3.50, 3.60, 3.55],
        "close": [3.42, 3.60, 3.55, 3.58],
        "high": [3.45, 3.70, 3.80, 3.60],
        "low": [3.38, 3.40, 3.50, 3.50],
        "amount": [900.0, 1000.0, 2000.0, 1500.0],
    }
)

# 新浪指数日线是全历史，同样含区间外数据
_SINA = pd.DataFrame(
    {
        "date": ["2023-12-29", "2024-01-02", "2024-01-03"],
        "open": [3400.0, 3450.0, 3480.0],
        "high": [3420.0, 3470.0, 3500.0],
        "low": [3390.0, 3440.0, 3470.0],
        "close": [3410.0, 3460.0, 3490.0],
        "volume": [1.0e9, 1.1e9, 1.2e9],
    }
)

_MISSING = object()


def _patch_sources(monkeypatch, *, eastmoney=_MISSING, tencent=_MISSING, sina=_MISSING):
    """按 akshare 函数身份分派，返回按调用顺序记录的 (函数名, kwargs)。"""
    calls = []

    def fake(func, *args, **kwargs):
        calls.append((getattr(func, "__name__", str(func)), kwargs))
        if func in (ak.fund_etf_hist_em, ak.index_zh_a_hist):
            value = eastmoney
        elif func is ak.stock_zh_a_hist_tx:
            value = tencent
        elif func is ak.stock_zh_index_daily:
            value = sina
        else:
            raise AssertionError(f"未预期的取数调用: {func}")
        if value is _MISSING:
            raise AssertionError(f"不该调用 {getattr(func, '__name__', func)}")
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(ix, "_call_akshare_api", fake)
    return calls


class TestMarketPrefixedCode:
    """新浪/腾讯需要「市场前缀 + 6 位代码」，猜错市场会静默取到别的标的。"""

    @pytest.mark.parametrize(
        "_symbol,_is_index,_expected",
        [
            ("510300", False, "sh510300"),
            ("510300.SH", False, "sh510300"),
            ("588000", False, "sh588000"),
            ("159919", False, "sz159919"),
            ("161725", False, "sz161725"),
            ("000300", True, "sh000300"),
            ("399006", True, "sz399006"),
            ("abc", False, ""),
            ("", False, ""),
        ],
    )
    def test_maps_symbol_to_market_prefix(self, _symbol, _is_index, _expected):
        assert ix.market_prefixed_code(_symbol, is_index=_is_index) == _expected


class TestEtfFallback:
    def test_eastmoney_success_never_touches_fallback(self, monkeypatch):
        calls = _patch_sources(monkeypatch, eastmoney=_OHLCV.copy())
        out = ix.get_etf_data("510300", "2024-01-01", "2024-03-01")
        assert "Close" in out
        assert "# Source:" not in out  # 东财正常时不写来源说明
        assert [name for name, _ in calls] == ["fund_etf_hist_em"]

    def test_falls_back_to_tencent_forward_adjusted(self, monkeypatch):
        calls = _patch_sources(
            monkeypatch,
            eastmoney=ConnectionError("Remote end closed connection without response"),
            tencent=_TX.copy(),
        )
        out = ix.get_etf_data("510300", "2024-01-01", "2024-03-01")
        assert "数据源访问失败" not in out
        assert "Close" in out
        assert "# Source: 腾讯前复权日线" in out
        assert "# Records: 3" in out
        assert "2024-01-02" in out
        # 请求区间外的行必须被裁掉
        assert "2023-12-29" not in out
        assert [name for name, _ in calls] == ["fund_etf_hist_em", "stock_zh_a_hist_tx"]
        # 腾讯接口必须收到带市场前缀的代码与 qfq
        tx_kwargs = calls[1][1]
        assert tx_kwargs["symbol"] == "sh510300"
        assert tx_kwargs["adjust"] == "qfq"

    def test_both_sources_fail_reports_both_reasons(self, monkeypatch):
        _patch_sources(
            monkeypatch,
            eastmoney=ConnectionError("Remote end closed"),
            tencent=RuntimeError("tx down"),
        )
        out = ix.get_etf_data("510300", "2024-01-01", "2024-03-01")
        assert "数据源访问失败" in out
        assert "Remote end closed" in out
        assert "tx down" in out

    def test_eastmoney_empty_keeps_not_found_semantics(self, monkeypatch):
        """东财正常返回空 = 查无此标的，不能报成数据源故障。"""
        _patch_sources(monkeypatch, eastmoney=pd.DataFrame(), tencent=_MISSING)
        out = ix.get_etf_data("999999", "2024-01-01", "2024-03-01")
        assert "未找到" in out
        assert "ETF 行情数据。" in out
        assert "数据源访问失败" not in out

    def test_fetch_frame_reports_source(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=ConnectionError("boom"), tencent=_TX.copy())
        frame, source = ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
        assert source == "tencent"
        assert list(frame["收盘"]) == [3.60, 3.55, 3.58]


class TestIndexFallback:
    def test_falls_back_to_sina_index_daily(self, monkeypatch):
        calls = _patch_sources(monkeypatch, eastmoney=RuntimeError("em down"), sina=_SINA.copy())
        out = ix.get_index_data("000300", "2024-01-01", "2024-03-01")
        assert "数据源访问失败" not in out
        assert "Close" in out
        assert "# Source: 新浪指数日线" in out
        assert "# Records: 2" in out  # 新浪返回全历史，必须裁剪到请求区间
        assert "2024-01-02" in out
        assert "2023-12-29" not in out
        assert calls[1][1]["symbol"] == "sh000300"

    def test_deep_index_code_maps_to_shenzhen(self, monkeypatch):
        calls = _patch_sources(monkeypatch, eastmoney=RuntimeError("em down"), sina=_SINA.copy())
        ix.get_index_data("399006", "2024-01-01", "2024-03-01")
        assert calls[1][1]["symbol"] == "sz399006"

    def test_both_sources_fail_reports_both_reasons(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=RuntimeError("em down"), sina=RuntimeError("sina down"))
        out = ix.get_index_data("000300", "2024-01-01", "2024-03-01")
        assert "数据源访问失败" in out
        assert "em down" in out
        assert "sina down" in out

    def test_eastmoney_empty_keeps_not_found_semantics(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=pd.DataFrame(), sina=_MISSING)
        out = ix.get_index_data("000300", "2024-01-01", "2024-03-01")
        assert "未找到" in out
        assert "指数行情数据。" in out
        assert "数据源访问失败" not in out


class TestSeriesFallback:
    """回测/结算走的是序列接口，回退必须同样生效，否则结算基准仍然取不到价。"""

    def test_etf_price_series_uses_fallback(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=ConnectionError("boom"), tencent=_TX.copy())
        series, label = ix._etf_price_series("510300", "2024-01-01", "2024-03-01")
        assert series is not None
        assert len(series) == 3
        assert label == "ETF 前复权收盘价（分红已还原）"

    def test_etf_price_series_degrades_when_all_sources_fail(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=ConnectionError("boom"), tencent=RuntimeError("tx down"))
        assert ix._etf_price_series("510300", "2024-01-01", "2024-03-01") == (None, "")

    def test_index_close_series_uses_fallback(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=RuntimeError("em down"), sina=_SINA.copy())
        series = ix._index_close_series("000300", "2024-01-01", "2024-03-01")
        assert series is not None
        assert len(series) == 2

    def test_index_close_series_degrades_when_all_sources_fail(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=RuntimeError("em down"), sina=RuntimeError("sina down"))
        assert ix._index_close_series("000300", "2024-01-01", "2024-03-01") is None


class TestEastmoneyBreaker:
    """东财熔断：机房 IP 上东财 100% 失败且每次要重试 3 次（索引约 17s）。

    没有熔断时，一个结算批次几百次取价几乎全在等超时；熔断后连续失败即暂时跳过东财，
    冷却窗口过后再给东财一次机会（避免把「临时抖动」永久当作「不可用」）。
    """

    def test_breaker_opens_after_threshold_and_skips_eastmoney(self, monkeypatch):
        calls = _patch_sources(monkeypatch, eastmoney=ConnectionError("blocked"), tencent=_TX.copy())
        for _ in range(3):
            _frame, source = ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
            assert source == ix._SOURCE_TENCENT
        names = [name for name, _ in calls]
        # 第三次不再打东财（省掉 3 次重试的等待），但备用源每次都照取
        assert names.count("fund_etf_hist_em") == ix._EASTMONEY_FAILURE_THRESHOLD
        assert names.count("stock_zh_a_hist_tx") == 3
        assert ix.eastmoney_breaker_open() is True

    def test_success_resets_consecutive_failures(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=ConnectionError("blocked"), tencent=_TX.copy())
        ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
        assert ix._eastmoney_consecutive_failures == 1
        assert ix.eastmoney_breaker_open() is False

        calls = _patch_sources(monkeypatch, eastmoney=_OHLCV.copy())
        _frame, source = ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
        assert source == ix._SOURCE_EASTMONEY
        assert ix._eastmoney_consecutive_failures == 0
        assert ix.eastmoney_breaker_open() is False
        assert [name for name, _ in calls] == ["fund_etf_hist_em"]

    def test_cooldown_expiry_retries_eastmoney(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=ConnectionError("blocked"), tencent=_TX.copy())
        for _ in range(2):
            ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
        assert ix.eastmoney_breaker_open() is True

        # 用假的 monotonic 跳过冷却窗口，避免真的等 5 分钟
        blocked_until = ix._eastmoney_blocked_until
        monkeypatch.setattr(ix, "time", SimpleNamespace(monotonic=lambda: blocked_until + 1.0))
        assert ix.eastmoney_breaker_open() is False
        calls = _patch_sources(monkeypatch, eastmoney=_OHLCV.copy())
        _frame, source = ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
        assert source == ix._SOURCE_EASTMONEY
        assert [name for name, _ in calls] == ["fund_etf_hist_em"]

    def test_breaker_open_with_both_sources_down_reports_both_reasons(self, monkeypatch):
        _patch_sources(monkeypatch, eastmoney=ConnectionError("blocked"), tencent=RuntimeError("tx down"))
        for _ in range(2):
            with pytest.raises(RuntimeError):
                ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
        with pytest.raises(RuntimeError) as excinfo:
            ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
        text = str(excinfo.value)
        # 熔断跳过东财时，也要把「跳过」和备用源失败两段原因都写清楚
        assert "熔断" in text
        assert "腾讯前复权日线" in text
        assert "tx down" in text

    def test_empty_eastmoney_response_keeps_not_found_semantics(self, monkeypatch):
        calls = _patch_sources(monkeypatch, eastmoney=pd.DataFrame())
        frame, source = ix.fetch_etf_hist_frame("510300", "2024-01-01", "2024-03-01")
        assert source == ix._SOURCE_NONE
        assert frame.empty
        # 东财正常应答（只是没数据）不算失败：不累计失败数、不开熔断，
        # 否则「无数据」会被误判成「数据源挂了」，把查无此项变成报错。
        assert ix._eastmoney_consecutive_failures == 0
        assert ix.eastmoney_breaker_open() is False
        # 东财空数据仍会给备用源一次机会（可能是东财区间口径或部分节点异常）
        names = [name for name, _ in calls]
        assert names[0] == "fund_etf_hist_em"
        assert "stock_zh_a_hist_tx" in names

    def test_index_path_shares_the_same_breaker(self, monkeypatch):
        calls = _patch_sources(monkeypatch, eastmoney=RuntimeError("blocked"), sina=_SINA.copy())
        for _ in range(3):
            _frame, source = ix.fetch_index_hist_frame("000300", "2024-01-01", "2024-03-01")
            assert source == ix._SOURCE_SINA
        assert ix.eastmoney_breaker_open() is True
        assert [name for name, _ in calls].count("index_zh_a_hist") == ix._EASTMONEY_FAILURE_THRESHOLD
