# ifa/backtest/fees.py
"""回测的交易成本假设。

基金净值（单位净值 / 累计净值 / ETF 前复权价）**已经扣除了**管理费、托管费与销售服务费，
所以在回测里再按年化费率扣一次就是重复计费。真正落在净值之外、必须显式建模的只有三笔：

* 场外基金的**前端申购费** —— 认购时从投资额里扣；
* 场外基金的**赎回费** —— 赎回时从赎回额里扣，费率随持有期递减；
* 场内 ETF 的**券商佣金** —— 买入、卖出各一次。

费率的来源必须能说清楚：能从 `fund_fee_em` 取到就用真实值（`source="fund_fee_em"`），
取不到就用保守默认值并在报告里标注 `source="default"` —— 不能让读者以为这些数字是查到的。
默认值刻意取偏保守（费率偏高）方向：宁可低估收益，也不要给出乐观的假象。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: 取不到真实申购费率时的保守默认值（%，前端）。常见指数基金 1 折后约 0.10%~0.15%。
DEFAULT_PURCHASE_PCT = 0.15
#: 取不到真实赎回费率时的保守默认值（%，持有 1 年以内）。
DEFAULT_REDEMPTION_PCT = 0.50
#: 场内 ETF 的单边券商佣金默认值（%，万 3）。可被 `commission_pct` 参数覆盖。
DEFAULT_COMMISSION_PCT = 0.03

_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_INT_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class FeeAssumptions:
    """一次回测用到的全部费用假设。`applies=False` 表示本次不扣任何费用。"""

    applies: bool
    holding_days: int = 0
    purchase_pct: float = 0.0
    redemption_pct: float = 0.0
    commission_pct: float = 0.0
    operating_pct: float | None = None
    source: str = "default"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def entry_pct(self) -> float:
        """买入时一次性扣掉的费率（%）。"""
        return self.purchase_pct + self.commission_pct

    @property
    def exit_pct(self) -> float:
        """卖出时一次性扣掉的费率（%）。"""
        return self.redemption_pct + self.commission_pct

    def as_dict(self) -> dict[str, Any]:
        return {
            "applies": self.applies,
            "source": self.source,
            "holding_days": self.holding_days,
            "purchase_pct": round(self.purchase_pct, 4),
            "redemption_pct": round(self.redemption_pct, 4),
            "commission_pct": round(self.commission_pct, 4),
            "operating_pct": None if self.operating_pct is None else round(self.operating_pct, 4),
            "notes": list(self.notes),
        }

    def describe(self) -> str:
        """一行人类可读的费用假设，直接进回测报告。"""
        if not self.applies:
            return "未计任何交易成本（收益偏乐观）"
        parts: list[str] = []
        if self.purchase_pct:
            parts.append(f"申购费 {self.purchase_pct:.2f}%")
        if self.redemption_pct:
            parts.append(f"赎回费 {self.redemption_pct:.2f}%（持有 {self.holding_days} 天）")
        if self.commission_pct:
            parts.append(f"券商佣金 {self.commission_pct:.3f}%/单边")
        if not parts:
            parts.append("无一次性费用")
        if self.operating_pct is not None:
            parts.append(f"运作费率 {self.operating_pct:.2f}%/年已含在净值中（不重复扣除）")
        return "、".join(parts)


def _parse_pct(value: Any) -> float | None:
    """从 `"1.50%"` / `"0.20%（每年）"` 这类文本里取出百分数。"""
    match = _PCT_RE.search(str(value))
    return float(match.group(1)) if match else None


def _operating_fee_pct(df: Any) -> float | None:
    """`运作费用` 表是 1 行 N 列的键值对（管理费率 / 托管费率 / 销售服务费率）。"""
    total = 0.0
    found = False
    for value in df.iloc[0].tolist():
        parsed = _parse_pct(value)
        if parsed is not None:
            total += parsed
            found = True
    return round(total, 4) if found else None


def _tier_lower_bound(text: str) -> int:
    """从持有期文本里取出该档的**下界天数**。

    `小<7天` → 0；`大于等于7天，小于365天` → 7；`大于等于730天` → 730。
    """
    numbers = _INT_RE.findall(text)
    if not numbers:
        return 0
    if len(numbers) >= 2:
        return int(numbers[0])
    if "<" in text or "小于" in text:
        return 0
    return int(numbers[0])


def _pick_redemption_pct(df: Any, holding_days: int) -> float | None:
    """按实际持有天数挑赎回费率档位（取「下界不超过持有天数」里最大的那一档）。"""
    columns = list(df.columns)
    if len(columns) < 2:
        return None
    best_bound = -1
    best_rate: float | None = None
    for _, row in df.iterrows():
        bound = _tier_lower_bound(str(row[columns[0]]))
        rate = _parse_pct(row[columns[1]])
        if rate is None:
            continue
        if bound <= holding_days and bound > best_bound:
            best_bound = bound
            best_rate = rate
    return best_rate


def resolve_fees(
    symbol: str,
    asset_type_name: str,
    holding_days: int,
    *,
    commission_pct: float | None = None,
) -> FeeAssumptions:
    """解析一次回测该用的费用假设。

    指数（`INDEX`）本身不可直接投资，故不收费；ETF 只收券商佣金；场外基金收申购费 + 赎回费。
    任何一步取数失败都退化为保守默认值并写进 `notes`，绝不静默按 0 计。
    """
    notes: list[str] = []
    operating: float | None = None

    if asset_type_name not in ("ETF", "PUBLIC_FUND", "OFFSHORE_FUND", "INDEX"):
        return FeeAssumptions(applies=False, holding_days=holding_days, source="not_applicable")

    if asset_type_name == "INDEX":
        return FeeAssumptions(
            applies=False,
            holding_days=holding_days,
            source="not_applicable",
            notes=("指数本身不可直接投资，未计费用；对应 ETF 的实际成本请对 ETF 代码单独回测",),
        )

    # 运作费率只作说明（已含在净值里），取不到也不影响计算
    try:
        from ifa.dataflows.a_share_public_fund import fetch_fund_fee_table

        operating_df = fetch_fund_fee_table(symbol, "运作费用")
        if operating_df is not None and not operating_df.empty:
            operating = _operating_fee_pct(operating_df)
    except Exception as exc:  # noqa: BLE001
        logger.debug("运作费用取数失败 (%s): %s", symbol, exc)

    if asset_type_name == "ETF":
        rate = DEFAULT_COMMISSION_PCT if commission_pct is None else float(commission_pct)
        source = "default" if commission_pct is None else "explicit"
        if commission_pct is None:
            notes.append(f"券商佣金按默认 {DEFAULT_COMMISSION_PCT:.3f}%/单边估算（可用 commission_pct 覆盖）")
        return FeeAssumptions(
            applies=True,
            holding_days=holding_days,
            commission_pct=rate,
            operating_pct=operating,
            source=source,
            notes=tuple(notes),
        )

    purchase: float | None = None
    redemption: float | None = None
    source = "fund_fee_em"
    try:
        from ifa.dataflows.a_share_public_fund import fetch_fund_fee_table

        purchase_df = fetch_fund_fee_table(symbol, "申购费率")
        if purchase_df is not None and not purchase_df.empty:
            for value in purchase_df.to_numpy().ravel().tolist():
                parsed = _parse_pct(value)
                if parsed is not None:
                    purchase = parsed
                    break
        redemption_df = fetch_fund_fee_table(symbol, "赎回费率")
        if redemption_df is not None and not redemption_df.empty:
            redemption = _pick_redemption_pct(redemption_df, holding_days)
    except Exception as exc:  # noqa: BLE001
        logger.warning("费率取数失败 (%s): %s", symbol, exc)
        source = "default"
        notes.append(f"费率接口失败（{exc}），改用保守默认值")

    if purchase is None:
        purchase = DEFAULT_PURCHASE_PCT
        source = "default"
        notes.append(f"未取到申购费率，按 {DEFAULT_PURCHASE_PCT:.2f}% 保守估算")
    if redemption is None:
        redemption = DEFAULT_REDEMPTION_PCT
        source = "default"
        notes.append(f"未取到赎回费率，按 {DEFAULT_REDEMPTION_PCT:.2f}% 保守估算")

    return FeeAssumptions(
        applies=True,
        holding_days=holding_days,
        purchase_pct=purchase,
        redemption_pct=redemption,
        operating_pct=operating,
        source=source,
        notes=tuple(notes),
    )
