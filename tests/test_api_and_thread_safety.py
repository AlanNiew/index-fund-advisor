"""API 端到端测试 + no_proxy 多线程测试。"""

import threading
import time

import pytest


class TestAPIEndpoints:
    """FastAPI TestClient 测试。"""

    @pytest.fixture
    def client(self):
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        with patch("api.routers.analysis._execute_graph", return_value={"report_md": "test report", "mode": "deep"}):
            from api.main import app

            client = TestClient(app)
            yield client

    def test_cors_headers(self, client):
        resp = client.options(
            "/api/v1/tasks",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 204)
        assert "access-control-allow-origin" in resp.headers

    def test_list_tasks_empty(self, client):
        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_index_categories(self, client):
        resp = client.get("/api/v1/indexes/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        assert "tracking_methods" in data

    def test_deep_analyze_creates_task(self, client):
        resp = client.post("/api/v1/analyze/deep", json={"fund_code": "510300"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["mode"] == "deep"
        assert "task_id" in data

    def test_screen_creates_task(self, client):
        resp = client.post("/api/v1/analyze/screen", json={"conditions": "大盘低波动"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["mode"] == "screen"

    def test_portfolio_creates_task(self, client):
        resp = client.post("/api/v1/analyze/portfolio", json={"risk_profile": "moderate"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["mode"] == "portfolio"

    def test_get_task_not_found(self, client):
        resp = client.get("/api/v1/tasks/nonexistent-id")
        assert resp.status_code == 404

    def test_api_key_auth_rejects(self):
        import importlib
        import os

        from fastapi.testclient import TestClient

        original = os.environ.get("IFA_API_KEY")
        os.environ["IFA_API_KEY"] = "test-secret-key"

        try:
            import api.main as main_mod

            importlib.reload(main_mod)

            client = TestClient(main_mod.app, raise_server_exceptions=False)
            resp = client.post("/api/v1/analyze/deep", json={"fund_code": "510300"})
            assert resp.status_code == 401
        finally:
            if original is None:
                os.environ.pop("IFA_API_KEY", None)
            else:
                os.environ["IFA_API_KEY"] = original
            importlib.reload(main_mod)

    def test_api_key_auth_allows(self):
        import importlib
        import os
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        original = os.environ.get("IFA_API_KEY")
        os.environ["IFA_API_KEY"] = "test-secret-key"

        try:
            import api.main as main_mod

            importlib.reload(main_mod)

            with patch("api.routers.analysis._execute_graph", return_value={"report_md": "ok", "mode": "deep"}):
                client = TestClient(main_mod.app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/v1/analyze/deep",
                    json={"fund_code": "510300"},
                    headers={"X-API-Key": "test-secret-key"},
                )
                assert resp.status_code == 200
        finally:
            if original is None:
                os.environ.pop("IFA_API_KEY", None)
            else:
                os.environ["IFA_API_KEY"] = original
            importlib.reload(main_mod)


class TestNoProxyThreadSafety:
    """no_proxy() 上下文管理器线程安全测试。

    新实现通过永久 patch requests.utils.get_environ_proxies + TLS 标记工作，
    不再修改 os.environ，不再修改全局 requests.Session.__init__。
    """

    def test_no_proxy_disables_proxies(self):
        """no_proxy 活跃时，get_environ_proxies 返回空代理。"""
        import requests.utils

        from ifa.dataflows.a_share_common import no_proxy

        # 先触发一次性 patch
        with no_proxy():
            pass

        url = "http://example.com"
        outside = requests.utils.get_environ_proxies(url)
        with no_proxy():
            assert requests.utils.get_environ_proxies(url) == {}
        after = requests.utils.get_environ_proxies(url)
        assert after == outside

    def test_no_proxy_thread_isolation(self):
        """多线程并发进入 no_proxy，TLS 标记互不影响。"""
        import requests.utils

        from ifa.dataflows.a_share_common import no_proxy

        # 先触发一次性 patch
        with no_proxy():
            pass

        url = "http://example.com"
        results = {}
        errors = []

        def inside_worker(tid, hold):
            try:
                with no_proxy():
                    if hold:
                        time.sleep(0.05)
                    results[tid] = requests.utils.get_environ_proxies(url)
            except Exception as e:
                errors.append(e)

        def outside_worker(tid):
            try:
                time.sleep(0.02)
                results[tid] = requests.utils.get_environ_proxies(url)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=inside_worker, args=(1, True))
        t2 = threading.Thread(target=inside_worker, args=(2, False))
        t3 = threading.Thread(target=outside_worker, args=(3,))
        t1.start()
        t2.start()
        t3.start()
        t1.join()
        t2.join()
        t3.join()

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert results.get(1) == {}, f"Thread 1 (in no_proxy) got {results.get(1)}"
        assert results.get(2) == {}, f"Thread 2 (in no_proxy) got {results.get(2)}"

    def test_no_proxy_nested(self):
        """嵌套 no_proxy 上下文，退出后 TLS 标记正确恢复。"""
        import requests.utils

        from ifa.dataflows.a_share_common import no_proxy

        url = "http://example.com"
        with no_proxy():
            assert requests.utils.get_environ_proxies(url) == {}
            with no_proxy():
                assert requests.utils.get_environ_proxies(url) == {}
            assert requests.utils.get_environ_proxies(url) == {}
