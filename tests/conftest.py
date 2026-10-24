"""pytest 全局夹具。"""

from __future__ import annotations

import pytest

import ifa.dataflows.a_share_index_fund as ix


@pytest.fixture(autouse=True)
def _reset_eastmoney_breaker():
    """每个测试前后清空东财熔断状态。

    熔断计数是进程级全局量（真实运行时这正是想要的效果：一个批次里连续失败后
    不再逐次等超时）。但测试之间必须隔离，否则前一个用例打开的熔断会让后一个
    用例跳过东财、拿不到它期待的异常文本。
    """
    ix.reset_eastmoney_breaker()
    yield
    ix.reset_eastmoney_breaker()
