#!/usr/bin/env python3
"""组装轻量发行包的 src/：从仓库 src/ifa 复制 MCP + 数据层子集。

复制的范围（自洽、不依赖 langchain/langgraph）：
    ifa/__init__.py        （懒加载版，import ifa 不会拉起分析引擎）
    ifa/default_config.py
    ifa/atomic_io.py       （default_config 的原子写）
    ifa/env_loader.py      （default_config / mcp 的 .env 与用户配置目录定位）
    ifa/providers.py       （default_config 的提供方清单）
    ifa/mcp/               （MCP server）
    ifa/data_tools/        （数据工具注册表 + 执行器）
    ifa/dataflows/         （AkShare 封装 + 估值指标 + MiniRacer/网络两个全局 guard）

刻意排除：ifa.common / ifa.graph / ifa.agents / ifa.llm_clients /
ifa.portfolio / ifa.backtest / ifa.observability（重依赖，留给完整版）。
mcp/server.py 的 analyze_fund 在缺少 ifa.common 时返回可操作错误，不会崩。

用法：
    python assemble.py             # 输出到 release/src/ifa
    python assemble.py <目标目录>   # 输出到指定目录（测试用临时目录）

复制前会自检「模块顶层 ifa 导入闭包」：任何被引用却没被复制的模块都会立刻报错退出，
而不是等到用户 import 时才 ModuleNotFoundError（历史上正是这样漏掉过 env_loader /
providers / atomic_io）。tests/test_release_package.py 会独立复算这条闭包。
"""

from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "ifa"
DST = HERE / "src" / "ifa"

KEEP_DIRS = ["mcp", "data_tools", "dataflows"]
KEEP_FILES = [
    "__init__.py",
    "default_config.py",
    "atomic_io.py",
    "env_loader.py",
    "providers.py",
]


def _module_level_ifa_imports(path: Path) -> set[str]:
    """返回文件里模块顶层（不含函数内的延迟导入）引用的 ifa 子模块名。"""
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


def _copied_relative_paths() -> set[str]:
    """相对 src/ifa 的「将被复制」文件集合（用于闭包自检）。"""
    copied = set(KEEP_FILES)
    for name in KEEP_DIRS:
        for path in (SRC / name).rglob("*.py"):
            copied.add(path.relative_to(SRC).as_posix())
    return copied


def _check_closure() -> list[str]:
    """自检：被模块顶层导入的 ifa 子模块必须都在复制范围内。"""
    copied = _copied_relative_paths()
    problems: list[str] = []
    for rel in sorted(copied):
        for dep in sorted(_module_level_ifa_imports(SRC / rel)):
            if dep == "ifa":
                continue
            parts = dep.split(".")[1:]
            candidates = {"/".join(parts) + ".py", "/".join(parts) + "/__init__.py"}
            if not (candidates & copied):
                problems.append(f"{rel} 顶层导入 {dep}，但它不在复制范围内")
    return problems


def assemble(dst: Path = DST) -> Path:
    """把轻量包需要的子集复制到 dst（dst 即 ifa 包目录），返回 dst。"""
    if not SRC.exists():
        raise SystemExit(f"找不到源目录：{SRC}")

    problems = _check_closure()
    if problems:
        raise SystemExit("复制范围自检失败：\n  " + "\n  ".join(problems))

    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    for name in KEEP_FILES:
        shutil.copy2(SRC / name, dst / name)

    for name in KEEP_DIRS:
        shutil.copytree(
            SRC / name,
            dst / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    return dst


def main() -> None:
    dst = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DST
    assemble(dst)
    print(f"[OK] assembled slim src at: {dst}")
    print("  contents:", sorted(p.name for p in dst.iterdir()))


if __name__ == "__main__":
    main()
