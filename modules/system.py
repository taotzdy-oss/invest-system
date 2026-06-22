"""系统改进 + OSS 调研 + 维护日志 页面。

完全独立于"明日计划 / 当日复盘"主流程：在这里展示我系统层面的迭代记录与开源项目调研。
按规约：策略迭代不走这里，不会从这里直接修改正式策略。
"""
from __future__ import annotations

import html as _html
import json

from core.db import get_conn, tx
from core.router import router, redirect
from core.templates import layout


def _esc(x) -> str:
    if x is None:
        return ""
    return _html.escape(str(x), quote=False)


@router.route("/system")
def system_index(req):
    conn = get_conn()
    try:
        oss = [dict(r) for r in conn.execute(
            "SELECT * FROM oss_candidates ORDER BY id DESC LIMIT 100"
        ).fetchall()]
        imps = [dict(r) for r in conn.execute(
            "SELECT * FROM system_improvements ORDER BY id DESC LIMIT 100"
        ).fetchall()]
        logs = [dict(r) for r in conn.execute(
            "SELECT * FROM system_changelog ORDER BY id DESC LIMIT 100"
        ).fetchall()]
    finally:
        conn.close()

    by_status = {"adopted": [], "evaluating": [], "referenced": [], "dropped": []}
    for o in oss:
        s = o.get("status") or "evaluating"
        by_status.setdefault(s, []).append(o)

    def _oss_table(items):
        rows = "".join(
            f"<tr><td>{_esc(o.get('topic',''))}</td>"
            f"<td><a href='{_esc(o.get('url',''))}' target='_blank'>{_esc(o.get('name',''))}</a></td>"
            f"<td>{_esc(o.get('license',''))}</td>"
            f"<td>{_esc(o.get('last_update',''))}</td>"
            f"<td>{_esc(o.get('fit','')[:60])}</td>"
            f"<td>{_esc(o.get('recommendation',''))}</td>"
            f"<td class='muted'>{_esc(o.get('reason','')[:80])}</td></tr>"
            for o in items
        )
        return f"""<div class="md-table-wrap"><table>
            <thead><tr><th>主题</th><th>名称</th><th>许可证</th><th>最近更新</th>
              <th>解决问题</th><th>建议</th><th>理由</th></tr></thead>
            <tbody>{rows or '<tr><td colspan=7 class=muted>暂无</td></tr>'}</tbody></table></div>"""

    imp_rows = ""
    for i in imps:
        cls = {"queued": "info", "in_progress": "warn",
               "done": "good", "dropped": "bad"}.get(i.get("status"), "info")
        imp_rows += f"""<tr>
          <td><strong>{_esc(i['title'])}</strong></td>
          <td>{_esc(i.get('priority',''))}</td>
          <td><span class="tag {cls}">{_esc(i['status'])}</span></td>
          <td>{'⚠ 触及策略' if i.get('affects_strategy') else '系统层'}</td>
          <td class="muted">{_esc((i.get('problem') or '')[:80])}</td>
          <td class="muted">{_esc((i.get('solution') or '')[:80])}</td>
          <td>{_esc(i.get('created_at'))}</td>
          <td>
            <form method="post" action="/system/improvement/{i['id']}/done" style="margin:0">
              <button class="btn small">✅ 完成</button>
            </form>
          </td>
        </tr>"""

    log_rows = ""
    for lg in logs:
        log_rows += f"""<tr>
          <td>{_esc(lg.get('version') or '')}</td>
          <td>{_esc(lg.get('kind') or '')}</td>
          <td><strong>{_esc(lg['title'])}</strong></td>
          <td class="muted">{_esc((lg.get('detail') or '')[:120])}</td>
          <td>{_esc(lg['created_at'])}</td>
        </tr>"""

    body = f"""
    <h1>系统改进</h1>
    <div class="alert info">
      本页只展示<strong>系统层</strong>改进（页面、任务、性能、监控等）。<br>
      正式策略变更走 <code>/Users/gegezi/.codex/skills/fengmang-a-share-breakout/SKILL.md</code>
      + <a href="/review/iteration">策略迭代日志</a>，不会因为采纳开源项目就修改正式策略。
    </div>

    <div class="card"><h2>OSS 调研记录（{len(oss)} 条）</h2>
      <div class="toolbar">
        <a class="btn primary" href="/system/oss/new">➕ 新增候选</a>
        <a class="btn" href="#imp">↓ 改进队列</a>
        <a class="btn" href="#chg">↓ 变更日志</a>
      </div>
      <h3>已采用 ({len(by_status.get('adopted', []))})</h3>
      {_oss_table(by_status.get('adopted', []))}
      <h3>评估中 ({len(by_status.get('evaluating', []))})</h3>
      {_oss_table(by_status.get('evaluating', []))}
      <h3>仅参考 ({len(by_status.get('referenced', []))})</h3>
      {_oss_table(by_status.get('referenced', []))}
      <h3>已放弃 ({len(by_status.get('dropped', []))})</h3>
      {_oss_table(by_status.get('dropped', []))}
    </div>

    <div class="card" id="imp"><h2>改进队列 ({len(imps)})</h2>
      <a class="btn primary" href="/system/improvement/new">➕ 新增改进项</a>
      <div class="md-table-wrap"><table>
        <thead><tr><th>标题</th><th>优先级</th><th>状态</th><th>类别</th>
          <th>问题</th><th>方案</th><th>创建</th><th>操作</th></tr></thead>
        <tbody>{imp_rows or '<tr><td colspan=8 class=muted>暂无</td></tr>'}</tbody>
      </table></div>
    </div>

    <div class="card" id="chg"><h2>变更日志 ({len(logs)})</h2>
      <a class="btn primary" href="/system/changelog/new">➕ 新增条目</a>
      <div class="md-table-wrap"><table>
        <thead><tr><th>版本</th><th>类别</th><th>标题</th><th>详情</th><th>时间</th></tr></thead>
        <tbody>{log_rows or '<tr><td colspan=5 class=muted>暂无</td></tr>'}</tbody>
      </table></div>
    </div>
    """
    return layout("系统改进", body, active="home")


@router.route("/system/oss/new")
def oss_new(req):
    body = """
    <h1>新增 OSS 候选</h1>
    <div class="card"><form method="post" action="/system/oss">
      <div class="field"><label>主题</label><input type="text" name="topic" placeholder="如 schedulers / dashboards"></div>
      <div class="field"><label>名称</label><input type="text" name="name" required></div>
      <div class="field"><label>地址</label><input type="text" name="url" required></div>
      <div class="field"><label>许可证</label><input type="text" name="license"></div>
      <div class="field"><label>最近更新</label><input type="text" name="last_update" placeholder="YYYY-MM-DD"></div>
      <div class="field"><label>能解决什么问题</label><textarea name="fit"></textarea></div>
      <div class="field"><label>兼容性</label><input type="text" name="compat"></div>
      <div class="field"><label>安全</label><input type="text" name="security"></div>
      <div class="field"><label>建议</label>
        <select name="recommendation">
          <option value="evaluating">评估中</option>
          <option value="adopt">采用</option>
          <option value="borrow_idea">借鉴思路</option>
          <option value="reference">仅参考</option>
          <option value="pass">放弃</option>
        </select></div>
      <div class="field"><label>理由</label><textarea name="reason"></textarea></div>
      <button class="btn primary">保存</button>
      <a class="btn" href="/system">取消</a>
    </form></div>
    """
    return layout("新增 OSS", body, active="home")


@router.route("/system/oss", methods=("POST",))
def oss_create(req):
    rec = req.get("recommendation") or "evaluating"
    status = {"adopt": "adopted", "borrow_idea": "referenced",
              "reference": "referenced", "pass": "dropped"}.get(rec, "evaluating")
    with tx() as conn:
        conn.execute(
            """INSERT INTO oss_candidates
            (topic, name, url, license, last_update, fit, compat, security,
             recommendation, reason, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (req.get("topic"), req.get("name"), req.get("url"),
             req.get("license"), req.get("last_update"), req.get("fit"),
             req.get("compat"), req.get("security"),
             rec, req.get("reason"), status),
        )
    return redirect("/system")


@router.route("/system/improvement/new")
def improvement_new(req):
    body = """
    <h1>新增系统改进</h1>
    <div class="card"><form method="post" action="/system/improvement">
      <div class="field"><label>标题</label><input type="text" name="title" required></div>
      <div class="field"><label>优先级</label>
        <select name="priority">
          <option value="low">低</option>
          <option value="normal" selected>普通</option>
          <option value="high">高</option>
          <option value="urgent">紧急</option>
        </select></div>
      <div class="field"><label>问题</label><textarea name="problem"></textarea></div>
      <div class="field"><label>方案</label><textarea name="solution"></textarea></div>
      <div class="field"><label>预期收益</label><textarea name="benefit"></textarea></div>
      <div class="field"><label>风险</label><textarea name="risk"></textarea></div>
      <div class="field"><label>回滚方案</label><textarea name="rollback"></textarea></div>
      <div class="field"><label><input type="checkbox" name="affects_strategy" value="1"> 触及正式策略</label></div>
      <button class="btn primary">保存</button>
      <a class="btn" href="/system">取消</a>
    </form></div>
    """
    return layout("新增系统改进", body, active="home")


@router.route("/system/improvement", methods=("POST",))
def improvement_create(req):
    with tx() as conn:
        conn.execute(
            """INSERT INTO system_improvements
            (title, priority, problem, solution, benefit, risk, rollback, affects_strategy, status)
            VALUES (?,?,?,?,?,?,?,?,'queued')""",
            (req.get("title"), req.get("priority") or "normal",
             req.get("problem"), req.get("solution"),
             req.get("benefit"), req.get("risk"), req.get("rollback"),
             1 if req.get("affects_strategy") else 0),
        )
    return redirect("/system")


@router.route("/system/improvement/<iid>/done", methods=("POST",))
def improvement_done(req, iid):
    with tx() as conn:
        conn.execute("UPDATE system_improvements SET status='done', "
                     "completed_at=datetime('now','localtime') WHERE id=?", (iid,))
    return redirect("/system")


@router.route("/system/changelog/new")
def changelog_new(req):
    body = """
    <h1>新增变更日志</h1>
    <div class="card"><form method="post" action="/system/changelog">
      <div class="field"><label>版本</label><input type="text" name="version" placeholder="v2.0.0"></div>
      <div class="field"><label>类别</label>
        <select name="kind">
          <option value="ops">运维</option>
          <option value="data">数据</option>
          <option value="ui">UI</option>
          <option value="bug">Bug 修复</option>
          <option value="strategy">策略</option>
        </select></div>
      <div class="field"><label>标题</label><input type="text" name="title" required></div>
      <div class="field"><label>详情</label><textarea name="detail"></textarea></div>
      <button class="btn primary">保存</button>
    </form></div>
    """
    return layout("新增变更日志", body, active="home")


@router.route("/system/changelog", methods=("POST",))
def changelog_create(req):
    with tx() as conn:
        conn.execute(
            "INSERT INTO system_changelog (version, kind, title, detail) VALUES (?,?,?,?)",
            (req.get("version"), req.get("kind"), req.get("title"), req.get("detail")),
        )
    return redirect("/system")
