"""策略管理模块：策略脚本列表 / 参数详情 / 版本快照 / 对比 / 回测占位。"""
from __future__ import annotations

import html as _html
import json

from adapters import strategy as st_adapter
from adapters import review as rv_adapter
from core.db import get_conn, tx
from core.router import router, redirect
from core.templates import layout


def _pretty_json(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except TypeError:
        return str(obj)


@router.route("/strategy")
def strategy_index(req):
    scripts = st_adapter.list_strategy_scripts()
    conn = get_conn()
    versions = conn.execute(
        "SELECT id, strategy_key, label, note, created_at FROM strategy_versions ORDER BY id DESC"
    ).fetchall()
    backtests = conn.execute(
        "SELECT id, strategy_key, version_id, started_at, sample_count, date_from, date_to "
        "FROM strategy_backtests ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    script_rows = ""
    for s in scripts:
        script_rows += f"""<tr>
          <td><a href="/strategy/script/{_html.escape(s.name)}">{_html.escape(s.name)}</a></td>
          <td>{s.source_date}</td>
          <td>{s.next_date}</td>
          <td>{len(s.params)}</td>
          <td>
            <form method="post" action="/strategy/snapshot" style="margin:0">
              <input type="hidden" name="script" value="{_html.escape(s.name)}">
              <input type="text" name="label" placeholder="版本标签" style="max-width:140px">
              <button class="btn small primary">📦 存为版本</button>
            </form>
          </td>
        </tr>"""

    ver_rows = "".join(
        f"<tr><td>{v['id']}</td><td>{_html.escape(v['strategy_key'])}</td>"
        f"<td>{_html.escape(v['label'] or '')}</td><td>{_html.escape(v['note'] or '')}</td>"
        f"<td>{v['created_at']}</td>"
        f"<td><a class='btn small' href='/strategy/version/{v['id']}'>查看</a> "
        f"<a class='btn small' href='/strategy/version/{v['id']}/diff'>对比上一版</a></td></tr>"
        for v in versions
    )

    bt_rows = "".join(
        f"<tr><td>{b['id']}</td><td>{_html.escape(b['strategy_key'])}</td>"
        f"<td>{b['version_id'] or ''}</td><td>{b['sample_count']}</td>"
        f"<td>{b['date_from']} ~ {b['date_to']}</td>"
        f"<td>{b['started_at']}</td>"
        f"<td><a class='btn small' href='/strategy/backtest/{b['id']}'>详情</a></td></tr>"
        for b in backtests
    )

    body = f"""
    <h1>策略管理</h1>

    <div class="card"><h2>历史策略脚本</h2>
      <p class="muted">脚本来源：<code>{st_adapter.CONFIG.legacy_root}/generate_fengmang_breakout_*.py</code>
      。每个脚本视为一个策略快照，可通过"存为版本"在本系统中留存。</p>
      <table><thead><tr><th>脚本</th><th>源日期</th><th>次日</th><th>参数项</th><th>操作</th></tr></thead>
      <tbody>{script_rows or '<tr><td colspan=5 class=muted>未发现脚本</td></tr>'}</tbody></table>
    </div>

    <div class="card"><h2>已留存版本</h2>
      <table><thead><tr><th>ID</th><th>策略</th><th>标签</th><th>说明</th><th>时间</th><th>操作</th></tr></thead>
      <tbody>{ver_rows or '<tr><td colspan=6 class=muted>暂无版本，前往脚本页保存</td></tr>'}</tbody></table>
    </div>

    <div class="card"><h2>回测记录</h2>
      <p class="muted">回测基于复盘台账 (review_ledger_csv) 对当前策略的命中率/封住率进行重算，不依赖外部行情。</p>
      <div class="toolbar">
        <a class="btn primary" href="/strategy/backtest/run">▶ 跑一次最新策略回测</a>
      </div>
      <table><thead><tr><th>ID</th><th>策略</th><th>版本</th><th>样本</th><th>区间</th><th>时间</th><th>操作</th></tr></thead>
      <tbody>{bt_rows or '<tr><td colspan=7 class=muted>暂无回测</td></tr>'}</tbody></table>
    </div>
    """
    return layout("策略管理", body, active="strategy")


@router.route("/strategy/script/<name>")
def strategy_script_detail(req, name):
    s = st_adapter.get_script(name)
    if not s:
        return (404, layout("策略", f"<div class='alert error'>未找到 {_html.escape(name)}</div>", active="strategy"))

    params_html = ""
    for k, v in s.params.items():
        params_html += f"""<div class="card compact"><h3>{_html.escape(k)}</h3>
          <pre class="code-block">{_html.escape(_pretty_json(v))}</pre></div>"""

    body = f"""
    <h1>{_html.escape(s.name)}</h1>
    <div class="toolbar">
      <a class="btn" href="/strategy">← 返回</a>
      <span class="muted">路径：{_html.escape(str(s.path))}</span>
    </div>
    <div class="card"><h2>策略元信息</h2>
      <ul>
        <li>源日期 (SOURCE_DATE)：{s.source_date}</li>
        <li>次日 (NEXT_DATE)：{s.next_date}</li>
        <li>参数项数：{len(s.params)}</li>
      </ul>
      <form method="post" action="/strategy/snapshot">
        <input type="hidden" name="script" value="{_html.escape(s.name)}">
        <div class="field"><label>版本标签</label>
          <input type="text" name="label" placeholder="如：v1-baseline / v2-加入封单"></div>
        <div class="field"><label>说明</label>
          <textarea name="note" placeholder="本次版本相对上一版做了什么调整、计划验证什么"></textarea></div>
        <button class="btn primary">📦 保存为版本</button>
      </form>
    </div>

    <h2>策略参数（提取自顶层常量）</h2>
    {params_html or '<div class="muted">未提取到参数；可能脚本使用了非字面量常量。</div>'}

    <h2>编辑参数（导出为 JSON / 修改 / 应用为新版本）</h2>
    <div class="card">
      <form method="post" action="/strategy/snapshot">
        <input type="hidden" name="script" value="{_html.escape(s.name)}">
        <input type="hidden" name="from_edit" value="1">
        <div class="field"><label>参数 JSON（可直接修改后存为新版本）</label>
          <textarea name="params_json" rows="14">{_html.escape(_pretty_json(s.params))}</textarea></div>
        <div class="field"><label>版本标签</label><input type="text" name="label" placeholder="如：v3-调参"></div>
        <div class="field"><label>说明</label><textarea name="note" placeholder="调参意图"></textarea></div>
        <button class="btn primary">💾 存为调参版本（不修改原脚本）</button>
        <p class="muted" style="margin-top:6px">注意：本系统遵循"只读旧项目"原则，调参版本只保存在 system.db，不会写回脚本。</p>
      </form>
    </div>
    """
    return layout(s.name, body, active="strategy")


@router.route("/strategy/snapshot", methods=("POST",))
def strategy_snapshot(req):
    name = req.get("script", "")
    s = st_adapter.get_script(name)
    if not s:
        return redirect("/strategy")
    label = (req.get("label") or "").strip()
    note = (req.get("note") or "").strip()
    if req.get("from_edit"):
        try:
            params = json.loads(req.get("params_json") or "{}")
        except json.JSONDecodeError as e:
            return (400, layout("策略", f"<div class='alert error'>参数 JSON 无效：{e}</div>", active="strategy"))
    else:
        params = s.params
    with tx() as conn:
        conn.execute(
            "INSERT INTO strategy_versions (strategy_key, label, note, params_json, source_path) "
            "VALUES (?,?,?,?,?)",
            (s.name, label, note, json.dumps(params, ensure_ascii=False), str(s.path)),
        )
    return redirect("/strategy")


@router.route("/strategy/version/<vid>")
def strategy_version(req, vid):
    conn = get_conn()
    v = conn.execute("SELECT * FROM strategy_versions WHERE id=?", (vid,)).fetchone()
    conn.close()
    if not v:
        return (404, layout("策略", "<div class='alert error'>版本不存在</div>", active="strategy"))
    try:
        params = json.loads(v["params_json"])
    except Exception:
        params = {}
    body = f"""
    <h1>版本 #{v['id']} - {_html.escape(v['label'] or '')}</h1>
    <div class="card">
      <ul>
        <li>策略：{_html.escape(v['strategy_key'])}</li>
        <li>说明：{_html.escape(v['note'] or '')}</li>
        <li>来源：<code>{_html.escape(v['source_path'] or '')}</code></li>
        <li>时间：{v['created_at']}</li>
      </ul>
      <pre class="code-block">{_html.escape(_pretty_json(params))}</pre>
      <div class="toolbar">
        <a class="btn" href="/strategy">← 返回</a>
        <a class="btn primary" href="/strategy/version/{v['id']}/diff">⇆ 对比上一版</a>
      </div>
    </div>
    """
    return layout(f"版本 {v['id']}", body, active="strategy")


@router.route("/strategy/version/<vid>/diff")
def strategy_diff(req, vid):
    conn = get_conn()
    v = conn.execute("SELECT * FROM strategy_versions WHERE id=?", (vid,)).fetchone()
    if not v:
        conn.close()
        return (404, "版本不存在")
    prev = conn.execute(
        "SELECT * FROM strategy_versions WHERE strategy_key=? AND id<? ORDER BY id DESC LIMIT 1",
        (v["strategy_key"], v["id"]),
    ).fetchone()
    conn.close()
    a = json.loads(v["params_json"])
    b = json.loads(prev["params_json"]) if prev else {}
    rows = ""
    keys = sorted(set(a.keys()) | set(b.keys()))
    for k in keys:
        va = _pretty_json(a.get(k, "—"))
        vb = _pretty_json(b.get(k, "—"))
        same = va == vb
        rows += f"""<tr>
          <td>{_html.escape(k)}</td>
          <td><pre class="code-block">{_html.escape(vb)}</pre></td>
          <td>{'<span class="tag good">未变</span>' if same else '<span class="tag warn">已变</span>'}</td>
          <td><pre class="code-block">{_html.escape(va)}</pre></td>
        </tr>"""
    title_prev = f"#{prev['id']} {prev['label'] or ''}" if prev else "（无上一版）"
    body = f"""
    <h1>版本对比</h1>
    <div class="card">
      <p>对比 <strong>#{v['id']} {_html.escape(v['label'] or '')}</strong> vs <strong>{_html.escape(title_prev)}</strong></p>
      <table><thead><tr><th>参数</th><th>上一版</th><th>差异</th><th>本版</th></tr></thead><tbody>{rows}</tbody></table>
      <a class="btn" href="/strategy">← 返回</a>
    </div>
    """
    return layout("版本对比", body, active="strategy")


@router.route("/strategy/backtest/run")
def strategy_backtest_run(req):
    """基于复盘台账对最新一个脚本做"事后回测"：

    - 选取该脚本 NEXT_DATE 当日台账行
    - 计算触板率 / 封住率 / 平均评分
    - 落库 strategy_backtests
    """
    scripts = st_adapter.list_strategy_scripts()
    if not scripts:
        return redirect("/strategy")
    s = scripts[0]
    target_iso = s.next_date or ""
    rows = [r for r in rv_adapter.ledger_rows() if r.get("交易日期") == target_iso]
    sample_count = len(rows)
    sealed = sum(1 for r in rows if r.get("是否封住") == "是")
    touched = sum(1 for r in rows if r.get("是否触板") == "是")
    try:
        avg_score = sum(float(r.get("计划评分") or 0) for r in rows) / sample_count if sample_count else 0
    except ValueError:
        avg_score = 0
    metrics = {
        "sample": sample_count,
        "sealed": sealed,
        "touched": touched,
        "seal_rate": (sealed / sample_count * 100) if sample_count else 0,
        "touch_rate": (touched / sample_count * 100) if sample_count else 0,
        "avg_score": avg_score,
        "matched_date": target_iso,
        "matched_codes": [r.get("代码") for r in rows],
    }
    with tx() as conn:
        conn.execute(
            "INSERT INTO strategy_backtests (strategy_key, version_id, metrics_json, "
            "sample_count, date_from, date_to) VALUES (?,?,?,?,?,?)",
            (s.name, None, json.dumps(metrics, ensure_ascii=False),
             sample_count, target_iso, target_iso),
        )
    return redirect("/strategy")


@router.route("/strategy/backtest/<bid>")
def strategy_backtest_detail(req, bid):
    conn = get_conn()
    b = conn.execute("SELECT * FROM strategy_backtests WHERE id=?", (bid,)).fetchone()
    conn.close()
    if not b:
        return (404, "回测不存在")
    metrics = json.loads(b["metrics_json"])
    body = f"""
    <h1>回测 #{b['id']}</h1>
    <div class="card">
      <ul>
        <li>策略：{_html.escape(b['strategy_key'])}</li>
        <li>样本数：{b['sample_count']}</li>
        <li>时间：{b['started_at']}</li>
        <li>区间：{b['date_from']} ~ {b['date_to']}</li>
      </ul>
      <pre class="code-block">{_html.escape(_pretty_json(metrics))}</pre>
      <a class="btn" href="/strategy">← 返回</a>
    </div>
    """
    return layout(f"回测 {b['id']}", body, active="strategy")
