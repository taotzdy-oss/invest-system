"""配置加载 — 提供全局只读配置对象。"""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


class Config:
    def __init__(self, raw: dict) -> None:
        self._raw = raw
        self.legacy_root = Path(raw["legacy_root"])
        self.legacy = raw.get("legacy", {})
        self.server = raw.get("server", {})
        self.git = raw.get("git", {})

    def legacy_path(self, key: str) -> Path:
        """根据 config.json -> legacy.<key> 解析为绝对路径。"""
        rel = self.legacy.get(key)
        if not rel:
            raise KeyError(f"legacy.{key} 未在 config.json 中配置")
        return self.legacy_root / rel

    def legacy_glob(self, key: str) -> list[Path]:
        """根据 glob 模式列出旧项目下匹配的所有路径。"""
        pattern = self.legacy.get(key)
        if not pattern:
            return []
        return sorted(self.legacy_root.glob(pattern))


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"未找到配置文件: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return Config(raw)


CONFIG = load_config()
DATA_DIR.mkdir(parents=True, exist_ok=True)
