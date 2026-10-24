#!/usr/bin/env python3
"""IFA 评级结算脚本 —— 把「当时给的评级」和「后来实际赚了多少」对上账。

数据来源是**已经落盘的分析日志**（`results/logs/**/*.json`，每次 ifa 分析都会写），
因此本脚本**零 LLM 调用**：它只是补取价格、算前瞻收益、做统计。这也意味着它可以在
任何一天重跑，不会改写历史判断。

它同时给出两条口径的统计：

1. **生效评级**（`final_rating`）—— 用户当时实际看到的、经过稳定化折算的评级；
2. **原始评级**（`final_rating_raw`）—— 模型当天单次判断的原始评级。

两条口径并排放，是为了回答「稳定化是让判断更准了，还是只是变钝了」：
只看生效评级会掩盖「模型一直在翻转、只是被压住了」这种情况。
差异只说明稳定化改变了什么，不证明变好或变坏。

用法:
    # 默认：结算 results/ 下全部日志，主视界 60 交易日，统计视界 20/60/120
    python scripts/settle_ratings.py

    # 只看最近两个月的日志
    python scripts/settle_ratings.py --since 2026-09-01

    # 不用磁盘缓存（价格每次现取，慢但保证新鲜）
    python scripts/settle_ratings.py --no-cache

    # 只要机器可读结果
    python scripts/settle_ratings.py --json

    # 只统计某几种模式
    python scripts/settle_ratings.py --modes deep,deep_simple

定时任务（Linux cron，每周六 09:00 结算一次）:
    0 9 * * 6 cd /path/to/index-fund-advisor && .venv/bin/python scripts/settle_ratings.py >> local_data/settle.log 2>&1

智识诚实提醒:
    样本 < 30 时统计结论无显著性；前瞻收益未到期的样本不会被计入（不是当成 0）。
    过往表现不代表未来结果。
"""

from __future__ import annotations

import argparse
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

#: 前瞻收益缓存的默认位置（放在结算报告的同一目录，便于随产物一起归档）。
DEFAULT_CACHE_PATH = "results/validation/forward_returns_cache.json"


def _parse_ints(raw: str, flag: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError:
        logger.error("%s 必须是逗号分隔的整数，例如 20,60,120", flag)
        sys.exit(1)
    if not values:
        logger.error("%s 不能为空", flag)
        sys.exit(1)
    return values


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IFA 评级结算：用已落盘的分析日志对照实际前瞻收益",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--results-dir", default="results", help="分析日志与报告的根目录（默认 results）")
    parser.add_argument(
        "--hold-days",
        type=int,
        default=60,
        help="主视界：评级后持有多少交易日看收益（默认 60）",
    )
    parser.add_argument(
        "--horizons",
        default="20,60,120",
        help="逗号分隔的统计视界（交易日），默认 20,60,120 且必含 --hold-days",
    )
    parser.add_argument("--since", help="只结算该日期（含）之后的日志，YYYY-MM-DD")
    parser.add_argument("--until", help="只结算该日期（含）之前的日志，YYYY-MM-DD")
    parser.add_argument("--modes", help="只结算这些分析模式，逗号分隔，如 deep,deep_simple")
    parser.add_argument("--output-dir", default="results/validation", help="报告输出目录（默认 results/validation）")
    parser.add_argument("--cache-path", default=DEFAULT_CACHE_PATH, help="前瞻收益缓存文件路径")
    parser.add_argument("--no-cache", action="store_true", help="不读也不写前瞻收益缓存（价格每次现取）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON（不打印 Markdown 报告）")
    parser.add_argument("--no-write", action="store_true", help="不写报告文件，只打印")
    args = parser.parse_args()

    # 延迟导入：参数解析失败时不必付导入成本
    from ifa.backtest.settlement import (
        format_settlement_report,
        settle_logged_ratings,
        write_settlement,
    )

    horizon_list = _parse_ints(args.horizons, "--horizons")
    modes = [m.strip() for m in (args.modes or "").split(",") if m.strip()] or None

    logger.info("=" * 60)
    logger.info("评级结算启动")
    logger.info("日志目录: %s", args.results_dir)
    logger.info("主视界: %d 个交易日 | 统计视界: %s", args.hold_days, ", ".join(map(str, horizon_list)))
    if args.since or args.until:
        logger.info("日期范围: %s ~ %s", args.since or "最早", args.until or "最新")
    if modes:
        logger.info("模式过滤: %s", ", ".join(modes))
    logger.info("=" * 60)

    try:
        result = settle_logged_ratings(
            args.results_dir,
            hold_days=args.hold_days,
            horizons=horizon_list,
            modes=modes,
            since=args.since,
            until=args.until,
            cache_path=None if args.no_cache else args.cache_path,
            use_cache=not args.no_cache,
        )
    except Exception as exc:  # noqa: BLE001 —— 运维脚本，失败必须非零退出
        logger.exception("结算失败: %s", exc)
        sys.exit(1)

    for warning in result.warnings:
        logger.warning("⚠️ %s", warning)

    if args.json:
        import json

        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("")
        print(format_settlement_report(result))

    if not args.no_write:
        try:
            json_path, md_path = write_settlement(result, args.output_dir)
        except Exception as exc:  # noqa: BLE001
            logger.exception("报告写盘失败: %s", exc)
            sys.exit(1)
        logger.info("JSON: %s", json_path)
        logger.info("Markdown: %s", md_path)

    # 结算简报：一眼能看出「样本够不够、稳定化改了什么」
    comparison = result.comparison()
    logger.info(
        "样本: %d 条日志（%d 个文件，去重 %d）| 已到期: %s",
        result.entries_n,
        result.log_files,
        result.duplicates,
        ", ".join(f"{h}日 {n}" for h, n in sorted(result.matured_counts.items())) or "无",
    )
    logger.info(
        "评级变更: 生效 %s 次 / 原始 %s 次 | 维持不变 %d 天",
        comparison["effective"].get("rating_changes") if isinstance(comparison.get("effective"), dict) else "?",
        comparison["raw"].get("rating_changes") if isinstance(comparison.get("raw"), dict) else "?",
        result.stability.held_days,
    )
    logger.info("取数: 缓存命中 %d / 远程获取 %d", result.cache_hits, result.remote_fetches)


if __name__ == "__main__":
    main()
