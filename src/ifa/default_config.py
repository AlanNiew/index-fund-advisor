# ifa/default_config.py
"""IFA 默认配置，融合 TradingAgents 的辩论和反思配置。"""

import importlib.util
import os
from pathlib import Path
from pprint import pformat

LAST_CONFIG_PATH = Path(__file__).with_name("last_config.py")


def _find_project_dir() -> str:
    """从 default_config.py 向上查找项目根目录（含 pyproject.toml）。"""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isfile(os.path.join(current, "pyproject.toml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


PROJECT_DIR = _find_project_dir()
LOCAL_DATA_DIR = os.getenv(
    "IFA_LOCAL_DATA_DIR",
    os.path.join(PROJECT_DIR, "local_data"),
)

_KNOWN_DATA_VENDORS = {"akshare"}

DEFAULT_CONFIG = {
    "project_dir": PROJECT_DIR,
    "results_dir": os.getenv("IFA_RESULTS_DIR", os.path.join(PROJECT_DIR, "results")),
    "data_cache_dir": os.path.join(PROJECT_DIR, "dataflows", "data_cache"),
    "local_data_dir": LOCAL_DATA_DIR,
    "data_tools_cache_dir": os.path.join(LOCAL_DATA_DIR, "data_tools", "cache"),
    "data_tools_snapshot_dir": os.path.join(LOCAL_DATA_DIR, "data_tools", "snapshots"),
    "agent_output_dir": os.path.join(LOCAL_DATA_DIR, "agents"),
    "market_region": "cn_a",
    # ── LLM 配置 ──
    "llm_provider": "zhipu",
    "deep_think_llm": "glm-5.1",
    "quick_think_llm": "glm-5-turbo",
    "backend_url": "https://open.bigmodel.cn/api/coding/paas/v4",
    # ── 提供方专属思考参数 ──
    "google_thinking_level": "high",
    "openai_reasoning_effort": "high",
    "anthropic_effort": "high",
    # ── 输出语言配置 ──
    "internal_language": "English",
    "final_output_language": "Chinese",
    "output_language": "Chinese",
    # ── 分析模式 ──
    "analysis_mode": "deep",
    # ── 辩论设置（借鉴 TradingAgents）──
    "enable_debate": True,
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    # ── 图执行 ──
    "max_recur_limit": 150,
    "timeout": 180,
    # ── 数据供应商配置 ──
    "data_vendors": {
        "etf_index_apis": "akshare",
        "public_fund": "akshare",
    },
    "tool_vendors": {},
    # ── 缓存有效期（秒）──
    "ohlcv_cache_ttl_seconds": 86400,
}


def load_last_config() -> dict:
    """加载上一次 CLI 保存的配置。"""
    if not LAST_CONFIG_PATH.exists():
        return {}
    try:
        spec = importlib.util.spec_from_file_location("ifa.last_config", LAST_CONFIG_PATH)
        if spec is None or spec.loader is None:
            return {}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = getattr(module, "LAST_CONFIG", {})
        if isinstance(config, dict):
            return config.copy()
    except Exception:
        return {}
    return {}


def validate_config(config: dict) -> None:
    """校验配置字典的合法性。"""
    errors = []

    timeout = config.get("timeout")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        errors.append(f"timeout 必须 > 0，当前值: {timeout}")

    provider = config.get("llm_provider")
    if not provider or not str(provider).strip():
        errors.append("llm_provider 不能为空")

    vendors = config.get("data_vendors")
    if isinstance(vendors, dict):
        for category, vendor_name in vendors.items():
            if vendor_name not in _KNOWN_DATA_VENDORS:
                errors.append(
                    f"data_vendors['{category}'] = '{vendor_name}' 不是已知供应商"
                    f"（可选: {', '.join(sorted(_KNOWN_DATA_VENDORS))}）"
                )

    if errors:
        raise ValueError("配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors))


def build_runtime_config() -> dict:
    """构建运行时配置，基于默认配置叠加上一次 CLI 保存的配置。"""
    runtime_config = DEFAULT_CONFIG.copy()
    runtime_config.update(load_last_config())
    runtime_config["project_dir"] = PROJECT_DIR
    runtime_config["results_dir"] = os.getenv("IFA_RESULTS_DIR", os.path.join(PROJECT_DIR, "results"))
    runtime_config["data_cache_dir"] = os.path.join(PROJECT_DIR, "dataflows", "data_cache")
    runtime_config["local_data_dir"] = LOCAL_DATA_DIR
    runtime_config["data_tools_cache_dir"] = os.path.join(LOCAL_DATA_DIR, "data_tools", "cache")
    runtime_config["data_tools_snapshot_dir"] = os.path.join(LOCAL_DATA_DIR, "data_tools", "snapshots")
    runtime_config["agent_output_dir"] = os.path.join(LOCAL_DATA_DIR, "agents")
    validate_config(runtime_config)
    return runtime_config


_PATH_KEYS = {
    "project_dir",
    "results_dir",
    "data_cache_dir",
    "local_data_dir",
    "data_tools_cache_dir",
    "data_tools_snapshot_dir",
    "agent_output_dir",
}


def save_last_config(config: dict) -> None:
    """将当前配置写入 last_config.py。"""
    serializable_config = {k: v for k, v in config.items() if k not in _PATH_KEYS}
    LAST_CONFIG_PATH.write_text(
        "# 该文件由 CLI 自动生成，用于保存上一次确认后的配置。\n"
        f"LAST_CONFIG = {pformat(serializable_config, width=100, sort_dicts=False)}\n",
        encoding="utf-8",
    )
