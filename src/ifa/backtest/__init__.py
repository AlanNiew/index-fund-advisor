# ifa/backtest/__init__.py
"""回测模块 —— 基于历史数据验证分析策略的实际收益表现。"""

from ifa.backtest.engine import BacktestResult, format_backtest_report, run_backtest
from ifa.backtest.rating_validator import (
    RatingRecord,
    RatingValidationResult,
    add_trading_days,
    compute_statistics,
    format_validation_report,
    generate_monthly_dates,
    run_rating_validation,
    wilson_ci,
)

__all__ = [
    "BacktestResult",
    "format_backtest_report",
    "run_backtest",
    "RatingRecord",
    "RatingValidationResult",
    "wilson_ci",
    "compute_statistics",
    "run_rating_validation",
    "format_validation_report",
    "add_trading_days",
    "generate_monthly_dates",
]
