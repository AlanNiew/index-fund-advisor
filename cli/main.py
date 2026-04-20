# cli/main.py
"""IFA CLI 入口，基于 Typer 框架。"""

import os
import sys
from datetime import datetime

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv()

app = typer.Typer(
    name="ifa",
    help="IFA - AI 驱动的指数基金分析工具",
    no_args_is_help=True,
)

console = Console()


@app.command()
def analyze(
    fund_code: str = typer.Argument(help="基金代码，如 510300"),
    date: str = typer.Option(
        datetime.now().strftime("%Y-%m-%d"),
        "--date", "-d",
        help="分析日期 YYYY-MM-DD",
    ),
    debug: bool = typer.Option(False, "--debug", help="启用调试模式"),
):
    """单只基金深度分析。"""
    console.print(Panel(f"[bold]IFA 单只基金深度分析[/bold]\n基金代码: {fund_code}\n分析日期: {date}"))

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        progress.add_task("初始化 LLM 客户端...", total=None)
        from ifa.llm_clients.factory import create_llm_client
        from ifa.default_config import build_runtime_config

        config = build_runtime_config()

        provider_kwargs = _get_provider_kwargs(config)
        if debug:
            provider_kwargs["callbacks"] = []

        quick_llm = create_llm_client(
            provider=config["llm_provider"],
            model=config["quick_think_llm"],
            base_url=config.get("backend_url"),
            **provider_kwargs,
        )
        deep_llm = create_llm_client(
            provider=config["llm_provider"],
            model=config["deep_think_llm"],
            base_url=config.get("backend_url"),
            **provider_kwargs,
        )

        progress.add_task("构建分析图...", total=None)
        from ifa.graph.advisor_graph import AdvisorGraph

        advisor = AdvisorGraph(
            quick_llm=quick_llm.get_llm(),
            deep_llm=deep_llm.get_llm(),
            config=config,
        )

        state = {
            "fund_codes": fund_code,
            "analysis_date": date,
            "mode": "deep",
            "asset_type": "",
            "screen_conditions": "",
            "risk_profile": "",
            "screen_results": "",
            "fund_analysis_report": "",
            "index_analysis_report": "",
            "portfolio_advice": "",
            "final_report": "",
            "messages": [],
        }

        progress.add_task("执行分析...", total=None)
        final_state = advisor.run("deep", state)

    report = final_state.get("final_report", "")
    if report:
        console.print(Panel(report, title="分析报告", border_style="green"))
    else:
        console.print("[yellow]分析完成但未生成报告[/yellow]")


@app.command()
def screen(
    category: str = typer.Option("全部", "--category", "-c", help="指数类别"),
    method: str = typer.Option("全部", "--method", "-m", help="跟踪方式"),
    query: str = typer.Option("", "--query", "-q", help="自然语言筛选条件"),
    top: int = typer.Option(10, "--top", "-n", help="返回前 N 只基金"),
    debug: bool = typer.Option(False, "--debug", help="启用调试模式"),
):
    """筛选指数基金。"""
    conditions = query or f"类别: {category}, 跟踪方式: {method}, 前 {top} 只"
    console.print(Panel(f"[bold]IFA 指数基金筛选[/bold]\n{conditions}"))

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        progress.add_task("初始化...", total=None)
        from ifa.llm_clients.factory import create_llm_client
        from ifa.default_config import build_runtime_config

        config = build_runtime_config()
        provider_kwargs = _get_provider_kwargs(config)

        quick_llm = create_llm_client(
            provider=config["llm_provider"],
            model=config["quick_think_llm"],
            base_url=config.get("backend_url"),
            **provider_kwargs,
        )
        deep_llm = create_llm_client(
            provider=config["llm_provider"],
            model=config["deep_think_llm"],
            base_url=config.get("backend_url"),
            **provider_kwargs,
        )

        progress.add_task("执行筛选...", total=None)
        from ifa.graph.advisor_graph import AdvisorGraph

        advisor = AdvisorGraph(
            quick_llm=quick_llm.get_llm(),
            deep_llm=deep_llm.get_llm(),
            config=config,
        )

        state = {
            "fund_codes": "",
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "mode": "screen",
            "asset_type": "",
            "screen_conditions": conditions,
            "risk_profile": "",
            "screen_results": "",
            "fund_analysis_report": "",
            "index_analysis_report": "",
            "portfolio_advice": "",
            "final_report": "",
            "messages": [],
        }

        final_state = advisor.run("screen", state)

    report = final_state.get("final_report", "")
    if report:
        console.print(Panel(report, title="筛选对比报告", border_style="green"))
    else:
        console.print("[yellow]筛选完成但未生成报告[/yellow]")


@app.command()
def portfolio(
    risk: str = typer.Option("moderate", "--risk", "-r", help="风险偏好: conservative/moderate/aggressive/growth"),
    amount: float = typer.Option(0, "--amount", "-a", help="投资金额（可选）"),
    debug: bool = typer.Option(False, "--debug", help="启用调试模式"),
):
    """生成指数基金组合配置建议。"""
    console.print(Panel(f"[bold]IFA 组合配置建议[/bold]\n风险偏好: {risk}" + (f"\n投资金额: {amount:,.0f} 元" if amount else "")))

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        progress.add_task("初始化...", total=None)
        from ifa.llm_clients.factory import create_llm_client
        from ifa.default_config import build_runtime_config

        config = build_runtime_config()
        provider_kwargs = _get_provider_kwargs(config)

        quick_llm = create_llm_client(
            provider=config["llm_provider"],
            model=config["quick_think_llm"],
            base_url=config.get("backend_url"),
            **provider_kwargs,
        )
        deep_llm = create_llm_client(
            provider=config["llm_provider"],
            model=config["deep_think_llm"],
            base_url=config.get("backend_url"),
            **provider_kwargs,
        )

        progress.add_task("生成组合配置...", total=None)
        from ifa.graph.advisor_graph import AdvisorGraph

        advisor = AdvisorGraph(
            quick_llm=quick_llm.get_llm(),
            deep_llm=deep_llm.get_llm(),
            config=config,
        )

        state = {
            "fund_codes": "",
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "mode": "portfolio",
            "asset_type": "",
            "screen_conditions": f"风险偏好: {risk}",
            "risk_profile": risk,
            "screen_results": "",
            "fund_analysis_report": "",
            "index_analysis_report": "",
            "portfolio_advice": "",
            "final_report": "",
            "messages": [],
        }

        final_state = advisor.run("portfolio", state)

    report = final_state.get("final_report", "")
    if report:
        console.print(Panel(report, title="组合配置报告", border_style="green"))
    else:
        console.print("[yellow]配置生成完成但未生成报告[/yellow]")


@app.command()
def search(
    keyword: str = typer.Argument(help="搜索关键词"),
    limit: int = typer.Option(20, "--limit", "-n", help="最大返回数量"),
):
    """快速搜索基金。"""
    from ifa.data_tools.api import run_data_tool

    console.print(f"搜索基金: {keyword}")
    result = run_data_tool("get_fund_list")
    # 简单过滤并展示
    lines = result.strip().split("\n")
    matched = [l for l in lines if keyword.upper() in l.upper()][:limit]
    if matched:
        console.print("\n".join(matched))
    else:
        console.print(f"[yellow]未找到匹配 '{keyword}' 的基金[/yellow]")


@app.command()
def info(
    fund_code: str = typer.Argument(help="基金代码"),
):
    """显示基金基本信息（不经过 LLM）。"""
    from ifa.data_tools.api import run_data_tool

    console.print(f"查询基金信息: {fund_code}")
    result = run_data_tool("get_fund_basic_info", symbol=fund_code)
    console.print(result)


@app.command()
def config(
    key: str = typer.Argument(None, help="配置项名称"),
    value: str = typer.Argument(None, help="配置值"),
):
    """查看或设置配置。"""
    from ifa.default_config import DEFAULT_CONFIG, build_runtime_config

    if key and value:
        console.print(f"[yellow]设置 {key} = {value}（需要手动编辑配置文件）[/yellow]")
        console.print(f"配置文件位置: ifa/last_config.py")
    else:
        config = build_runtime_config()
        for k, v in config.items():
            console.print(f"  {k}: {v}")


def _get_provider_kwargs(config: dict) -> dict:
    """获取 LLM 客户端提供方参数。"""
    kwargs = {}
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

    timeout = config.get("timeout")
    if timeout is not None:
        kwargs["timeout"] = timeout

    return kwargs


if __name__ == "__main__":
    app()
