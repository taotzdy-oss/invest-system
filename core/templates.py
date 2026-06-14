"""极简模板引擎 — 仅支持 {{ var }} 替换 + {% include "x.html" %} + {% if %} 标记。

这里只做最小集，复杂的页面由 Python 直接拼字符串，更可控。
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from core.config import TEMPLATES_DIR


_VAR_RE = re.compile(r"\{\{\s*([\w\.\|]+)\s*\}\}")
_INCLUDE_RE = re.compile(r"\{%\s*include\s+\"([^\"]+)\"\s*%\}")


def _resolve(ctx: dict, dotted: str) -> str:
    """支持 a.b.c 取值，以及 |raw 跳过 escape。"""
    raw = False
    if "|" in dotted:
        name, flag = dotted.split("|", 1)
        raw = flag.strip() == "raw"
    else:
        name = dotted
    val: object = ctx
    for part in name.split("."):
        if isinstance(val, dict):
            val = val.get(part, "")
        else:
            val = getattr(val, part, "")
    s = "" if val is None else str(val)
    return s if raw else html.escape(s, quote=False)


def render(template_name: str, **ctx) -> str:
    tpl_path = TEMPLATES_DIR / template_name
    text = tpl_path.read_text(encoding="utf-8")
    # include
    def _inc(m: re.Match) -> str:
        inc_path = TEMPLATES_DIR / m.group(1)
        return inc_path.read_text(encoding="utf-8")
    text = _INCLUDE_RE.sub(_inc, text)
    # variable
    text = _VAR_RE.sub(lambda m: _resolve(ctx, m.group(1)), text)
    return text


def render_string(text: str, **ctx) -> str:
    text = _VAR_RE.sub(lambda m: _resolve(ctx, m.group(1)), text)
    return text


def layout(title: str, body_html: str, active: str = "") -> str:
    """统一注入 layout.html。"""
    return render("layout.html", title=title, body=body_html, active=active,
                  nav_strategy_active="active" if active == "strategy" else "",
                  nav_picks_active="active" if active == "picks" else "",
                  nav_review_active="active" if active == "review" else "",
                  nav_kb_active="active" if active == "kb" else "",
                  nav_home_active="active" if active == "home" else "")
