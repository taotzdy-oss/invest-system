"""每日选股模块：观察池列表 / 详情 / 标记 / 批注 / 重跑脚本。"""
from __future__ import annotations

import html as _html
import json

from adapters import stock_pick as sp_adapter
from adapters.runner import run_python
from core.db import get_conn, tx
from core.router import router, redirect
from core.templates import layout


@router.route("/picks")
def picks_index(req):
    pools = sp_adapter.list_pools()
    scripts = sp_adapter.list_scripts()

    pool_rows = ""
    for p in pools:
        pool_rows += f"""<tr>
          <td><a href="/picks/{p.date}">{p.iso_date}</a></td>
          <td><span class="muted">{_html.escape(p.dir_path.name)}</span></td>
          <td>{'✅' if p.csv_path else '—'}</td>
          <td>{'✅' if p.html_path else '—'}</td>
          <td>{len(p.extra_htmls)}</td>
        </tr>"""

    script_rows = ""
    for s in scripts:
        script_rows += f"""<tr>
          <td>{_html.escape(s.name)}</td>
          <td>{s.stat().st_size if hasattr(s, 'stat') else ''}</td>
          <td><form method="post" action="/picks/run" style="margin:0">
            <input type="hidden" name="script" value="{_html.escape(s.name)}">
            <button class="btn small primary" data-confirm="将在子进程运行 {_html.escape(s.name)}，可能需要联网，是否继续？">▶ 运行</button>
          </form></td>
        </tr>"""

    body = f"""
    <h1>每日选股</h1>
    <div class="card"><h2>观察池列表（按日期倒序）</h2>
      <table><thead><tr><th>交易日</th><th>目录</th><th>CSV</th><th>分析HTML</th><th>附加HTML</th></tr></thead>
      <tbody>{pool_rows or '<tr><td colspan=5 class="muted">尚未发现观察池目录</td></tr>'}</tbody></table>
    </div>
    <div class="card"><h2>历史选股脚本</h2>
      <p class="muted">点击"运行"会在子进程中调用对应脚本，输出落到 <a href="/system/logs">运行日志</a>。</p>
      <table><thead><tr><th>脚本</th><th>大小</th><th>操作</th></tr></thead>
      <tbody>{script_rows or '<tr><td colspan=3 class="muted">未发现策略脚本</td></tr>'}</tbody></table>
    </div>
    """
    return layout("每日选股", body, active="picks")


@router.route("/picks/run", methods=("POST",))
def picks_run(req):
    name = req.get("script", "")
    for s in sp_adapter.list_scripts():
        if s.name == name:
            run_python(s, kind="stock_pick")
            return redirect("/system/logs")
    return redirect("/picks")


@router.route("/picks/<date>")
def picks_detail(req, date):
    pool = sp_adapter.get_pool(date)
    if not pool:
        return (404, layout("选股详情", f"<div class='alert error'>未找到观察池：{_html.escape(date)}</div>", active="picks"))

    codes = sp_adapter.parse_csv_codes(pool)
    candidates = sp_adapter.parse_html_candidates(pool)

    # 取已有标记
    conn = get_conn()
    marks = {r["code"]: dict(r) for r in conn.execute(
        "SELECT * FROM stock_pick_marks WHERE trade_date=?", (pool.iso_date,)
    ).fetchall()}
    conn.close()

    cand_rows = ""
    for c in candidates:
        code = c.get("代码", "")
        m = marks.get(code) or {}
        mark = m.get("mark") or ""
        note = m.get("note") or ""
        mark_badge = ""
        if mark == "buy":   mark_badge = '<span class="tag good">已建仓</span>'
        elif mark == "watch": mark_badge = '<span class="tag info">观察</span>'
        elif mark == "drop":  mark_badge = '<span class="tag bad">已放弃</span>'
        elif mark == "hold":  mark_badge = '<span class="tag warn">持仓</span>'
        cand_rows += f"""<tr>
          <td>{_html.escape(c.get('分组',''))}</td>
          <td><strong>{_html.escape(code)}</strong></td>
          <td>{_html.escape(c.get('名称',''))} {mark_badge}</td>
          <td>{_html.escape(c.get('角色',''))}</td>
          <td>{_html.escape(c.get('评分',''))}</td>
          <td>{_html.escape(c.get('执行优先级',''))}</td>
          <td>{_html.escape(c.get('行业',''))}/{_html.escape(c.get('题材',''))}</td>
          <td>{_html.escape(c.get('首次封板',''))}<br><span class="muted">最后:{_html.escape(c.get('最后封板',''))}</span></td>
          <td>{_html.escape(c.get('成交额',''))}<br><span class="muted">换手:{_html.escape(c.get('换手',''))}</span></td>
          <td>{_html.escape(c.get('临盘触发条件',''))}</td>
          <td>{_html.escape(c.get('放弃条件',''))}</td>
          <td>
            <form method="post" action="/picks/{pool.date}/mark" class="flex" style="gap:4px">
              <input type="hidden" name="code" value="{_html.escape(code)}">
              <input type="hidden" name="name" value="{_html.escape(c.get('名称',''))}">
              <select name="mark" style="width:90px">
                <option value="" {'selected' if not mark else ''}>—</option>
                <option value="watch" {'selected' if mark=='watch' else ''}>观察</option>
                <option value="buy" {'selected' if mark=='buy' else ''}>已建仓</option>
                <option value="hold" {'selected' if mark=='hold' else ''}>持仓</option>
                <option value="drop" {'selected' if mark=='drop' else ''}>已放弃</option>
              </select>
              <input type="text" name="note" value="{_html.escape(note)}" placeholder="批注">
              <button class="btn small primary">保存</button>
            </form>
          </td>
        </tr>"""

    code_list = ", ".join(codes) if codes else "<span class='muted'>CSV 为空</span>"
    html_path = pool.html_path
    html_link = f'<a href="/picks/{pool.date}/html" target="_blank">查看原 HTML 分析结论</a>' if html_path else ''

    body = f"""
    <h1>{pool.iso_date} 观察池</h1>
    <div class="toolbar">
      <a class="btn" href="/picks">← 返回列表</a>
      {html_link}
      <span class="muted">目录：{_html.escape(str(pool.dir_path))}</span>
    </div>

    <div class="card"><h2>同花顺导入 CSV ({len(codes)} 只)</h2>
      <div class="code-block">{_html.escape(', '.join(codes)) if codes else '（CSV 为空）'}</div>
    </div>

    <div class="card"><h2>可执行候选池（{len(candidates)} 行）</h2>
      <div class="md-table-wrap"><table>
        <thead><tr><th>分组</th><th>代码</th><th>名称</th><th>角色</th><th>评分</th><th>优先级</th><th>行业/题材</th><th>封板</th><th>成交/换手</th><th>触发</th><th>放弃</th><th>标记 / 批注</th></tr></thead>
        <tbody>{cand_rows or '<tr><td colspan=12 class="muted">未解析到候选行（请检查 HTML 模板）</td></tr>'}</tbody>
      </table></div>
    </div>
    """
    return layout(f"{pool.iso_date} 选股", body, active="picks")


@router.route("/picks/<date>/mark", methods=("POST",))
def picks_mark(req, date):
    pool = sp_adapter.get_pool(date)
    if not pool:
        return redirect("/picks")
    code = (req.get("code") or "").strip()
    name = (req.get("name") or "").strip()
    mark = (req.get("mark") or "").strip()
    note = (req.get("note") or "").strip()
    if not code:
        return redirect(f"/picks/{pool.date}")
    with tx() as conn:
        existing = conn.execute(
            "SELECT id FROM stock_pick_marks WHERE trade_date=? AND code=?",
            (pool.iso_date, code),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE stock_pick_marks SET name=?, mark=?, note=?, "
                "pool_dir=?, updated_at=datetime('now','localtime') WHERE id=?",
                (name, mark, note, str(pool.dir_path), existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO stock_pick_marks (trade_date, code, name, pool_dir, mark, note) "
                "VALUES (?,?,?,?,?,?)",
                (pool.iso_date, code, name, str(pool.dir_path), mark, note),
            )
    return redirect(f"/picks/{pool.date}")


@router.route("/picks/<date>/html")
def picks_html(req, date):
    pool = sp_adapter.get_pool(date)
    if not pool or not pool.html_path:
        return (404, "未找到 HTML")
    text = pool.html_path.read_text(encoding="utf-8")
    return (200, text, {"Content-Type": "text/html; charset=utf-8"})


@router.route("/picks/<date>/marks.json")
def picks_marks_json(req, date):
    pool = sp_adapter.get_pool(date)
    if not pool:
        return {"error": "no such pool"}
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM stock_pick_marks WHERE trade_date=? ORDER BY code",
            (pool.iso_date,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
