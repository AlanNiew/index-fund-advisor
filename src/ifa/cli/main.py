"""IFA CLI 入口，基于 Typer 框架。"""

import os
import re
import sys

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
        console.print("[yellow]分析完成但未生成报告[/yellow]")


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
    build_kwargs = {"callbacks": []} if debug else {}
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
    build_kwargs = {"callbacks": []} if debug else {}
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
    build_kwargs = {"callbacks": []} if debug else {}
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


if __name__ == "__main__":
    app()
