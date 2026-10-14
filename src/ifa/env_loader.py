# ifa/env_loader.py
"""用户配置目录与 .env 加载 —— 让全局安装的 CLI / MCP 在任意目录都能读到 API Key。

为什么需要它：`load_dotenv()` 只从当前工作目录向上查找 .env。`ifa` 一旦被装成全局
命令（`uv tool install`）或被 MCP 客户端在任意目录拉起，CWD 里就没有 .env，所有
API Key 都读不到、分析必然失败 —— 而报错是 "Missing credentials"，看不出是路径问题。

因此在 CWD 之外补上用户配置目录这一个位置。优先级（先加载者生效，
`load_dotenv(override=False)` 不会覆盖已存在的环境变量）：

1. 当前工作目录向上找到的 .env（开发时的常规位置，也是项目根的 .env）
2. 用户配置目录 `<APPDATA>/ifa/.env`（可用 `IFA_CONFIG_DIR` 覆盖）

本模块只依赖 python-dotenv 与标准库，刻意不导入 `ifa.default_config`：
后者反过来要用这里的 `user_config_dir()`，且 `ifa search` / `ifa info`
不该为了读一个路径就把整个配置体系拉起来。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def user_config_dir() -> str:
    """返回用户配置目录（可用 IFA_CONFIG_DIR 覆盖）。"""
    override = os.getenv("IFA_CONFIG_DIR", "").strip()
    if override:
        return override
    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    else:
        base = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "ifa")


def user_env_path() -> Path:
    """用户级 .env 路径 —— 全局安装后 API Key 的推荐存放位置。"""
    return Path(user_config_dir()) / ".env"


def find_dotenv_from_cwd() -> Path | None:
    """从当前工作目录向上查找 .env；找不到返回 None。"""
    current = Path.cwd()
    for _ in range(6):
        candidate = current / ".env"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def env_file_candidates() -> list[Path]:
    """按优先级返回待加载的 .env 路径（不判断文件是否存在）。"""
    candidates: list[Path] = []
    found = find_dotenv_from_cwd()
    if found is not None:
        candidates.append(found)
    user_env = user_env_path()
    if user_env not in candidates:
        candidates.append(user_env)
    return candidates


def load_env_files() -> list[Path]:
    """加载全部存在的 .env，返回实际加载成功的文件列表（供日志与测试使用）。

    读文件失败（权限、编码、坏路径）只记 warning：缺 Key 会在真正调用 LLM 时
    给出明确报错，不该在启动阶段就让整个 CLI 崩掉。
    """
    loaded: list[Path] = []
    for candidate in env_file_candidates():
        if not candidate.is_file():
            continue
        try:
            load_dotenv(candidate, override=False)
        except OSError as exc:
            logger.warning("加载 %s 失败：%s", candidate, exc)
            continue
        loaded.append(candidate)
    return loaded
