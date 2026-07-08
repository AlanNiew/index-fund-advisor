"""一次性迁移脚本：把 results/ 下混放的产出物按类型分离到顶层子目录。

目标结构：
    results/
    ├── reports/{fund_code}/{date}_{mode}.md   人读报告
    ├── logs/{fund_code}/{date}_{mode}.json    状态日志
    ├── traces/{fund_code}/{request_id}.json   执行追踪
    └── validation/                            回测验证（不动）

默认 dry-run，加 --apply 才真正移动文件。

用法：
    python scripts/migrate_results_layout.py            # 预览
    python scripts/migrate_results_layout.py --apply    # 执行
    python scripts/migrate_results_layout.py --results-dir /path/to/results
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# 基金代码目录：6 位数字
FUND_CODE_RE = re.compile(r"^\d{6}$")
# 状态日志：YYYY-MM-DD_*.json
STATE_LOG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_.*\.json$")
# trace 文件：12 位 hex .json
TRACE_RE = re.compile(r"^[0-9a-f]{12}\.json$")
# 顶层旧命名报告：{fund_code}_{date}_{mode}.md
LEGACY_TOP_MD_RE = re.compile(r"^(\d{6})_(\d{4}-\d{2}-\d{2})_(.+)\.md$")


def classify_json(name: str) -> str:
    """区分状态日志和 trace 文件。返回 'state' / 'trace' / ''（无法识别）。"""
    if STATE_LOG_RE.match(name):
        return "state"
    if TRACE_RE.match(name):
        return "trace"
    return ""


def plan_migration(results_dir: Path) -> list[tuple[Path, Path, str]]:
    """生成迁移计划：[(源, 目标, 类别), ...]。"""
    moves: list[tuple[Path, Path, str]] = []

    if not results_dir.exists():
        return moves

    for entry in sorted(results_dir.iterdir()):
        if entry.is_dir():
            # validation 不动；reports/logs 是新目录也不动
            if entry.name in {"reports", "logs", "validation"}:
                continue
            if entry.name == "ifa_logs":
                # 顶层不会有 ifa_logs，跳过
                continue

            if FUND_CODE_RE.match(entry.name):
                # 基金目录：分发其中的文件
                fund_code = entry.name
                _plan_fund_dir(entry, fund_code, results_dir, moves)
            elif entry.name == "traces":
                # 已存在的 traces/ 目录：把无基金子目录的 legacy trace 归到 _legacy/
                _plan_legacy_traces_dir(entry, results_dir, moves)
            # 其他目录名跳过
            continue

        # 顶层散落文件
        if entry.suffix == ".md":
            m = LEGACY_TOP_MD_RE.match(entry.name)
            if m:
                fund_code, date, mode = m.group(1), m.group(2), m.group(3)
                dest = results_dir / "reports" / fund_code / f"{date}_{mode}.md"
                moves.append((entry, dest, "report"))
            else:
                # 无基金代码前缀的报告（screen/portfolio 等）→ reports/
                dest = results_dir / "reports" / entry.name
                moves.append((entry, dest, "report"))

    return moves


def _plan_fund_dir(
    fund_dir: Path,
    fund_code: str,
    results_dir: Path,
    moves: list[tuple[Path, Path, str]],
) -> None:
    """处理 results/{fund_code}/ 下的文件。"""
    for path in sorted(fund_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(fund_dir)
        name = path.name

        # ifa_logs/ 子目录里的 json 一律按状态日志处理
        if rel.parts[0] == "ifa_logs" and path.suffix == ".json":
            dest = results_dir / "logs" / fund_code / name
            moves.append((path, dest, "state"))
            continue

        if path.suffix == ".md":
            dest = results_dir / "reports" / fund_code / name
            moves.append((path, dest, "report"))
        elif path.suffix == ".json":
            kind = classify_json(name)
            if kind == "state":
                dest = results_dir / "logs" / fund_code / name
                moves.append((path, dest, "state"))
            elif kind == "trace":
                dest = results_dir / "traces" / fund_code / name
                moves.append((path, dest, "trace"))
            else:
                # 无法识别的 json，留在原处不动
                print(f"  ⚠ 无法识别，跳过: {path}", file=sys.stderr)


def _plan_legacy_traces_dir(
    traces_dir: Path,
    results_dir: Path,
    moves: list[tuple[Path, Path, str]],
) -> None:
    """处理已存在的 results/traces/ 目录。

    无基金子目录的 trace（{request_id}.json 直接放在 traces/ 下）归到 _legacy/。
    已有基金子目录的 trace 保持不动（符合新结构）。
    """
    for path in sorted(traces_dir.iterdir()):
        if path.is_dir():
            # 基金子目录或 _legacy，符合新结构，跳过
            continue
        if path.suffix == ".json" and TRACE_RE.match(path.name):
            dest = traces_dir / "_legacy" / path.name
            moves.append((path, dest, "trace"))


def apply_moves(moves: list[tuple[Path, Path, str]]) -> dict[str, int]:
    """执行迁移，返回各类别计数。"""
    counts: dict[str, int] = {"report": 0, "state": 0, "trace": 0}
    for src, dest, kind in moves:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def cleanup_empty_dirs(results_dir: Path) -> int:
    """删除空的基金目录和 ifa_logs 子目录。返回删除数量。"""
    skip = {"reports", "logs", "traces", "validation"}
    removed = 0
    # 自底向上扫描
    for path in sorted(
        (p for p in results_dir.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        if path == results_dir or path.name in skip:
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            path.rmdir()
            removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把 results/ 下混放的产出物按类型分离到 reports/ logs/ traces/",
    )
    parser.add_argument(
        "--results-dir",
        default=str(Path(__file__).resolve().parent.parent / "results"),
        help="results 目录路径（默认: 项目根/results）",
    )
    parser.add_argument("--apply", action="store_true", help="真正执行迁移（默认仅预览）")
    args = parser.parse_args()

    results_dir = Path(args.results_dir).resolve()
    if not results_dir.exists():
        print(f"✗ 目录不存在: {results_dir}", file=sys.stderr)
        return 1

    mode_label = "执行" if args.apply else "预览（dry-run）"
    print(f"迁移目录: {results_dir}")
    print(f"模式: {mode_label}\n")

    moves = plan_migration(results_dir)
    if not moves:
        print("无需迁移，结构已是目标状态。")
        return 0

    # 按类别分组打印
    by_kind: dict[str, list[tuple[Path, Path, str]]] = {"report": [], "state": [], "trace": []}
    for m in moves:
        by_kind.setdefault(m[2], []).append(m)

    label = {"report": "📄 报告", "state": "📋 状态日志", "trace": "🔍 执行追踪"}
    for kind in ("report", "state", "trace"):
        items = by_kind.get(kind, [])
        if not items:
            continue
        print(f"{label[kind]} ({len(items)} 个)")
        for src, dest, _ in items:
            arrow = "→" if args.apply else "(将)"
            print(f"  {src.relative_to(results_dir)}  {arrow}  {dest.relative_to(results_dir)}")
        print()

    total = len(moves)
    print(f"共 {total} 个文件待迁移。")

    if not args.apply:
        print("\n这是预览模式。确认无误后加 --apply 执行。")
        return 0

    # 执行
    counts = apply_moves(moves)
    removed = cleanup_empty_dirs(results_dir)
    print(f"\n✓ 完成: 报告 {counts['report']}，状态日志 {counts['state']}，追踪 {counts['trace']}")
    print(f"✓ 清理空目录 {removed} 个。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
