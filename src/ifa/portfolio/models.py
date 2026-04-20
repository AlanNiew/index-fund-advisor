# ifa/portfolio/models.py
"""风险偏好模型和资产配置模板。"""

from dataclasses import dataclass, field


@dataclass
class RiskProfile:
    """风险偏好模型，定义大类资产配置约束。"""

    level: str
    description: str = ""
    allocation_template: dict[str, float] = field(default_factory=dict)
    max_single_fund_pct: float = 0.30
    min_bond_pct: float = 0.0
    max_international_pct: float = 0.20


# 预设风险偏好模板
RISK_PROFILES: dict[str, RiskProfile] = {
    "conservative": RiskProfile(
        level="conservative",
        description="保守型：追求资产保值，低波动，以债券和货币基金为主",
        allocation_template={
            "宽基指数": 0.30,
            "债券": 0.50,
            "货币": 0.15,
            "行业主题": 0.05,
        },
        max_single_fund_pct=0.40,
        min_bond_pct=0.40,
        max_international_pct=0.10,
    ),
    "moderate": RiskProfile(
        level="moderate",
        description="稳健型：追求资产增值与风险平衡，股债均衡配置",
        allocation_template={
            "宽基指数": 0.45,
            "中盘指数": 0.15,
            "债券": 0.25,
            "行业主题": 0.10,
            "QDII": 0.05,
        },
        max_single_fund_pct=0.30,
        min_bond_pct=0.15,
        max_international_pct=0.20,
    ),
    "aggressive": RiskProfile(
        level="aggressive",
        description="积极型：追求较高收益，承受较大波动，以权益类资产为主",
        allocation_template={
            "宽基指数": 0.35,
            "中盘指数": 0.20,
            "行业主题": 0.25,
            "QDII": 0.15,
            "债券": 0.05,
        },
        max_single_fund_pct=0.25,
        min_bond_pct=0.0,
        max_international_pct=0.25,
    ),
    "growth": RiskProfile(
        level="growth",
        description="成长型：追求高收益，高风险高波动，几乎全权益配置",
        allocation_template={
            "宽基指数": 0.25,
            "中盘指数": 0.25,
            "行业主题": 0.35,
            "QDII": 0.15,
        },
        max_single_fund_pct=0.20,
        min_bond_pct=0.0,
        max_international_pct=0.30,
    ),
}
