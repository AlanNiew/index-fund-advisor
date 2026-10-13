"""
py_mini_racer 并发构造保护的回归测试。

对应缺陷：py_mini_racer 0.14.x 在两个线程同时构造 MiniRacer 时会让 V8 命中
partition_address_space.cc(243) 断言并 abort 整个进程（退出码 0x80000003）。
IFA 侧表现为 ifa analyze 在 LangGraph 并发执行估值工具时直接猝死。
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import types

import pytest

from ifa.dataflows._mini_racer_guard import (
    _CONSTRUCTION_LOCK,
    _GUARD_MARKER,
    _make_guarded,
    install_mini_racer_guard,
)


class _FakeRacer:
    """只用于验证加锁语义的替身，不触碰 V8。"""

    def __init__(self, value: int = 1) -> None:
        self.value = value


class TestGuardInstallation:
    def test_dataflows_import_installs_the_guard(self) -> None:
        import py_mini_racer

        assert getattr(py_mini_racer.MiniRacer, _GUARD_MARKER, False) is True

    def test_install_is_idempotent(self) -> None:
        import py_mini_racer

        before = py_mini_racer.MiniRacer
        assert install_mini_racer_guard() is True
        assert py_mini_racer.MiniRacer is before

    def test_strict_alias_is_guarded_when_the_build_exposes_it(self) -> None:
        """Linux 上 akshare 拉的是 akracer，它没有 StrictMiniRacer 别名。"""
        import py_mini_racer

        alias = getattr(py_mini_racer, "StrictMiniRacer", None)
        if alias is None:
            pytest.skip("当前 py_mini_racer 构建（Linux 上的 akracer）未导出 StrictMiniRacer")
        assert alias is py_mini_racer.MiniRacer

    def test_alias_is_replaced_when_the_build_exposes_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """不依赖具体构建：别名存在时必须一起换成受保护类。"""
        fake = types.ModuleType("py_mini_racer")
        fake.MiniRacer = _FakeRacer  # type: ignore[attr-defined]
        fake.StrictMiniRacer = _FakeRacer  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "py_mini_racer", fake)

        assert install_mini_racer_guard() is True
        assert getattr(fake.MiniRacer, _GUARD_MARKER, False) is True
        assert fake.StrictMiniRacer is fake.MiniRacer

    def test_missing_library_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "py_mini_racer", None)
        assert install_mini_racer_guard() is False


class TestConstructionIsSerialized:
    def test_guarded_class_blocks_while_lock_is_held(self) -> None:
        guarded = _make_guarded(_FakeRacer)
        started = threading.Event()
        finished = threading.Event()

        def build() -> None:
            started.set()
            guarded(7)
            finished.set()

        with _CONSTRUCTION_LOCK:
            worker = threading.Thread(target=build, daemon=True)
            worker.start()
            assert started.wait(5)
            assert not finished.wait(0.5), "构造必须在锁被释放前阻塞"
        assert finished.wait(5)

    def test_guarded_class_keeps_identity_and_attributes(self) -> None:
        guarded = _make_guarded(_FakeRacer)
        assert guarded.__name__ == "_FakeRacer"
        assert issubclass(guarded, _FakeRacer)
        assert getattr(guarded, _GUARD_MARKER, False) is True
        assert guarded(3).value == 3


class TestConcurrentConstructionInSubprocess:
    def test_four_threads_construct_concurrently(self) -> None:
        pytest.importorskip("py_mini_racer")
        code = textwrap.dedent(
            """
            import threading

            import ifa.dataflows  # noqa: F401  导入即装上并发构造保护
            from py_mini_racer import MiniRacer

            results = []

            def work():
                racer = MiniRacer()
                results.append(racer.eval("1+1"))

            threads = [threading.Thread(target=work) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            print("RESULTS", sorted(results))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "RESULTS [2, 2, 2, 2]" in completed.stdout
