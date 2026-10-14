"""依赖锁与 CI 配置的一致性测试 —— 防止「只在 Windows 上装得上」的锁文件再次推到公开仓库。

背景：requirements.lock 里的 pywin32 长期没有平台标记，而它只有 Windows wheel、
在 PyPI 上既无 Linux 分发也无 sdist；CI 跑在 ubuntu-latest，于是
pip install -r requirements.lock 必然失败 —— 修好之前每个 commit 的 CI 都是红的。

第二类是反向的：锁文件在 Windows 上生成，只固定了 akshare 在非 Linux 上需要的 mini-racer，
而 Linux 上 akshare 要的是 akracer 与 py-mini-racer（三个包都往同一个 py_mini_racer/ 目录写
文件）。ubuntu-latest 于是会在锁之外补装，实际生效的 py_mini_racer 变成 akracer（没有
StrictMiniRacer 别名）—— tests/test_mini_racer_guard.py 因此成为 CI 上唯一的失败用例。
"""

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

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


def _normalize_marker(marker: str) -> str:
    """把环境标记压成可比较的形式（去掉空白与引号风格差异）。"""
    return re.sub(r"\s+", "", marker).replace('"', "'")


class TestPlatformConditionalDependencies:
    """akshare 的 V8 包装器按平台分流，锁文件必须带同样的标记。

    akshare 1.18.64 元数据：mini-racer 仅非 Linux，akracer 与 py-mini-racer 仅 Linux。
    三者都往同一个顶层目录 py_mini_racer/ 写文件。锁文件是 pip-compile 在 Windows 上生成的，
    原先只固定了 mini-racer，于是 ubuntu-latest 会在锁之外自行补装另外两个包：可复现性被
    破坏，且实际生效的 py_mini_racer 变成 akracer（没有 StrictMiniRacer 别名）——
    曾让 tests/test_mini_racer_guard.py 成为 CI 上唯一的失败用例。
    """

    def test_racer_pins_carry_the_same_platform_markers_as_akshare(self):
        from importlib.metadata import requires

        pins = _parse_lock()
        racer_deps = [dep for dep in (requires("akshare") or []) if "racer" in dep.lower()]
        assert racer_deps, "akshare 元数据里应当有 racer 依赖，否则本测试失去意义"
        for dep in racer_deps:
            requirement, _, marker = dep.partition(";")
            name = requirement.split(">=")[0].split("==")[0].strip().lower()
            assert name in pins, f"{name} 不在 requirements.lock 里（akshare 依赖：{dep}）"
            if not marker.strip():
                continue
            locked = pins[name] or ""
            assert locked, (
                f"{name} 在锁文件里没有平台标记；akshare 声明的是 {marker.strip()}，"
                "否则 Linux CI 会在锁之外再装一个同目录的包"
            )
            assert _normalize_marker(locked) == _normalize_marker(marker), (
                f"{name} 的平台标记与 akshare 声明不一致：锁={locked!r}，akshare={marker.strip()!r}"
            )


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


def _declared_requirements() -> list[str]:
    """pyproject.toml 声明的全部依赖（dependencies + 所有 extras）。"""
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = data["project"]
    declared = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        declared.extend(extra)
    return declared


def _declared_extras() -> dict[str, list[str]]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return dict(data["project"].get("optional-dependencies", {}))


def _parse_lock_versions() -> dict[str, str]:
    """把 requirements.lock 解析成 {包名: 版本}。"""
    versions: dict[str, str] = {}
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line[0].isspace():
            continue
        match = _PIN_RE.match(stripped)
        assert match, f"requirements.lock 里不是合法的 pin 行：{line!r}"
        versions[match["name"].lower()] = match["version"]
    return versions


def _parse_lock_via() -> dict[str, str]:
    """{包名: 该 pin 下方 '# via' 注释原文}（兼容 pip-compile 的单行与多行写法）。"""
    via: dict[str, str] = {}
    current: str | None = None
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            current = None
            continue
        if stripped.startswith("#"):
            if current is not None and line.startswith("    #"):
                via[current] = f"{via.get(current, '')} {stripped.lstrip('#').strip()}".strip()
            continue
        if line[0].isspace():
            continue
        match = _PIN_RE.match(stripped)
        if match:
            current = match["name"].lower()
            via.setdefault(current, "")
    return via


class TestDeclaredDependenciesStayInTheLock:
    """pyproject 里声明的依赖必须在锁文件里被标注为「本项目直接依赖」。

    新增依赖却忘了重新生成锁文件时，锁里要么没有这个包、要么 '# via' 注释里没有
    'index-fund-advisor (pyproject.toml)' —— 前者会在干净环境里装不上，后者说明锁已经过期。
    """

    def test_every_declared_requirement_is_annotated(self):
        via = _parse_lock_via()
        missing: list[str] = []
        for requirement in _declared_requirements():
            name = Requirement(requirement).name.lower()
            if name not in via:
                missing.append(f"{name}（锁文件里完全没有）")
            elif "index-fund-advisor (pyproject.toml)" not in via[name]:
                missing.append(f"{name}（# via 里没有 index-fund-advisor (pyproject.toml)：{via[name]!r}）")
        assert not missing, (
            "以下依赖在 pyproject.toml 里声明了，但 requirements.lock 没有对应标注：\n"
            + "\n".join(f"  - {item}" for item in missing)
            + "\n请重新生成锁文件："
            "pip-compile pyproject.toml --extra dev --extra mcp --no-emit-index-url -o requirements.lock"
        )

    def test_extra_bounds_allow_the_locked_version(self):
        """extra 的版本上限不能把锁里已经钉死（并已验证）的版本排除掉。"""
        versions = _parse_lock_versions()
        problems: list[str] = []
        for extra, requirements in _declared_extras().items():
            for requirement in requirements:
                parsed = Requirement(requirement)
                locked = versions.get(parsed.name.lower())
                if locked is None:
                    continue
                if not parsed.specifier.contains(locked):
                    problems.append(f"[{extra}] {requirement} 不允许锁里的 {locked}")
        assert not problems, "\n".join(problems)

    def test_mcp_extra_stays_on_v1_because_the_server_uses_fastmcp(self):
        """mcp 2.x 移除了 mcp.server.fastmcp，extra 必须挡在 2.x 之外。"""
        requirements = [Requirement(item) for item in _declared_extras()["mcp"]]
        mcp_requirement = next(item for item in requirements if item.name.lower() == "mcp")
        assert not mcp_requirement.specifier.contains("2.0"), (
            "mcp 2.x 把 FastMCP 改名 MCPServer（mcp.server.fastmcp 已不存在），"
            "src/ifa/mcp/server.py 用的是 1.x API；请保持 mcp>=1.0,<2"
        )
        locked = _parse_lock_versions()["mcp"]
        assert mcp_requirement.specifier.contains(locked), (
            f"锁里的 mcp {locked} 不满足 extra 约束 {mcp_requirement.specifier}"
        )
