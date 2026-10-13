"""
数据源出站请求超时保护的回归测试。

对应缺陷：AkShare 多个接口直接 requests.get(url)（不传 timeout），上游建立连接后
不再返回任何字节时，ifa analyze 会被无限期挂住（实测 oss-ch.csindex.com.cn 挂死
14 分钟：进程存活、CPU 接近 0、日志停滞、try/except 永不触发）。

修复方式不是 socket.setdefaulttimeout —— requests 会把 timeout=None 包成
Timeout(connect=None, read=None) 并显式 sock.settimeout(None)，覆盖 socket 默认值。
本文件把「裸 socket 默认值对 requests 无效」也固化成测试，避免再次走回那条死路。
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
import requests

from ifa.dataflows._network_guard import (
    DATA_SOURCE_TIMEOUT_ENV,
    DEFAULT_DATA_SOURCE_TIMEOUT,
    current_data_source_timeout,
    install_data_source_timeout,
    resolve_data_source_timeout,
)


@pytest.fixture()
def restore_timeout():
    """install_data_source_timeout 会改进程级默认值，结束后必须还原。"""
    original = current_data_source_timeout()
    yield
    install_data_source_timeout(original)


class _BlackHoleServer:
    """接受连接但永不响应的本地服务端，用来制造「读挂死」。"""

    def __init__(self) -> None:
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(4)
        self._server.settimeout(0.2)
        self.port: int = self._server.getsockname()[1]
        self._connections: list[socket.socket] = []
        self._stop = threading.Event()
        threading.Thread(target=self._accept_forever, daemon=True).start()

    def _accept_forever(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self._connections.append(conn)

    def close(self) -> None:
        self._stop.set()
        for conn in self._connections:
            conn.close()
        self._server.close()


class _FixedResponseServer:
    """返回一个固定 200 响应的本地服务端，用来确认正常请求不受影响。"""

    def __init__(self, body: bytes = b"ok") -> None:
        self._body = body
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(4)
        self._server.settimeout(0.2)
        self.port: int = self._server.getsockname()[1]
        self._stop = threading.Event()
        threading.Thread(target=self._serve_forever, daemon=True).start()

    def _serve_forever(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                conn.recv(4096)
                header = (
                    b"HTTP/1.1 200 OK\r\nContent-Length: "
                    + str(len(self._body)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                )
                conn.sendall(header + self._body)
            except OSError:
                pass
            finally:
                conn.close()

    def close(self) -> None:
        self._stop.set()
        self._server.close()


class TestResolveTimeout:
    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(DATA_SOURCE_TIMEOUT_ENV, raising=False)
        assert resolve_data_source_timeout() == DEFAULT_DATA_SOURCE_TIMEOUT

    def test_env_value_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DATA_SOURCE_TIMEOUT_ENV, "12.5")
        assert resolve_data_source_timeout() == 12.5

    @pytest.mark.parametrize("raw", ["abc", "0", "-3", "   "])
    def test_invalid_values_fall_back(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv(DATA_SOURCE_TIMEOUT_ENV, raw)
        assert resolve_data_source_timeout() == DEFAULT_DATA_SOURCE_TIMEOUT


class TestInstall:
    def test_explicit_argument_wins(self, restore_timeout) -> None:
        assert install_data_source_timeout(5.0) == 5.0
        assert current_data_source_timeout() == 5.0

    def test_env_value_is_used_without_argument(self, monkeypatch: pytest.MonkeyPatch, restore_timeout) -> None:
        monkeypatch.setenv(DATA_SOURCE_TIMEOUT_ENV, "7")
        assert install_data_source_timeout() == 7.0
        assert current_data_source_timeout() == 7.0

    def test_wrapping_is_not_stacked(self, restore_timeout) -> None:
        install_data_source_timeout(4.0)
        wrapper = requests.sessions.Session.request
        assert getattr(wrapper, "_ifa_default_timeout_patch", False) is True
        assert callable(getattr(wrapper, "__wrapped__", None))

        install_data_source_timeout(2.0)
        assert requests.sessions.Session.request is wrapper, "重复安装不应叠加包装层"
        assert current_data_source_timeout() == 2.0

    def test_socket_default_is_left_alone(self, restore_timeout) -> None:
        before = socket.getdefaulttimeout()
        install_data_source_timeout(3.0)
        assert socket.getdefaulttimeout() == before


class TestRequestTimeoutInjection:
    def test_request_without_timeout_is_interrupted(self, restore_timeout) -> None:
        install_data_source_timeout(2.0)
        server = _BlackHoleServer()
        try:
            started = time.monotonic()
            with pytest.raises(requests.exceptions.Timeout):
                requests.get(f"http://127.0.0.1:{server.port}/")
            elapsed = time.monotonic() - started
        finally:
            server.close()
        assert elapsed < 10.0, f"请求未被超时中断，耗时 {elapsed:.1f}s"

    def test_session_level_call_is_covered(self, restore_timeout) -> None:
        install_data_source_timeout(2.0)
        server = _BlackHoleServer()
        try:
            with requests.Session() as session:
                started = time.monotonic()
                with pytest.raises(requests.exceptions.Timeout):
                    session.get(f"http://127.0.0.1:{server.port}/")
                elapsed = time.monotonic() - started
        finally:
            server.close()
        assert elapsed < 10.0, f"Session.get 未被超时中断，耗时 {elapsed:.1f}s"

    def test_explicit_timeout_is_preserved(self, restore_timeout) -> None:
        install_data_source_timeout(30.0)
        server = _BlackHoleServer()
        try:
            started = time.monotonic()
            with pytest.raises(requests.exceptions.Timeout):
                requests.get(f"http://127.0.0.1:{server.port}/", timeout=0.5)
            elapsed = time.monotonic() - started
        finally:
            server.close()
        assert elapsed < 5.0, f"显式 timeout=0.5 未被尊重，耗时 {elapsed:.1f}s"

    def test_normal_response_is_unaffected(self, restore_timeout) -> None:
        install_data_source_timeout(5.0)
        server = _FixedResponseServer()
        try:
            response = requests.get(f"http://127.0.0.1:{server.port}/")
        finally:
            server.close()
        assert response.status_code == 200
        assert response.text == "ok"

    def test_socket_default_alone_does_not_protect_requests(self) -> None:
        """固化「socket 默认超时对 requests 无效」这一实测结论。"""
        original_socket_default = socket.getdefaulttimeout()
        original_request = requests.sessions.Session.request
        socket.setdefaulttimeout(1.0)
        requests.sessions.Session.request = original_request.__wrapped__  # type: ignore[attr-defined]
        server = _BlackHoleServer()
        outcome: dict[str, str] = {}

        def call() -> None:
            try:
                requests.get(f"http://127.0.0.1:{server.port}/")
                outcome["result"] = "returned"
            except Exception as exc:  # noqa: BLE001 - 只关心它是否退出
                outcome["result"] = type(exc).__name__

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        try:
            worker.join(3)
            assert worker.is_alive(), "requests 不应受 socket 默认超时约束"
        finally:
            server.close()
            socket.setdefaulttimeout(original_socket_default)
            requests.sessions.Session.request = original_request
        worker.join(10)
        assert outcome.get("result") not in (None, "returned")


class TestPackageImport:
    def test_importing_dataflows_patches_requests(self) -> None:
        import ifa.dataflows  # noqa: F401

        wrapper = requests.sessions.Session.request
        assert getattr(wrapper, "_ifa_default_timeout_patch", False) is True
        assert current_data_source_timeout() > 0
