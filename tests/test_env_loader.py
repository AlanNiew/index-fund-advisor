"""用户配置目录与 .env 加载的测试。

背景：`ifa` 被全局安装（uv tool install）或在 MCP 客户端里被任意 CWD 拉起时，
工作目录里没有 .env，只靠 `load_dotenv()` 会读不到任何 API Key，而报错是
"Missing credentials"，看不出是路径问题。因此用户配置目录必须也是候选位置。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from ifa.env_loader import (
    env_file_candidates,
    find_dotenv_from_cwd,
    load_env_files,
    user_config_dir,
    user_env_path,
)


@pytest.fixture()
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 CWD 与用户配置目录都指到临时目录，避免读到仓库真实的 .env。"""
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("IFA_CONFIG_DIR", str(tmp_path / "cfg"))
    return workdir


def _cleanup_env(*names: str) -> None:
    for name in names:
        os.environ.pop(name, None)


class TestUserConfigDir:
    def test_ifa_config_dir_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IFA_CONFIG_DIR", str(tmp_path / "custom"))
        assert user_config_dir() == str(tmp_path / "custom")
        assert user_env_path() == tmp_path / "custom" / ".env"

    def test_blank_override_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IFA_CONFIG_DIR", "   ")
        assert Path(user_config_dir()).name == "ifa"


class TestCandidates:
    def test_user_env_is_always_a_candidate(self, isolated_cwd: Path) -> None:
        assert user_env_path() in env_file_candidates()

    def test_cwd_env_comes_first(self, isolated_cwd: Path) -> None:
        cwd_env = isolated_cwd / ".env"
        cwd_env.write_text("A=1\n", encoding="utf-8")
        candidates = env_file_candidates()
        assert candidates[0] == cwd_env
        assert candidates[-1] == user_env_path()

    def test_find_dotenv_walks_upwards(self, isolated_cwd: Path) -> None:
        (isolated_cwd / ".env").write_text("A=1\n", encoding="utf-8")
        nested = isolated_cwd / "a" / "b"
        nested.mkdir(parents=True)
        os.chdir(nested)
        assert find_dotenv_from_cwd() == isolated_cwd / ".env"


class TestLoadEnvFiles:
    def test_loads_user_level_env_when_cwd_has_none(self, isolated_cwd: Path) -> None:
        user_env = user_env_path()
        user_env.parent.mkdir(parents=True, exist_ok=True)
        user_env.write_text("IFA_TEST_USER_LEVEL=yes\n", encoding="utf-8")
        _cleanup_env("IFA_TEST_USER_LEVEL")
        try:
            loaded = load_env_files()
            assert loaded == [user_env]
            assert os.environ["IFA_TEST_USER_LEVEL"] == "yes"
        finally:
            _cleanup_env("IFA_TEST_USER_LEVEL")

    def test_cwd_env_wins_over_user_env(self, isolated_cwd: Path) -> None:
        (isolated_cwd / ".env").write_text("IFA_TEST_PRIORITY=cwd\n", encoding="utf-8")
        user_env = user_env_path()
        user_env.parent.mkdir(parents=True, exist_ok=True)
        user_env.write_text("IFA_TEST_PRIORITY=user\n", encoding="utf-8")
        _cleanup_env("IFA_TEST_PRIORITY")
        try:
            load_env_files()
            # override=False：先加载的 CWD 值不会被后面的用户级文件覆盖。
            assert os.environ["IFA_TEST_PRIORITY"] == "cwd"
        finally:
            _cleanup_env("IFA_TEST_PRIORITY")

    def test_existing_environment_variable_is_not_overridden(
        self, isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (isolated_cwd / ".env").write_text("IFA_TEST_KEEP=from_file\n", encoding="utf-8")
        monkeypatch.setenv("IFA_TEST_KEEP", "from_process")
        load_env_files()
        assert os.environ["IFA_TEST_KEEP"] == "from_process"

    def test_missing_files_are_skipped(self, isolated_cwd: Path) -> None:
        assert load_env_files() == []

    def test_unreadable_file_only_warns(
        self, isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        (isolated_cwd / ".env").write_text("A=1\n", encoding="utf-8")

        def _boom(*args: object, **kwargs: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr("ifa.env_loader.load_dotenv", _boom)
        with caplog.at_level(logging.WARNING):
            loaded = load_env_files()
        assert loaded == []
        assert "permission denied" in caplog.text
