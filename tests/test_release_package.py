"""轻量发行包（release/assemble.py）与 wheel 能力边界的测试。

背景：assemble.py 用白名单从 src/ifa 复制子集，历史上漏掉过 ifa.env_loader /
ifa.providers / ifa.atomic_io —— 轻量包里 import ifa.default_config（乃至 ifa-mcp
启动）直接 ModuleNotFoundError。这里用「模块顶层 ifa 导入闭包」把它钉住，并在临时
目录里真正组装一次、用「看不到仓库 src」的解释器 import 一遍（顺带断言没拉起
langchain/langgraph）。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSEMBLE_PATH = REPO_ROOT / "release" / "assemble.py"
SRC_IFA = REPO_ROOT / "src" / "ifa"
SHARED_LEAF_MODULES = ["atomic_io.py", "env_loader.py", "providers.py"]
GLOBAL_GUARDS = ["_mini_racer_guard.py", "_network_guard.py"]
HEAVY_LAYERS = ["common.py", "graph", "agents", "llm_clients", "backtest", "observability", "portfolio"]


def _load_assemble() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ifa_release_assemble", ASSEMBLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_level_ifa_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    deps: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "ifa" or alias.name.startswith("ifa."):
                    deps.add(alias.name)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and (node.module == "ifa" or node.module.startswith("ifa."))
        ):
            deps.add(node.module)
    return deps


class TestSlimClosure:
    """白名单必须覆盖轻量包里所有模块顶层的 ifa 导入。"""

    def test_every_module_level_import_is_inside_the_keep_list(self) -> None:
        asm = _load_assemble()
        copied = set(asm.KEEP_FILES)
        for name in asm.KEEP_DIRS:
            copied |= {p.relative_to(SRC_IFA).as_posix() for p in (SRC_IFA / name).rglob("*.py")}
        violations: list[str] = []
        for rel in sorted(copied):
            for dep in sorted(_module_level_ifa_imports(SRC_IFA / rel)):
                if dep == "ifa":
                    continue
                parts = dep.split(".")[1:]
                if not ({"/".join(parts) + ".py", "/".join(parts) + "/__init__.py"} & copied):
                    violations.append(f"{rel} -> {dep}")
        assert violations == [], f"轻量包引用了未复制的模块：{violations}"

    def test_shared_leaf_modules_are_explicitly_kept(self) -> None:
        asm = _load_assemble()
        for name in SHARED_LEAF_MODULES:
            assert name in asm.KEEP_FILES, f"{name} 必须显式列入 KEEP_FILES"

    def test_heavy_layers_stay_excluded(self) -> None:
        asm = _load_assemble()
        for name in HEAVY_LAYERS:
            assert name not in asm.KEEP_FILES
            assert name not in asm.KEEP_DIRS


class TestAssemble:
    def test_assemble_copies_shared_modules_and_guards(self, tmp_path: Path) -> None:
        asm = _load_assemble()
        dst = asm.assemble(tmp_path / "ifa")
        for name in [*asm.KEEP_FILES, *SHARED_LEAF_MODULES]:
            assert (dst / name).is_file(), f"缺少 {name}"
        for name in GLOBAL_GUARDS:
            assert (dst / "dataflows" / name).is_file(), f"缺少 dataflows/{name}"
        assert (dst / "mcp" / "server.py").is_file()
        assert (dst / "data_tools" / "builtin.py").is_file()

    def test_assemble_does_not_write_into_the_repo(self, tmp_path: Path) -> None:
        asm = _load_assemble()
        release_src = REPO_ROOT / "release" / "src"
        existed = release_src.exists()
        asm.assemble(tmp_path / "ifa")
        assert release_src.exists() == existed, "测试不得往 release/src 写生成物"

    def test_assemble_replaces_previous_output(self, tmp_path: Path) -> None:
        asm = _load_assemble()
        first = asm.assemble(tmp_path / "ifa")
        (first / "stale.py").write_text("x = 1", encoding="utf-8")
        second = asm.assemble(tmp_path / "ifa")
        assert not (second / "stale.py").exists()


class TestSlimPackageImports:
    """真正组装一次，再用「看不到仓库 src」的解释器 import 轻量包。"""

    _PROBE = '''
import json
import sys
from pathlib import Path

repo_src = Path(sys.argv[1]).resolve()
slim_src = Path(sys.argv[2]).resolve()
kept = []
for entry in sys.path:
    if not entry:
        continue
    try:
        if Path(entry).resolve() == repo_src:
            continue
    except OSError:
        pass
    kept.append(entry)
sys.path = kept
sys.path.insert(0, str(slim_src))

import ifa
import ifa.default_config
import ifa.data_tools.api
import ifa.mcp.server
from ifa.data_tools.builtin import create_default_data_tool_registry

heavy = sorted(
    name
    for name in sys.modules
    if name.split(".")[0] in {"langchain", "langchain_core", "langchain_openai", "langgraph", "anthropic"}
)
print(
    "PROBE_JSON:"
    + json.dumps(
        {
            "ifa_file": ifa.__file__,
            "config_file": ifa.default_config.__file__,
            "tool_count": len(create_default_data_tool_registry().list_tools()),
            "heavy": heavy,
        }
    )
)
'''

    def _run_probe(self, tmp_path: Path) -> dict:
        asm = _load_assemble()
        dst = asm.assemble(tmp_path / "src" / "ifa")
        probe = tmp_path / "probe.py"
        probe.write_text(self._PROBE, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(probe), str(REPO_ROOT / "src"), str(dst.parent)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert proc.returncode == 0, f"轻量包 import 失败：{proc.stderr[-2000:]}"
        line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("PROBE_JSON:"))
        return json.loads(line[len("PROBE_JSON:") :])

    def test_slim_tree_imports_without_langchain(self, tmp_path: Path) -> None:
        payload = self._run_probe(tmp_path)
        dst = tmp_path / "src" / "ifa"
        assert Path(payload["ifa_file"]).is_relative_to(dst), "轻量包被仓库内的 ifa 遮蔽了"
        assert Path(payload["config_file"]).is_relative_to(dst)
        assert payload["tool_count"] >= 30
        assert payload["heavy"] == [], f"轻量包拉起了重依赖：{payload['heavy']}"


class TestWheelBoundaries:
    """wheel / 全局安装只含 ifa 包：Web 界面必须给出可操作报错而不是崩在路径上。"""

    def test_ifa_web_reports_missing_checkout(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        from ifa.cli import web_entry

        monkeypatch.setattr(web_entry.os.path, "exists", lambda _path: False)
        with pytest.raises(SystemExit) as excinfo:
            web_entry.main()
        assert excinfo.value.code == 1
        assert "需要仓库检出" in capsys.readouterr().err
