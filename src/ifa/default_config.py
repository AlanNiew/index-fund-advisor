# ifa/default_config.py
"""IFA 默认配置，融合 TradingAgents 的辩论和反思配置。"""

import copy
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
    # 默认走 OpenCode Go 聚合端点（订阅制，OpenAI 兼容协议）；需要在 .env 里配置
    # OPENCODE_API_KEY。base_url 见 llm_clients/openai_client.py 的 _PROVIDER_CONFIG；
    # 下方 backend_url 仅对未内置 base_url 的提供方生效。
    "llm_provider": "opencode",
    "deep_think_llm": "deepseek-v4-pro",
    "quick_think_llm": "deepseek-v4.1-flash",
    "backend_url": "https://opencode.ai/inference/go/v1",
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
    runtime_config = copy.deepcopy(DEFAULT_CONFIG)
    runtime_config.update(load_last_config())
    runtime_config["project_dir"] = PROJECT_DIR
    runtime_config["results_dir"] = os.getenv("IFA_RESULTS_DIR", os.path.join(PROJECT_DIR, "results"))
    runtime_config["data_cache_dir"] = os.path.join(PROJECT_DIR, "dataflows", "data_cache")
    runtime_config["local_data_dir"] = LOCAL_DATA_DIR
    runtime_config["data_tools_cache_dir"] = os.path.join(LOCAL_DATA_DIR, "data_tools", "cache")
    runtime_config["data_tools_snapshot_dir"] = os.path.join(LOCAL_DATA_DIR, "data_tools", "snapshots")
    runtime_config["agent_output_dir"] = os.path.join(LOCAL_DATA_DIR, "agents")
    runtime_config["memory_dir"] = os.path.join(LOCAL_DATA_DIR, "memory")
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
    "memory_dir",
}


def save_last_config(config: dict) -> None:
    """将当前配置原子写入 last_config.py。"""
    serializable_config = {k: v for k, v in config.items() if k not in _PATH_KEYS}
    content = (
        "# 该文件由 CLI 自动生成，用于保存上一次确认后的配置。\n"
        f"LAST_CONFIG = {pformat(serializable_config, width=100, sort_dicts=False)}\n"
    )
    tmp_path = LAST_CONFIG_PATH.with_suffix(".tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(LAST_CONFIG_PATH)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        LAST_CONFIG_PATH.write_text(content, encoding="utf-8")
