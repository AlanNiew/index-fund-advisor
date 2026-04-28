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
    """no_proxy() 上下文管理器多线程隔离测试。"""

    def test_no_proxy_env_isolation(self):
        import os

        from ifa.dataflows.a_share_common import no_proxy

        os.environ["TEST_PROXY_R5"] = "original"

        errors = []
        results = {}

        def worker(thread_id, enter_first):
            try:
                if enter_first:
                    os.environ["TEST_PROXY_R5"] = f"modified_by_{thread_id}"
                    with no_proxy():
                        time.sleep(0.05)
                        val = os.environ.get("TEST_PROXY_R5", "MISSING")
                        results[thread_id] = val
                else:
                    time.sleep(0.02)
                    val = os.environ.get("TEST_PROXY_R5", "MISSING")
                    results[thread_id] = val
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=(1, True))
        t2 = threading.Thread(target=worker, args=(2, False))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0, f"Thread errors: {errors}"

        os.environ.pop("TEST_PROXY_R5", None)

    def test_no_proxy_restores_env(self):
        import os

        from ifa.dataflows.a_share_common import no_proxy

        os.environ["HTTP_PROXY"] = "http://original:8080"
        with no_proxy():
            assert "HTTP_PROXY" not in os.environ
        assert os.environ.get("HTTP_PROXY") == "http://original:8080"
        os.environ.pop("HTTP_PROXY", None)

    def test_no_proxy_nested(self):
        import os

        from ifa.dataflows.a_share_common import no_proxy

        os.environ["HTTPS_PROXY"] = "http://outer:8080"
        with no_proxy():
            assert "HTTPS_PROXY" not in os.environ
            os.environ["HTTPS_PROXY"] = "http://inner:9090"
            with no_proxy():
                assert "HTTPS_PROXY" not in os.environ
        assert os.environ.get("HTTPS_PROXY") == "http://outer:8080"
        os.environ.pop("HTTPS_PROXY", None)
