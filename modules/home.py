"""总览页：聚合各模块关键指标 + 快速入口。"""
from __future__ import annotations

import html as _html
from datetime import datetime

from adapters import knowledge_base as kb_adapter
from adapters import review as rv_adapter
from adapters import stock_pick as sp_adapter
from adapters import strategy as st_adapter
from core.config import CONFIG
from core.router import router
from core.templates import layout


@router.route("/")
def home(req):
    pools = sp_adapter.list_pools()
    review_days = rv_adapter.list_review_days()
    scripts = st_adapter.list_strategy_scripts()
    kb_docs = kb_adapter.list_docs()
    bucket = rv_adapter.bucket_summary()
    idx = rv_adapter.ledger_index()

    latest_pool = pools[0] if pools else None
    latest_review = review_days[0] if review_days else None
    latest_script = scripts[0] if scripts else None

    stats_html = f"""
    <div class="grid grid-4">
      <div class="stat"><div class="label">最新观察池</div>
        <div class="value">{latest_pool.iso_date if latest_pool else '—'}</div>
        <div class="sub">共 {len(pools)} 个池子</div></div>
      <div class="stat"><div class="label">最新复盘</div>
        <div class="value">{latest_review.iso_date if latest_review else '—'}</div>
        <div class="sub">共 {len(review_days)} 天复盘</div></div>
      <div class="stat"><div class="label">策略脚本</div>
        <div class="value">{len(scripts)}</div>
        <div class="sub">最近：{latest_script.name if latest_script else '—'}</div></div>
      <div class="stat"><div class="label">知识库文档</div>
        <div class="value">{len(kb_docs)}</div>
        <div class="sub">来自 {CONFIG.legacy.get('knowledge_base_dir', '')}</div></div>
    </div>
    """

    bucket_html = f"""
    <div class="grid grid-4">
      <div class="stat"><div class="label">复盘样本总数</div><div class="value">{idx['total']}</div>
        <div class="sub">{idx['by_date'][0][0] if idx['by_date'] else ''} ~ {idx['by_date'][-1][0] if idx['by_date'] else ''}</div></div>
      <div class="stat"><div class="label">触板率</div><div class="value">{idx['touch_rate']:.1f}%</div>
        <div class="sub">{idx['touched']} / {idx['total']}</div></div>
      <div class="stat"><div class="label">封住率</div><div class="value">{idx['seal_rate']:.1f}%</div>
        <div class="sub">{idx['sealed']} / {idx['total']}</div></div>
      <div class="stat"><div class="label">成功晋级池</div><div class="value">{bucket.get('成功晋级池', 0)}</div>
        <div class="sub">失败晋级：{bucket.get('失败晋级池', 0)} · 失败样本：{bucket.get('失败样本池', 0)}</div></div>
    </div>
    """

    recent_pools = "".join(
        f'<li><a href="/picks/{p.date}">{p.iso_date}</a> '
        f'<span class="muted">{_html.escape(p.dir_path.name)}</span></li>'
        for p in pools[:8]
    ) or '<li class="muted">尚未发现观察池</li>'

    recent_reviews = "".join(
        f'<li><a href="/review/{d.date}">{d.iso_date}</a></li>'
        for d in review_days[:8]
    ) or '<li class="muted">尚未发现复盘报告</li>'

    legacy_root = str(CONFIG.legacy_root)
    body = f"""
    <h1>总览</h1>
    <div class="alert success">系统启动正常。当前时间：{datetime.now():%Y-%m-%d %H:%M:%S}。
      旧项目根目录：<code>{_html.escape(legacy_root)}</code></div>

    <div class="card"><h2>核心指标</h2>{stats_html}</div>

    <div class="card"><h2>复盘台账聚合</h2>{bucket_html}</div>

    <div class="grid grid-2">
      <div class="card"><h2>最近观察池</h2><ul>{recent_pools}</ul>
        <a class="btn primary" href="/picks">进入每日选股 →</a></div>
      <div class="card"><h2>最近复盘</h2><ul>{recent_reviews}</ul>
        <a class="btn primary" href="/review">进入复盘管理 →</a></div>
    </div>

    <div class="card"><h2>快速操作</h2>
      <div class="toolbar">
        <a class="btn" href="/strategy">📊 策略管理</a>
        <a class="btn" href="/kb">📚 知识库检索</a>
        <a class="btn" href="/picks">📈 今日观察池</a>
        <a class="btn" href="/review/template">📝 复盘模板</a>
        <a class="btn" href="/system/logs">📜 运行日志</a>
      </div>
    </div>
    """
    return layout("总览", body, active="home")


@router.route("/system/logs")
def system_logs(req):
    from adapters.runner import list_recent_logs
    logs = list_recent_logs(limit=30)
    rows = ""
    for lg in logs:
        out = (lg.get("stdout") or "")[-2000:]
        err = (lg.get("stderr") or "")[-2000:]
        rows += f"""<tr>
          <td>{lg['id']}</td><td>{_html.escape(lg.get('kind') or '')}</td>
          <td>{_html.escape(lg.get('cmd') or '')}</td>
          <td>{lg['exit_code']}</td><td>{lg['duration_ms']} ms</td>
          <td>{lg['started_at']}</td>
          <td><details><summary>stdout</summary><pre class="code-block">{_html.escape(out)}</pre></details>
              <details><summary>stderr</summary><pre class="code-block">{_html.escape(err)}</pre></details></td>
        </tr>"""
    body = f"""
    <h1>运行日志</h1>
    <div class="card"><h2>最近 30 次脚本调用</h2>
      <table><thead><tr><th>ID</th><th>类型</th><th>命令</th><th>退出码</th><th>耗时</th><th>开始时间</th><th>输出</th></tr></thead>
      <tbody>{rows or '<tr><td colspan=7 class="muted">暂无日志</td></tr>'}</tbody></table>
    </div>
    """
    return layout("运行日志", body, active="home")
