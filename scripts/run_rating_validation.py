#!/usr/bin/env python3
"""IFA 评级 vs 实际收益 回测验证脚本（独立入口，可 cron 调度）。

跑历史分析，对比「AI 当时给的评级」和「事后实际收益」，
输出命中率、置信区间、混淆矩阵、基准对比。

注意：仅支持 ETF/指数基金（避开公募基金净值的 tail(120) 截断问题）。

用法:
    # 基本用法：默认 ETF，过去 3 个月每月一次，持有 60 交易日
    python scripts/run_rating_validation.py

    # 指定基金和日期
    python scripts/run_rating_validation.py --codes 510300,159919 --dates 2024-01-15,2024-04-15

    # 过去 6 个月，持有 90 天
    python scripts/run_rating_validation.py --months-back 6 --hold-days 90

    # 显式开启记忆更新（注意幸存者偏差风险）
    python scripts/run_rating_validation.py --update-memory

智识诚实提醒：
    样本量 < 30 时统计结论无显著性。本验证不证明评级「有效」或「无效」，
    仅描述其在给定样本上的历史表现。过往表现不代表未来结果。

定时任务配置（Windows 任务计划程序）:
    每月 1 号 16:00 运行:
    schtasks /create /tn "IFA评级回测" /tr "python D:\\path\\to\\scripts\\run_rating_validation.py" /sc monthly /st 16:00
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

# 将 src 目录加入 sys.path，确保直接运行也能导入 ifa
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from ifa.env_loader import load_env_files

load_env_files()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 默认 ETF 列表（主流宽基，数据质量最高，避开公募基金 tail(120) 截断）
DEFAULT_FUND_CODES = ["510300", "159919", "510500", "510050"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IFA 评级 vs 实际收益 回测验证",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--codes",
        default=",".join(DEFAULT_FUND_CODES),
        help=f"逗号分隔的 ETF/指数基金代码（默认: {','.join(DEFAULT_FUND_CODES)}）",
    )
    parser.add_argument("--dates", help="逗号分隔的分析日期 YYYY-MM-DD（与 --months-back 二选一）")
    parser.add_argument("--months-back", type=int, default=3, help="自动生成过去 N 个月每月一个分析日期（默认 3）")
    parser.add_argument("--hold-days", type=int, default=60, help="评级后持有多少交易日看收益（默认 60）")
    parser.add_argument("--update-memory", action="store_true", help="把结果喂回反思系统（注意幸存者偏差风险）")
    parser.add_argument("--output-dir", default="results/validation", help="报告输出目录")
    args = parser.parse_args()

    # 延迟导入，避免 argparse 解析失败时白付导入成本
    from ifa.backtest.rating_validator import (
        format_validation_report,
        generate_monthly_dates,
        run_rating_validation,
    )
    from ifa.common import build_advisor

    fund_codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    if not fund_codes:
        logger.error("未提供有效基金代码")
        sys.exit(1)

    if args.dates:
        analysis_dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    else:
        analysis_dates = generate_monthly_dates(args.months_back)

    total_tasks = len(fund_codes) * len(analysis_dates)
    logger.info("=" * 60)
    logger.info("评级验证回测启动")
    logger.info("基金: %s", ", ".join(fund_codes))
    logger.info("分析日期: %s", ", ".join(analysis_dates))
    logger.info("持有周期: %d 个交易日", args.hold_days)
    logger.info("总任务数: %d", total_tasks)
    if args.update_memory:
        logger.warning("已开启 --update-memory，将更新 Agent 记忆（存在幸存者偏差风险）")
    logger.info("=" * 60)

    advisor = build_advisor()

    def on_progress(phase: str, idx: int, total: int, code: str, date: str, status: str):
        logger.info("[%d/%d] %s %s @ %s: %s", idx, total, phase, code, date, status)

    result = run_rating_validation(
        fund_codes=fund_codes,
        analysis_dates=analysis_dates,
        hold_days=args.hold_days,
        advisor=advisor,
        on_progress=on_progress,
        update_memory=args.update_memory,
    )

    # 输出报告
    report_md = format_validation_report(result)
    print("\n" + "=" * 60)
    print(report_md)
    print("=" * 60)

    # 落盘
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = out_dir / f"validation_{ts}.json"
    payload = {
        "meta": {
            "generated_at": dt.datetime.now().isoformat(),
            "hold_days": result.hold_days,
            "period_start": result.period_start,
            "period_end": result.period_end,
            "fund_codes": fund_codes,
            "update_memory": args.update_memory,
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

    logger.info("JSON: %s", json_path)
    logger.info("Markdown: %s", md_path)

    # 命中率简报
    if result.bullish_hit_rate is not None:
        ci = ""
        if result.bullish_ci_low is not None and result.bullish_ci_high is not None:
            ci = f" (95% CI: {result.bullish_ci_low:.1%} ~ {result.bullish_ci_high:.1%})"
        logger.info("看涨命中率: %.1f%%%s [n=%d]", result.bullish_hit_rate * 100, ci, result.bullish_n)
    if result.alpha_vs_random is not None:
        logger.info("Alpha vs 随机: %+.1f%%", result.alpha_vs_random * 100)
    if result.alpha_vs_csi300 is not None:
        logger.info("Alpha vs 沪深300: %+.1f%%", result.alpha_vs_csi300 * 100)

    for w in result.warnings:
        logger.warning("⚠️ %s", w)


if __name__ == "__main__":
    main()
