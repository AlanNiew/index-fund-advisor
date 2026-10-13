"""依赖锁与 CI 配置的一致性测试 —— 防止「只在 Windows 上装得上」的锁文件再次推到公开仓库。

背景：requirements.lock 里的 pywin32 长期没有平台标记，而它只有 Windows wheel、
在 PyPI 上既无 Linux 分发也无 sdist；CI 跑在 ubuntu-latest，于是
pip install -r requirements.lock 必然失败 —— 修好之前每个 commit 的 CI 都是红的。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "requirements.lock"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# 只在 Windows 上有发行版的包：Linux 上 pip 找不到任何候选（无 wheel、无 sdist），
# 必须带平台标记，否则 ubuntu-latest 上的 CI 会在安装依赖这一步直接失败。
WINDOWS_ONLY_DISTS = {"pywin32"}

_PIN_RE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)(?:\[[^\]]+\])?==(?P<version>[^\s;]+)(?:\s*;\s*(?P<marker>.+))?$")
_LOCAL_PATH_MARKERS = ("-e ", "file://", "@ file", "://")


def _parse_lock() -> dict[str, str | None]:
    """把 requirements.lock 解析成 {包名: 环境标记或 None}。"""
    pins: dict[str, str | None] = {}
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[0].isspace():  # pip-compile 的 "# via ..." 缩进注释
            continue
        match = _PIN_RE.match(stripped)
        assert match, f"requirements.lock 里不是合法的 pin 行：{line!r}"
        pins[match["name"].lower()] = match["marker"]
    return pins


def _requires_python_minimum() -> tuple[int, ...]:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*">=([0-9.]+)"', text)
    assert match, "pyproject.toml 里找不到 requires-python >=X.Y"
    return tuple(int(part) for part in match.group(1).split("."))


def _ci_matrix_versions() -> list[str]:
    text = CI_PATH.read_text(encoding="utf-8")
    match = re.search(r"python-version:\s*\[([^\]]+)\]", text)
    assert match, "ci.yml 里找不到 python-version 矩阵"
    return re.findall(r'"([0-9.]+)"', match.group(1))


class TestLockIsInstallable:
    """锁文件必须在 Linux CI 上装得上，而不只是在本机 Windows 上。"""

    def test_every_requirement_is_pinned_with_equals(self):
        pins = _parse_lock()
        assert len(pins) > 100, "requirements.lock 解析出来的包太少，解析规则可能坏了"

    def test_windows_only_dists_carry_a_platform_marker(self):
        pins = _parse_lock()
        for name in WINDOWS_ONLY_DISTS:
            assert name in pins, f"{name} 不在 requirements.lock 里，请同步维护 WINDOWS_ONLY_DISTS"
            marker = pins[name] or ""
            assert "win32" in marker or "Windows" in marker, (
                f"{name} 只有 Windows 发行版，必须带平台标记（如 '; sys_platform == win32'），"
                f"否则 ubuntu-latest 上的 pip install -r requirements.lock 会失败；当前标记={marker!r}"
            )

    def test_no_local_paths_or_editable_entries(self):
        for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
            for marker in _LOCAL_PATH_MARKERS:
                assert marker not in line, f"锁文件里不允许出现本地路径/可编辑条目：{line!r}"


class TestCiWorkflowWiring:
    """CI 矩阵与门禁必须和 pyproject 声明一致（曾经矩阵覆盖 3.10/3.11 却没有对应 wheel）。"""

    def test_matrix_covers_only_supported_pythons(self):
        minimum = _requires_python_minimum()
        versions = _ci_matrix_versions()
        assert versions, "CI 矩阵为空"
        for version in versions:
            assert tuple(int(part) for part in version.split(".")) >= minimum, (
                f"CI 矩阵里的 {version} 低于 pyproject 声明的 requires-python >= {'.'.join(map(str, minimum))}"
            )

    def test_ci_installs_the_lock_and_keeps_gates_hard(self):
        text = CI_PATH.read_text(encoding="utf-8")
        assert "pip install -r requirements.lock" in text, "CI 必须按锁文件安装依赖"
        assert "continue-on-error" not in text, "质量门禁不允许 continue-on-error（mypy 曾是软门）"
        for command in ("ruff check .", "mypy src", "pytest -q"):
            assert command in text, f"CI 缺少门禁命令：{command}"
