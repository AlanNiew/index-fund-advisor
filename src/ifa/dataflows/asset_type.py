# ifa/dataflows/asset_type.py
"""资产类型检测系统 —— 根据证券代码自动判断资产类型。"""

from __future__ import annotations

from enum import Enum

from .a_share_common import normalize_ashare_symbol


class AssetType(str, Enum):
    """资产类型枚举。"""

    STOCK = "stock"                  # A 股个股
    ETF = "etf"                      # 场内 ETF 基金
    INDEX = "index"                  # 股票指数（如沪深 300、上证 50）
    OFFSHORE_FUND = "offshore_fund"  # 场外指数基金（联接基金、LOF）
    PUBLIC_FUND = "public_fund"      # 公募基金（股票型/混合型/债券型/QDII/FOF 等）


# ── 已知指数代码集合 ──────────────────────────────────────────
# 指数代码与个股存在前缀重叠（如 000001 既可是上证指数也可是平安银行），
# 因此维护一份主流指数白名单，优先匹配。
_KNOWN_INDEX_CODES: frozenset[str] = frozenset(
    {
        # ── 上证系列指数 ──
        "000001.SH",  # 上证指数
        "000002.SH",  # 上证 A 股
        "000003.SH",  # 上证 B 股
        "000004.SH",  # 上证工业
        "000005.SH",  # 上证商业
        "000006.SH",  # 上证地产
        "000007.SH",  # 上证公用
        "000009.SH",  # 上证 380
        "000010.SH",  # 上证 180
        "000011.SH",  # 上证基金
        "000012.SH",  # 上证国债
        "000015.SH",  # 上证红利
        "000016.SH",  # 上证 50
        "000021.SH",  # 上证可转债
        "000300.SH",  # 沪深 300
        # ── 中证系列指数 ──
        "000905.SH",  # 中证 500
        "000906.SH",  # 中证 800
        "000922.SH",  # 中证红利
        "000933.SH",  # 中证可选消费
        "000934.SH",  # 中证主要消费
        "000935.SH",  # 中证医药卫生
        "000936.SH",  # 中证金融地产
        "000937.SH",  # 中证能源
        "000938.SH",  # 中证原材料
        "000939.SH",  # 中证工业
        "000940.SH",  # 中证信息
        "000985.SH",  # 中证全指
        "000986.SH",  # 中证全指全收益
        "000987.SH",  # 中证军工
        "000988.SH",  # 中证银行
        "000989.SH",  # 中证新能源汽车
        "000993.SH",  # 中证全指金融
        "000991.SH",  # 中证全指消费
        "000992.SH",  # 中证全指医药
        "000994.SH",  # 中证全指信息
        "001004.SH",  # 中证 100
        "001255.SH",  # 中证 A50
        "001257.SH",  # 中证 A500
        # ── 深证系列指数 ──
        "399001.SZ",  # 深证成指
        "399004.SZ",  # 深证 100
        "399005.SZ",  # 中小板指
        "399006.SZ",  # 创业板指
        "399007.SZ",  # 深证 300
        "399010.SZ",  # 深证综指
        "399011.SZ",  # 深证指数
        "399106.SZ",  # 深证综指
        "399107.SZ",  # 深证 A 股
        "399314.SZ",  # 巨潮全 A
        "399550.SZ",  # 央视 50
        "399673.SZ",  # 创业板 50
        "399971.SZ",  # 中证创新驱动
        "399975.SZ",  # 中证全指证券
        "399976.SZ",  # 中证新能源汽车
        "399977.SZ",  # 中证内地低碳
        "399980.SZ",  # 中证新能源
        "399981.SZ",  # 中证银行
        "399984.SZ",  # 中证光伏
        "399989.SZ",  # 中证人工智能
        "399991.SZ",  # 中证半导体
        "399992.SZ",  # 中证创新药
        "399993.SZ",  # 中证白酒
        "399995.SZ",  # 中证智能家居
    }
)

# ── ETF 代码前缀（上交所 + 深交所） ─────────────────────────
_ETF_SH_PREFIXES = (
    "510", "511", "512", "513", "514", "515",
    "516", "517", "518", "519", "560", "561",
    "562", "563", "588",
)
_ETF_SZ_PREFIXES = ("159",)

# ── 场外基金（LOF/联接基金）代码前缀 ───────────────────────
_LOF_SH_PREFIXES = ("501",)
_LOF_SZ_PREFIXES = (
    "160", "161", "162", "163", "164",
    "165", "166", "167", "168", "169",
)


# ── 模糊指数代码 ────────────────────────────────────────────
# 这些代码同时存在于指数（.SH）和个股（.SZ），需要用户明确指定交易所才能判定为指数。
# 不在此集合中的指数代码即使只输入6位数字也自动识别为指数（因为无对应个股）。
_AMBIGUOUS_INDEX_CODES: frozenset[str] = frozenset(
    {
        "000001",  # 上证指数 / 平安银行
        "000002",  # 上证A指 / 万科A
        "000003",  # 上证B指 / 国农科技(退市)
        "000004",  # 上证工业 / 国华网安
        "000005",  # 上证商业 / ST星源
        "000006",  # 上证地产 / 深振业A
        "000007",  # 上证公用 / 全新好
        "000008",  # 上证综合 / 神州高铁
        "000009",  # 上证380 / 中国宝安
        "000010",  # 上证180 / 美丽生态
        "000011",  # 上证基金 / 深物业A
    }
)


def detect_asset_type(symbol: str) -> AssetType:
    """
    根据证券代码自动检测资产类型。

    检测优先级：
    1. 提取纯6位代码和交易所信息
    2. 检查是否属于已知指数白名单（需交易所匹配）
    3. 规范化代码后按前缀 + 交易所组合判定
    4. 默认返回 STOCK

    参数：
        symbol: 任意格式的证券代码（如 "510300"、"159919.SZ"、"SH000001"）。

    返回：
        AssetType: 检测到的资产类型。
    """
    import re

    # 提取纯6位代码
    normalized = symbol.strip().upper().replace(" ", "")
    if not normalized:
        return AssetType.STOCK

    # 从各种格式中提取纯代码和交易所
    digits_match = re.search(r"\d{6}", normalized)
    if not digits_match:
        return AssetType.STOCK
    plain_code = digits_match.group(0)

    # 检查用户是否明确指定了交易所
    has_explicit_sh = bool(re.search(r"(?:^SH|\.SH$)", normalized))
    has_explicit_sz = bool(re.search(r"(?:^SZ|\.SZ$)", normalized))
    has_explicit_exchange = has_explicit_sh or has_explicit_sz

    # 1. 检查已知指数白名单
    # 模糊代码（如 000001）需要用户明确指定交易所
    # 非模糊代码（如 000300）可直接匹配，因为无对应个股
    is_ambiguous = plain_code in _AMBIGUOUS_INDEX_CODES

    if has_explicit_sh and f"{plain_code}.SH" in _KNOWN_INDEX_CODES:
        return AssetType.INDEX
    if has_explicit_sz and f"{plain_code}.SZ" in _KNOWN_INDEX_CODES:
        return AssetType.INDEX
    # 非模糊代码：在白名单中即判定为指数
    if not is_ambiguous:
        if f"{plain_code}.SH" in _KNOWN_INDEX_CODES or f"{plain_code}.SZ" in _KNOWN_INDEX_CODES:
            return AssetType.INDEX

    # 2. 规范化代码
    try:
        normalized_symbol = normalize_ashare_symbol(symbol)
    except (ValueError, TypeError):
        # 无法识别交易所前缀 → 可能是场外基金代码（如 012414、007540）
        return AssetType.OFFSHORE_FUND

    code, _, exchange = normalized_symbol.partition(".")

    # 3. ETF 前缀判定（需结合交易所）
    if exchange == "SH" and code.startswith(_ETF_SH_PREFIXES):
        return AssetType.ETF
    if exchange == "SZ" and code.startswith(_ETF_SZ_PREFIXES):
        return AssetType.ETF

    # 4. LOF/场外基金前缀判定
    if exchange == "SH" and code.startswith(_LOF_SH_PREFIXES):
        return AssetType.OFFSHORE_FUND
    if exchange == "SZ" and code.startswith(_LOF_SZ_PREFIXES):
        return AssetType.OFFSHORE_FUND

    # 5. 深市指数：399xxx 均为指数
    if exchange == "SZ" and code.startswith("399"):
        return AssetType.INDEX

    # 6. 默认返回个股
    return AssetType.STOCK


def get_asset_label(asset_type: AssetType | str) -> dict[str, str]:
    """
    根据资产类型返回动态措辞字典，用于 Agent prompt 适配。

    参数：
        asset_type: 资产类型枚举值或字符串。

    返回：
        dict: 包含 instrument_noun、instrument_cn、entity_type 等键的措辞字典。
    """
    if isinstance(asset_type, str):
        try:
            asset_type = AssetType(asset_type)
        except ValueError:
            asset_type = AssetType.STOCK

    labels = {
        AssetType.STOCK: {
            "instrument_noun": "stock",
            "instrument_cn": "个股",
            "entity_type": "listed company",
            "analysis_focus": (
                "Analyze the company's financial statements, business fundamentals, "
                "and competitive position."
            ),
        },
        AssetType.ETF: {
            "instrument_noun": "ETF fund",
            "instrument_cn": "ETF 基金",
            "entity_type": "ETF fund",
            "analysis_focus": (
                "Analyze the ETF's tracking index, constituent stocks, fund profile, "
                "and liquidity."
            ),
        },
        AssetType.INDEX: {
            "instrument_noun": "market index",
            "instrument_cn": "指数",
            "entity_type": "market index",
            "analysis_focus": (
                "Analyze the index's constituent stocks, sector distribution, "
                "and weight concentration."
            ),
        },
        AssetType.OFFSHORE_FUND: {
            "instrument_noun": "index fund",
            "instrument_cn": "指数基金",
            "entity_type": "index fund",
            "analysis_focus": (
                "Analyze the fund's NAV trend, tracking error, "
                "and underlying index performance."
            ),
        },
        AssetType.PUBLIC_FUND: {
            "instrument_noun": "public fund",
            "instrument_cn": "公募基金",
            "entity_type": "public fund",
            "analysis_focus": (
                "Analyze the fund's NAV trend, risk metrics, performance ranking, "
                "holdings, and fund manager track record."
            ),
        },
    }
    return labels.get(asset_type, labels[AssetType.STOCK])
