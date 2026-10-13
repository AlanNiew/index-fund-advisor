# ifa/atomic_io.py
"""原子文件写入工具。

被 `common.py`（报告）、`observability/tracer.py`（追踪）、`agents/memory.py`（记忆）
等多处复用。单独成模块的原因：`agents/memory.py` 是叶子模块，不该为了写一个 JSON
就去 import 处于组合根位置的 `ifa.common`——后者会连带拉起 langgraph / langchain 全栈
（实测单次导入约 25 秒），既拖慢调用方，也把依赖方向倒置了。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def atomic_write_text(path: str | os.PathLike, content: str) -> None:
    """原子写文本:先写 tmp 文件,再 Path.replace 原子改名。

    参考 default_config.save_last_config 的模式。replace 失败则清理 tmp 并降级为直写
    (非原子但保证能写,避免 tmp 残留或写入完全失败)。
    """
    atomic_write(path, lambda t: t.write_text(content, encoding="utf-8"))


def atomic_write_json(path: str | os.PathLike, obj: Any) -> None:
    """原子写 JSON。"""
    atomic_write(path, lambda t: t.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8"))


def atomic_write(path: str | os.PathLike, write_fn: Callable[[Path], Any]) -> None:
    """原子写内部实现:tmp 文件 → Path.replace,失败兜底直写。

    write_fn(tmp_path) 负责把内容写到 tmp 文件。tmp 与目标同目录(同文件系统)保证 replace 原子。
    返回值被忽略——Path.write_text() 返回写入字符数，签名不能收窄为 None。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        write_fn(tmp)
        tmp.replace(target)
    except Exception:
        with contextlib.suppress(Exception):
            tmp.unlink(missing_ok=True)
        # 兜底:非原子直写。崩溃可能截断,但好过完全不写
        logger.warning("原子写失败,降级为直写: %s", target)
        write_fn(target)
