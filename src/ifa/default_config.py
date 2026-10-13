# ifa/default_config.py
"""IFA 默认配置，融合 TradingAgents 的辩论和反思配置。"""

import copy
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from ifa.atomic_io import atomic_write_json
from ifa.providers import PROVIDER_CONFIG, canonical_base_urls, default_base_url

# 路径类配置不写入用户配置文件：换机器/换目录后会读到过期绝对路径，
# 它们始终由 PROJECT_DIR / LOCAL_DATA_DIR 现场推导。
_PATH_KEYS = {
    "project_dir",
    "results_dir",
    "data_cache_dir",
    "local_data_dir",
    "data_tools_cache_dir",
    "data_tools_snapshot_dir",
    "agent_output_dir",
    "memory_dir",
}


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


def _user_config_dir() -> str:
    """返回用户配置目录（可用 IFA_CONFIG_DIR 覆盖）。"""
    override = os.getenv("IFA_CONFIG_DIR", "").strip()
    if override:
        return override
    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    else:
        base = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "ifa")


PROJECT_DIR = _find_project_dir()
LOCAL_DATA_DIR = os.getenv(
    "IFA_LOCAL_DATA_DIR",
    os.path.join(PROJECT_DIR, "local_data"),
)

# 用户配置文件（JSON）。放在用户可写目录，而不是已安装包目录：此前配置写在
# <包目录>/last_config.py，pip 安装的用户既不该、常常也无法改 site-packages，
# 升级一次就把配置丢掉。现在 ifa config <key> <value> 会真正写这个文件。
LAST_CONFIG_PATH = Path(_user_config_dir()) / "config.json"

# 旧版配置位置（Python 字面量）。仅作只读兼容：老用户升级后仍能读到原先保存的配置，
# 下一次 save_last_config() 会写到新的 JSON 位置。
LEGACY_LAST_CONFIG_PATH = Path(__file__).with_name("last_config.py")

# 可配置的数据供应商白名单：只列**真正有实现**的名字。
# tushare 曾被列在这里，但 VENDOR_METHODS 中没有任何 tushare 实现，配置它会被
# route_to_vendor 静默回退到 akshare（无日志、无提示）。与其保留「配置了却不生效」
# 的选项，不如让 validate_config 直接报错。新增供应商必须同时补实现。
_KNOWN_DATA_VENDORS = {"akshare"}

# 辩论轮数默认值。AdvisorGraph 在 config 缺键时回退到同一常量——此前那里硬编码 1
# 而这里写 2，配置不完整时辩论轮数会静默减半，与文档描述不符。
DEFAULT_MAX_DEBATE_ROUNDS = 2
DEFAULT_MAX_RISK_DISCUSS_ROUNDS = 2

DEFAULT_CONFIG = {
    "project_dir": PROJECT_DIR,
    "results_dir": os.getenv("IFA_RESULTS_DIR", os.path.join(PROJECT_DIR, "results")),
    "data_cache_dir": os.path.join(PROJECT_DIR, "dataflows", "data_cache"),
    "local_data_dir": LOCAL_DATA_DIR,
    "data_tools_cache_dir": os.path.join(LOCAL_DATA_DIR, "data_tools", "cache"),
    "data_tools_snapshot_dir": os.path.join(LOCAL_DATA_DIR, "data_tools", "snapshots"),
    "agent_output_dir": os.path.join(LOCAL_DATA_DIR, "agents"),
    # BM25 情景记忆落盘目录（见 agents/memory.py）。此前记忆只存在于内存，
    # 正常分析流程中 get_memories() 恒为空——落盘后 Reflector 的经验才能真正跨会话复用。
    "memory_dir": os.path.join(LOCAL_DATA_DIR, "memory"),
    "market_region": "cn_a",
    # ── LLM 配置 ──
    # 注：quick_think_llm 用于工具调用与结构化输出解析，是数据采集链路的根基。
    # 不要用最便宜的 turbo 档——结构化输出在弱模型上不可靠，会污染整条分析管道。
    # 若确需降级，请显式覆盖此配置并接受工具调用失败率上升。
    #
    # 提供方与内置端点见 ifa/providers.py 的 PROVIDER_CONFIG。默认走 OpenCode Go
    # 聚合端点（订阅制，OpenAI 兼容协议），需要在 .env 里配置 OPENCODE_API_KEY。
    # 换提供方的三个入口（优先级从高到低）：环境变量（IFA_LLM_PROVIDER 等）、
    # ifa config llm_provider <name> 写入的用户配置文件、此处默认值。
    "llm_provider": "opencode",
    "deep_think_llm": "deepseek-v4-pro",
    "quick_think_llm": "deepseek-v4.1-flash",
    "backend_url": "https://opencode.ai/inference/go/v1",
    # 自定义提供方（llm_provider="custom"）的凭据：端点复用上面的 backend_url，
    # Key 也可用环境变量 IFA_CUSTOM_API_KEY 提供（推荐，避免明文落在配置文件里）。
    "custom_api_key": None,
    # ── 提供方专属思考参数 ──
    "google_thinking_level": "high",
    "openai_reasoning_effort": "high",
    "anthropic_effort": "high",
    # Azure OpenAI 的 API 版本（仅 azure 提供方使用）
    "azure_api_version": None,
    # ── 输出语言配置 ──
    "internal_language": "English",
    "final_output_language": "Chinese",
    "output_language": "Chinese",
    # ── 分析模式 ──
    "analysis_mode": "deep",
    # ── 辩论设置（借鉴 TradingAgents）──
    "enable_debate": True,
    "max_debate_rounds": DEFAULT_MAX_DEBATE_ROUNDS,
    "max_risk_discuss_rounds": DEFAULT_MAX_RISK_DISCUSS_ROUNDS,
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

#: 可用 ifa config <key> <value> 或环境变量覆盖的键（路径键与嵌套字典除外——
#: data_vendors / tool_vendors 是结构化的，请直接编辑配置文件）。
CONFIGURABLE_KEYS: tuple[str, ...] = tuple(
    sorted(key for key, value in DEFAULT_CONFIG.items() if key not in _PATH_KEYS and not isinstance(value, dict))
)

#: 环境变量覆盖表：优先级 env > 用户配置文件 > DEFAULT_CONFIG。
#: 用途：容器/CI/临时试验不必改任何文件，第三方集成也只依赖这几个变量。
_ENV_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("IFA_LLM_PROVIDER", "llm_provider"),
    ("IFA_DEEP_LLM", "deep_think_llm"),
    ("IFA_QUICK_LLM", "quick_think_llm"),
    ("IFA_BACKEND_URL", "backend_url"),
    ("IFA_CUSTOM_API_KEY", "custom_api_key"),
    ("IFA_ANALYSIS_MODE", "analysis_mode"),
    ("IFA_AZURE_API_VERSION", "azure_api_version"),
    ("IFA_TIMEOUT", "timeout"),
    ("IFA_ENABLE_DEBATE", "enable_debate"),
)

_INT_KEYS = {"timeout", "max_debate_rounds", "max_risk_discuss_rounds", "max_recur_limit", "ohlcv_cache_ttl_seconds"}
_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


def _coerce_config_value(key: str, raw: str) -> Any:
    """把环境变量/CLI 传来的字符串转成配置文件里的类型。

    非法值直接报错：配置类错误的静默降级正是本仓库反复踩到的坑（tushare 白名单、
    过期 backend_url），宁可让命令失败也不要「配了不生效」。
    """
    value = raw.strip()
    if key in _INT_KEYS:
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{key} 需要整数，收到 {raw!r}") from exc
    if key == "enable_debate":
        lowered = value.lower()
        if lowered in _BOOL_TRUE:
            return True
        if lowered in _BOOL_FALSE:
            return False
        raise ValueError(f"enable_debate 需要布尔值（true/false），收到 {raw!r}")
    return value


def _load_json_config(path: Path) -> dict:
    """读取 JSON 配置。文件缺失/损坏/不是对象都返回空字典——配置读失败不该让 CLI 起不来。"""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str)}


def _load_legacy_python_config(path: Path) -> dict:
    """读取旧版 Python 字面量配置（曾写在包目录的 last_config.py）。"""
    if not path.exists():
        return {}
    try:
        spec = importlib.util.spec_from_file_location("ifa.last_config", path)
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


def load_last_config() -> dict:
    """加载用户配置（JSON 优先，其次旧版 last_config.py）。"""
    config = _load_json_config(LAST_CONFIG_PATH)
    if config:
        return config
    if LEGACY_LAST_CONFIG_PATH != LAST_CONFIG_PATH:
        return _load_legacy_python_config(LEGACY_LAST_CONFIG_PATH)
    return {}


def _env_overrides() -> dict:
    """收集环境变量覆盖项；非法值抛 ValueError（而不是被静默忽略）。"""
    overrides: dict = {}
    for env_name, key in _ENV_OVERRIDES:
        raw = os.getenv(env_name)
        if raw is None or not raw.strip():
            continue
        overrides[key] = _coerce_config_value(key, raw)
    return overrides


def validate_config(config: dict) -> None:
    """校验配置字典的合法性。"""
    errors = []

    timeout = config.get("timeout")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        errors.append(f"timeout 必须 > 0，当前值: {timeout}")

    provider = config.get("llm_provider")
    if not provider or not str(provider).strip():
        errors.append("llm_provider 不能为空")
    else:
        provider_name = str(provider).strip().lower()
        if provider_name not in PROVIDER_CONFIG:
            errors.append(f"llm_provider = '{provider}' 不是已知提供方（可选: {', '.join(sorted(PROVIDER_CONFIG))}）")
        elif provider_name == "custom" and not str(config.get("backend_url") or "").strip():
            errors.append(
                "llm_provider = 'custom' 时必须设置 backend_url"
                "（自定义端点的 OpenAI 兼容地址，如 https://your-gateway/v1）"
            )

    vendors = config.get("data_vendors")
    if isinstance(vendors, dict):
        for category, vendor_name in vendors.items():
            if vendor_name not in _KNOWN_DATA_VENDORS:
                errors.append(
                    f"data_vendors['{category}'] = '{vendor_name}' 不是已知供应商"
                    f"（可选: {', '.join(sorted(_KNOWN_DATA_VENDORS))}）"
                )

    if errors:
        raise ValueError("配置校验失败:" + chr(10) + chr(10).join(f"  - {e}" for e in errors))


def _normalize_backend_url(config: dict) -> None:
    """保证 backend_url 与 llm_provider 一致。

    历史漂移：backend_url 曾长期残留上一个提供方的地址（指向智谱而 provider 是 deepseek），
    这种地址会被客户端当作显式覆盖发出去，请求必然失败。这里只在**存的确实是别的提供方的
    内置端点**时丢弃它并回落到所选提供方的默认端点；用户自定义的地址（自建网关、代理）
    原样保留——那正是接第三方端点的用法。
    """
    provider = str(config.get("llm_provider") or "").strip().lower()
    stored = str(config.get("backend_url") or "").strip()
    other_providers = canonical_base_urls() - {default_base_url(provider) or ""}
    if not stored or stored in other_providers:
        config["backend_url"] = default_base_url(provider)


def build_runtime_config() -> dict:
    """构建运行时配置：DEFAULT_CONFIG ← 用户配置文件 ← 环境变量（后者覆盖前者）。"""
    runtime_config = copy.deepcopy(DEFAULT_CONFIG)
    runtime_config.update(load_last_config())
    runtime_config.update(_env_overrides())
    runtime_config["project_dir"] = PROJECT_DIR
    runtime_config["results_dir"] = os.getenv("IFA_RESULTS_DIR", os.path.join(PROJECT_DIR, "results"))
    runtime_config["data_cache_dir"] = os.path.join(PROJECT_DIR, "dataflows", "data_cache")
    runtime_config["local_data_dir"] = LOCAL_DATA_DIR
    runtime_config["data_tools_cache_dir"] = os.path.join(LOCAL_DATA_DIR, "data_tools", "cache")
    runtime_config["data_tools_snapshot_dir"] = os.path.join(LOCAL_DATA_DIR, "data_tools", "snapshots")
    runtime_config["agent_output_dir"] = os.path.join(LOCAL_DATA_DIR, "agents")
    runtime_config["memory_dir"] = os.path.join(LOCAL_DATA_DIR, "memory")
    _normalize_backend_url(runtime_config)
    validate_config(runtime_config)
    return runtime_config


def save_last_config(config: dict) -> None:
    """把当前配置原子写入用户配置文件（JSON）。路径键会被丢弃。"""
    serializable_config = {k: v for k, v in config.items() if k not in _PATH_KEYS}
    atomic_write_json(LAST_CONFIG_PATH, serializable_config)


def set_user_config(key: str, raw_value: str) -> Any:
    """把单个配置项写入用户配置文件，返回写入后的值（类型已按 key 归一）。

    异常：
        ValueError: key 未知，或值无法按该键的类型解析。
    """
    if key not in CONFIGURABLE_KEYS:
        raise ValueError(f"未知配置项: '{key}'（可配置项: {', '.join(CONFIGURABLE_KEYS)}）")
    value = _coerce_config_value(key, raw_value)
    stored = _load_json_config(LAST_CONFIG_PATH)
    stored[key] = value
    atomic_write_json(LAST_CONFIG_PATH, stored)
    return value


def unset_user_config(key: str) -> bool:
    """从用户配置文件删除一个配置项（回落到默认值）；返回是否真的删掉了东西。"""
    if key not in CONFIGURABLE_KEYS:
        raise ValueError(f"未知配置项: '{key}'（可配置项: {', '.join(CONFIGURABLE_KEYS)}）")
    stored = _load_json_config(LAST_CONFIG_PATH)
    if key not in stored:
        return False
    del stored[key]
    if stored:
        atomic_write_json(LAST_CONFIG_PATH, stored)
    else:
        LAST_CONFIG_PATH.unlink(missing_ok=True)
    return True
