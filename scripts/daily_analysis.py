"""IFA 每日基金批处理分析脚本。

对指定基金列表逐一执行 deep 模式深度分析，保存 Markdown 报告，
并在控制台打印评级汇总表格。非交易日自动跳过。

--email 发出的正文是**盘后摘要**（基金名称/净值(日期)/日涨跌/评级 + 指数估值）：
HTML 版由 ifa.notify.markdown 现场渲染（客户端不渲染 Markdown），纯文本版是可读摘要；完整报告作为 .md 附件送达。

用法:
    python scripts/daily_analysis.py                 # 分析「前一交易日」（仅交易日运行）
    python scripts/daily_analysis.py --force         # 强制运行（不检查交易日）
    python scripts/daily_analysis.py --date 2025-04-25  # 指定日期
    python scripts/daily_analysis.py --codes 161725,110020  # 指定基金
    python scripts/daily_analysis.py --mode deep_simple     # 无辩论（快得多）
    python scripts/daily_analysis.py --email         # 跑完把摘要（HTML + 纯文本）发到邮箱（.md 报告作附件）

退出码（供 cron / systemd 判断是否告警）:
    0  正常（含「非交易日跳过」—— 休市不是故障，不该触发告警）
    1  有基金分析失败，或邮件发送失败

分析日期：默认取「前一交易日」（周一 → 上周五，长假后 → 节前最后一个交易日）；
今天不是交易日则直接跳过、不发邮件（休市不是故障）。

定时任务配置（Windows 任务计划程序）:
    每个工作日 08:00 运行（早上跑，前一交易日的净值已公布；分析的是前一交易日）:
    schtasks /create /tn "IFA每日基金分析" /tr "python D:\\path\\to\\scripts\\daily_analysis.py --email" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:00

定时任务配置（Linux crontab，工作日 08:00 跑，跑完即发）:
    0 8 * * 1-5 cd /home/alan/index-fund-advisor && .venv/bin/python scripts/daily_analysis.py --email >> local_data/daily_analysis.log 2>&1

邮件配置见 README「每日邮件报告」一节；SMTP 密码建议放 IFA_SMTP_PASSWORD 环境变量。
"""

import argparse
import logging
import math
import sys
import time
from datetime import datetime, timedelta
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

# 基金代码 → 跟踪指数（**可选覆盖**）：只有当基金名称里看不出跟踪指数时才需要登记。
# 注意：乐咕乐股只提供下面 SUPPORTED_INDEX_NAMES 里这 12 个指数的 PE/PB，其它指数
# （如中证白酒、纳斯达克100、标普500）即使登记了也只会显示 '-'，不会编造数字。
FUND_INDEX_MAP = {
    "161725": "中证白酒",  # 乐咕乐股未覆盖 → 估值显示 '-'
    "110020": "沪深300",
    "000834": "纳斯达克100",  # 乐咕乐股未覆盖
    "017641": "标普500",  # 乐咕乐股未覆盖
    "012761": "上证红利",
}

# 乐咕乐股支持的指数名（来源：akshare stock_index_pe_lg / stock_index_pb_lg 的 symbol_map）。
# 自动识别只在名单内匹配，免得认出一个根本取不到估值数据的指数。
SUPPORTED_INDEX_NAMES = (
    "上证50",
    "沪深300",
    "上证380",
    "创业板50",
    "中证500",
    "上证180",
    "深证红利",
    "深证100",
    "中证1000",
    "上证红利",
    "中证100",
    "中证800",
)

# 按名称长度降序匹配，避免「中证1000」被更短的「中证100」抢先命中
_INDEX_NAMES_BY_LENGTH = tuple(sorted(SUPPORTED_INDEX_NAMES, key=len, reverse=True))


def detect_index_from_name(fund_name: str) -> str | None:
    """从基金名称识别跟踪指数（如「华泰柏瑞上证红利ETF联接A」→ 上证红利）。

    只认 SUPPORTED_INDEX_NAMES 里的指数：认不出来宁可显示 '-'，也不猜一个取不到数据、
    或者根本不对的指数 —— 估值张冠李戴比没有估值更糟。
    """
    text = (fund_name or "").strip()
    if not text:
        return None
    for name in _INDEX_NAMES_BY_LENGTH:
        if name in text:
            return name
    return None


def check_trading_day(date_str: str) -> bool:
    """判断指定日期是否为 A 股交易日。"""
    try:
        from ifa.dataflows.a_share_common import is_trade_date

        return is_trade_date(date_str)
    except Exception as e:
        logger.warning("交易日判断失败 (%s)，默认视为非交易日。请检查网络连接。", e)
        return False


def previous_trading_day(reference: str | None = None) -> str | None:
    """返回 reference（默认今天）之前最近的一个交易日；交易日历取不到时返回 None。

    早上跑批时「今天」还没收盘，能拿到的完整数据属于前一交易日 ——
    周一取上周五，长假后第一个工作日取节前最后一个交易日。
    """
    try:
        from ifa.dataflows.a_share_common import get_previous_trade_date

        base = datetime.strptime(reference, "%Y-%m-%d") if reference else datetime.now()
        return get_previous_trade_date((base - timedelta(days=1)).strftime("%Y-%m-%d"))
    except Exception as e:  # noqa: BLE001
        logger.error("无法确定前一交易日 (%s): %s", reference or "今天", e)
        return None


def fetch_fund_snapshots(fund_codes: list[str]) -> dict[str, dict]:
    """获取基金净值快照（名称/净值/净值日期/日涨跌幅），供邮件摘要使用。

    取数失败只记 warning 并返回空 dict —— 摘要少两列，不该让整封邮件发不出去。
    """
    try:
        from ifa.dataflows.a_share_public_fund import fetch_fund_daily_snapshots

        return fetch_fund_daily_snapshots(fund_codes)
    except Exception as e:
        logger.warning("基金净值快照获取失败，邮件摘要将缺少净值/涨跌列: %s", e)
        return {}


def resolve_index_name(fund_code: str, fund_name: str | None = None) -> str | None:
    """确定基金跟踪的指数：先看 FUND_INDEX_MAP 覆盖，再从基金名称自动识别。"""
    override = FUND_INDEX_MAP.get(fund_code.strip())
    if override:
        return override
    return detect_index_from_name(fund_name or "")


def fetch_valuations(fund_codes: list[str], fund_snapshots: dict[str, dict] | None = None) -> dict[str, dict]:
    """获取基金列表涉及的指数估值指标，返回 {fund_code: {"index_name", **metrics}}。"""
    from ifa.dataflows.a_share_macro import fetch_valuation_metrics

    snapshots = fund_snapshots or {}

    # 逐只确定跟踪指数；认不出来的（主动基金等）估值列显示 '-'
    index_by_code: dict[str, str | None] = {}
    for raw_code in fund_codes:
        code = raw_code.strip()
        snapshot = snapshots.get(code) or {}
        index_by_code[code] = resolve_index_name(code, snapshot.get("name"))

    unmapped = [code for code, name in index_by_code.items() if not name]
    if unmapped:
        logger.info("以下基金无法确定跟踪指数，估值列显示 '-': %s", ", ".join(unmapped))

    # 按指数拉取（同一指数只请求一次）
    index_metrics: dict[str, dict] = {}
    for name in sorted({value for value in index_by_code.values() if value}):
        try:
            logger.info("获取 %s 估值数据...", name)
            index_metrics[name] = fetch_valuation_metrics(name)
        except Exception as e:
            logger.warning("获取 %s 估值数据失败: %s", name, e)
            index_metrics[name] = {"index_name": name}

    # 映射回基金维度（复制一份，避免多只基金共享同一指数时互相污染）
    fund_metrics: dict[str, dict] = {}
    for code, index_name in index_by_code.items():
        metrics = dict(index_metrics.get(index_name, {})) if index_name else {}
        metrics.setdefault("index_name", index_name)
        fund_metrics[code] = metrics

    return fund_metrics


def _is_nan(value) -> bool:
    """判断是否为 NaN（仅 float 类型，其余返回 False）。"""
    return isinstance(value, float) and math.isnan(value)


def _fmt_val(value, suffix: str = "") -> str:
    """格式化估值指标，None/NaN 时返回 '-'。"""
    if value is None or _is_nan(value):
        return "-"
    return f"{value:.2f}{suffix}"


def _fmt_erp(value, markup: bool = True) -> str:
    """格式化 ERP 指标，正值带 + 号、负值带号；markup=True 时叠加 Rich 颜色，None/NaN 返回 '-'。"""
    if value is None or _is_nan(value):
        return "-"
    if value >= 0:
        return f"[green]+{value:.2f}%[/]" if markup else f"+{value:.2f}%"
    return f"[red]{value:.2f}%[/]" if markup else f"{value:.2f}%"


def print_valuation_overview(fund_codes: list[str], fund_metrics: dict[str, dict]):
    """分析前输出详细估值概览表。"""
    # 收集不重复的指数数据（按 fund_codes 顺序去重；指数名以 fetch_valuations 的结果为准）
    seen: set[str] = set()
    indices: list[tuple[str, dict]] = []
    for code in fund_codes:
        m = fund_metrics.get(code.strip(), {})
        idx = str(m.get("index_name") or "").strip()
        if idx and idx not in seen:
            seen.add(idx)
            indices.append((idx, m))

    if not indices:
        return

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="指数估值概览", show_lines=True)
        table.add_column("指数", style="cyan", justify="center")
        table.add_column("PE(TTM)", justify="right")
        table.add_column("PB", justify="right")
        table.add_column("ROE", justify="right")
        table.add_column("股息率(参考)", justify="right")
        table.add_column("盈利收益率", justify="right")
        table.add_column("无风险利率", justify="right")
        table.add_column("ERP", justify="right")

        for idx_name, m in indices:
            erp_str = _fmt_erp(m.get("erp"))

            table.add_row(
                idx_name,
                _fmt_val(m.get("pe_ttm")),
                _fmt_val(m.get("pb")),
                _fmt_val(m.get("roe"), "%"),
                _fmt_val(m.get("dividend_yield"), "%"),
                _fmt_val(m.get("earnings_yield"), "%"),
                _fmt_val(m.get("risk_free_rate"), "%"),
                erp_str,
            )

        console.print()
        console.print(table)
        console.print()

    except ImportError:
        # 纯文本 fallback
        print(f"\n{'=' * 90}")
        print("  指数估值概览")
        print(f"{'=' * 90}")
        header = f"  {'指数':<10} {'PE(TTM)':>8} {'PB':>8} {'ROE':>8} {'股息率(参考)':>8} {'盈利收益率':>10} {'无风险利率':>10} {'ERP':>8}"
        print(header)
        print(f"  {'-' * 86}")
        for idx_name, m in indices:
            row = (
                f"  {idx_name:<10} "
                f"{_fmt_val(m.get('pe_ttm')):>8} "
                f"{_fmt_val(m.get('pb')):>8} "
                f"{_fmt_val(m.get('roe'), '%'):>8} "
                f"{_fmt_val(m.get('dividend_yield'), '%'):>8} "
                f"{_fmt_val(m.get('earnings_yield'), '%'):>10} "
                f"{_fmt_val(m.get('risk_free_rate'), '%'):>10} "
                f"{_fmt_erp(m.get('erp'), markup=False):>8}"
            )
            print(row)
        print(f"{'=' * 90}\n")


def analyze_single_fund(advisor, fund_code: str, analysis_date: str, mode: str = "deep") -> dict:
    """分析单只基金，返回结果字典（含 report 全文，落盘为邮件附件）。"""
    from ifa.common import build_state, save_report

    logger.info("开始分析基金 %s（模式 %s）...", fund_code, mode)
    start_time = time.time()

    state = build_state(
        mode=mode,
        fund_codes=fund_code,
        analysis_date=analysis_date,
    )

    final_state = advisor.run(mode=mode, state=state)
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
        "report": report,
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


def print_summary(results: list[dict], analysis_date: str, fund_metrics: dict[str, dict] | None = None):
    """用 Rich 打印汇总表格。"""
    fund_metrics = fund_metrics or {}

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()

        table = Table(title=f"IFA 每日基金分析汇总 — {analysis_date}", show_lines=True)
        table.add_column("基金代码", style="cyan", justify="center")
        table.add_column("评级", justify="center")
        table.add_column("置信度", justify="center")
        table.add_column("PE(TTM)", justify="right")
        table.add_column("股息率(参考)", justify="right")
        table.add_column("ERP", justify="right")
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

            # 估值指标
            m = fund_metrics.get(r["fund_code"], {})
            pe_str = _fmt_val(m.get("pe_ttm"))
            div_str = _fmt_val(m.get("dividend_yield"), "%")
            erp_str = _fmt_erp(m.get("erp"))

            table.add_row(
                r["fund_code"],
                rating_display,
                r["confidence"],
                pe_str,
                div_str,
                erp_str,
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
        print(f"\n{'=' * 90}")
        print(f"  IFA 每日基金分析汇总 — {analysis_date}")
        print(f"{'=' * 90}")
        print(
            f"  {'基金代码':<10} {'评级':<15} {'置信度':<10} {'PE(TTM)':>8} {'股息率(参考)':>8} {'ERP':>8} {'耗时':>8}  {'状态'}"
        )
        print(f"  {'-' * 86}")
        for r in results:
            status = "失败" if r["error"] else "成功"
            m = fund_metrics.get(r["fund_code"], {})
            pe_str = _fmt_val(m.get("pe_ttm"))
            div_str = _fmt_val(m.get("dividend_yield"), "%")
            erp_str = _fmt_erp(m.get("erp"), markup=False)
            print(
                f"  {r['fund_code']:<10} {r['rating']:<15} {r['confidence']:<10} "
                f"{pe_str:>8} {div_str:>8} {erp_str:>8} {r['elapsed']:>7.1f}s  {status}"
            )
        print(f"{'=' * 90}")


def send_report_email(
    results: list[dict],
    analysis_date: str,
    mode: str,
    fund_metrics: dict[str, dict] | None = None,
    fund_snapshots: dict[str, dict] | None = None,
) -> None:
    """把本次结果组装成一封邮件发出去。

    配置缺失或发送失败都直接抛异常，由 main() 决定退出码 —— 发信失败必须让 cron 知道。
    """
    from ifa.default_config import build_runtime_config
    from ifa.notify.email import (
        EmailConfig,
        EmailConfigError,
        build_daily_report_email,
        send_email,
    )

    config = EmailConfig.from_config(build_runtime_config())
    if config is None:
        raise EmailConfigError(
            "未配置邮件通知：--email 需要 smtp_host / smtp_recipients / smtp_sender"
            "（用 ifa config 写入，或设置 IFA_SMTP_* / IFA_EMAIL_TO 环境变量，"
            "详见 README「每日邮件报告」）。"
        )

    subject, body, html_body, attachments = build_daily_report_email(
        analysis_date=analysis_date,
        results=results,
        fund_metrics=fund_metrics,
        fund_snapshots=fund_snapshots,
        mode=mode,
    )
    attached = send_email(subject, body, config=config, attachments=attachments, html_body=html_body)
    logger.info(
        "邮件已发送至 %s（纯文本 %d 字符 / HTML %d 字符，附件 %d 个）",
        ", ".join(config.recipients),
        len(body),
        len(html_body),
        attached,
    )


def main() -> int:
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
        help="分析日期 YYYY-MM-DD，默认前一交易日",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制运行，跳过交易日检查",
    )
    parser.add_argument(
        "--mode",
        choices=["deep", "deep_simple"],
        default="deep",
        help="分析模式: deep（含辩论，默认）/ deep_simple（无辩论，快得多）",
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="分析完成后发送邮件（正文为摘要 + HTML 渲染的报告全文，.md 报告作附件）",
    )
    args = parser.parse_args()

    # 加载 .env（含用户配置目录下的 .env）
    try:
        from ifa.env_loader import load_env_files

        load_env_files()
    except ImportError:
        pass

    # 确定分析日期：显式 --date 优先；否则分析「前一交易日」
    # （早上 08:00 跑批时当天还没收盘，能拿到的完整数据属于前一交易日）
    if args.date:
        analysis_date = args.date
        if not args.force and not check_trading_day(analysis_date):
            logger.info("%s 非交易日，跳过分析（不发邮件）。使用 --force 强制运行。", analysis_date)
            return 0
        logger.info("%s 是交易日，开始分析。", analysis_date)
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        if not args.force and not check_trading_day(today):
            logger.info("%s 非交易日，跳过分析（不发邮件）。使用 --force 强制运行。", today)
            return 0
        resolved = previous_trading_day(today)
        if resolved is None:
            logger.error("交易日历不可用，无法确定 %s 的前一交易日，跳过本次分析。", today)
            return 1
        analysis_date = resolved
        logger.info("%s 是交易日，分析前一交易日 %s。", today, analysis_date)

    # 确定基金列表
    fund_codes = args.codes.split(",") if args.codes else DEFAULT_FUND_CODES

    logger.info("待分析基金: %s", ", ".join(fund_codes))
    logger.info("分析模式: %s", args.mode)

    # 净值/涨跌快照（邮件摘要用；失败只影响摘要两列，不影响分析）
    fund_snapshots = fetch_fund_snapshots(fund_codes)

    # 获取估值指标（分析前，用于概览和汇总表）
    fund_metrics: dict[str, dict] = {}
    try:
        fund_metrics = fetch_valuations(fund_codes, fund_snapshots)
        print_valuation_overview(fund_codes, fund_metrics)
    except Exception as e:
        logger.warning("估值数据获取失败（不影响后续分析）: %s", e)

    # 创建 Advisor（复用同一个实例，共享 LLM 连接和记忆）
    from ifa.common import build_advisor

    advisor = build_advisor()

    # 逐只分析（串行：单只峰值内存约 500MB，小内存服务器上并行会 OOM）
    results = []
    for i, code in enumerate(fund_codes, 1):
        logger.info("[%d/%d] 分析基金 %s ...", i, len(fund_codes), code)
        result = analyze_single_fund(advisor, code.strip(), analysis_date, mode=args.mode)
        results.append(result)

    # 打印汇总
    print_summary(results, analysis_date, fund_metrics)

    # 失败即非零退出，让 cron / systemd 能发现（此前无论成败都返回 0）
    failed = [r["fund_code"] for r in results if r["error"]]
    exit_code = 0
    if failed:
        logger.error("以下基金分析失败: %s", ", ".join(failed))
        exit_code = 1

    if args.email:
        try:
            send_report_email(results, analysis_date, args.mode, fund_metrics, fund_snapshots)
        except Exception as e:
            logger.error("邮件发送失败: %s", e)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
