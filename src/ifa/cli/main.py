"""IFA CLI 入口，基于 Typer 框架。"""

import os
import re
import sys
from typing import Any

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# 仅匹配 6 位纯数字的基金代码（如 510300、161725）。
# 用途：让 `ifa 161725` 这种简写等价于 `ifa info 161725`。
_FUND_CODE_RE = re.compile(r"^\d{6}$")

# 本模块位于 src/ifa/cli/，项目根在三层目录之上。
# 将 src 和项目根加入 sys.path，保证 api/、web/ 等顶层包在开发模式下可导入。
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
sys.path.insert(0, _PROJECT_ROOT)

load_dotenv()


class _FundCodeGroup(typer.core.TyperGroup):
    """容错分发：`ifa <6位数字>` 自动转走 `analyze` 命令。

    其他场景保持 Typer 原生行为——未知子命令（如 `ifa foobar`）仍按正常报错处理，
    避免把拼写错误的子命令静默当成基金代码。
    """

    def resolve_command(self, ctx, args):
        # 仅当存在首个位置参数、且恰好是 6 位纯数字时进行转发。
        # 排除带 `-`/`--` 的选项（如 `ifa --help`），以免误判。
        if args and not args[0].startswith("-") and _FUND_CODE_RE.match(args[0]):
            # 把 `161725` 重写为 `analyze 161725`，再交给 Typer 正常解析。
            args = ["analyze", *args]
        return super().resolve_command(ctx, args)


app = typer.Typer(
    name="ifa",
    help="IFA - AI 驱动的指数基金分析工具",
    no_args_is_help=True,
    cls=_FundCodeGroup,
)

console = Console()


def _run_analysis(mode: str, state: dict, title: str, **build_kwargs):
    """公共分析执行逻辑：初始化 AdvisorGraph 并运行。"""
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("初始化...", total=None)
        from ifa.common import build_advisor

        advisor = build_advisor(**build_kwargs)

        # 定义进度回调，实时更新 Rich spinner 描述
        def on_progress(node_name: str, description: str):
            progress.update(task, description=description)

        final_state = advisor.run(mode, state, on_progress=on_progress)

    report = final_state.get("final_report", "")
    if report:
        console.print(Panel(report, title=title, border_style="green"))
        from ifa.common import save_report

        path = save_report(final_state)
        if path:
            console.print(f"[dim]报告已保存: {path}[/dim]")
    else:
        # 没有报告就是失败。此前这里只打印一行黄字就正常返回，退出码为 0，
        # 包装脚本/定时任务因此无法发现故障（Web 入口有正确上报）。
        error = final_state.get("error")
        console.print("[red]分析失败：未生成报告[/red]")
        if error:
            console.print(f"[red]失败原因：{error}[/red]")
        raise typer.Exit(code=1)


@app.command()
def analyze(
    fund_code: str = typer.Argument(help="基金代码，如 510300"),
    date: str = typer.Option(
        __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        "--date",
        "-d",
        help="分析日期 YYYY-MM-DD",
    ),
    debug: bool = typer.Option(False, "--debug", help="启用调试模式"),
):
    """单只基金深度分析。"""
    from ifa.common import build_state

    console.print(Panel(f"[bold]IFA 单只基金深度分析[/bold]\n基金代码: {fund_code}\n分析日期: {date}"))
    state = build_state("deep", fund_codes=fund_code, analysis_date=date)
    build_kwargs: dict[str, Any] = {"callbacks": []} if debug else {}
    _run_analysis("deep", state, "分析报告", **build_kwargs)


@app.command()
def screen(
    category: str = typer.Option("全部", "--category", "-c", help="指数类别"),
    method: str = typer.Option("全部", "--method", "-m", help="跟踪方式"),
    query: str = typer.Option("", "--query", "-q", help="自然语言筛选条件"),
    top: int = typer.Option(10, "--top", "-n", help="返回前 N 只基金"),
    debug: bool = typer.Option(False, "--debug", help="启用调试模式"),
):
    """筛选指数基金。"""
    from ifa.common import build_state

    conditions = query or f"类别: {category}, 跟踪方式: {method}, 前 {top} 只"
    console.print(Panel(f"[bold]IFA 指数基金筛选[/bold]\n{conditions}"))
    state = build_state("screen", screen_conditions=conditions)
    build_kwargs: dict[str, Any] = {"callbacks": []} if debug else {}
    _run_analysis("screen", state, "筛选对比报告", **build_kwargs)


@app.command()
def portfolio(
    risk: str = typer.Option("moderate", "--risk", "-r", help="风险偏好: conservative/moderate/aggressive/growth"),
    amount: float = typer.Option(0, "--amount", "-a", help="投资金额（可选）"),
    debug: bool = typer.Option(False, "--debug", help="启用调试模式"),
):
    """生成指数基金组合配置建议。"""
    from ifa.common import build_state

    console.print(
        Panel(f"[bold]IFA 组合配置建议[/bold]\n风险偏好: {risk}" + (f"\n投资金额: {amount:,.0f} 元" if amount else ""))
    )
    state = build_state("portfolio", risk_profile=risk, screen_conditions=f"风险偏好: {risk}")
    build_kwargs: dict[str, Any] = {"callbacks": []} if debug else {}
    _run_analysis("portfolio", state, "组合配置报告", **build_kwargs)


@app.command()
def search(
    keyword: str = typer.Argument(help="搜索关键词"),
    limit: int = typer.Option(20, "--limit", "-n", help="最大返回数量"),
):
    """快速搜索基金。"""
    from ifa.data_tools.api import run_data_tool

    console.print(f"搜索基金: {keyword}")
    result = run_data_tool("get_fund_list")
    lines = result.strip().split("\n")
    matched = [line for line in lines if keyword.upper() in line.upper()][:limit]
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


@app.command(name="config")
def config_cmd(
    key: str = typer.Argument(None, help="配置项名称"),
    value: str = typer.Argument(None, help="配置值"),
):
    """查看或设置配置。"""
    from ifa.default_config import build_runtime_config

    if key and value:
        console.print(f"[yellow]设置 {key} = {value}（需要手动编辑配置文件）[/yellow]")
        console.print("配置文件位置: ifa/last_config.py")
    else:
        cfg = build_runtime_config()
        for k, v in cfg.items():
            console.print(f"  {k}: {v}")


@app.command()
def validate(
    codes: str = typer.Option(..., "--codes", help="逗号分隔的基金代码，如 510300,159919"),
    dates: str = typer.Option(None, "--dates", help="逗号分隔的分析日期 YYYY-MM-DD（与 --months-back 二选一）"),
    months_back: int = typer.Option(None, "--months-back", help="自动生成过去 N 个月每月一个分析日期"),
    hold_days: int = typer.Option(60, "--hold-days", help="评级后持有多少交易日看收益（默认 60）"),
    update_memory: bool = typer.Option(False, "--update-memory", help="显式开启：把结果喂回反思系统（注意幸存者偏差风险）"),
    output: str = typer.Option(None, "--output", "-o", help="报告输出路径（默认 results/validation/）"),
):
    """评级 vs 实际收益 回测验证。

    跑历史分析，对比「AI 当时给的评级」和「事后实际收益」，
    输出命中率、置信区间、混淆矩阵、基准对比。

    智识诚实提醒：样本量 < 30 时统计结论无显著性，本验证不证明评级「有效」或「无效」。
    """
    import datetime as _dt
    import json
    from pathlib import Path

    from ifa.backtest.rating_validator import (
        format_validation_report,
        generate_monthly_dates,
        run_rating_validation,
    )
    from ifa.common import build_advisor

    # 解析参数
    fund_codes = [c.strip() for c in codes.split(",") if c.strip()]
    if not fund_codes:
        console.print("[red]未提供有效基金代码[/red]")
        raise typer.Exit(1)

    if dates:
        analysis_dates = [d.strip() for d in dates.split(",") if d.strip()]
    elif months_back:
        analysis_dates = generate_monthly_dates(months_back)
    else:
        console.print("[red]必须指定 --dates 或 --months-back[/red]")
        raise typer.Exit(1)

    total_tasks = len(fund_codes) * len(analysis_dates)
    console.print(
        Panel(
            f"[bold]评级验证回测[/bold]\n"
            f"基金: {', '.join(fund_codes)}\n"
            f"分析日期: {', '.join(analysis_dates)}\n"
            f"持有周期: {hold_days} 个交易日\n"
            f"总任务数: {total_tasks}"
        )
    )

    advisor = build_advisor()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("启动验证...", total=total_tasks)

        def on_progress(phase: str, idx: int, total: int, code: str, date: str, status: str):
            progress.update(task, completed=idx, description=f"[{phase}] {code} @ {date}: {status}")

        result = run_rating_validation(
            fund_codes=fund_codes,
            analysis_dates=analysis_dates,
            hold_days=hold_days,
            advisor=advisor,
            on_progress=on_progress,
            update_memory=update_memory,
        )

    # 输出报告
    report_md = format_validation_report(result)
    console.print(Panel(report_md, title="评级验证报告", border_style="cyan"))

    # 落盘
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output) if output else Path("results/validation")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"validation_{ts}.json"
    payload = {
        "meta": {
            "generated_at": _dt.datetime.now().isoformat(),
            "hold_days": result.hold_days,
            "period_start": result.period_start,
            "period_end": result.period_end,
            "fund_codes": fund_codes,
            "update_memory": update_memory,
        },
        "summary": {
            "total": result.total,
            "valid": result.valid,
            "skipped": result.skipped,
            "bullish_hit_rate": result.bullish_hit_rate,
            "bullish_n": result.bullish_n,
            "bullish_ci_95": [result.bullish_ci_low, result.bullish_ci_high],
            "bearish_hit_rate": result.bearish_hit_rate,
            "bearish_n": result.bearish_n,
            "bearish_ci_95": [result.bearish_ci_low, result.bearish_ci_high],
            "alpha_vs_random": result.alpha_vs_random,
            "alpha_vs_csi300": result.alpha_vs_csi300,
            "random_benchmark": result.random_benchmark,
            "csi300_benchmark": result.csi300_benchmark,
        },
        "confusion_matrix": result.confusion_matrix,
        "records": [
            {
                "fund_code": r.fund_code,
                "analysis_date": r.analysis_date,
                "rating": r.rating,
                "confidence": r.confidence,
                "forward_return_pct": r.forward_return_pct,
                "benchmark_return_pct": r.benchmark_return_pct,
                "excess_return_pct": r.excess_return_pct,
                "hold_days": r.hold_days,
                "fetch_error": r.fetch_error,
            }
            for r in result.records
        ],
        "warnings": result.warnings,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    md_path = out_dir / f"validation_{ts}.md"
    md_path.write_text(report_md, encoding="utf-8")

    console.print(f"[dim]JSON: {json_path}[/dim]")
    console.print(f"[dim]Markdown: {md_path}[/dim]")

    if update_memory:
        console.print("[yellow]⚠️ 已开启 --update-memory，Agent 记忆已被本次结果更新（存在幸存者偏差风险）[/yellow]")


if __name__ == "__main__":
    app()
