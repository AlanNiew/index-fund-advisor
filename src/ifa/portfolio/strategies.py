# ifa/portfolio/strategies.py
"""资产配置策略描述，注入到 Portfolio Advisor 的 prompt 中。"""

STRATEGY_DESCRIPTIONS: dict[str, dict] = {
    "core_satellite": {
        "name": "核心-卫星策略 (Core-Satellite)",
        "description": (
            "核心仓位（60-70%）配置宽基指数基金（如沪深300、中证500），"
            "提供市场基准收益；卫星仓位（30-40%）配置行业主题或风格基金，"
            "追求超额收益。适合稳健型和积极型投资者。"
        ),
        "applicable_profiles": ["moderate", "aggressive"],
    },
    "equal_weight": {
        "name": "等权策略 (Equal Weight)",
        "description": ("各指数类别等权配置，不偏好任何单一资产类别。分散化程度最高，适合不确定市场方向的投资者。"),
        "applicable_profiles": ["conservative", "moderate"],
    },
    "risk_parity": {
        "name": "风险平价策略 (Risk Parity)",
        "description": (
            "按风险贡献等权配置，使每个资产类别对组合总风险的贡献相等。"
            "低波动资产获得更高权重，高波动资产获得更低权重。"
            "适合追求风险调整后收益最大化的投资者。"
        ),
        "applicable_profiles": ["moderate", "aggressive"],
    },
    "barbell": {
        "name": "杠铃策略 (Barbell)",
        "description": (
            "两端配置（高防御+高进攻），中间减少。"
            "如债券/货币 + 行业主题基金，减少宽基指数配置。"
            "适合保守型和成长型投资者。"
        ),
        "applicable_profiles": ["conservative", "growth"],
    },
}
