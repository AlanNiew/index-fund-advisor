# ifa/notify/markdown.py
"""极简 Markdown → HTML 渲染器（只用标准库）。

为什么自己写，而不是引入 `markdown` / `markdown-it-py`：

- 通知层的既定约束是「只用标准库」（见 `email.py` 顶部说明）。引入第三方渲染器会同时
  扩大 wheel 的依赖面、触发 `tests/test_dependency_declarations.py` 的「src/ifa 里直接
  导入的第三方库必须写进 pyproject」门禁，还要重算 requirements.lock —— 为一个发信功能
  付这个代价不划算。
- 输入是我们自己的 `report_generator` 产出（标题 / 表格 / 列表 / 粗体 / 分隔线），不是
  任意 Markdown 文档。覆盖这几种构造就够；**不认识的构造一律降级为段落文本**，绝不把
  原文吞掉 —— 渲染器的失败模式必须是「少一点样式」，不能是「少一段内容」。

安全：所有文本先 `html.escape(quote=True)` 再套行内标记，所以 `<script>` 只会变成转义后的
纯文本；链接只放行 http / https / mailto，其余协议（含 `javascript:`）按纯文本输出。
"""

from __future__ import annotations

import html
import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_FENCE_RE = re.compile(r"^(```+|~~~+)\s*(\S*)$")
_UL_RE = re.compile(r"^[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^\d{1,3}[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")

_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC_RE = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)|(?<![_\w])_([^_\n]+)_(?!_)")
_STRIKE_RE = re.compile(r"~~([^~]+)~~")
_SAFE_URL_RE = re.compile(r"^(?:https?://|mailto:)", re.IGNORECASE)


def _link(match: re.Match[str]) -> str:
    """只放行安全协议；其余按「文本（地址）」原样显示，不生成可点击链接。"""
    label, url = match.group(1), match.group(2)
    if not _SAFE_URL_RE.match(url):
        return f"{label}（{url}）"
    return f'<a href="{url}">{label}</a>'


def render_inline(text: str) -> str:
    """行内标记 → HTML。必须先转义再套标记，反过来会把生成的标签也转义掉。"""
    escaped = html.escape(text, quote=True)
    escaped = _INLINE_CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", escaped)
    escaped = _LINK_RE.sub(_link, escaped)
    escaped = _STRIKE_RE.sub(lambda m: f"<del>{m.group(1)}</del>", escaped)
    escaped = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", escaped)
    escaped = _ITALIC_RE.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", escaped)
    return escaped


def _split_row(line: str) -> list[str]:
    """拆一行表格：去首尾竖线，按未转义的 `|` 切分。"""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def _is_separator(line: str) -> bool:
    """`| :--- | ---: |` 这种对齐行。"""
    cells = _split_row(line)
    return bool(cells) and all(_TABLE_SEP_CELL_RE.match(cell) for cell in cells)


def _table(lines: list[str], start: int) -> tuple[str, int]:
    """渲染一张表。表头后必须紧跟对齐行（否则在调用方就不算表格）。"""
    header = _split_row(lines[start])
    separators = _split_row(lines[start + 1])
    aligns: list[str] = []
    for index in range(len(header)):
        sep_cell = separators[index] if index < len(separators) else ""
        if sep_cell.startswith(":") and sep_cell.endswith(":"):
            aligns.append("center")
        elif sep_cell.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")

    index = start + 2
    rows: list[list[str]] = []
    while index < len(lines) and lines[index].strip().startswith("|"):
        rows.append(_split_row(lines[index]))
        index += 1

    def cell(tag: str, text: str, position: int) -> str:
        align = aligns[position] if position < len(aligns) else "left"
        styles = [f"text-align:{align}"]
        if tag == "th":
            styles.append("background:#f2f2f2")
        return f'<{tag} style="{";".join(styles)}">{render_inline(text)}</{tag}>'

    parts = [
        '<table border="1" cellspacing="0" cellpadding="6" '
        'style="border-collapse:collapse;font-size:13px;margin:8px 0">',
        "<thead><tr>",
    ]
    parts.extend(cell("th", value, position) for position, value in enumerate(header))
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        parts.extend(cell("td", value, position) for position, value in enumerate(row))
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts), index


def _fence(lines: list[str], start: int, marker: str) -> tuple[str, int]:
    index = start + 1
    block: list[str] = []
    while index < len(lines) and not lines[index].strip().startswith(marker):
        block.append(lines[index])
        index += 1
    return "\n".join(block), min(index + 1, len(lines))


def _list(lines: list[str], start: int, pattern: re.Pattern[str]) -> tuple[list[str], int]:
    items: list[str] = []
    index = start
    while index < len(lines):
        match = pattern.match(lines[index].strip())
        if not match:
            break
        items.append(match.group(1))
        index += 1
    return items, index


def _quote(lines: list[str], start: int) -> tuple[str, int]:
    parts: list[str] = []
    index = start
    while index < len(lines):
        match = _QUOTE_RE.match(lines[index].strip())
        if not match:
            break
        parts.append(match.group(1))
        index += 1
    return "<br>".join(render_inline(part) for part in parts), index


def _paragraph(lines: list[str], start: int) -> tuple[str, int]:
    """连续的普通行合成一段（行内换行用 <br>，中英混排时比丢空格更安全）。"""
    parts: list[str] = []
    index = start
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            break
        if (
            _HEADING_RE.match(stripped)
            or _HR_RE.match(stripped)
            or _FENCE_RE.match(stripped)
            or _UL_RE.match(stripped)
            or _OL_RE.match(stripped)
            or _QUOTE_RE.match(stripped)
        ):
            break
        if stripped.startswith("|") and index + 1 < len(lines) and _is_separator(lines[index + 1]):
            break
        parts.append(stripped)
        index += 1
    return "<br>".join(render_inline(part) for part in parts), index


def render_markdown(text: str) -> str:
    """把 Markdown 文本渲染成 HTML 片段（块级）。空输入返回空串。"""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    index = 0
    total = len(lines)
    while index < total:
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue

        fence = _FENCE_RE.match(stripped)
        if fence:
            code, index = _fence(lines, index, fence.group(1))
            blocks.append(f"<pre><code>{html.escape(code, quote=True)}</code></pre>")
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{render_inline(heading.group(2).strip())}</h{level}>")
            index += 1
            continue

        if _HR_RE.match(stripped):
            blocks.append('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0">')
            index += 1
            continue

        if stripped.startswith("|") and index + 1 < total and _is_separator(lines[index + 1]):
            table, index = _table(lines, index)
            blocks.append(table)
            continue

        if _QUOTE_RE.match(stripped):
            quoted, index = _quote(lines, index)
            blocks.append(f"<blockquote>{quoted}</blockquote>")
            continue

        if _UL_RE.match(stripped):
            items, index = _list(lines, index, _UL_RE)
            blocks.append("<ul>" + "".join(f"<li>{render_inline(item)}</li>" for item in items) + "</ul>")
            continue

        if _OL_RE.match(stripped):
            items, index = _list(lines, index, _OL_RE)
            blocks.append("<ol>" + "".join(f"<li>{render_inline(item)}</li>" for item in items) + "</ol>")
            continue

        paragraph, index = _paragraph(lines, index)
        if paragraph:
            blocks.append(f"<p>{paragraph}</p>")
        else:
            index += 1
    return "\n".join(blocks)
