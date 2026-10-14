# ifa/cli/tools_cmd.py
"""`ifa tool` / `ifa tools` / `ifa skill` —— 数据工具透传、skill 安装。

为什么要把它们做成 CLI 子命令：skill、shell 脚本、其他语言的调用方此前只能靠
`python -c "from ifa.data_tools.api import run_data_tool; ..."` 取数，这要求仓库在盘、
venv 已激活、Python 路径正确 —— 也就是「不能脱离本项目/环境使用」。有了这几条命令，
任何能跑 shell 的地方都只需要一个全局 `ifa`。

工具清单与参数**不是手写的**：名字与说明来自注册表，参数来自处理函数的签名
（`inspect.signature`）。因此不会像手写文档那样漂移（本项目已发生过
25 → 33 → 35 → 36 的四次漂移）。`ifa tools --markdown` 的输出被内置 skill
文件与 `tests/test_skill_doc.py` 同时引用，任何一侧改动都会被测试发现。

注意：本模块刻意不在顶层导入 `ifa.data_tools.builtin` —— 它会连带导入 akshare
（秒级）。注册表在真正需要时于函数内部导入，让 `ifa analyze` 等命令不受影响。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from ifa.data_tools.types import DataToolDefinition

console = Console()

#: 默认安装目录：Claude Code 的用户级 skill 目录（所有项目可见）。
DEFAULT_SKILL_DIR = Path.home() / ".claude" / "skills"

#: 生成表格的边界标记 —— skill 文件里被这一对标记包住的部分由本模块生成。
TOOL_TABLE_BEGIN = "<!-- BEGIN GENERATED TOOL TABLE -->"
TOOL_TABLE_END = "<!-- END GENERATED TOOL TABLE -->"


def _tool_definitions() -> list[DataToolDefinition]:
    """返回全部已注册的数据工具定义（延迟导入注册表，避免拖慢其他命令）。"""
    from ifa.data_tools.builtin import create_default_data_tool_registry

    return create_default_data_tool_registry().list_tools()


def _type_name(annotation: Any) -> str:
    """把签名里的类型注解转成面向使用者的短名字。"""
    if annotation is inspect.Parameter.empty:
        return "Any"
    if annotation in (str, int, float, bool):
        return str(annotation.__name__)
    return "Any"


def describe_parameters(handler: Any) -> list[dict[str, Any]]:
    """从处理函数签名推导参数表（含默认值）—— 工具参数的唯一事实来源。"""
    specs: list[dict[str, Any]] = []
    for parameter in inspect.signature(handler).parameters.values():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        required = parameter.default is inspect.Parameter.empty
        specs.append(
            {
                "name": parameter.name,
                "type": _type_name(parameter.annotation),
                "required": required,
                "default": None if required else parameter.default,
            }
        )
    return specs


def describe_tool(definition: DataToolDefinition) -> dict[str, Any]:
    """把工具定义整理成可 JSON 序列化的结构。"""
    return {
        "name": definition.name,
        "description": definition.description,
        "namespace": definition.namespace,
        "cache_enabled": definition.cache_enabled,
        "parameters": describe_parameters(definition.handler),
    }


def tools_payload() -> list[dict[str, Any]]:
    """全部工具的 JSON 结构（供 `ifa tools --json` 与测试使用）。"""
    return [describe_tool(definition) for definition in _tool_definitions()]


def _format_parameter_spec(parameter: dict[str, Any]) -> str:
    if parameter["required"]:
        return str(parameter["name"])
    return f"{parameter['name']}={parameter['default']!r}"


def tools_markdown(tools: list[dict[str, Any]] | None = None) -> str:
    """生成 Markdown 工具表（`ifa tools --markdown` 与 skill 文件共用）。"""
    payload = tools if tools is not None else tools_payload()
    lines = ["| 工具 | 参数 | 说明 |", "| ---- | ---- | ---- |"]
    for tool in payload:
        params = ", ".join(_format_parameter_spec(p) for p in tool["parameters"]) or "—"
        lines.append(f"| `{tool['name']}` | `{params}` | {tool['description']} |")
    return "\n".join(lines)


def parse_params(raw_params: list[str] | None) -> dict[str, Any]:
    """把 `-p key=value` 解析成参数字典；值按 JSON 解析，失败则按字符串处理。"""
    params: dict[str, Any] = {}
    for raw in raw_params or []:
        if "=" not in raw:
            raise ValueError(f"参数格式应为 key=value：{raw}")
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"参数名不能为空：{raw}")
        try:
            params[key] = json.loads(value)
        except json.JSONDecodeError:
            # 000300 / 沪深300 这类不是合法 JSON，按字符串处理（前导零与中文都保留）。
            params[key] = value
    return params


def validate_params(definition: DataToolDefinition, params: dict[str, Any]) -> None:
    """校验参数名与必填项 —— 让错误在使用者面前暴露，而不是变成 TypeError。"""
    allowed = {p["name"]: p for p in describe_parameters(definition.handler)}
    unknown = [name for name in params if name not in allowed]
    if unknown:
        hint = ", ".join(allowed) or "无"
        raise ValueError(f"工具 {definition.name} 不认识参数 {', '.join(unknown)}；可用参数：{hint}")
    missing = [name for name, spec in allowed.items() if spec["required"] and name not in params]
    if missing:
        raise ValueError(f"工具 {definition.name} 缺少必填参数：{', '.join(missing)}")


def serialize_value(value: Any) -> Any:
    """把工具返回值转成可 JSON 序列化的形式（DataFrame → 记录列表）。"""
    if value is None or isinstance(value, (str, int, float, bool, dict, list)):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict(orient="records")
    return str(value)


def read_bundled_skill() -> str:
    """读取随包分发的内置 skill 文件（`ifa skill install` 的内容来源）。"""
    from importlib.resources import files

    return (files("ifa") / "skills" / "fund.md").read_text(encoding="utf-8")


def register_tool_commands(app: typer.Typer) -> None:
    """把 `tools` / `tool` / `skill` 三个子命令挂到主 Typer app 上。"""

    @app.command(name="tools")
    def tools_cmd(
        json_out: bool = typer.Option(False, "--json", help="输出 JSON（含参数类型与默认值）"),
        markdown: bool = typer.Option(False, "--markdown", help="输出 Markdown 表格（用于生成 skill 文档）"),
    ) -> None:
        """列出全部数据工具及其参数（不经过 LLM）。"""
        payload = tools_payload()
        if markdown:
            # 用 typer.echo 直出，避免 rich 按终端宽度折行破坏 Markdown。
            typer.echo(tools_markdown(payload))
            return
        if json_out:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return

        table = Table(title=f"IFA 数据工具（{len(payload)} 个）")
        table.add_column("工具", style="cyan", no_wrap=True)
        table.add_column("参数", style="green")
        table.add_column("说明")
        for tool in payload:
            params = ", ".join(_format_parameter_spec(p) for p in tool["parameters"]) or "—"
            table.add_row(tool["name"], params, tool["description"])
        console.print(table)
        console.print("[dim]调用：ifa tool <名字> -p key=value [--json][/dim]")

    @app.command(name="tool")
    def tool_cmd(
        name: str = typer.Argument(help="工具名（见 ifa tools）"),
        # 可重复选项用 Annotated 声明：把列表写成默认值（typer.Option(...)）会被 B008 判为
        # 可变默认值，而 Annotated 写法把选项声明移出默认值，同时保留 -p 短选项。
        param: Annotated[list[str] | None, typer.Option("--param", "-p", help="工具参数 key=value，可重复")] = None,
        json_out: bool = typer.Option(False, "--json", help="以 JSON 输出结果"),
        no_cache: bool = typer.Option(False, "--no-cache", help="跳过缓存，强制重新取数"),
    ) -> None:
        """直接调用一个数据工具并打印结果（不经过 LLM）。"""
        from ifa.data_tools.api import get_default_data_executor
        from ifa.dataflows.a_share import DATA_SOURCE_ERROR_MARKER

        definitions = {definition.name: definition for definition in _tool_definitions()}
        definition = definitions.get(name)
        if definition is None:
            console.print(f"[red]未知数据工具: {name}[/red]")
            console.print(f"[dim]可用工具（{len(definitions)}）：{', '.join(sorted(definitions))}[/dim]")
            raise typer.Exit(code=1)

        try:
            params = parse_params(param)
            validate_params(definition, params)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        try:
            result = get_default_data_executor().execute(name, use_cache=not no_cache, **params)
        except Exception as exc:  # noqa: BLE001 —— CLI 边界：取数异常一律转成可读报错 + 非零退出码
            console.print(f"[red]工具 {name} 执行失败：{type(exc).__name__}: {exc}[/red]")
            raise typer.Exit(code=1) from exc

        value = serialize_value(result.value)
        if json_out:
            typer.echo(
                json.dumps(
                    {"tool": name, "params": params, "from_cache": result.from_cache, "result": value},
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )
        elif isinstance(value, str):
            console.print(value)
        else:
            console.print(json.dumps(value, ensure_ascii=False, indent=2, default=str))

        # 数据源失败会被格式化成带标记的文本（工具内部吞掉异常以保证图流程不中断）。
        # 在 CLI 边界必须还原成非零退出码，否则脚本会把「数据源挂了」当成「没有数据」。
        if isinstance(value, str) and DATA_SOURCE_ERROR_MARKER in value:
            raise typer.Exit(code=1)

    @app.command(name="skill")
    def skill_cmd(
        print_only: bool = typer.Option(False, "--print", help="只打印内置 skill 内容，不安装"),
        force: bool = typer.Option(False, "--force", help="覆盖已存在的文件"),
        target_dir: str = typer.Option(None, "--dir", help="安装目录（默认用户级 skill 目录）"),
    ) -> None:
        """把内置 skill 安装到用户级目录，使其在所有项目中可用。"""
        content = read_bundled_skill()
        if print_only:
            typer.echo(content)
            return

        target = Path(target_dir) if target_dir else DEFAULT_SKILL_DIR
        path = target / "fund.md"
        if path.exists() and not force:
            console.print(f"[yellow]已存在，未覆盖：{path}（加 --force 覆盖）[/yellow]")
            return
        target.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        console.print(f"[green]已安装 skill：{path}[/green]")
        console.print("[dim]工具表由 ifa tools --markdown 生成，无需手改[/dim]")
