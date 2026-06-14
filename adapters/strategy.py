"""策略适配器：扫描旧项目策略脚本与参数。

每个 `generate_fengmang_breakout_<YYYYMMDD>.py` 文件被视为一个策略快照，
通过正则提取顶层常量（ROLE_RULES、TRIGGER_RULES、EXCLUDED_REVIEW 等）作为参数。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from adapters.files import read_text
from core.config import CONFIG


KEYS_TO_EXTRACT = [
    "SOURCE_DATE", "NEXT_DATE", "NEXT_COMPACT",
    "ROLE_RULES", "TRIGGER_RULES", "EXCLUDED_REVIEW",
]


@dataclass
class StrategyScript:
    name: str               # generate_fengmang_breakout_20260615
    path: Path
    date: str               # 20260615 (NEXT_COMPACT)
    source_date: str        # 2026-06-12
    next_date: str          # 2026-06-15
    params: dict = field(default_factory=dict)


def _extract_top_level_assignments(src: str) -> dict:
    """用 AST 取得脚本顶层简单常量赋值。"""
    out: dict = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if tgt.id not in KEYS_TO_EXTRACT:
            continue
        try:
            out[tgt.id] = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            # 非字面量（如调用、复合表达式），存为 source 文本
            out[tgt.id] = ast.unparse(node.value)
    return out


def list_strategy_scripts() -> list[StrategyScript]:
    scripts: list[StrategyScript] = []
    for p in CONFIG.legacy_glob("stock_pick_script_glob"):
        if not p.is_file():
            continue
        m = re.search(r"_(\d{8})\.py$", p.name)
        compact = m.group(1) if m else ""
        src = read_text(p)
        params = _extract_top_level_assignments(src)
        scripts.append(StrategyScript(
            name=p.stem, path=p, date=compact,
            source_date=str(params.get("SOURCE_DATE", "")),
            next_date=str(params.get("NEXT_DATE", "")),
            params=params,
        ))
    scripts.sort(key=lambda s: s.date, reverse=True)
    return scripts


def get_script(name: str) -> StrategyScript | None:
    for s in list_strategy_scripts():
        if s.name == name:
            return s
    return None
