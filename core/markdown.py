"""极简 Markdown -> HTML 渲染器。

只支持本系统真正用到的语法子集，零依赖：
- 标题 # ## ### …
- 段落、空行
- 无序列表 -, * （单层 + 嵌套两级）
- 有序列表 1.
- GFM 表格 | a | b |
- 代码块 ``` … ```
- 行内：**粗体** *斜体* `code` [text](url)
- 块引用 >

足以渲染旧项目所有复盘报告/知识库 MD，且无 pip 依赖。
"""
from __future__ import annotations

import html
import re


_INLINE_PATTERNS = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![\*_])\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2" target="_blank" rel="noopener">\1</a>'),
]


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    # 还原已被 escape 的 markdown 链接的 ()，让后续替换有效
    for pat, rep in _INLINE_PATTERNS:
        text = pat.sub(rep, text)
    return text


def _is_table_sep(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    parts = [p.strip() for p in stripped.split("|")]
    return all(re.fullmatch(r":?-{2,}:?", p) for p in parts) and len(parts) >= 1


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip() for c in stripped.split("|")]


def render(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    in_code = False
    code_lang = ""
    code_buf: list[str] = []

    def flush_code() -> None:
        nonlocal code_buf
        if not code_buf:
            return
        body = html.escape("\n".join(code_buf))
        cls = f' class="lang-{html.escape(code_lang)}"' if code_lang else ""
        out.append(f"<pre><code{cls}>{body}</code></pre>")
        code_buf = []

    while i < n:
        line = lines[i]

        # 代码块
        if line.strip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
                code_lang = ""
            else:
                in_code = True
                code_lang = line.strip()[3:].strip()
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        stripped = line.strip()

        # 空行
        if not stripped:
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # 块引用（聚合连续行）
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + _inline(" ".join(buf)) + "</blockquote>")
            continue

        # 表格：表头 + 分隔 + 数据
        if "|" in line and i + 1 < n and _is_table_sep(lines[i + 1]):
            headers = _split_table_row(line)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_table_row(lines[i]))
                i += 1
            thead = "".join(f"<th>{_inline(h)}</th>" for h in headers)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                for r in rows
            )
            out.append(
                f'<div class="md-table-wrap"><table><thead><tr>{thead}</tr></thead>'
                f'<tbody>{tbody}</tbody></table></div>'
            )
            continue

        # 列表（仅支持单层；嵌套以缩进 2/4 空格识别为子项）
        if re.match(r"^\s*[-*]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.\s+", line))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < n:
                m_ul = re.match(r"^\s*([-*])\s+(.*)$", lines[i])
                m_ol = re.match(r"^\s*\d+\.\s+(.*)$", lines[i])
                if ordered and m_ol:
                    items.append(_inline(m_ol.group(1)))
                    i += 1
                elif not ordered and m_ul:
                    items.append(_inline(m_ul.group(2)))
                    i += 1
                else:
                    break
            out.append(f"<{tag}>" + "".join(f"<li>{it}</li>" for it in items) + f"</{tag}>")
            continue

        # 段落（聚合连续非空、非块语法行）
        buf = [stripped]
        i += 1
        while i < n:
            s = lines[i].strip()
            if not s:
                break
            if re.match(r"^#{1,6}\s+", s) or s.startswith("```") or s.startswith(">"):
                break
            if re.match(r"^[-*]\s+", s) or re.match(r"^\d+\.\s+", s):
                break
            if "|" in lines[i] and i + 1 < n and _is_table_sep(lines[i + 1]):
                break
            buf.append(s)
            i += 1
        out.append("<p>" + _inline(" ".join(buf)) + "</p>")

    if in_code:
        flush_code()

    return "\n".join(out)
