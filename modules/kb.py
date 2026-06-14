"""知识库模块：分类树 / 文档查看 / 全文检索 / 用户笔记。"""
from __future__ import annotations

import html as _html

from adapters import knowledge_base as kb_adapter
from core.config import CONFIG
from core.db import get_conn, tx
from core.markdown import render as md_render
from core.router import router, redirect
from core.templates import layout


@router.route("/kb")
def kb_index(req):
    q = (req.get("q") or "").strip()
    cats = kb_adapter.categories()
    manifest = kb_adapter.manifest_info()

    tree_html = ""
    total_docs = 0
    for cat, docs in cats:
        items = "".join(
            f'<li><a href="/kb/doc?path={_html.escape(d.relpath)}">{_html.escape(d.title)}</a>'
            f'<div class="muted" style="margin-left:8px">{_html.escape(d.relpath)} · {d.size} 字节</div></li>'
            for d in docs
        )
        total_docs += len(docs)
        tree_html += f"""<div class="card compact">
          <h3 style="margin-top:0">{_html.escape(cat)} <span class="muted">({len(docs)})</span></h3>
          <ul class="kbd-list">{items}</ul></div>"""

    search_html = ""
    if q:
        hits = kb_adapter.search(q)
        rows = "".join(
            f"<tr><td><a href='/kb/doc?path={_html.escape(h['relpath'])}#L{h['line']}'>{_html.escape(h['title'])}</a></td>"
            f"<td>{_html.escape(h['category'])}</td><td>L{h['line']}</td>"
            f"<td>{_html.escape(h['snippet'])}</td></tr>"
            for h in hits
        )
        search_html = f"""
        <div class="card"><h2>搜索 "{_html.escape(q)}" 命中 {len(hits)} 条</h2>
          <table><thead><tr><th>文档</th><th>分类</th><th>行</th><th>片段</th></tr></thead>
          <tbody>{rows or '<tr><td colspan=4 class=muted>无匹配</td></tr>'}</tbody></table>
        </div>"""

    notes_btn = '<a class="btn" href="/kb/notes">📝 我的知识笔记</a>'

    src_info = ""
    if manifest:
        src_info = (f"<div class='muted'>知识库源自 <code>{_html.escape(str(CONFIG.legacy_path('knowledge_base_dir')))}</code>，"
                    f"共 {len(manifest.get('items', []))} 个原始条目。</div>")

    body = f"""
    <h1>知识库</h1>
    <div class="card">
      <form method="get" class="toolbar">
        <input type="search" name="q" value="{_html.escape(q)}" placeholder="全文检索（不区分大小写）" style="max-width:420px">
        <button class="btn primary">🔍 搜索</button>
        {notes_btn}
        <a class="btn" href="/kb/note/new">✏ 新增笔记</a>
      </form>
      {src_info}
      <p class="muted">共 {total_docs} 个文档，按分类列出。点击文档名进入查看页。</p>
    </div>
    {search_html}
    {tree_html}
    """
    return layout("知识库", body, active="kb")


@router.route("/kb/doc")
def kb_doc(req):
    path = req.get("path", "")
    doc, text = kb_adapter.read_doc(path)
    if not doc:
        return (404, layout("知识库", f"<div class='alert error'>未找到文档：{_html.escape(path)}</div>", active="kb"))
    if doc.path.suffix.lower() == ".md":
        rendered = md_render(text)
    elif doc.path.suffix.lower() == ".html":
        rendered = text  # 直接嵌入
    elif doc.path.suffix.lower() == ".csv":
        rendered = _render_csv(text)
    else:
        rendered = f"<pre class='code-block'>{_html.escape(text[:200000])}</pre>"

    # 查找关联笔记
    conn = get_conn()
    notes = conn.execute(
        "SELECT * FROM kb_notes WHERE refs LIKE ? ORDER BY id DESC", (f"%{doc.relpath}%",)
    ).fetchall()
    conn.close()

    notes_html = "".join(
        f"<div class='card compact'><strong>{_html.escape(n['title'])}</strong>"
        f"<div class='muted'>{n['updated_at']}</div>"
        f"<div class='md-render'>{md_render(n['body'])}</div></div>"
        for n in notes
    )

    body = f"""
    <h1>{_html.escape(doc.title)}</h1>
    <div class="toolbar">
      <a class="btn" href="/kb">← 返回知识库</a>
      <a class="btn" href="/kb/note/new?ref={_html.escape(doc.relpath)}">✏ 为本文档新增笔记</a>
      <span class="muted">路径：{_html.escape(doc.relpath)}（{doc.size} 字节）</span>
    </div>
    <div class="grid grid-2">
      <div class="card md-render">{rendered}</div>
      <div>
        <h2>关联笔记 ({len(notes)})</h2>
        {notes_html or '<div class="muted">尚无关联笔记</div>'}
      </div>
    </div>
    """
    return layout(doc.title, body, active="kb")


def _render_csv(text: str) -> str:
    import csv, io
    rdr = csv.reader(io.StringIO(text))
    rows = list(rdr)
    if not rows:
        return "<div class='muted'>空 CSV</div>"
    head = "".join(f"<th>{_html.escape(c)}</th>" for c in rows[0])
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{_html.escape(c)}</td>" for c in r) + "</tr>"
        for r in rows[1:200]
    )
    extra = f"<div class='muted'>仅显示前 200 行，共 {len(rows)-1} 行</div>" if len(rows) > 201 else ""
    return f"<div class='md-table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body_rows}</tbody></table></div>{extra}"


@router.route("/kb/notes")
def kb_notes(req):
    conn = get_conn()
    notes = conn.execute("SELECT * FROM kb_notes ORDER BY id DESC").fetchall()
    conn.close()
    rows = ""
    for n in notes:
        rows += f"""<tr>
          <td><a href="/kb/note/{n['id']}">{_html.escape(n['title'])}</a></td>
          <td>{_html.escape(n['tags'] or '')}</td>
          <td>{_html.escape(n['refs'] or '')}</td>
          <td>{n['updated_at']}</td>
          <td>
            <form method="post" action="/kb/note/{n['id']}/delete" style="margin:0">
              <button class="btn small danger" data-confirm="确认删除？">删除</button>
            </form>
          </td>
        </tr>"""
    body = f"""
    <h1>我的知识笔记</h1>
    <div class="card">
      <div class="toolbar">
        <a class="btn primary" href="/kb/note/new">✏ 新增笔记</a>
        <a class="btn" href="/kb">← 返回知识库</a>
      </div>
      <table><thead><tr><th>标题</th><th>标签</th><th>关联文档</th><th>更新</th><th>操作</th></tr></thead>
      <tbody>{rows or '<tr><td colspan=5 class=muted>暂无</td></tr>'}</tbody></table>
    </div>
    """
    return layout("我的知识笔记", body, active="kb")


@router.route("/kb/note/new")
def kb_note_new(req):
    ref = req.get("ref", "")
    body = f"""
    <h1>新增知识笔记</h1>
    <div class="card">
      <form method="post" action="/kb/note">
        <div class="field"><label>标题</label><input type="text" name="title" required></div>
        <div class="field"><label>正文 (Markdown)</label><textarea name="body" rows="14" required></textarea></div>
        <div class="field"><label>标签 (逗号分隔)</label><input type="text" name="tags"></div>
        <div class="field"><label>关联文档相对路径 (逗号分隔)</label>
          <input type="text" name="refs" value="{_html.escape(ref)}"></div>
        <button class="btn primary">保存</button>
        <a class="btn" href="/kb">取消</a>
      </form>
    </div>
    """
    return layout("新增笔记", body, active="kb")


@router.route("/kb/note", methods=("POST",))
def kb_note_create(req):
    title = (req.get("title") or "").strip()
    body = (req.get("body") or "").strip()
    tags = (req.get("tags") or "").strip()
    refs = (req.get("refs") or "").strip()
    if not title or not body:
        return redirect("/kb/note/new")
    with tx() as conn:
        conn.execute(
            "INSERT INTO kb_notes (title, body, tags, refs) VALUES (?,?,?,?)",
            (title, body, tags, refs),
        )
    return redirect("/kb/notes")


@router.route("/kb/note/<nid>")
def kb_note_detail(req, nid):
    conn = get_conn()
    n = conn.execute("SELECT * FROM kb_notes WHERE id=?", (nid,)).fetchone()
    conn.close()
    if not n:
        return (404, "笔记不存在")
    body = f"""
    <h1>{_html.escape(n['title'])}</h1>
    <div class="toolbar">
      <a class="btn" href="/kb/notes">← 返回</a>
      <a class="btn" href="/kb/note/{n['id']}/edit">✏ 编辑</a>
    </div>
    <div class="card">
      <div class="muted">标签：{_html.escape(n['tags'] or '')} · 关联：{_html.escape(n['refs'] or '')} · 更新：{n['updated_at']}</div>
      <div class="md-render">{md_render(n['body'])}</div>
    </div>
    """
    return layout(n['title'], body, active="kb")


@router.route("/kb/note/<nid>/edit")
def kb_note_edit(req, nid):
    conn = get_conn()
    n = conn.execute("SELECT * FROM kb_notes WHERE id=?", (nid,)).fetchone()
    conn.close()
    if not n:
        return (404, "笔记不存在")
    body = f"""
    <h1>编辑笔记 #{n['id']}</h1>
    <div class="card">
      <form method="post" action="/kb/note/{n['id']}/update">
        <div class="field"><label>标题</label><input type="text" name="title" value="{_html.escape(n['title'])}" required></div>
        <div class="field"><label>正文</label><textarea name="body" rows="14" required>{_html.escape(n['body'])}</textarea></div>
        <div class="field"><label>标签</label><input type="text" name="tags" value="{_html.escape(n['tags'] or '')}"></div>
        <div class="field"><label>关联文档</label><input type="text" name="refs" value="{_html.escape(n['refs'] or '')}"></div>
        <button class="btn primary">保存</button>
        <a class="btn" href="/kb/note/{n['id']}">取消</a>
      </form>
    </div>
    """
    return layout("编辑笔记", body, active="kb")


@router.route("/kb/note/<nid>/update", methods=("POST",))
def kb_note_update(req, nid):
    title = (req.get("title") or "").strip()
    body = (req.get("body") or "").strip()
    tags = (req.get("tags") or "").strip()
    refs = (req.get("refs") or "").strip()
    with tx() as conn:
        conn.execute(
            "UPDATE kb_notes SET title=?, body=?, tags=?, refs=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (title, body, tags, refs, nid),
        )
    return redirect(f"/kb/note/{nid}")


@router.route("/kb/note/<nid>/delete", methods=("POST",))
def kb_note_delete(req, nid):
    with tx() as conn:
        conn.execute("DELETE FROM kb_notes WHERE id=?", (nid,))
    return redirect("/kb/notes")
