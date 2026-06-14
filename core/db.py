"""SQLite 增量数据层 — 只存储新系统产生的批注/笔记/版本/操作日志，绝不写旧项目。"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.config import DATA_DIR


DB_PATH = DATA_DIR / "system.db"
_LOCK = threading.Lock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_key TEXT NOT NULL,           -- 策略键，例如 fengmang-breakout
    label TEXT,                            -- 版本标签
    note TEXT,                             -- 版本说明
    params_json TEXT NOT NULL,             -- 参数 JSON 快照
    source_path TEXT,                      -- 关联的源文件（脚本/skill）
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS strategy_backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_key TEXT NOT NULL,
    version_id INTEGER,                    -- 关联 strategy_versions.id（可空）
    started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    metrics_json TEXT NOT NULL,            -- 回测指标 JSON
    sample_count INTEGER,                  -- 样本数
    date_from TEXT,
    date_to TEXT
);

CREATE TABLE IF NOT EXISTS stock_pick_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,              -- 交易日 YYYY-MM-DD
    code TEXT NOT NULL,                    -- 股票代码
    name TEXT,                             -- 股票名称
    pool_dir TEXT,                         -- 来源观察池目录
    mark TEXT,                             -- 标记：watch / buy / drop / hold
    note TEXT,                             -- 批注
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(trade_date, code)
);

CREATE TABLE IF NOT EXISTS review_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    strategy_key TEXT,                     -- 关联策略
    note TEXT NOT NULL,                    -- markdown 笔记
    tags TEXT,                             -- 逗号分隔
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS kb_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,                    -- markdown
    tags TEXT,
    refs TEXT,                             -- 关联的知识库文件路径，逗号分隔
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                    -- 'stock_pick' | 'review_rebuild' | ...
    cmd TEXT NOT NULL,                     -- 完整命令
    cwd TEXT,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_marks_date ON stock_pick_marks(trade_date);
CREATE INDEX IF NOT EXISTS idx_review_date ON review_notes(trade_date);
CREATE INDEX IF NOT EXISTS idx_versions_key ON strategy_versions(strategy_key);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _LOCK:
        conn = get_conn()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


@contextmanager
def tx():
    """事务上下文管理器。"""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
