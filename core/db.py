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

-- v2 schema extension --------------------------------------------------------

-- 交易日（自旧项目 ladder 数据导入；标志该日是真实 A 股交易日）
CREATE TABLE IF NOT EXISTS trading_days (
    iso_date TEXT PRIMARY KEY,             -- YYYY-MM-DD
    compact TEXT NOT NULL,                 -- YYYYMMDD
    weekday INTEGER,                       -- 1-7
    source TEXT DEFAULT 'ladder',
    inserted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 每日"明日计划"快照（每个观察池目录 = 一个 plan）
CREATE TABLE IF NOT EXISTS plans (
    trade_date TEXT PRIMARY KEY,           -- 该 plan 的目标交易日 (YYYY-MM-DD)
    compact TEXT NOT NULL,
    pool_dir TEXT NOT NULL,
    html_path TEXT,
    csv_path TEXT,
    csv_codes_json TEXT,                   -- ["000123","002456",...]
    candidates_json TEXT,                  -- 全部解析后的候选行
    market_summary TEXT,
    theme_summary TEXT,
    risk_summary TEXT,
    execution_summary TEXT,
    source_script TEXT,
    th_import_status TEXT DEFAULT 'pending',  -- pending/done/blocked/failed
    th_import_note TEXT,
    th_imported_count INTEGER,
    snapshot_json TEXT,                    -- 全量原始字段冗余存档（可追溯）
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 每个候选展开成行（便于查询、筛选、跨日对比）
CREATE TABLE IF NOT EXISTS plan_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    role TEXT,                              -- 主选 / 条件 / 备选 / 参考
    rank INTEGER,
    score INTEGER,
    role_label TEXT,
    theme TEXT,
    industry TEXT,
    stage TEXT,                             -- 连板阶段：首板/2板/3板...
    pressure TEXT,
    next_day_board_price TEXT,
    trigger TEXT,
    abandon TEXT,
    risk_tag TEXT,
    raw_json TEXT,
    UNIQUE(trade_date, code)
);
CREATE INDEX IF NOT EXISTS idx_plan_cand_date ON plan_candidates(trade_date);
CREATE INDEX IF NOT EXISTS idx_plan_cand_code ON plan_candidates(code);

-- 每日复盘（一日一行；逐股结果在 review_results 表）
CREATE TABLE IF NOT EXISTS reviews (
    trade_date TEXT PRIMARY KEY,
    compact TEXT NOT NULL,
    report_path TEXT,
    market_state TEXT,                      -- 指数 + 成交概览
    breadth TEXT,                           -- 涨停/炸板/跌停数等
    top_themes TEXT,
    risk_feedback TEXT,
    metrics_json TEXT,                      -- {触板率, 封住率, 炸板率, 计划内可参与率…}
    sample_count INTEGER,
    sealed_count INTEGER,
    touched_count INTEGER,
    one_word_count INTEGER,                 -- 一字不可参与数
    afternoon_seal_count INTEGER,           -- 午后才封板
    high_break_seal_count INTEGER,          -- 高炸板封住
    snapshot_json TEXT,
    sources_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 逐股复盘结果（与 ledger CSV 1:1）
CREATE TABLE IF NOT EXISTS review_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    strategy_group TEXT,        -- 策略组：正式 / 对照
    code TEXT NOT NULL,
    name TEXT,
    plan_level TEXT,            -- 主选 / 条件 / 备选
    plan_role TEXT,
    plan_score INTEGER,
    plan_trigger TEXT,
    plan_abandon TEXT,
    actual_result TEXT,         -- 封住成功 / 触板炸板 / 未触板 / 弱于预期 / 一字不可参与 / 条件未满足
    touched TEXT,               -- 是 / 否
    sealed TEXT,                -- 是 / 否
    first_touch_time TEXT,
    last_seal_time TEXT,
    break_count TEXT,
    turnover_amount TEXT,
    turnover_rate TEXT,
    theme_feedback TEXT,
    diff_kind TEXT,
    experience_tag TEXT,
    evidence_source TEXT,
    report_path TEXT,
    raw_json TEXT,
    UNIQUE(trade_date, code, strategy_group)
);
CREATE INDEX IF NOT EXISTS idx_review_results_date ON review_results(trade_date);
CREATE INDEX IF NOT EXISTS idx_review_results_code ON review_results(code);

-- 次日溢价跟踪（晋级日期 + 溢价观察日 + 代码 唯一）
CREATE TABLE IF NOT EXISTS premium_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_date TEXT NOT NULL,            -- 晋级日期 YYYY-MM-DD
    premium_date TEXT NOT NULL,              -- 溢价观察日 YYYY-MM-DD
    code TEXT NOT NULL,
    name TEXT,
    prev_close REAL,
    next_open REAL,
    high_before_10 REAL,
    low_before_10 REAL,
    price_10 REAL,
    open_premium_pct REAL,
    high_premium_pct REAL,
    p10_premium_pct REAL,
    low_premium_pct REAL,
    shape TEXT,                              -- 高开高走/高开低走/低开高走/低开低走
    conclusion TEXT,                         -- 有正溢价可兑现 / ...
    data_source TEXT,
    raw_json TEXT,
    UNIQUE(promotion_date, premium_date, code)
);
CREATE INDEX IF NOT EXISTS idx_premium_promo ON premium_tracking(promotion_date);
CREATE INDEX IF NOT EXISTS idx_premium_obs ON premium_tracking(premium_date);

-- 连板天梯日概览
CREATE TABLE IF NOT EXISTS ladder_daily (
    iso_date TEXT PRIMARY KEY,
    raw_json TEXT NOT NULL                   -- 一日整行（含所有列）
);

-- 次日打板建议
CREATE TABLE IF NOT EXISTS ladder_advice (
    iso_date TEXT PRIMARY KEY,
    强度 TEXT,
    可打板 TEXT,
    可打级别 TEXT,
    建议仓位 TEXT,
    判断依据 TEXT,
    raw_json TEXT
);

-- 自动任务定义 + 运行状态
CREATE TABLE IF NOT EXISTS jobs (
    name TEXT PRIMARY KEY,                   -- e.g. review_daily / picks_daily / ladder_refresh
    cron_hint TEXT,                          -- 文本提示，例如 "weekday 16:30"
    target_script TEXT,                      -- 真要跑的脚本路径
    enabled INTEGER DEFAULT 1,
    last_run_at TEXT,
    last_status TEXT,                        -- ok / failed / skipped / pending
    last_message TEXT,
    last_target_date TEXT,                   -- 该次跑的目标交易日
    consecutive_failures INTEGER DEFAULT 0
);

-- 自动任务每次运行的明细
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    finished_at TEXT,
    target_date TEXT,
    status TEXT,                             -- ok / failed / skipped
    message TEXT,
    artifacts_json TEXT,                     -- 关键产物路径
    UNIQUE(job_name, target_date, started_at)
);
CREATE INDEX IF NOT EXISTS idx_job_runs_name ON job_runs(job_name, started_at DESC);

-- 数据来源记录
CREATE TABLE IF NOT EXISTS data_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                      -- review / plan / ladder / premium / kb
    iso_date TEXT,
    url TEXT,
    fetched_at TEXT,
    note TEXT
);

-- OSS 评估记录 + 系统改进队列
CREATE TABLE IF NOT EXISTS oss_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT,
    name TEXT,
    url TEXT,
    license TEXT,
    last_update TEXT,
    stars TEXT,
    fit TEXT,
    compat TEXT,
    security TEXT,
    recommendation TEXT,                     -- adopt / borrow_idea / reference / pass
    reason TEXT,
    status TEXT DEFAULT 'evaluating',        -- evaluating / adopted / referenced / dropped
    adopted_components TEXT,
    discovered_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS system_improvements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    problem TEXT,
    solution TEXT,
    status TEXT DEFAULT 'queued',            -- queued / in_progress / done / dropped
    priority TEXT DEFAULT 'normal',
    affects_strategy INTEGER DEFAULT 0,      -- 是否触及正式策略
    benefit TEXT,
    risk TEXT,
    rollback TEXT,
    related_oss TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    completed_at TEXT
);

-- 系统改进 / 维护变更日志
CREATE TABLE IF NOT EXISTS system_changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT,
    kind TEXT,                               -- ops / data / ui / strategy / bug
    title TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 数据健康问题（每次检查写一份；旧的标 resolved）
CREATE TABLE IF NOT EXISTS health_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    severity TEXT,                           -- info / warn / error
    kind TEXT,                               -- freshness / mismatch / source / job / ...
    target TEXT,
    detail TEXT,
    detected_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_health_active ON health_issues(resolved_at);
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
