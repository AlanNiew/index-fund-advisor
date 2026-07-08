# ifa/dataflows/data_cleaning.py
"""数据清洗管道 —— 统一处理 AkShare 返回的 DataFrame。

借鉴 TradingAgents 的 _clean_dataframe 模式：
datetime 解析 → 缺失值处理 → 数值类型强制转换 → ffill/bfill
"""

import contextlib
import logging

import pandas as pd

logger = logging.getLogger(__name__)

# 常见日期列名（优先匹配）
_DATE_COLUMNS = {"date", "日期", "Date", "trade_date", "trading_date"}
# 常见价格列名
_PRICE_COLUMNS = {"open", "high", "low", "close", "pre_close", " setOpen", "setHigh", "setLow", "setClose"}
# 常见数值列名（排除这些之外的不强制转换）
_NUMERIC_EXCLUDE = {"code", "symbol", "ticker", "name", "名称", "代码", "类型"}


def clean_dataframe(df: pd.DataFrame, context: str = "") -> pd.DataFrame:
    """统一清洗 DataFrame，处理缺失值和类型不一致问题。

    参数:
        df: 原始 DataFrame
        context: 上下文描述（用于日志，如 "510300 ETF 日线"）

    返回:
        清洗后的 DataFrame（原地修改的副本）
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df

    original_len = len(df)
    df = df.copy()

    # 1. 解析日期列
    df = _parse_date_columns(df)

    # 2. 数值类型强制转换
    df = _coerce_numeric_columns(df)

    # 3. 缺失值处理
    df = _fill_missing_values(df)

    # 4. 按日期排序（如有日期列）
    for col in df.columns:
        if col.lower() in _DATE_COLUMNS:
            with contextlib.suppress(Exception):
                df = df.sort_values(col).reset_index(drop=True)
            break

    cleaned_len = len(df)
    if original_len != cleaned_len:
        logger.debug("数据清洗 [%s]: %d 行 → %d 行", context, original_len, cleaned_len)

    return df


def _parse_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将疑似日期列转换为 datetime 类型。"""
    for col in df.columns:
        col_lower = col.lower().strip()
        if col_lower in _DATE_COLUMNS or "date" in col_lower:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将疑似数值列强制转换为 numeric 类型。"""
    for col in df.columns:
        col_lower = col.lower().strip()
        # 跳过明确的非数值列
        if col_lower in _NUMERIC_EXCLUDE:
            continue
        # 对 object / string 类型尝试转换
        # 注意:pandas 3.0 起字符串列默认 dtype 由 object 改为 str(StringDtype),
        # 单用 `dtype == object` 会漏掉 str 列,改用 is_object_dtype/is_string_dtype 兼容两版
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            try:
                converted = pd.to_numeric(df[col], errors="coerce")
                # 如果转换后非空率 > 80%，接受转换
                if converted.notna().mean() > 0.8:
                    df[col] = converted
            except Exception:
                pass
    return df


def _fill_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """对数值列做前向/后向填充，非数值列保持原样。"""
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].ffill().bfill()
    return df


def truncate_report(report: str, max_chars: int = 3000) -> str:
    """截断过长的分析报告，防止超出 LLM 上下文窗口。

    参数:
        report: 原始报告文本
        max_chars: 最大字符数

    返回:
        截断后的报告（末尾附加省略提示）
    """
    if not report or len(report) <= max_chars:
        return report
    return report[:max_chars] + "\n\n[... 报告已截断，完整报告见日志 ...]"


def cap_tool_result(result: str, max_chars: int = 5000) -> str:
    """智能截断工具返回结果，保留标题行和数据行结构。

    与 truncate_report 不同，此函数会保留结果中的标题行（# 开头的行），
    然后截断数据部分，确保 LLM 仍然理解数据结构。

    参数:
        result: 工具返回的原始字符串
        max_chars: 最大字符数（默认 5000）

    返回:
        截断后的结果（保留标题 + 尽可能多的数据行 + 省略提示）
    """
    if not result or len(result) <= max_chars:
        return result

    # 分离标题行（# 开头）和数据行
    lines = result.split("\n")
    header_lines = []
    data_lines = []
    for line in lines:
        if line.startswith("#") or (not data_lines and not line.strip()):
            header_lines.append(line)
        else:
            data_lines.append(line)

    header_block = "\n".join(header_lines)
    if not data_lines:
        return result[:max_chars] + "\n\n[... 数据已截断 ...]"

    # 计算数据部分可用空间
    data_budget = max_chars - len(header_block) - 50  # 预留省略提示空间

    # 逐行添加数据，直到超出预算
    kept = []
    for line in data_lines:
        if sum(len(k) + 1 for k in kept) + len(line) + 1 > data_budget:
            break
        kept.append(line)

    result = header_block + "\n".join(kept)
    skipped = len(data_lines) - len(kept)
    if skipped > 0:
        result += f"\n\n[... 数据已截断，省略 {skipped} 行 ...]"
    return result
