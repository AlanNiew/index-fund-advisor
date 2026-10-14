"""直接导入的第三方模块必须在 pyproject 里声明 —— 防止「开发机能跑、装出来的包起不来」。

背景：``src/ifa/env_loader.py`` 顶层 ``from dotenv import load_dotenv``，但 python-dotenv 从未写进
``pyproject.toml`` 的 dependencies。开发环境里它是被 streamlit → pydantic-settings 顺带装上的，所以本地
一切正常；wheel 装进干净 venv 后 ``ifa --help`` 直接
``ModuleNotFoundError: No module named 'dotenv'``（C1 的发行冒烟才发现）。

规则：``src/ifa`` 里 import 的任何第三方顶层模块，其发行版必须出现在 pyproject 的 dependencies 或
optional-dependencies 中。例外只有 ``OPTIONAL_IMPORTS`` 里显式登记（并写明理由）的那几个。
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "ifa"

# 仓库内自己的顶层包：靠入口模块注入 sys.path，不走依赖声明。
LOCAL_TOP_LEVEL = {"ifa", "api", "web", "scripts"}

# 允许「不声明」的例外，值必须写清理由。
OPTIONAL_IMPORTS = {
    # akshare 按平台提供 V8 包装器（非 Linux 是 mini-racer，Linux 是 akracer / py-mini-racer），
    # 而 _mini_racer_guard 在它缺失时静默跳过 —— 声明其中任何一个都会在另一个平台上装错包。
    "py_mini_racer": "akshare 按平台提供的可选 V8 包装器，guard 在缺失时静默跳过",
}


def _requirement_name(requirement: str) -> str:
    """'langchain-core>=0.3.81,<2' -> 'langchain-core'"""
    return re.split(r"[<>=!\[; ]", requirement.strip())[0].lower().replace("_", "-")


def _declared_distributions() -> set[str]:
    """pyproject 里声明的全部发行版名（dependencies + 所有 extras）。"""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    declared = {_requirement_name(item) for item in project.get("dependencies", [])}
    for extra in project.get("optional-dependencies", {}).values():
        declared |= {_requirement_name(item) for item in extra}
    return declared


def _imported_top_level_modules() -> dict[str, list[str]]:
    """{顶层模块名: ["src/ifa/xxx.py:12", ...]}，含函数内 import（调用时同样会失败）。"""
    found: dict[str, list[str]] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                found.setdefault(name, []).append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


class TestDeclaredDependencies:
    """任何被直接导入的发行版都必须直接声明，不能靠别的包顺带装上。"""

    def test_third_party_imports_are_declared(self):
        declared = _declared_distributions()
        distribution_by_module = packages_distributions()
        offenders: list[str] = []
        for module, sites in sorted(_imported_top_level_modules().items()):
            if module in sys.stdlib_module_names or module in LOCAL_TOP_LEVEL:
                continue
            if module in OPTIONAL_IMPORTS:
                continue
            candidates = {name.lower().replace("_", "-") for name in distribution_by_module.get(module, [])}
            candidates = candidates or {module.lower().replace("_", "-")}
            if candidates & declared:
                continue
            places = ", ".join(sorted(set(sites))[:4])
            offenders.append(f"{module}（发行版 {sorted(candidates)}）出现在 {places}")
        assert not offenders, (
            "以下第三方模块被 src/ifa 直接导入，但没写进 pyproject 的 dependencies / optional-dependencies：\n"
            + "\n".join(f"  - {item}" for item in offenders)
            + "\n请在 pyproject.toml 里直接声明（或加进本测试的 OPTIONAL_IMPORTS 并写明理由）。"
        )

    def test_optional_imports_stay_documented(self):
        imported = _imported_top_level_modules()
        for module, reason in OPTIONAL_IMPORTS.items():
            assert reason.strip(), f"{module} 的例外理由不能为空"
            assert module in imported, f"{module} 已不再被导入，请从 OPTIONAL_IMPORTS 里删掉"
