"""复盘模块：复盘日历表 / 每日详情 / 台账 / 晋级池 / 经验 / 笔记 / 重建分桶。"""
from __future__ import annotations

import html as _html

from adapters import review as rv_adapter
from adapters.runner import run_python
from core.config import CONFIG
from core.db import get_conn, tx
from core.markdown import render as md_render
from core.router import router, redirect
from core.templates import layout


@router.route("/review")
def review_index(req):
    days = rv_adapter.list_review_days()
    bucket = rv_adapter.bucket_summary()
    idx = rv_adapter.ledger_index()

    day_rows = ""
    for d in days:
        day_rows += f"""<tr>
          <td><a href="/review/{d.date}">{d.iso_date}</a></td>
          <td><span class="muted">{_html.escape(d.dir_path.name)}</span></td>
          <td>{'✅ 复盘报告' if d.report_path else '⚠ 缺失报告'}</td>
        </tr>"""

    by_date_html = "".join(
        f'<tr><td>{date}</td><td>{n}</td></tr>'
        for date, n in idx['by_date']
    )

    by_level_html = "".join(
        f'<tr><td>{lv}</td><td>{n}</td></tr>'
        for lv, n in idx['by_level']
    )

    body = f"""
    <h1>复盘管理</h1>
    <div class="grid grid-4">
      <div class="stat"><div class="label">总样本</div><div class="value">{idx['total']}</div></div>
      <div class="stat"><div class="label">触板率</div><div class="value">{idx['touch_rate']:.1f}%</div><div class="sub">{idx['touched']} / {idx['total']}</div></div>
      <div class="stat"><div class="label">封住率</div><div class="value">{idx['seal_rate']:.1f}%</div><div class="sub">{idx['sealed']} / {idx['total']}</div></div>
      <div class="stat"><div class="label">成功晋级</div><div class="value">{bucket.get('成功晋级池', 0)}</div>
        <div class="sub">失败晋级 {bucket.get('失败晋级池', 0)} · 失败样本 {bucket.get('失败样本池', 0)}</div></div>
    </div>

    <div class="grid grid-2">
      <div class="card"><h2>复盘日列表（按日期倒序）</h2>
        <table><thead><tr><th>交易日</th><th>目录</th><th>报告</th></tr></thead>
        <tbody>{day_rows or '<tr><td colspan=3 class="muted">尚未发现复盘报告</td></tr>'}</tbody></table>
      </div>
      <div class="card"><h2>分布概览</h2>
        <h3>每日样本数</h3>
        <table><thead><tr><th>日期</th><th>样本</th></tr></thead><tbody>{by_date_html}</tbody></table>
        <h3 style="margin-top:14px">按计划级别</h3>
        <table><thead><tr><th>级别</th><th>样本</th></tr></thead><tbody>{by_level_html}</tbody></table>
      </div>
    </div>

    <div class="card"><h2>快速跳转</h2>
      <div class="toolbar">
        <a class="btn" href="/review/ledger">📋 完整台账</a>
        <a class="btn" href="/review/bucket/成功晋级池">✅ 成功晋级池</a>
        <a class="btn" href="/review/bucket/失败晋级池">❎ 失败晋级池</a>
        <a class="btn" href="/review/bucket/失败样本池">⬛ 失败样本池</a>
        <a class="btn" href="/review/experience">📘 经验库</a>
        <a class="btn" href="/review/iteration">🧭 策略迭代日志</a>
        <a class="btn" href="/review/template">📝 复盘模板</a>
        <a class="btn" href="/review/notes">🗒 我的复盘笔记</a>
        <form method="post" action="/review/rebuild-buckets" style="display:inline">
          <button class="btn primary" data-confirm="将运行 rebuild_promotion_buckets.py 重建晋级分层，是否继续？">🔄 重建分层池</button>
        </form>
      </div>
    </div>
    """
    return layout("复盘管理", body, active="review")


@router.route("/review/rebuild-buckets", methods=("POST",))
def rebuild_buckets(req):
    script = CONFIG.legacy_path("rebuild_buckets_script")
    if not script.exists():
        return (404, layout("复盘", "<div class='alert error'>未找到 rebuild_promotion_buckets.py</div>", active="review"))
    run_python(script, kind="review_rebuild")
    return redirect("/system/logs")


@router.route("/review/ledger")
def review_ledger(req):
    rows = rv_adapter.ledger_rows()
    date_filter = req.get("date", "")
    code_filter = req.get("code", "")
    if date_filter:
        rows = [r for r in rows if r.get("交易日期") == date_filter]
    if code_filter:
        rows = [r for r in rows if code_filter in (r.get("代码") or "") or code_filter in (r.get("名称") or "")]
    head = "".join(f"<th>{h}</th>" for h in rv_adapter.LEDGER_FIELDS)
    body_rows = ""
    for r in rows:
        cells = "".join(f"<td>{_html.escape(str(r.get(h, '')))}</td>" for h in rv_adapter.LEDGER_FIELDS)
        body_rows += f"<tr>{cells}</tr>"
    body = f"""
    <h1>复盘台账</h1>
    <div class="card">
      <form method="get" class="toolbar">
        <input type="text" name="date" value="{_html.escape(date_filter)}" placeholder="YYYY-MM-DD" style="max-width:180px">
        <input type="text" name="code" value="{_html.escape(code_filter)}" placeholder="代码 / 名称" style="max-width:240px">
        <button class="btn primary">筛选</button>
        <a class="btn" href="/review/ledger">清除</a>
        <span class="muted">共 {len(rows)} 行</span>
      </form>
      <div class="md-table-wrap" style="max-height:680px;overflow:auto">
        <table><thead><tr>{head}</tr></thead><tbody>{body_rows or '<tr><td colspan=22 class=muted>无匹配</td></tr>'}</tbody></table>
      </div>
    </div>
    """
    return layout("复盘台账", body, active="review")


@router.route("/review/bucket/<name>")
def review_bucket(req, name):
    rows = rv_adapter.bucket_rows(name)
    head = "".join(f"<th>{h}</th>" for h in rv_adapter.LEDGER_FIELDS)
    body_rows = ""
    for r in rows:
        cells = "".join(f"<td>{_html.escape(str(r.get(h, '')))}</td>" for h in rv_adapter.LEDGER_FIELDS)
        body_rows += f"<tr>{cells}</tr>"
    body = f"""
    <h1>{_html.escape(name)}（{len(rows)} 条）</h1>
    <div class="card">
      <div class="toolbar">
        <a class="btn" href="/review">← 返回复盘</a>
        <a class="btn" href="/review/bucket/成功晋级池">成功晋级池</a>
        <a class="btn" href="/review/bucket/失败晋级池">失败晋级池</a>
        <a class="btn" href="/review/bucket/失败样本池">失败样本池</a>
        <a class="btn" href="/review/bucket/失败上板池">失败上板池</a>
      </div>
      <div class="md-table-wrap" style="max-height:680px;overflow:auto">
        <table><thead><tr>{head}</tr></thead><tbody>{body_rows or '<tr><td colspan=22 class=muted>暂无</td></tr>'}</tbody></table>
      </div>
    </div>
    """
    return layout(name, body, active="review")


@router.route("/review/experience")
def review_experience(req):
    md = rv_adapter.experience_md()
    body = f"""
    <h1>复盘经验库</h1>
    <div class="card">
      <p class="muted">源文件：<code>{_html.escape(str(CONFIG.legacy_path('review_experience_md')))}</code></p>
      <div class="md-render">{md_render(md)}</div>
    </div>
    """
    return layout("复盘经验库", body, active="review")


@router.route("/review/iteration")
def review_iteration(req):
    md = rv_adapter.strategy_iteration_md()
    body = f"""
    <h1>策略迭代日志</h1>
    <div class="card">
      <p class="muted">源文件：<code>{_html.escape(str(CONFIG.legacy_path('strategy_iteration_md')))}</code></p>
      <div class="md-render">{md_render(md)}</div>
    </div>
    """
    return layout("策略迭代日志", body, active="review")


@router.route("/review/template")
def review_template(req):
    md = rv_adapter.review_template_md()
    body = f"""
    <h1>每日复盘模板</h1>
    <div class="card"><div class="md-render">{md_render(md)}</div></div>
    """
    return layout("复盘模板", body, active="review")


@router.route("/review/<date>")
def review_day(req, date):
    if not date.isdigit() or len(date) != 8:
        return (404, "日期格式应为 YYYYMMDD")
    d = rv_adapter.get_review_day(date)
    if not d:
        return (404, layout("复盘", f"<div class='alert error'>未找到 {date} 的复盘目录</div>", active="review"))
    report_html = ""
    if d.report_path:
        report_html = md_render(d.report_path.read_text(encoding="utf-8"))

    # 取本系统补充的笔记
    conn = get_conn()
    notes = conn.execute(
        "SELECT * FROM review_notes WHERE trade_date=? ORDER BY id DESC", (d.iso_date,)
    ).fetchall()
    conn.close()

    notes_html = ""
    for n in notes:
        notes_html += f"""<div class="card compact">
          <div class="muted">{n['created_at']} · 标签：{_html.escape(n['tags'] or '')}</div>
          <div class="md-render">{md_render(n['note'])}</div>
          <form method="post" action="/review/{d.date}/note/delete" style="margin-top:6px">
            <input type="hidden" name="id" value="{n['id']}">
            <button class="btn small danger" data-confirm="确认删除该笔记？">删除</button>
          </form>
        </div>"""

    body = f"""
    <h1>{d.iso_date} 复盘</h1>
    <div class="toolbar">
      <a class="btn" href="/review">← 返回</a>
      <span class="muted">目录：{_html.escape(str(d.dir_path))}</span>
    </div>
    <div class="grid grid-2">
      <div class="card"><h2>原复盘报告</h2>
        {'<div class="md-render">' + report_html + '</div>' if report_html else '<div class="alert warn">该日缺少复盘报告 .md</div>'}
      </div>
      <div>
        <div class="card"><h2>追加复盘笔记</h2>
          <form method="post" action="/review/{d.date}/note">
            <div class="field"><label>笔记内容 (Markdown)</label><textarea name="note" required></textarea></div>
            <div class="field"><label>标签 (逗号分隔)</label><input type="text" name="tags" placeholder="如：执行/失败案例/卖点"></div>
            <button class="btn primary">保存笔记</button>
          </form>
        </div>
        <h2 style="margin-top:14px">已记录笔记 ({len(notes)})</h2>
        {notes_html or '<div class="muted">暂无</div>'}
      </div>
    </div>
    """
    return layout(f"{d.iso_date} 复盘", body, active="review")


@router.route("/review/<date>/note", methods=("POST",))
def review_add_note(req, date):
    d = rv_adapter.get_review_day(date)
    if not d:
        return redirect("/review")
    note = (req.get("note") or "").strip()
    tags = (req.get("tags") or "").strip()
    if not note:
        return redirect(f"/review/{d.date}")
    with tx() as conn:
        conn.execute(
            "INSERT INTO review_notes (trade_date, note, tags) VALUES (?,?,?)",
            (d.iso_date, note, tags),
        )
    return redirect(f"/review/{d.date}")


@router.route("/review/<date>/note/delete", methods=("POST",))
def review_delete_note(req, date):
    nid = req.get("id")
    if nid:
        with tx() as conn:
            conn.execute("DELETE FROM review_notes WHERE id=?", (nid,))
    return redirect(f"/review/{date}")


@router.route("/review/notes")
def review_notes_list(req):
    conn = get_conn()
    notes = conn.execute("SELECT * FROM review_notes ORDER BY trade_date DESC, id DESC").fetchall()
    conn.close()
    rows = ""
    for n in notes:
        rows += f"""<tr>
          <td><a href="/review/{n['trade_date'].replace('-','')}">{n['trade_date']}</a></td>
          <td>{_html.escape(n['tags'] or '')}</td>
          <td>{md_render((n['note'] or '')[:300])}</td>
          <td>{n['created_at']}</td>
        </tr>"""
    body = f"""
    <h1>我的复盘笔记</h1>
    <div class="card">
      <p class="muted">共 {len(notes)} 条；点击日期可跳转到当日复盘详情。</p>
      <table><thead><tr><th>日期</th><th>标签</th><th>内容</th><th>创建</th></tr></thead>
      <tbody>{rows or '<tr><td colspan=4 class=muted>暂无</td></tr>'}</tbody></table>
    </div>
    """
    return layout("复盘笔记", body, active="review")
