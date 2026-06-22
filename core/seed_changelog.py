"""把 v2 的变更日志和初始改进项种入 DB。"""
from __future__ import annotations

from core.db import tx


CHANGELOG = [
    ("v2.0.0", "ops",  "v2 大重构：单页 Dashboard + 自动调度 + 数据回填",
     "1) 6 段统一首页（today/tomorrow/review/trend/iteration/health）"
     "; 2) 后台调度器（每分钟 tick；review@16:00, picks@18:00, ladder@15:30/17:00）"
     "; 3) 一次性回填全部历史（73 交易日 / 11 观察池 / 10 复盘 / 80 台账 / 10 溢价）"
     "; 4) 上层数据全部来自 SQLite，旧项目原文件作为可追溯证据"
     "; 5) 健康检查 + 数据新鲜度 + CSV 校验持续运行"),
    ("v2.0.0", "data", "Schema 扩 14 张表",
     "trading_days/plans/plan_candidates/reviews/review_results/premium_tracking/"
     "ladder_daily/ladder_advice/jobs/job_runs/oss_candidates/system_improvements/"
     "system_changelog/health_issues"),
    ("v2.0.0", "ui",   "支持新旧两套 HTML 观察池模板",
     "06-15 之前是 20 列固定表头；06-16 起表头变为动态。改为按 thead 动态读列名，避免错列。"),
    ("v2.0.0", "ops",  "launchd 开机自启 + KeepAlive",
     "scripts/launchd/install.sh 安装后，进程异常退出 15s 内自动重启；下次开机自动启动。"),
]


IMPROVEMENTS_INIT = [
    {
        "title": "把 Pico CSS / Tabler 抽取为可选主题",
        "priority": "low",
        "problem": "默认 CSS 是手写的，缺少专业仪表盘观感。",
        "solution": "在 static/css/ 下增加 themes/pico.css，layout.html 用 <link> 切换。",
        "benefit": "UI 一致性更好；不增加 JS 依赖。",
        "risk": "若 vendor 的 CSS 文件大于 50KB，加载会变慢。",
        "rollback": "删除 themes/，回到默认 app.css。",
    },
    {
        "title": "K 线分时小图（个股复盘弹窗）",
        "priority": "low",
        "problem": "复盘逐股看分时还要切到东方财富/腾讯。",
        "solution": "vendor klinecharts，在 review 行点击展开分时（数据从 sina/tencent 接口异步拉）。",
        "benefit": "复盘效率提升。",
        "risk": "依赖第三方行情接口，网络异常时降级隐藏。",
        "rollback": "前端无依赖；直接移除 chart 模块。",
    },
    {
        "title": "次日 10:00 前溢价自动抓取",
        "priority": "high",
        "problem": "目前 premium_tracking 完全依赖复盘 skill 手动填；自动化空缺。",
        "solution": "新增 premium_collector.py，每个交易日 10:10 抓取昨日成功晋级池次日 10:00 前价格，写 premium_tracking。",
        "benefit": "首页趋势分析的可兑现率更新更及时。",
        "risk": "外部行情接口可能限流；做好缓存与重试。",
        "rollback": "禁用 premium_collector 任务即可，已有手填数据不受影响。",
    },
    {
        "title": "夜间自动 git push 到 GitHub",
        "priority": "normal",
        "problem": "目前 system.db 不入 git；config / 代码改动需要手动 push。",
        "solution": "把 scripts/git_sync.sh 加入 launchd，每天 23:30 跑一次。",
        "benefit": "天然异地备份；变更可追溯。",
        "risk": "需要 SSH key 一直可用。",
        "rollback": "卸载 launchd 任务。",
    },
    {
        "title": "对照组观察池支持（不导入同花顺）",
        "priority": "normal",
        "problem": "证据门槛到 10 日 / 50 条之后需要支持'对照组'，但目前未实现。",
        "solution": "在 plans 表加 strategy_group 字段；新建对照组 skill 后由 picks_daily 同时产出两份。",
        "benefit": "为后续策略迭代铺路（仍受 SKILL 证据门槛约束）。",
        "risk": "需谨慎避免对照组 CSV 误入同花顺。",
        "rollback": "下线对照组任务即可，正式策略不受影响。",
    },
]


def seed() -> dict:
    nlog = 0
    nimp = 0
    with tx() as conn:
        for v, k, t, d in CHANGELOG:
            exist = conn.execute(
                "SELECT id FROM system_changelog WHERE version=? AND title=?",
                (v, t),
            ).fetchone()
            if not exist:
                conn.execute(
                    "INSERT INTO system_changelog (version, kind, title, detail) VALUES (?,?,?,?)",
                    (v, k, t, d),
                )
                nlog += 1
        for imp in IMPROVEMENTS_INIT:
            exist = conn.execute(
                "SELECT id FROM system_improvements WHERE title=?", (imp["title"],)
            ).fetchone()
            if not exist:
                conn.execute(
                    """INSERT INTO system_improvements
                    (title, priority, problem, solution, benefit, risk, rollback, affects_strategy, status)
                    VALUES (?,?,?,?,?,?,?,?, 'queued')""",
                    (imp["title"], imp["priority"], imp["problem"], imp["solution"],
                     imp["benefit"], imp["risk"], imp["rollback"], 0),
                )
                nimp += 1
    return {"changelog_inserted": nlog, "improvements_inserted": nimp}


if __name__ == "__main__":
    import json
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
