"""IFA 每日基金批处理分析脚本。

对指定基金列表逐一执行 deep 模式深度分析，保存 Markdown 报告，
并在控制台打印评级汇总表格。非交易日自动跳过。

用法:
    python scripts/daily_analysis.py                 # 分析今天（仅交易日）
    python scripts/daily_analysis.py --force         # 强制运行（不检查交易日）
    python scripts/daily_analysis.py --date 2025-04-25  # 指定日期
    python scripts/daily_analysis.py --codes 161725,110020  # 指定基金

定时任务配置（Windows 任务计划程序）:
    每个工作日 15:30 运行:
    schtasks /create /tn "IFA每日基金分析" /tr "python D:\\path\\to\\scripts\\daily_analysis.py" /sc weekly /d MON,TUE,WED,THU,FRI /st 15:30
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# 将 src 目录加入 sys.path，确保直接运行也能导入 ifa
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 默认分析的基金列表
DEFAULT_FUND_CODES = ["161725", "110020", "000834", "017641", "012761"]


def check_trading_day(date_str: str) -> bool:
    """判断指定日期是否为 A 股交易日。"""
    try:
        from ifa.dataflows.a_share_common import is_trade_date

        return is_trade_date(date_str)
    except Exception as e:
        logger.warning("交易日判断失败 (%s)，默认视为非交易日。请检查网络连接。", e)
        return False


def get_fund_name(fund_code: str) -> str:
    """尝试获取基金名称，失败时返回代码。"""
    try:
        from ifa.agents.tools.public_fund_tools import get_fund_basic_info

        result = get_fund_basic_info.invoke({"fund_code": fund_code})
        if isinstance(result, str) and result.strip():
            # 取第一行中可能的名称
            for line in result.strip().split("\n"):
                if fund_code in line and "|" in line:
                    parts = [p.strip() for p in line.split("|")]
                    for p in parts:
                        if p and p != fund_code and not p.replace(".", "").replace("%", "").replace("-", "").isdigit():
                            return p[:20]
        return fund_code
    except Exception:
        return fund_code


def analyze_single_fund(advisor, fund_code: str, analysis_date: str) -> dict:
    """分析单只基金，返回结果字典。"""
    from ifa.common import build_state, save_report

    logger.info("开始分析基金 %s ...", fund_code)
    start_time = time.time()

    state = build_state(
        mode="deep",
        fund_codes=fund_code,
        analysis_date=analysis_date,
    )

    final_state = advisor.run(mode="deep", state=state)
    elapsed = time.time() - start_time

    # 提取报告
    report = final_state.get("final_report", "")
    report_path = save_report(final_state) if report else None

    # 提取评级和置信度
    rating = "N/A"
    confidence = "N/A"
    if report:
        try:
            rating = advisor.process_signal(report)
            confidence = advisor.process_confidence(report)
        except Exception as e:
            logger.warning("评级提取失败 (%s): %s", fund_code, e)

    # 检查是否有错误
    error = final_state.get("error", "")

    result = {
        "fund_code": fund_code,
        "rating": rating,
        "confidence": confidence,
        "report_path": report_path,
        "elapsed": elapsed,
        "error": error,
    }

    if error:
        logger.error("基金 %s 分析失败: %s", fund_code, error)
    else:
        logger.info(
            "基金 %s 分析完成: %s / %s (%.1f 秒)",
            fund_code,
            rating,
            confidence,
            elapsed,
        )

    return result


def print_summary(results: list[dict], analysis_date: str):
    """用 Rich 打印汇总表格。"""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()

        table = Table(title=f"IFA 每日基金分析汇总 — {analysis_date}", show_lines=True)
        table.add_column("基金代码", style="cyan", justify="center")
        table.add_column("评级", justify="center")
        table.add_column("置信度", justify="center")
        table.add_column("耗时", justify="right")
        table.add_column("状态", justify="center")
        table.add_column("报告路径", style="dim", max_width=50)

        rating_styles = {
            "STRONG_BUY": "[bold green]",
            "BUY": "[green]",
            "HOLD": "[yellow]",
            "UNDERWEIGHT": "[red]",
            "SELL": "[bold red]",
        }

        for r in results:
            rating = r["rating"]
            style_prefix = rating_styles.get(rating, "")
            rating_display = f"{style_prefix}{rating}[/]" if style_prefix else rating

            status = "失败" if r["error"] else "成功"
            status_display = f"[red]{status}[/]" if r["error"] else f"[green]{status}[/]"

            table.add_row(
                r["fund_code"],
                rating_display,
                r["confidence"],
                f"{r['elapsed']:.1f}s",
                status_display,
                r["report_path"] or "-",
            )

        console.print()
        console.print(table)

        # 统计
        total = len(results)
        success = sum(1 for r in results if not r["error"])
        total_time = sum(r["elapsed"] for r in results)
        console.print(
            f"\n  合计: {total} 只基金 | 成功: {success} | 失败: {total - success} | 总耗时: {total_time:.1f}s"
        )
        console.print()

    except ImportError:
        # Rich 未安装，用纯文本 fallback
        print(f"\n{'=' * 70}")
        print(f"  IFA 每日基金分析汇总 — {analysis_date}")
        print(f"{'=' * 70}")
        print(f"  {'基金代码':<10} {'评级':<15} {'置信度':<10} {'耗时':>8}  {'状态'}")
        print(f"  {'-' * 60}")
        for r in results:
            status = "失败" if r["error"] else "成功"
            print(f"  {r['fund_code']:<10} {r['rating']:<15} {r['confidence']:<10} {r['elapsed']:>7.1f}s  {status}")
        print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(
        description="IFA 每日基金批处理深度分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--codes",
        type=str,
        default=None,
        help="基金代码列表（逗号分隔），默认分析 161725/110020/000834/017641/012761",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="分析日期 YYYY-MM-DD，默认今天",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制运行，跳过交易日检查",
    )
    args = parser.parse_args()

    # 加载 .env
    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        pass

    # 确定分析日期
    analysis_date = args.date or datetime.now().strftime("%Y-%m-%d")

    # 交易日检查
    if not args.force:
        if not check_trading_day(analysis_date):
            logger.info("%s 非交易日，跳过分析。使用 --force 强制运行。", analysis_date)
            return
        logger.info("%s 是交易日，开始分析。", analysis_date)

    # 确定基金列表
    fund_codes = args.codes.split(",") if args.codes else DEFAULT_FUND_CODES

    logger.info("待分析基金: %s", ", ".join(fund_codes))

    # 创建 Advisor（复用同一个实例，共享 LLM 连接和记忆）
    from ifa.common import build_advisor

    advisor = build_advisor()

    # 逐只分析
    results = []
    for i, code in enumerate(fund_codes, 1):
        logger.info("[%d/%d] 分析基金 %s ...", i, len(fund_codes), code)
        result = analyze_single_fund(advisor, code.strip(), analysis_date)
        results.append(result)

    # 打印汇总
    print_summary(results, analysis_date)


if __name__ == "__main__":
    main()
