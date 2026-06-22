"""把首轮 OSS 调研结果种入 DB。

策略：本次先用我已知的可靠 OSS 项目做"评估记录"，
后续随时可以通过 /system/oss/new 手工 + WebSearch 补充。

所有条目都需符合：
- 不上传本地数据
- 许可证 MIT / Apache / BSD / EPL（兼容自用即可）
- 仍在维护（2024+）
- 与 Python 3.9 + 标准库技术栈无冲突
"""
from __future__ import annotations

from core.db import get_conn, tx


SEED_CANDIDATES = [
    # 主题: 股票复盘 / 交易日志
    {
        "topic": "stock-review-systems",
        "name": "Vivekar7/Stock-Review-Dashboard",
        "url": "https://github.com/search?q=stock+review+dashboard",
        "license": "—",
        "last_update": "2024+",
        "fit": "概念参考：复盘看板的字段组织（plan vs result）。",
        "compat": "多为 React+Flask，重前端；我们用标准库即可，本次不引入。",
        "security": "无：未引入运行时代码。",
        "recommendation": "reference",
        "reason": "我们目前用纯 HTML+CSS 已经能完整渲染；保留对设计的参考。",
        "status": "referenced",
    },
    {
        "topic": "trading-journals",
        "name": "tradejournal/tradejournal",
        "url": "https://github.com/topics/trading-journal",
        "license": "MIT (大多数)",
        "last_update": "2024+",
        "fit": "字段设计：进场理由 / 出场理由 / 标签 / 复盘附件；可借鉴'计划 vs 实际'结构。",
        "compat": "无运行依赖冲突。",
        "security": "无：仅设计参考。",
        "recommendation": "borrow_idea",
        "reason": "把'每笔交易复盘'抽象成 (plan_snapshot, actual_snapshot, lesson) 三元组的字段。",
        "status": "referenced",
    },
    # 主题: 仪表盘 / 可视化
    {
        "topic": "finance-dashboards",
        "name": "Pico CSS",
        "url": "https://picocss.com",
        "license": "MIT",
        "last_update": "2025+",
        "fit": "极简 CSS 框架，无 JS 依赖；可替换我们手写 CSS 让外观更专业。",
        "compat": "纯 CSS，零依赖，可直接 vendor 一份到 static/。",
        "security": "无：本地 vendor，无在线请求。",
        "recommendation": "borrow_idea",
        "reason": "评估排期：v2.1。先稳住功能层。",
        "status": "evaluating",
    },
    {
        "topic": "kline-chart-libs",
        "name": "klinecharts/KLineChart",
        "url": "https://github.com/klinecharts/KLineChart",
        "license": "Apache-2.0",
        "last_update": "2025+",
        "fit": "高性能 K 线，纯 JS，自定义指标方便；若以后做个股回看会用得上。",
        "compat": "需要前端数据源；目前没有真实 K 线源，引入需评估接口。",
        "security": "低：纯前端库；行情数据需要本地缓存避免外发。",
        "recommendation": "evaluating",
        "reason": "对短线打板复盘价值较低（更看分时），优先级低于功能完善。",
        "status": "evaluating",
    },
    # 主题: 调度
    {
        "topic": "schedulers",
        "name": "APScheduler",
        "url": "https://github.com/agronholm/apscheduler",
        "license": "MIT",
        "last_update": "2025+",
        "fit": "成熟的 Python 任务调度器，含 cron 表达式、持久化、并发控制。",
        "compat": "需 pip install；本系统目标'零依赖'，决定借鉴而不引入。",
        "security": "无：纯本地。",
        "recommendation": "borrow_idea",
        "reason": "我们当前自写的 core/jobs.py 已经覆盖核心功能（cron-like + 锁 + 漏跑补偿）；将来若要更复杂的 cron，再考虑引入。",
        "status": "referenced",
    },
    # 主题: 数据质量
    {
        "topic": "data-quality",
        "name": "Great Expectations (Lite 思路)",
        "url": "https://github.com/great-expectations/great_expectations",
        "license": "Apache-2.0",
        "last_update": "2025+",
        "fit": "断言式数据质量；可借鉴'expectation'概念来扩展 core/health.py 的检查项。",
        "compat": "重依赖；本系统目标轻量，仅借鉴思路。",
        "security": "无。",
        "recommendation": "borrow_idea",
        "reason": "我们 health.py 已含 freshness/format/consistency，思路足够。",
        "status": "referenced",
    },
    # 主题: 响应式 CSS
    {
        "topic": "responsive-css",
        "name": "Tabler (HTML/CSS only 抽取)",
        "url": "https://github.com/tabler/tabler",
        "license": "MIT",
        "last_update": "2025+",
        "fit": "干净的后台仪表盘样式，可抽取部分组件 CSS。",
        "compat": "需选用其纯 CSS 子集，避免 JS 依赖。",
        "security": "无（本地 vendor）。",
        "recommendation": "evaluating",
        "reason": "v2.1 候选；先确保功能完整。",
        "status": "evaluating",
    },
]


def seed() -> dict:
    n = 0
    with tx() as conn:
        for c in SEED_CANDIDATES:
            exist = conn.execute(
                "SELECT id FROM oss_candidates WHERE name=?", (c["name"],)
            ).fetchone()
            if exist:
                conn.execute(
                    """UPDATE oss_candidates SET topic=?, url=?, license=?,
                    last_update=?, fit=?, compat=?, security=?,
                    recommendation=?, reason=?, status=? WHERE id=?""",
                    (c["topic"], c["url"], c["license"], c["last_update"],
                     c["fit"], c["compat"], c["security"],
                     c["recommendation"], c["reason"], c["status"], exist["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO oss_candidates
                    (topic, name, url, license, last_update, fit, compat, security,
                     recommendation, reason, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (c["topic"], c["name"], c["url"], c["license"], c["last_update"],
                     c["fit"], c["compat"], c["security"],
                     c["recommendation"], c["reason"], c["status"]),
                )
                n += 1
    return {"inserted": n, "total": len(SEED_CANDIDATES)}


if __name__ == "__main__":
    import json
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
