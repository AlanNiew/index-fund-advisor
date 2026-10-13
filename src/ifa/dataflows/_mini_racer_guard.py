"""
py_mini_racer 并发构造保护（第三方库兼容补丁）。

背景：py_mini_racer 0.14.x 的 V8 在「两个线程同时创建 MiniRacer 实例」时会命中
V8 分区分配器的断言并**直接 abort 整个 Python 进程**：

    [FATAL:partition_address_space.cc(243)] Check failed: !IsConfigurablePoolInitialized().

而 akshare 有多个接口内部会构造 MiniRacer（stock_index_pe_lg、
tool_trade_date_hist_sina、fund_open_fund_info_em 等），LangGraph 的 ToolNode 又会在
线程池里并发执行数据工具 —— 于是两个并发的估值工具调用就能把整个进程打死
（Windows / Python 3.13 / py_mini_racer 0.14.1 实测，退出码 0x80000003）。

因此这里把 MiniRacer 的构造串行化：上下文（V8 isolate）创建加进程级锁，
构造完成后的 eval 仍可并发（多 isolate 并发执行本身是安全的）。
"""

from __future__ import annotations

import sys
import threading
from typing import Any

# 串行化 MiniRacer 构造；用 RLock 是为了容忍 StrictMiniRacer 之类的子类嵌套构造。
_CONSTRUCTION_LOCK = threading.RLock()

# 打在受保护类上的标记，用于判断是否已经打过补丁。
_GUARD_MARKER = "_ifa_serialized_construction"


def _make_guarded(cls: type) -> type:
    """
    为一个 MiniRacer 类生成「构造加锁」的子类。

    参数：
        cls: 原始的 MiniRacer 类。

    返回：
        type: 构造过程持有 _CONSTRUCTION_LOCK 的子类。
    """

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        with _CONSTRUCTION_LOCK:
            # 直接调用基类 __init__ 是这里唯一的意图（不跑子类重写）。
            cls.__init__(self, *args, **kwargs)  # type: ignore[misc]

    return type(
        cls.__name__,
        (cls,),
        {
            "__init__": __init__,
            "__qualname__": cls.__qualname__,
            _GUARD_MARKER: True,
        },
    )


def install_mini_racer_guard() -> bool:
    """
    给 py_mini_racer 装上并发构造保护。

    幂等：重复调用不会二次包装。未安装 py_mini_racer 时静默跳过。

    返回：
        bool: 保护是否生效（True 表示已生效或本次已装好；False 表示库不可用）。
    """
    try:
        import py_mini_racer
    except Exception:
        return False

    original = getattr(py_mini_racer, "MiniRacer", None)
    if original is None:
        return False
    if getattr(original, _GUARD_MARKER, False):
        return True

    guarded = _make_guarded(original)
    # 补丁的是第三方模块属性，用 setattr 避开 mypy 对「给类型赋值」的检查。
    setattr(py_mini_racer, "MiniRacer", guarded)  # noqa: B010
    if getattr(py_mini_racer, "StrictMiniRacer", None) is original:
        setattr(py_mini_racer, "StrictMiniRacer", guarded)  # noqa: B010

    # 已经执行过 from py_mini_racer import MiniRacer 的模块持有旧引用，逐个替换。
    for module in list(sys.modules.values()):
        if module is None or module is py_mini_racer:
            continue
        if getattr(module, "MiniRacer", None) is original:
            # 动态模块补丁，无法用属性赋值写法（mypy 也认不出该属性）。
            setattr(module, "MiniRacer", guarded)  # noqa: B010

    return True
