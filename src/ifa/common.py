# ifa/common.py
"""CLI / Web / API 共享的初始化与工具函数。"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from ifa.atomic_io import atomic_write_json, atomic_write_text
from ifa.graph.advisor_graph import AdvisorGraph
from ifa.llm_clients.factory import create_llm_client

logger = logging.getLogger(__name__)


def get_provider_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    """根据配置构建 LLM 提供方专属参数。"""
    kwargs: dict[str, Any] = {}
    provider = config.get("llm_provider", "").lower()

    if provider == "google":
        thinking = config.get("google_thinking_level")
        if thinking:
            kwargs["thinking_level"] = thinking
    elif provider in ("openai", "azure"):
        effort = config.get("openai_reasoning_effort")
        if effort:
            kwargs["reasoning_effort"] = effort
        if provider == "azure":
            api_version = config.get("azure_api_version")
            if api_version:
                kwargs["azure_api_version"] = api_version
    elif provider == "anthropic":
        effort = config.get("anthropic_effort")
        if effort:
            kwargs["effort"] = effort
    elif provider == "custom":
        # 自定义端点：不注入任何提供方专属参数（对方未必认 reasoning_effort）。
        # Key 优先取配置里的 custom_api_key；未设置时由客户端回落到 IFA_CUSTOM_API_KEY。
        api_key = config.get("custom_api_key")
        if api_key:
            kwargs["api_key"] = api_key

    timeout = config.get("timeout")
    if timeout is not None:
        kwargs["timeout"] = timeout

    return kwargs


def build_advisor(config: dict[str, Any] | None = None, **extra_kwargs: Any) -> AdvisorGraph:
    """根据运行时配置创建 AdvisorGraph 实例。"""
    from ifa.default_config import build_runtime_config

    if config is None:
        config = build_runtime_config()

    provider_kwargs = get_provider_kwargs(config)
    provider_kwargs.update(extra_kwargs)

    quick_llm = create_llm_client(
        provider=config["llm_provider"],
        model=config["quick_think_llm"],
        base_url=config.get("backend_url"),
        **provider_kwargs,
    )
    # deep 档单独一档超时：报告生成与裁决产出最终报告，quick 档的默认超时对它们偏紧。
    deep_kwargs = dict(provider_kwargs)
    deep_timeout = config.get("deep_timeout")
    if deep_timeout is not None:
        deep_kwargs["timeout"] = deep_timeout
    deep_llm = create_llm_client(
        provider=config["llm_provider"],
        model=config["deep_think_llm"],
        base_url=config.get("backend_url"),
        **deep_kwargs,
    )

    return AdvisorGraph(
        quick_llm=quick_llm.get_llm(),
        deep_llm=deep_llm.get_llm(),
        config=config,
    )


def build_state(mode: str, **kwargs: str) -> dict[str, str]:
    """构建 AdvisorGraph 所需的初始状态字典（使用 Propagator）。"""
    from ifa.graph.propagation import Propagator

    propagator = Propagator()
    return propagator.create_initial_state(
        fund_codes=kwargs.get("fund_codes", ""),
        analysis_date=kwargs.get("analysis_date", datetime.now().strftime("%Y-%m-%d")),
        mode=mode,
        screen_conditions=kwargs.get("screen_conditions", ""),
        risk_profile=kwargs.get("risk_profile", ""),
    )


_MODE_LABEL = {"deep": "深度分析", "screen": "筛选对比", "portfolio": "组合配置"}


# 兼容既有调用点：advisor_graph._log_state / tracer.save 仍从 ifa.common 导入这两个私有名。
# 实现已迁至 ifa/atomic_io.py（叶子模块可直接用，无需经由组合根）。
_atomic_write_text = atomic_write_text
_atomic_write_json = atomic_write_json


def save_report(state: dict) -> str | None:
    """将分析报告保存为 Markdown 文件，返回文件路径。无报告时返回 None。"""
    report = state.get("final_report", "")
    if not report:
        return None

    from ifa.default_config import build_runtime_config

    config = build_runtime_config()
    results_dir = config.get("results_dir", "results")

    mode = state.get("mode", "unknown")
    date = state.get("analysis_date", datetime.now().strftime("%Y-%m-%d"))
    fund_codes = state.get("fund_codes", "").replace(",", "_").strip()
    # request_id 后缀防并发覆盖:同基金同日同模式并发时各自落不同文件;
    # request_id 缺失时(兼容未走 run() 的旧调用)fallback 到秒级时间戳
    suffix = state.get("request_id") or datetime.now().strftime("%H%M%S")
    suffix = suffix[:8]

    if fund_codes:
        # 人读报告统一放在 reports/ 下，与日志/追踪分离
        save_dir = os.path.join(results_dir, "reports", fund_codes)
        filename = f"{date}_{mode}_{suffix}.md"
    else:
        save_dir = os.path.join(results_dir, "reports")
        filename = f"{_MODE_LABEL.get(mode, mode)}_{date}_{suffix}.md"

    filepath = os.path.join(save_dir, filename)
    _atomic_write_text(filepath, report)

    return os.path.abspath(filepath)
