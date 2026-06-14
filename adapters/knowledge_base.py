"""知识库适配器：读取旧项目 `锋芒策略解析知识库_*` 目录。

数据结构按"分类 -> 文档 -> 章节"组织，提供搜索与按路径读取。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from adapters.files import read_json, read_text
from core.config import CONFIG


@dataclass
class KBDoc:
    title: str
    path: Path
    relpath: str
    category: str
    size: int
    summary: str


def _category_of(rel: str) -> str:
    parts = rel.split("/")
    if rel.startswith("01_解析文本/"):
        return f"01 解析文本/{parts[1]}" if len(parts) > 2 else "01 解析文本"
    if rel.startswith("02_合并阅读稿/"):
        return "02 合并阅读稿"
    if rel.startswith("03_知识库/"):
        return "03 知识库主索引"
    if rel.startswith("04_案例验证/"):
        return "04 案例验证"
    return rel.split("/", 1)[0] if "/" in rel else "其他"


def list_docs() -> list[KBDoc]:
    """列出知识库内所有 md/html/csv 文件。"""
    kb_root = CONFIG.legacy_path("knowledge_base_dir")
    if not kb_root.exists():
        return []
    docs: list[KBDoc] = []
    for p in kb_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".md", ".html", ".csv", ".json"):
            continue
        if p.name.startswith("~$") or p.name == ".DS_Store":
            continue
        rel = str(p.relative_to(kb_root)).replace("\\", "/")
        title = p.stem
        summary = ""
        if p.suffix.lower() == ".md":
            txt = read_text(p)
            m = re.search(r"^#\s+(.+)$", txt, re.MULTILINE)
            if m:
                title = m.group(1).strip()
            # 取首段非空非标题文字
            for line in txt.splitlines():
                s = line.strip()
                if s and not s.startswith("#") and not s.startswith("```"):
                    summary = s[:80]
                    break
        docs.append(KBDoc(
            title=title, path=p, relpath=rel,
            category=_category_of(rel), size=p.stat().st_size,
            summary=summary,
        ))
    docs.sort(key=lambda d: (d.category, d.relpath))
    return docs


def categories() -> list[tuple[str, list[KBDoc]]]:
    grouped: dict[str, list[KBDoc]] = {}
    for d in list_docs():
        grouped.setdefault(d.category, []).append(d)
    return sorted(grouped.items())


def read_doc(relpath: str) -> tuple[KBDoc | None, str]:
    """按相对路径读取知识库内文件内容（含安全校验）。"""
    kb_root = CONFIG.legacy_path("knowledge_base_dir").resolve()
    target = (kb_root / relpath).resolve()
    try:
        target.relative_to(kb_root)
    except ValueError:
        return None, ""
    if not target.is_file():
        return None, ""
    rel = str(target.relative_to(kb_root)).replace("\\", "/")
    title = target.stem
    text = read_text(target)
    if target.suffix.lower() == ".md":
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if m:
            title = m.group(1).strip()
    doc = KBDoc(
        title=title, path=target, relpath=rel,
        category=_category_of(rel), size=target.stat().st_size, summary="",
    )
    return doc, text


def search(keyword: str, limit: int = 50) -> list[dict]:
    """全文检索（按行匹配）。返回 [{doc, line, snippet}, …]。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    out: list[dict] = []
    for doc in list_docs():
        if doc.path.suffix.lower() not in (".md", ".csv", ".html"):
            continue
        try:
            text = read_text(doc.path)
        except Exception:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                snippet = line.strip()
                if len(snippet) > 160:
                    snippet = snippet[:160] + "…"
                out.append({
                    "title": doc.title, "relpath": doc.relpath,
                    "category": doc.category, "line": idx, "snippet": snippet,
                })
                if len(out) >= limit:
                    return out
    return out


def manifest_info() -> dict:
    p = CONFIG.legacy_path("kb_manifest_json")
    data = read_json(p)
    return data if isinstance(data, dict) else {}
