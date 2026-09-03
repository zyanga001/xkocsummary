"""从真实归档生成简报：杂志页视觉 + 左右 tab 切换（主人确认的最终形态 + 六点调整）。

主人 6 点要求：
1. 导航去掉「归档」tab，保留 日报/高/中/低/博主；高/中/低都用「值得精读」模板，
   显示「为什么是高/中/低」，颜色 高=绿 中=黄 低=红
2. 导航用杂志「小志」样式（小字 + 下划线高亮，不是按钮），横排、左右切换，切换时顶部固定
3. 信息透明度：在 meta-row 同一行位置，可折叠 —— 点击展开成运行透明度表格（抓取详情），
   再点折叠，默认折叠
4. 博主雷达：去掉刻度尺，改成点开看该博主今天发了什么
5. 加 favicon
6. 顶部「信号台」三个字改成「x日报」

视觉 = 杂志页 preview-real-b.html 原样 CSS。
用法：python3 build_page.py
"""
from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

ARCHIVE_DATE = "2026-08-06"
ARCHIVE_RUN = "run-1"
TEMPLATE = Path("preview-real-b.html")
OUT = Path("output/v4/index.html")
FAVICON = (
    "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<rect width='100' height='100' rx='20' fill='%2324568C'/>"
    "<text x='50' y='70' font-size='56' text-anchor='middle' fill='%23F9F7F2' "
    "font-family='Georgia,serif' font-weight='900'>x</text></svg>"
)


def load_run(date: str, run: str) -> dict:
    # 优先读本地新跑出来的 run.json（含推导链 chain），没有才回退 git 归档
    local = Path("output/v4-live/run.json")
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    for ref in ("FETCH_HEAD", "gh-pages-local"):
        raw = subprocess.run(
            ["git", "show", f"{ref}:archive/{date}/{run}/run.json"],
            capture_output=True, check=False, text=True,
        )
        if raw.returncode == 0:
            return json.loads(raw.stdout)
    raise SystemExit(f"找不到 {date}/{run} 的归档")


def extract_css(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", text, re.S)
    if not m:
        raise SystemExit("模板里找不到 style 块")
    return m.group(1)


def archive_calendar() -> list[dict]:
    lines = []
    for ref in ("FETCH_HEAD", "gh-pages-local"):
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref, "archive/"],
            capture_output=True, check=False, text=True,
        )
        if out.returncode == 0:
            lines = out.stdout.splitlines()
            break
    days: dict[str, set[str]] = {}
    for line in lines:
        parts = line.split("/")
        if len(parts) >= 3 and parts[2].startswith("run-"):
            days.setdefault(parts[1], set()).add(parts[2])
    return [{"date": d, "runs": sorted(days[d])} for d in sorted(days)]


def calendar_days_from_history(history: list[dict]) -> list[dict]:
    days: dict[str, set[str]] = {}
    for entry in history:
        path = Path(str(entry.get("path") or ""))
        parts = path.parts
        if len(parts) >= 2 and parts[1].startswith("run-"):
            days.setdefault(parts[0], set()).add(parts[1])
    return [{"date": date, "runs": sorted(runs)} for date, runs in sorted(days.items())]


def esc(s: object) -> str:
    return html.escape(str(s or ""), quote=True)


# 导航小志样式 + 透明度折叠 + 分层配色 + 博主 + 日历（全用杂志变量）
TAB_CSS = """
  /* —— 各博主观点：跟正文一样协调，不加粗，普通阅读正文样式 —— */
  .who-block { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line-soft); }
  .who-label { font-family: var(--mono); font-size: 11px; letter-spacing: 0.14em; color: var(--muted); margin-bottom: 6px; }
  .who-text { font-size: 14px; line-height: 1.9; color: var(--ink-2); }
  /* —— 导航：杂志「小志」样式，小字 + 下划线高亮，不是按钮 —— */
  .nav { position: sticky; top: 0; z-index: 20; background: var(--paper);
    display: flex; gap: 0 26px; overflow-x: auto; padding: 2px 0 0;
    border-bottom: 1px solid var(--line); scrollbar-width: none; }
  .nav::-webkit-scrollbar { display: none; }
  .nav a { flex: none; padding: 12px 1px 9px; font-size: 13px; color: var(--ink-2);
    white-space: nowrap; border-bottom: 2px solid transparent; margin-bottom: -1px; cursor: pointer; }
  .nav a:hover { text-decoration: none; color: var(--ink); }
  .nav a.active { color: var(--ink); font-weight: 700; border-bottom-color: var(--ink); }
  .panel { display: none; }
  .panel.active { display: block; }
  /* —— 信息透明度：meta-row 同行可折叠，默认收起 —— */
  .runline { font-family: var(--mono); font-size: 11.5px; color: var(--ink-2);
    border-bottom: 1px solid var(--line); margin-bottom: 18px; }
  .runline summary { cursor: pointer; display: flex; align-items: center; gap: 8px;
    padding: 7px 0; color: var(--muted); user-select: none; list-style: none; }
  .runline summary::-webkit-details-marker { display: none; }
  .runline summary::before { content: "▸ "; color: var(--muted); }
  .runline[open] summary::before { content: "▾ "; }
  .runline summary b { color: var(--ink); font-weight: 700; }
  .runline summary:hover { color: var(--ink); }
  .runline .runline-body { margin: 4px 0 12px; }
  /* —— 分层：都值得精读模板，颜色 高绿/中黄/低红 —— */
  .read.tier-high h4, .read.tier-high .why { border-left-color: var(--bull); }
  .read.tier-medium h4, .read.tier-medium .why { border-left-color: var(--warn-ink); }
  .read.tier-low h4, .read.tier-low .why { border-left-color: var(--bear); }
  .badge { font-family: var(--mono); font-size: 11px; padding: 1px 7px; border-radius: 2px; }
  .badge.tier-high { background: var(--ok-bg); color: var(--ok-ink); }
  .badge.tier-medium { background: var(--warn-bg); color: var(--warn-ink); }
  .badge.tier-low { background: var(--line-soft); color: var(--muted); }
  /* —— 博主：点开看今天发了什么（去掉刻度尺） —— */
  .author-block { border-bottom: 1px solid var(--line-soft); padding: 12px 0; }
  .author-block summary { cursor: pointer; display: flex; justify-content: space-between;
    gap: 12px; align-items: baseline; list-style: none; }
  .author-block summary::-webkit-details-marker { display: none; }
  .author-block .an { font-family: var(--serif); font-weight: 900; font-size: 14.5px; color: var(--ink); }
  .author-block .st { font-family: var(--mono); font-size: 11.5px; color: var(--muted); }
  .author-block ul { margin: 10px 0 0; padding: 0; list-style: none; }
  .author-block li { padding: 7px 0; border-bottom: 1px solid var(--line-soft); font-size: 13.5px; line-height: 1.7; }
  .author-block li a { color: var(--ink-2); }
  .author-block li a:hover { color: var(--accent); }
  /* —— 日历 —— */
  .cal { display: grid; grid-template-columns: repeat(auto-fill, minmax(54px, 1fr)); gap: 6px;
    background: var(--card); border: 1px solid var(--line); padding: 14px; }
  .day { aspect-ratio: 1; border: 1px solid var(--line); border-radius: 3px; padding: 6px;
    display: flex; flex-direction: column; justify-content: space-between; font-size: 12px;
    cursor: pointer; font-family: var(--mono); }
  .day .dots { display: flex; gap: 3px; justify-content: flex-end; }
  .dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
  .dot.on { background: var(--ok-ink); }
  .dot.off { background: var(--line); }
  .day.full { background: var(--ok-bg); border-color: var(--ok-ink); }
  .day.half { background: var(--warn-bg); border-color: var(--warn-ink); }
  .day.none { background: transparent; color: var(--muted); }
  .legend { margin-top: 10px; font-size: 11.5px; color: var(--muted); }
  .legend span { display: inline-flex; align-items: center; gap: 4px; margin-right: 14px; }
  .legend .dot { width: 9px; height: 9px; }
  @media (max-width: 600px) { .nav { gap: 0 18px; } }
"""


def render_calendar_page(days: list[dict], css: str) -> str:
    cells = []
    for d in days:
        n = len(d["runs"])
        state = "full" if n >= 2 else ("half" if n == 1 else "none")
        hint = {"full": "两期都生成", "half": "只生成了一次", "none": "未生成"}[state]
        dots = []
        for slot in ("run-1", "run-2"):
            if slot in d["runs"]:
                link = f'<a class="dot on" href="../archive/{d["date"]}/{slot}/report.html" title="{d["date"]} {slot}"></a>'
            else:
                link = f'<span class="dot off" title="该时段未生成"></span>'
            dots.append(link)
        cells.append(
            f'<div class="day {state}" title="{esc(d["date"])} · {hint}">'
            f'<span class="dnum">{esc(d["date"][-2:])}</span>'
            f'<span class="dots">{"".join(dots)}</span></div>'
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>历史归档 · 每日简报</title>
<style>{css}{TAB_CSS}</style>
</head>
<body>
<div class="shell">
  <header class="masthead">
    <div class="masthead-row">
      <div class="brand">历史归档<small>ARCHIVE · 每日简报</small></div>
      <div class="issue"><a href="../index.html" style="font-family:var(--mono);font-size:12px;color:var(--muted);">← 返回简报</a></div>
    </div>
    <div class="rule-double" aria-hidden="true"></div>
  </header>
  <p style="color:var(--muted);margin:14px 0;font-size:12.5px;">一格一天 · 左=早报 右=晚报 · 两绿=两期都有 · 半=只生成一次 · 灰=未生成</p>
  <div class="cal">{''.join(cells)}</div>
  <div class="legend">
    <span><span class="dot" style="background:var(--ok-ink)"></span> 两期都生成</span>
    <span><span class="dot" style="background:var(--warn-ink)"></span> 只生成一次</span>
    <span><span class="dot" style="background:var(--line)"></span> 未生成</span>
  </div>
</div>
</body>
</html>"""


def render_focus(run: dict, items: list[dict]) -> str:
    """日报面板：展示已审计事件的状态、证据、变化和未知项。"""
    daily_brief = [
        event
        for event in (run.get("daily_brief") or [])
        if event.get("presentation") != "trace"
    ]
    if not daily_brief:
        return '<div class="panel active" id="panel-brief"><div class="empty-state">本期没有日报话题</div></div>'

    topics_html = ""
    for t in daily_brief:
        topic = t.get("title") or "未命名事件"
        path = " / ".join(t.get("theme_path") or [])
        evidence = "".join(
            f'<li><span class="an">{esc(item.get("post_id"))}</span>：'
            f'{esc(item.get("claim"))}</li>'
            for item in t.get("new_evidence") or []
        )
        unknowns = "".join(
            f"<li>{esc(value)}</li>" for value in t.get("unknowns") or []
        )
        topics_html += f"""
  <article class="topic">
    <div class="topic-kicker">
      <span class="chip track">{esc(path)}</span>
      <span class="chip">话题{esc(t.get('topic_importance'))} · {esc(t.get('presentation'))} · 置信度{esc(t.get('confidence'))}</span>
    </div>
    <h3>{esc(topic)}</h3>
    <p class="topic-gist"><b>核心判断：</b>{esc(t.get('thesis'))}</p>
    <div class="who-block">
      <p class="who-label">此前状态</p>
      <p class="who-text">{esc(t.get('prior_state'))}</p>
      <p class="who-label">本期新证据</p>
      <ul class="who-text">{evidence}</ul>
      <p class="who-label">判断变化</p>
      <p class="who-text">{esc(t.get('judgment_delta'))}</p>
      <p class="who-label">仍未知</p>
      <ul class="who-text">{unknowns}</ul>
    </div>
  </article>"""

    return f"""
<div class="panel active" id="panel-brief">
<section id="topics">
  <div class="eyebrow">
    <span class="no">§ 01</span><h2>焦点话题</h2>
    <span class="prov">今日话题 · {len(daily_brief)} 个</span>
  </div>
  {topics_html}
</section>
</div>"""


def render_tier(items: list[dict], tier: str, no: str, label: str, prov: str, panel_id: str) -> str:
    """高/中/低都用一个模板：值得精读 .read。内容显示「为什么是X」，颜色分档。"""
    color_cls = {"高": "tier-high", "中": "tier-medium", "低": "tier-low"}[tier]
    rows = []
    for x in items:
        if x.get("importance") != tier:
            continue
        body = (x.get("content_full") or x.get("content") or "").strip()
        summary = (x.get("summary") or "").strip()
        pub = (x.get("published_at") or "")
        time = pub[11:16] if len(pub) >= 16 else ""
        why = (x.get("why_worth") or summary or body[:40]).strip()
        rows.append(f"""
<article class="read {color_cls}">
  <h4>{esc(x.get("author"))}：{esc(why[:50])}</h4>
  <div class="why">💡 为什么是{esc(tier)}价值：{esc(why)}</div>
  <div class="src"><span class="badge {color_cls}">{esc(tier)}</span> {esc(time)} · <a href="{esc(x.get("url"))}" target="_blank" rel="noopener">原文 ↗</a></div>
</article>""")
    count = sum(1 for x in items if x.get("importance") == tier)
    return f"""
<div class="panel" id="panel-{esc(panel_id)}">
<section id="reads-{esc(panel_id)}">
  <div class="eyebrow">
    <span class="no">§ {esc(no)}</span><h2>{esc(label)}</h2>
    <span class="prov">{esc(prov)} · {count} 条</span>
  </div>
  {"".join(rows) if rows else '<p style="color:var(--muted);">本期没有' + esc(tier) + '价值内容</p>'}
</section>
</div>"""


def render_authors(run: dict) -> str:
    """博主：点开看今天发了什么（去掉刻度尺，用在线预览的展开方式）。"""
    items = run["items"]
    by_author: dict[str, list[dict]] = {}
    for x in items:
        by_author.setdefault(x["author"], []).append(x)
    blocks = []
    for author, own in sorted(by_author.items(), key=lambda kv: -len(kv[1])):
        dist = {"高": 0, "中": 0, "低": 0}
        for x in own:
            dist[x.get("importance", "低")] = dist.get(x.get("importance", "低"), 0) + 1
        tweets = "".join(
            f'<li><a href="{esc(x.get("url"))}" target="_blank" rel="noopener">'
            f'{esc((x.get("content_full") or x.get("content") or "")[:120])}</a></li>'
            for x in own
        )
        blocks.append(f"""
<details class="author-block">
  <summary><span class="an">@{esc(author)}</span>
    <span class="st">{len(own)} 条 · 高 {dist['高']} / 中 {dist['中']} / 低 {dist['低']}</span>
  </summary>
  <ul>{tweets}</ul>
</details>""")
    return f"""
<div class="panel" id="panel-authors">
<section id="authors">
  <div class="eyebrow">
    <span class="no">§ 05</span><h2>博主</h2>
    <span class="prov">{len(by_author)} 人有内容 · 点击展开今天发的推文</span>
  </div>
  {"".join(blocks)}
</section>
</div>"""


def render_editorial_report(
    run: dict,
    css: str,
    archive_href: str = "archive/index.html",
    archive_date: str = "",
    archive_run: str = "",
) -> str:
    items = run["items"]

    date_str = archive_date or str(run.get("planned_at") or run.get("created_at") or "")[:10]
    slot = run.get("slot_label") or "早报"
    total = run.get("total_authors", 0)
    n_items = len(items)

    ok = run.get("scan_ok", 0)
    no_posts = run.get("scan_no_posts_in_window", 0)
    empty_feed = run.get("scan_empty_all_instances", 0)
    fail = run.get("scan_fail", 0)
    hi, mid, low = run.get("high_count", 0), run.get("medium_count", 0), run.get("low_count", 0)
    errs = (run.get("scan_errors") or [])[:15]
    err_rows = "".join(
        f'<tr><td>@{esc(e["author"])}</td><td><span class="status warn">失败</span></td>'
        f'<td class="detail">{esc(str(e.get("error", ""))[:90])}</td></tr>'
        for e in errs
    )

    # 信息透明度：meta-row 同行可折叠，默认收起，点开是运行透明度表格
    transparency = f"""
<details class="runline">
  <summary>本次运行透明度：有内容 <b>{ok}</b> · 窗口内无帖 <b>{no_posts}</b> · 空feed <b>{empty_feed}</b> · 失败 <b>{fail}</b> ·
    判 <b>高{hi} / 中{mid} / 低{low}</b></summary>
  <div class="runline-body">
    <div class="table-scroll">
      <table class="runtable">
        <tr><th>阶段</th><th>状态</th><th>明细</th></tr>
        <tr><td>抓取</td><td><span class="status {'ok' if fail == 0 else 'warn'}">{'✓ 正常' if fail == 0 else '⚠ 降级'}</span></td>
          <td class="detail">{total} 人名单，有内容 {ok} · 窗口内无帖 {no_posts} · 所有实例空feed {empty_feed} · 硬失败 {fail} · 时间不明 {run.get('scan_time_uncertain', 0)}</td></tr>
        <tr><td>解析去重</td><td><span class="status ok">✓ 正常</span></td>
          <td class="detail">本期 {n_items} 条内容 · 来自 {run.get('authors_count', 0)} 个博主 · 判 高{hi} / 中{mid} / 低{low}</td></tr>
        <tr><td>事件推导</td><td><span class="status ok">✓ 正常</span></td>
          <td class="detail">证据抽取 → 事件合成 → 事件审计 → 条目判断 → 条目审计；按 rubric 标尺（落点 + 可学）</td></tr>
        {err_rows}
      </table>
    </div>
    <div class="runmeta">数据源：archive/{esc(archive_date)}/{esc(archive_run)} · 证据与审计记录见 run.json</div>
  </div>
</details>"""

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="{FAVICON}">
<title>x日报 · {date_str} · {esc(slot)}</title>
<style>{css}{TAB_CSS}</style>
</head>
<body>
<div class="shell">

  <header class="masthead">
    <div class="masthead-row">
      <div class="brand">x日报<small>SIGNALPOST · X KOL DAILY BRIEF</small></div>
      <div class="issue">
        <span class="date">{date_str}</span><span class="slot">{esc(slot)}</span>
      </div>
    </div>
    <div class="rule-double" aria-hidden="true"></div>
    <div class="meta-row">
      <span class="dot-ok">数据完整度 {esc(round((ok/total*100) if total else 0))}%</span>
      <span>窗口 {esc(run.get("window_start",""))[11:16]}–{esc(run.get("window_end",""))[11:16]}</span>
      <span>{n_items} 条 → 信号 {esc(hi)} 条</span>
      <span>约 5 分钟读完</span>
      <a href="{esc(archive_href)}">历史归档 ↗</a>
      <button class="theme-btn" id="themeBtn" type="button" aria-label="切换日间/夜间配色">🌙 夜间</button>
    </div>
    {transparency}
  </header>

  <nav class="nav" aria-label="本期目录">
    <a href="#brief" class="active">日报</a>
    <a href="#high">高 · {hi}</a>
    <a href="#medium">中 · {mid}</a>
    <a href="#low">低 · {low}</a>
    <a href="#authors">博主</a>
  </nav>

  {render_focus(run, items)}
  {render_tier(items, '高', '02', '值得精读 · 高', '为什么是高价值 · 必须看', 'high')}
  {render_tier(items, '中', '03', '值得精读 · 中', '为什么是中价值 · 可选', 'medium')}
  {render_tier(items, '低', '04', '值得精读 · 低', '为什么是低价值 · 噪音', 'low')}
  {render_authors(run)}

  <footer>
    <div><b>x日报</b> · 每天早晚各一期。内容由 LLM 自动分类与综合，可能有误——任何操作请先点开原文核实；教程类内容常含邀请码/邀请链接，请自行甄别。折叠与降级都不删数据，run.json 永远保留完整现场。</div>
  </footer>
</div>
<script>
(function(){{
  var links = document.querySelectorAll('.nav a');
  var panels = document.querySelectorAll('.panel');
  function show(name) {{
    panels.forEach(function (p) {{ p.classList.toggle('active', p.id === 'panel-' + name); }});
    links.forEach(function (a) {{ a.classList.toggle('active', a.getAttribute('href') === '#' + name); }});
    window.location.hash = name;
  }}
  links.forEach(function (a) {{
    a.addEventListener('click', function (e) {{ e.preventDefault(); show(a.getAttribute('href').slice(1)); }});
  }});
  var btn = document.getElementById('themeBtn');
  var root = document.documentElement;
  function apply(mode) {{
    root.setAttribute('data-theme', mode);
    if (btn) btn.textContent = mode === 'dark' ? '☀️ 日间' : '🌙 夜间';
    try {{ localStorage.setItem('sp-theme', mode); }} catch (e) {{}}
  }}
  var saved = 'light'; try {{ saved = localStorage.getItem('sp-theme') || 'light'; }} catch (e) {{}}
  apply(saved);
  if (btn) btn.addEventListener('click', function () {{
    apply(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  }});
  var h = window.location.hash.slice(1);
  if (h && document.getElementById('panel-' + h)) show(h);
}})();
</script>
</body>
</html>"""

    return page


def main() -> None:
    run = load_run(ARCHIVE_DATE, ARCHIVE_RUN)
    css = extract_css(TEMPLATE)
    days = archive_calendar()
    calendar_path = Path("output/v4/archive/index.html")
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    calendar_path.write_text(render_calendar_page(days, css), encoding="utf-8")
    page = render_editorial_report(
        run,
        css,
        archive_date=ARCHIVE_DATE,
        archive_run=ARCHIVE_RUN,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"[ok] {OUT} · {len(page)} 字节 · {len(run['items'])} 条内容 · 归档 {len(days)} 天")


if __name__ == "__main__":
    main()
