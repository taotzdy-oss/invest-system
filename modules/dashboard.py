"""单页 Dashboard：6 大区块 + 系统改进入口。

URL：固定 / （根路径）。这是你"每天只打开同一个网页"的入口。
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime

from core.dashboard import aggregate
from core.jobs import run_job
from core.router import router, redirect
from core.templates import layout


def _esc(x) -> str:
    if x is None:
        return ""
    return _html.escape(str(x), quote=False)


def _badge(text: str, kind: str = "info") -> str:
    return f'<span class="tag {kind}">{_esc(text)}</span>'


def _job_status_badge(status: str) -> str:
    return {"ok": '<span class="tag good">OK</span>',
            "failed": '<span class="tag bad">失败</span>',
            "skipped": '<span class="tag warn">跳过</span>',
            }.get(status, f'<span class="tag">{_esc(status or "—")}</span>')


def _render_today_overview(d: dict) -> str:
    lr = d["latest_trading_day"]
    nx = d["next_trading_day"]
    conf = d["next_trading_day_confidence"]
    ladder = d.get("ladder") or {}
    advice = d.get("advice") or {}
    review = d.get("review") or {}
    rm = d.get("recent_metrics") or {}
    agg = rm.get("aggregate", {})
    by_lv = rm.get("by_level", {})

    advice_html = ""
    if advice:
        advice_html = f"""
        <div class="card compact">
          <div class="muted">基于连板天梯的次日打板建议（{_esc(advice.get('iso_date',''))}）</div>
          <div><strong>{_esc(advice.get('强度') or '—')}</strong> · {_esc(advice.get('可打板') or '')}</div>
          <div>可打级别：{_esc(advice.get('可打级别') or '—')}　仓位：{_esc(advice.get('建议仓位') or '—')}</div>
          <div class="muted" style="margin-top:6px">{_esc(advice.get('判断依据') or '')}</div>
        </div>
        """

    ladder_html = ""
    if ladder:
        ladder_html = f"""
        <div class="card compact">
          <div class="muted">连板天梯当日（{_esc(ladder.get('日期',''))}）</div>
          <div>最高连板 <strong>{_esc(ladder.get('最高连板'))}</strong>　封板成功 {_esc(ladder.get('封板成功股票数'))}　10cm 最高 {_esc(ladder.get('10cm最高连板'))} 板</div>
          <div>梯队 首/二/三/四+：{_esc(ladder.get('10cm首板数'))}/{_esc(ladder.get('10cm二板数'))}/{_esc(ladder.get('10cm三板数'))}/{_esc(ladder.get('10cm四板及以上数'))}</div>
          <div class="muted" style="margin-top:6px">题材 Top：{_esc(ladder.get('涉及题材Top10'))}</div>
        </div>
        """

    review_html = ""
    if review:
        market = _esc(review.get("market_state") or "")
        breadth = _esc(review.get("breadth") or "")
        themes = _esc(review.get("top_themes") or "")
        review_html = f"""
        <div class="card compact">
          <div class="muted">最新复盘 ({_esc(review.get('trade_date',''))})</div>
          <div>{market}</div>
          <div>{breadth}</div>
          <div class="muted" style="margin-top:6px">领涨：{themes}</div>
        </div>
        """

    # 风险灯：基于近 5 日数据简化判断
    risk_class = "good"
    risk_text = "稳定"
    if agg.get("touch_rate", 0) < 40:
        risk_class, risk_text = "warn", "市场偏弱"
    if agg.get("burst_rate", 0) > 35:
        risk_class, risk_text = "warn", "炸板偏多"
    if agg.get("sample") == 0:
        risk_class, risk_text = "info", "数据不足"

    by_lv_html = ""
    for lv in ("主选", "条件", "备选"):
        m = by_lv.get(lv, {})
        by_lv_html += f"<div>{_esc(lv)}：触板 {_esc(m.get('touch_rate'))}% · 封住 {_esc(m.get('seal_rate'))}% · 样本 {_esc(m.get('total'))}</div>"

    confidence_badge = _badge("已确认交易日", "good") if conf == "confirmed" else _badge("预测（待确认）", "warn")

    return f"""
    <section id="today" class="card">
      <div class="flex between">
        <h2 style="margin:0">① 今日总览</h2>
        <span class="muted">数据时间 {_esc(d['now_ts'])}</span>
      </div>
      <div class="grid grid-4">
        <div class="stat"><div class="label">当前交易日</div>
          <div class="value">{_esc(lr)}</div>
          <div class="sub">下一交易日 <strong>{_esc(nx)}</strong> {confidence_badge}</div></div>
        <div class="stat"><div class="label">近 5 日触板率</div>
          <div class="value">{_esc(agg.get('touch_rate'))}%</div>
          <div class="sub">封住 {_esc(agg.get('seal_rate'))}% · 炸板 {_esc(agg.get('burst_rate'))}% · 样本 {_esc(agg.get('total'))}</div></div>
        <div class="stat"><div class="label">近 5 日可参与率</div>
          <div class="value">{_esc(agg.get('actionable_rate'))}%</div>
          <div class="sub">{by_lv_html}</div></div>
        <div class="stat"><div class="label">风险开关</div>
          <div class="value">{_badge(risk_text, risk_class)}</div>
          <div class="sub">基于近 5 日封住+炸板综合判断</div></div>
      </div>
      <div class="grid grid-3" style="margin-top:14px">
        {ladder_html or '<div class="muted">未取得连板天梯数据</div>'}
        {advice_html or '<div class="muted">未取得次日建议</div>'}
        {review_html or '<div class="muted">尚无最新复盘</div>'}
      </div>
    </section>
    """


def _render_tomorrow_plan(d: dict) -> str:
    if d.get("empty"):
        return '<section id="tomorrow" class="card"><h2>② 明日计划</h2><div class="alert warn">尚无任何观察池数据；请先运行选股任务。</div></section>'

    td = d["trade_date"]
    cands = d.get("candidates", [])
    refs = d.get("references", [])
    codes = d.get("csv_codes", [])
    by_role = {"主选": [], "条件": [], "备选": []}
    for c in cands:
        by_role.setdefault(c.get("role") or "备选", []).append(c)

    def _cand_row(c: dict) -> str:
        return f"""<tr>
          <td><strong>{_esc(c.get('code'))}</strong></td>
          <td>{_esc(c.get('name'))}</td>
          <td>{_esc(c.get('role_label') or '')}</td>
          <td class="text-right">{_esc(c.get('score') if c.get('score') is not None else '')}</td>
          <td>{_esc(c.get('stage') or '')}</td>
          <td>{_esc(c.get('industry') or '')}</td>
          <td>{_esc(c.get('pressure') or '')}</td>
          <td class="muted">{_esc((c.get('trigger') or '')[:80])}</td>
          <td class="muted">{_esc((c.get('abandon') or '')[:80])}</td>
          <td>{_badge('在 CSV','good') if c.get('code') in codes else _badge('未导','warn')}</td>
        </tr>"""

    blocks = ""
    for lv, items in by_role.items():
        if not items:
            continue
        rows = "".join(_cand_row(c) for c in items)
        blocks += f"""
        <h3>{_esc(lv)} ({len(items)})</h3>
        <div class="md-table-wrap"><table>
          <thead><tr><th>代码</th><th>名称</th><th>角色</th><th>评分</th>
            <th>连板</th><th>行业</th><th>压力/日期</th>
            <th>临盘触发</th><th>放弃</th><th>CSV</th></tr></thead>
          <tbody>{rows}</tbody></table></div>
        """

    refs_html = ""
    if refs:
        ref_rows = ""
        for r in refs:
            ref_rows += f"""<tr>
              <td>{_esc(r.get('代码',''))}</td>
              <td>{_esc(r.get('名称',''))}</td>
              <td>{_badge(r.get('涨跌幅类型') or r.get('类型') or '20%','warn')}</td>
              <td>{_esc(r.get('行业',''))}</td>
              <td>{_esc(r.get('连板',''))}</td>
              <td>{_esc(r.get('首封',''))}</td>
              <td>{_esc(r.get('炸板',''))}</td>
              <td>{_esc(r.get('成交额(亿)') or r.get('成交额',''))}</td>
              <td>{_esc(r.get('换手',''))}</td>
              <td>{_badge('不导入/不执行','bad')}</td>
            </tr>"""
        refs_html = f"""
        <h3>20% / 30% 参考区（不导入、不执行，仅题材/情绪参考）</h3>
        <div class="md-table-wrap"><table>
          <thead><tr><th>代码</th><th>名称</th><th>类型</th><th>行业</th>
            <th>连板</th><th>首封</th><th>炸板</th><th>成交额</th><th>换手</th><th>处理</th></tr></thead>
          <tbody>{ref_rows}</tbody></table></div>
        """

    th_status = d.get("th_status") or "pending"
    th_badge = {"done": _badge("已导入","good"),
                "blocked": _badge("阻塞","warn"),
                "failed": _badge("失败","bad")}.get(th_status, _badge("待导入","info"))

    return f"""
    <section id="tomorrow" class="card">
      <div class="flex between">
        <h2 style="margin:0">② 明日计划 — {_esc(td)}</h2>
        <span>同花顺 CSV {_esc(len(codes))} 只 · {th_badge}</span>
      </div>
      <div class="muted" style="margin:6px 0 10px">
        {_esc(d.get('market_summary') or '')}
        <br>{_esc(d.get('theme_summary') or '')}
        <br>{_esc(d.get('execution_summary') or '')}
      </div>
      {blocks or '<div class="alert warn">该计划未解析到候选行</div>'}
      {refs_html}
    </section>
    """


def _render_today_review(d: dict) -> str:
    if d.get("empty"):
        return '<section id="review" class="card"><h2>③ 当日复盘</h2><div class="muted">尚无复盘数据</div></section>'
    td = d["trade_date"]
    m = d.get("metrics", {})
    rows = d.get("rows", [])
    plans_map = {p["code"]: p for p in d.get("plan_candidates", [])}

    def _row_html(r: dict) -> str:
        p = plans_map.get(r["code"], {})
        result_cls = "good" if r["sealed"] == "是" else ("warn" if r["touched"] == "是" else "")
        return f"""<tr>
          <td>{_esc(r.get('plan_level'))}</td>
          <td><strong>{_esc(r.get('code'))}</strong></td>
          <td>{_esc(r.get('name'))}</td>
          <td>{_esc(r.get('plan_role'))}</td>
          <td class="text-right">{_esc(r.get('plan_score') or '')}</td>
          <td>{_badge(r.get('actual_result',''), result_cls or 'info')}</td>
          <td>{_esc(r.get('touched'))} / {_esc(r.get('sealed'))}</td>
          <td>{_esc(r.get('first_touch_time'))}</td>
          <td>{_esc(r.get('last_seal_time'))}</td>
          <td class="text-right">{_esc(r.get('break_count'))}</td>
          <td>{_esc(r.get('turnover_amount'))}</td>
          <td>{_esc(r.get('turnover_rate'))}</td>
          <td class="muted">{_esc(r.get('experience_tag') or '')}</td>
        </tr>"""

    table = "".join(_row_html(r) for r in rows)

    prev_premium = d.get("prev_premium") or []
    if prev_premium:
        prem_rows = ""
        for p in prev_premium:
            shape = p.get("shape") or ""
            cls = "good" if "高走" in shape and "高开" in shape else ("warn" if "低开低走" in shape else "info")
            prem_rows += f"""<tr>
              <td>{_esc(p['code'])}</td>
              <td>{_esc(p['name'])}</td>
              <td>{_esc(p['promotion_date'])}</td>
              <td class="text-right">{_esc(p.get('open_premium_pct'))}%</td>
              <td class="text-right">{_esc(p.get('high_premium_pct'))}%</td>
              <td class="text-right">{_esc(p.get('p10_premium_pct'))}%</td>
              <td>{_badge(shape, cls)}</td>
              <td class="muted">{_esc(p.get('conclusion'))}</td>
            </tr>"""
        premium_block = f"""
        <h3>上一交易日"成功晋级池"的次日溢价回看（10:00 前）</h3>
        <div class="md-table-wrap"><table>
          <thead><tr><th>代码</th><th>名称</th><th>晋级日</th><th>开盘溢价</th>
            <th>10:00 前最高</th><th>10:00 溢价</th><th>形态</th><th>结论</th></tr></thead>
          <tbody>{prem_rows}</tbody></table></div>
        """
    else:
        premium_block = '<div class="muted" style="margin-top:8px">无上一日溢价数据</div>'

    return f"""
    <section id="review" class="card">
      <div class="flex between">
        <h2 style="margin:0">③ 当日复盘 — {_esc(td)}</h2>
        <a class="btn small" href="/review/{_esc(d.get('compact',''))}">查看完整复盘报告</a>
      </div>
      <div class="grid grid-4" style="margin:10px 0">
        <div class="stat"><div class="label">触板率</div><div class="value">{_esc(m.get('touch_rate'))}%</div>
          <div class="sub">{_esc(m.get('touched'))} / {_esc(m.get('total'))}</div></div>
        <div class="stat"><div class="label">封住率</div><div class="value">{_esc(m.get('seal_rate'))}%</div>
          <div class="sub">{_esc(m.get('sealed'))} / {_esc(m.get('total'))}</div></div>
        <div class="stat"><div class="label">炸板率</div><div class="value">{_esc(m.get('burst_rate'))}%</div>
          <div class="sub">触板未封 {_esc(m.get('burst'))}</div></div>
        <div class="stat"><div class="label">计划内可参与</div><div class="value">{_esc(m.get('actionable_rate'))}%</div>
          <div class="sub">封住且非一字 {_esc(m.get('actionable'))}</div></div>
      </div>
      <div class="md-table-wrap"><table>
        <thead><tr><th>级别</th><th>代码</th><th>名称</th><th>角色</th><th>分</th>
          <th>实际结果</th><th>触/封</th><th>首触</th><th>末封</th><th>炸</th>
          <th>成交</th><th>换手</th><th>经验标签</th></tr></thead>
        <tbody>{table}</tbody></table></div>
      {premium_block}
    </section>
    """


def _render_trend(d: dict) -> str:
    def _agg_row(label: str, m: dict) -> str:
        return f"""<tr>
          <td>{_esc(label)}</td>
          <td>{_esc(m.get('total'))}</td>
          <td>{_esc(m.get('touch_rate'))}%</td>
          <td>{_esc(m.get('seal_rate'))}%</td>
          <td>{_esc(m.get('burst_rate'))}%</td>
          <td>{_esc(m.get('actionable_rate'))}%</td>
        </tr>"""

    rows = "".join([
        _agg_row("近 5 日", d["last_5"]["aggregate"]),
        _agg_row("近 10 日", d["last_10"]["aggregate"]),
        _agg_row("近 20 日", d["last_20"]["aggregate"]),
    ])

    by_lv = d["last_10"]["by_level"]
    by_lv_rows = ""
    for lv in ("主选", "条件", "备选"):
        m = by_lv.get(lv, {})
        by_lv_rows += _agg_row(f"近 10 日 · {lv}", m)

    shape = d.get("shape_dist", {})
    shape_html = "".join(f"<li>{_esc(k)} <strong>{_esc(v)}</strong></li>" for k, v in shape.items())

    return f"""
    <section id="trend" class="card">
      <h2 style="margin-top:0">④ 趋势分析</h2>
      <div class="grid grid-2">
        <div>
          <h3>整体表现</h3>
          <table><thead><tr><th>窗口</th><th>样本</th><th>触板</th>
            <th>封住</th><th>炸板</th><th>可参与</th></tr></thead>
            <tbody>{rows}</tbody></table>
          <h3 style="margin-top:14px">按级别（近 10 日）</h3>
          <table><thead><tr><th>窗口/级别</th><th>样本</th><th>触板</th>
            <th>封住</th><th>炸板</th><th>可参与</th></tr></thead>
            <tbody>{by_lv_rows}</tbody></table>
        </div>
        <div>
          <h3>次日 10:00 前溢价</h3>
          <div class="stat"><div class="label">可兑现率（10:00 前最高 &gt; 前收）</div>
            <div class="value">{_esc(d.get('premium_actionable_rate'))}%</div>
            <div class="sub">基于 premium_tracking 全量样本</div></div>
          <h3 style="margin-top:14px">次日形态分布</h3>
          <ul>{shape_html or '<li class="muted">暂无数据</li>'}</ul>
        </div>
      </div>
    </section>
    """


def _render_iteration(d: dict) -> str:
    progress = d.get("progress", {})
    pg_rows = ""
    for k, v in progress.items():
        label_map = {"observation": "观察假设", "reusable": "可复用经验", "control": "对照策略"}
        met = "✅ 已达" if v["met"] else "⏳ 未达"
        pg_rows += f"""<tr>
          <td>{_esc(label_map.get(k, k))}</td>
          <td>{v['days_threshold']} 日 / {v['cands_threshold']} 条</td>
          <td>{v['days_current']} 日 / {v['cands_current']} 条</td>
          <td>{met}</td>
          <td>距日 {v['days_remaining']}, 距条 {v['cands_remaining']}</td>
        </tr>"""

    iter_md_short = (d.get("iteration_md") or "")[:1500]
    return f"""
    <section id="iteration" class="card">
      <h2 style="margin-top:0">⑤ 策略迭代</h2>
      <div class="alert info">
        正式策略：<code>{_esc(d.get('official_strategy_skill'))}</code>
        复盘 skill：<code>{_esc(d.get('review_skill'))}</code>
        <br>当前累计：复盘交易日 <strong>{_esc(d.get('review_day_count'))}</strong> 个，候选样本 <strong>{_esc(d.get('sample_count'))}</strong> 条
      </div>
      <h3>证据门槛进度</h3>
      <table>
        <thead><tr><th>阶段</th><th>门槛</th><th>当前</th><th>状态</th><th>距门槛</th></tr></thead>
        <tbody>{pg_rows}</tbody>
      </table>
      <h3 style="margin-top:16px">策略迭代日志（最近）</h3>
      <pre class="code-block">{_esc(iter_md_short)}</pre>
      <div class="toolbar">
        <a class="btn" href="/review/experience">📘 复盘经验库</a>
        <a class="btn" href="/review/iteration">🧭 策略迭代日志全文</a>
      </div>
    </section>
    """


def _render_health(d: dict) -> str:
    jobs = d.get("jobs", [])
    runs = d.get("runs", [])
    issues = d.get("issues", [])

    job_rows = ""
    for j in jobs:
        job_rows += f"""<tr>
          <td><strong>{_esc(j['name'])}</strong></td>
          <td>{_esc(j.get('cron_hint',''))}</td>
          <td>{_job_status_badge(j.get('last_status'))}</td>
          <td>{_esc(j.get('last_run_at','—'))}</td>
          <td>{_esc(j.get('last_target_date','—'))}</td>
          <td class="muted">{_esc(j.get('last_message','')[:80])}</td>
          <td>
            <form method="post" action="/jobs/run/{_esc(j['name'])}" style="margin:0">
              <button class="btn small primary">▶ 立即跑</button>
            </form>
          </td>
        </tr>"""

    issue_rows = ""
    for i in issues:
        sev = i["severity"] or ""
        cls = {"error": "bad", "warn": "warn", "info": "info"}.get(sev, "info")
        issue_rows += f"""<tr>
          <td>{_badge(sev, cls)}</td>
          <td>{_esc(i['kind'])}</td>
          <td>{_esc(i['target'])}</td>
          <td class="muted">{_esc(i['detail'])}</td>
          <td>{_esc(i['detected_at'])}</td>
        </tr>"""

    run_rows = ""
    for r in runs[:10]:
        st = r["status"]
        cls = {"ok": "good", "failed": "bad", "skipped": "warn"}.get(st, "info")
        run_rows += f"""<tr>
          <td>{_esc(r['id'])}</td>
          <td>{_esc(r['job_name'])}</td>
          <td>{_badge(st, cls)}</td>
          <td>{_esc(r['target_date'])}</td>
          <td>{_esc(r['started_at'])}</td>
          <td class="muted">{_esc((r['message'] or '')[:80])}</td>
        </tr>"""

    return f"""
    <section id="health" class="card">
      <h2 style="margin-top:0">⑥ 系统健康</h2>
      <h3>自动任务</h3>
      <table>
        <thead><tr><th>任务</th><th>调度</th><th>状态</th><th>最近执行</th><th>目标日</th><th>消息</th><th>手动</th></tr></thead>
        <tbody>{job_rows or '<tr><td colspan=7 class=muted>暂无</td></tr>'}</tbody>
      </table>
      <h3 style="margin-top:14px">活跃告警</h3>
      <table>
        <thead><tr><th>等级</th><th>类型</th><th>目标</th><th>详情</th><th>发现时间</th></tr></thead>
        <tbody>{issue_rows or '<tr><td colspan=5 class="muted good">✅ 暂无告警</td></tr>'}</tbody>
      </table>
      <h3 style="margin-top:14px">最近 10 次任务执行</h3>
      <table>
        <thead><tr><th>ID</th><th>任务</th><th>状态</th><th>目标日</th><th>开始时间</th><th>消息</th></tr></thead>
        <tbody>{run_rows or '<tr><td colspan=6 class=muted>暂无</td></tr>'}</tbody>
      </table>
    </section>
    """


@router.route("/")
def dashboard(req):
    d = aggregate()

    body = (
        _render_today_overview(d["today"]) +
        _render_tomorrow_plan(d["tomorrow"]) +
        _render_today_review(d["review"]) +
        _render_trend(d["trend"]) +
        _render_iteration(d["iteration"]) +
        _render_health(d["health"]) +
        """
        <div class="card compact">
          <div class="flex between">
            <span class="muted">本页是统一入口；其它功能：
              <a href="/picks">观察池历史</a> ·
              <a href="/review">复盘历史</a> ·
              <a href="/strategy">策略管理</a> ·
              <a href="/kb">知识库</a> ·
              <a href="/system">系统改进</a></span>
            <a class="btn small" href="/" onclick="location.reload();return false;">🔄 刷新</a>
          </div>
        </div>
        """
    )
    return layout("总览", body, active="home")


@router.route("/jobs/run/<name>", methods=("POST",))
def run_job_now(req, name):
    run_job(name)
    return redirect("/#health")


@router.route("/api/dashboard.json")
def dashboard_json(req):
    """便于外部工具/手机端获取最新数据。"""
    return aggregate()
