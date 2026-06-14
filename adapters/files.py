"""通用文件读取工具 — CSV / JSON / 文本，统一处理 utf-8-sig / utf-8。"""
from __future__ import annotations

import csv
import json
from pathlib import Path


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


def read_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError:
        return None


def read_csv_rows(path: Path) -> list[dict]:
    """读取 CSV 为字典列表，自动处理 BOM。"""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except UnicodeDecodeError:
        with path.open("r", encoding="gbk", newline="") as f:
            return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    """仅用于 system.db 之外的导出场景（默认禁止写旧项目目录）。"""
    if not rows and not fieldnames:
        return
    fieldnames = fieldnames or list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def safe_relative(p: Path, base: Path) -> str:
    """返回相对路径字符串；如果不在 base 之下则返回绝对。"""
    try:
        return str(p.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(p)
