#!/usr/bin/env python3
"""组装轻量发行包的 src/：从仓库 src/ifa 复制 MCP + 数据层子集。

复制的范围（自洽、不依赖 langchain/langgraph）：
    ifa/__init__.py        （懒加载版）
    ifa/default_config.py
    ifa/mcp/               （MCP server）
    ifa/data_tools/        （数据工具注册表 + 执行器）
    ifa/dataflows/         （AkShare 封装 + 估值指标）

刻意排除：ifa.common / ifa.graph / ifa.agents / ifa.llm_clients /
ifa.portfolio / ifa.backtest / ifa.observability（重依赖，留给完整版）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "ifa"
DST = HERE / "src" / "ifa"

KEEP_DIRS = ["mcp", "data_tools", "dataflows"]
KEEP_FILES = ["__init__.py", "default_config.py"]


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"找不到源目录：{SRC}")
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    for name in KEEP_FILES:
        shutil.copy2(SRC / name, DST / name)

    for name in KEEP_DIRS:
        shutil.copytree(
            SRC / name,
            DST / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    print(f"[OK] assembled slim src at: {DST}")
    print("  contents:", sorted(p.name for p in DST.iterdir()))


if __name__ == "__main__":
    main()
