"""V2 四段式 HTML 报告生成器。

布局参考用户指定站点：导航标签切换视图，纯静态 GitHub Pages 兼容。
"""

from __future__ import annotations

from html import escape
from typing import Any

from .enrich import format_meta, _compact


def render_v2_report(result: dict[str, Any], run_label: str = "") -> str:
    """渲染4段式日报HTML。

    Args:
        result: pipeline运行结果字典，包含 items, daily_brief, author_profiles 等
        run_label: 可读的运行标签，如 "2026-06-12 14:30 CST · 今日第2次更新"
    """
    date = run_label or (result.get("created_at") or "")[:10]
    items = result.get("items", [])
    daily_brief = result.get("daily_brief", [])
    author_profiles = result.get("author_profiles", [])
    medium_merge = result.get("medium_merge", "")

    high_items = [i for i in items if i.get("importance") == "高"]
    medium_items = [i for i in items if i.get("importance") == "中"]
    low_items = [i for i in items if i.get("importance") == "低"]
    total = len(items)
    active_authors = result.get("authors_count", 0)
    total_authors = result.get("total_authors", active_authors)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>每日简报 · {date}</title>
  <style>
    :root {{
      --bg: #f6f8fa;
      --card: #ffffff;
      --text: #1f2328;
      --muted: #656d76;
      --border: #d0d7de;
      --link: #0969da;
      --accent: #0969da;
      --high: #1a7f37;
      --high-bg: #dafbe1;
      --med: #9a6700;
      --med-bg: #fff8c5;
      --low: #cf222e;
      --low-bg: #ffebe9;
      --tag-bg: #f3f4f6;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Noto Sans SC", sans-serif;
      line-height: 1.6;
      font-size: 15px;
    }}
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .shell {{ max-width: 900px; margin: 0 auto; padding: 20px 16px 60px; }}

    /* Top bar */
    .topbar {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 12px 0; margin-bottom: 24px; border-bottom: 1px solid var(--border);
    }}
    .topbar .brand {{ font-size: 18px; font-weight: 700; }}
    .topbar .archive-link {{ font-size: 14px; color: var(--muted); }}

    /* Nav tabs */
    .nav-tabs {{
      display: flex; gap: 2px; margin-bottom: 24px;
      background: var(--card); border-radius: 6px; padding: 4px;
      box-shadow: 0 1px 0 rgba(31,35,40,0.04);
      border: 1px solid var(--border);
      overflow-x: auto;
    }}
    .nav-tab {{
      flex: 1; min-width: 72px; padding: 8px 12px; border: none; background: transparent;
      font-size: 14px; font-weight: 600; color: var(--muted); cursor: pointer;
      border-radius: 4px; white-space: nowrap; text-align: center;
      transition: background 0.12s;
    }}
    .nav-tab:hover {{ background: var(--tag-bg); }}
    .nav-tab.active {{ background: var(--link); color: #fff; }}
    .nav-tab .count {{ font-weight: 400; font-size: 12px; opacity: 0.85; }}

    /* Panels */
    .panel {{ display: none; }}
    .panel.active {{ display: block; }}

    /* Cards */
    .card {{
      background: var(--card); border: 1px solid var(--border); border-radius: 6px;
      padding: 20px; margin-bottom: 16px;
    }}
    .card.high {{ border-left: 3px solid var(--high); }}
    .card.medium {{ border-left: 3px solid var(--med); }}
    .card.low {{ border-left: 3px solid var(--low); }}

    .card-title {{
      font-size: 16px; font-weight: 700; margin-bottom: 4px;
    }}
    .card-title a {{ font-weight: 700; }}
    .card-meta {{ font-size: 13px; color: var(--muted); margin-bottom: 8px; }}

    .badge {{
      display: inline-block; padding: 2px 8px; border-radius: 12px;
      font-size: 12px; font-weight: 600; margin-right: 6px;
    }}
    .badge.high {{ background: var(--high-bg); color: var(--high); }}
    .badge.medium {{ background: var(--med-bg); color: var(--med); }}
    .badge.low {{ background: var(--low-bg); color: var(--low); }}

    .why-worth {{
      margin-top: 10px; padding: 10px 12px; background: #f6f8fa;
      border-radius: 6px; font-size: 14px; border-left: 2px solid var(--high);
    }}

    .brief-section {{ margin-bottom: 28px; }}
    .brief-section h3 {{ font-size: 18px; margin-bottom: 6px; }}
    .brief-topic {{
      padding: 16px; background: var(--card); border: 1px solid var(--border);
      border-radius: 6px; margin-bottom: 12px;
    }}
    .brief-topic .topic-name {{ font-size: 16px; font-weight: 700; }}
    .brief-topic .topic-who {{ font-size: 13px; color: var(--muted); }}
    .brief-topic .topic-sentiment {{ font-size: 13px; }}
    .brief-topic .topic-gist {{ margin-top: 8px; line-height: 1.65; }}

    .medium-merge-block {{
      background: var(--card); border: 1px solid var(--border); border-radius: 6px;
      padding: 20px; line-height: 1.75; white-space: pre-wrap;
    }}

    .author-list {{ display: grid; gap: 10px; }}
    .author-row {{
      background: var(--card); border: 1px solid var(--border); border-radius: 6px;
      padding: 12px 16px; display: flex; align-items: center; gap: 12px;
      cursor: pointer; transition: background 0.1s;
    }}
    .author-row:hover {{ background: #f6f8fa; }}
    .author-name {{ font-weight: 700; min-width: 130px; }}
    .author-stats {{ font-size: 13px; color: var(--muted); flex: 1; }}
    .author-tweets {{ display: none; padding: 12px 0 0; border-top: 1px solid var(--border); margin-top: 8px; }}
    .author-row.open .author-tweets {{ display: block; }}
    .author-tweet-item {{
      padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 14px;
      display: flex; align-items: baseline; gap: 8px;
    }}

    .empty-state {{ text-align: center; padding: 48px 20px; color: var(--muted); }}
    .warning-chip {{ color: var(--low); font-weight: 600; font-size: 12px; }}

    @media (max-width: 600px) {{
      .shell {{ padding: 12px 10px 40px; }}
      .card {{ padding: 14px; }}
      .nav-tab {{ font-size: 13px; padding: 8px 6px; }}
    }}
  </style>
</head>
<body>
<div class="shell">
  <div class="topbar">
    <div class="brand">📋 每日简报</div>
    <a class="archive-link" href="../archive/index.html">← 历史归档</a>
  </div>

  <h1 style="font-size:24px;margin-bottom:4px;">每日简报 · {_t(date)}</h1>
  <p style="color:var(--muted);margin-bottom:20px;font-size:14px;">
    共关注 {_t(total_authors)} 位博主 · {_t(active_authors)} 位有更新 · {_t(total)} 条推文 · 窗口 {_t(result.get('window','12h'))}
  </p>

  <nav class="nav-tabs" id="nav">
    <button class="nav-tab active" data-panel="brief">日报<span class="count"> · {_t(len(daily_brief))}话题</span></button>
    <button class="nav-tab" data-panel="high">高<span class="count"> · {_t(len(high_items))}</span></button>
    <button class="nav-tab" data-panel="medium">中<span class="count"> · {_t(len(medium_items))}</span></button>
    <button class="nav-tab" data-panel="low">低<span class="count"> · {_t(len(low_items))}</span></button>
    <button class="nav-tab" data-panel="authors">按博主</button>
  </nav>

  <!-- 日报 -->
  <div class="panel active" id="panel-brief">
{_render_brief(daily_brief, medium_merge, daily_brief)}
  </div>

  <!-- 高 -->
  <div class="panel" id="panel-high">
{_render_quality_list(high_items, "高", "本期没有高价值内容")}
  </div>

  <!-- 中 -->
  <div class="panel" id="panel-medium">
{_render_quality_list(medium_items, "中", "本期没有中等价值内容")}
  </div>

  <!-- 低 -->
  <div class="panel" id="panel-low">
{_render_quality_list(low_items, "低", "")}
  </div>

  <!-- 按博主 -->
  <div class="panel" id="panel-authors">
{_render_authors(author_profiles, items)}
  </div>

</div>

<script>
(function() {{
  var nav = document.getElementById('nav');
  var panels = document.querySelectorAll('.panel');
  var tabs = document.querySelectorAll('.nav-tab');

  function switchTo(name) {{
    panels.forEach(function(p) {{ p.classList.remove('active'); }});
    tabs.forEach(function(t) {{ t.classList.remove('active'); }});
    var target = document.getElementById('panel-' + name);
    if (target) target.classList.add('active');
    var tab = nav.querySelector('[data-panel="' + name + '"]');
    if (tab) tab.classList.add('active');
    window.location.hash = name;
  }}

  nav.addEventListener('click', function(e) {{
    var btn = e.target.closest('button');
    if (!btn) return;
    var panel = btn.getAttribute('data-panel');
    if (panel) switchTo(panel);
  }});

  // Author expand/collapse
  document.querySelectorAll('.author-row').forEach(function(row) {{
    row.addEventListener('click', function() {{
      this.classList.toggle('open');
    }});
  }});

  // Restore from hash
  var hash = window.location.hash.replace('#', '');
  if (hash) {{ switchTo(hash); }}
}})();
</script>
</body>
</html>"""


def _t(val: Any) -> str:
    return escape(str(val or ""))


def _render_brief(daily_brief: list, medium_merge: str, brief_items: list) -> str:
    parts = []
    if daily_brief:
        parts.append('<div class="brief-section"><h2 style="margin-bottom:16px;">📰 今日话题</h2>')
        for bp in daily_brief:
            sentiment = bp.get("sentiment", "")
            sentiment_emoji = {"乐观": "🟢", "观望": "🟡", "担忧": "🔴", "吐槽": "😤", "中性": "⚪"}.get(sentiment, "")
            what_they_said = bp.get("what_they_said", "")
            gist = bp.get("gist", "")
            if not gist or not gist.strip():
                continue  # 跳过空洞话题
            parts.append(f"""<div class="brief-topic">
  <div class="topic-name">{_t(bp.get('topic',''))}</div>
  <div class="topic-sentiment">{sentiment_emoji} 总体态度: {_t(sentiment)}</div>
  <div class="topic-gist">{_t(gist)}</div>""")
            if what_they_said:
                parts.append(f'  <div class="topic-who" style="margin-top:8px;color:var(--muted);font-size:14px;">各博主观点: {_t(what_they_said)}</div>')
            parts.append('</div>')
        parts.append('</div>')

    if medium_merge:
        parts.append(f"""<div class="brief-section">
<h3>📝 中等价值内容摘要</h3>
<div class="medium-merge-block">{_t(medium_merge)}</div>
</div>""")
    elif not daily_brief:
        parts.append('<div class="empty-state">本期没有足够信息生成日报</div>')

    return "\n".join(parts)


def _render_quality_list(items: list, level: str, empty_msg: str) -> str:
    if not items:
        if empty_msg:
            return f'<div class="empty-state">{empty_msg}</div>'
        return '<div class="empty-state">—</div>'

    cards = []
    level_cn = {"高": "高价值", "中": "中等价值", "低": "低价值"}.get(level, level)
    css_level = {"高": "high", "中": "medium", "低": "low"}.get(level, "low")

    for item in items:
        author = item.get("author", "")
        display = item.get("display_name") or author
        url = item.get("url", "")
        summary = item.get("summary", "")
        why_worth = item.get("why_worth", "")
        meta = format_meta(item)

        card = f"""<div class="card {css_level}">
  <div class="card-title"><a href="{_t(url)}" target="_blank" rel="noopener">{_t(display)} (@{_t(author)}) · 原文链接</a></div>
  <div class="card-meta"><span class="badge {css_level}">{_t(level_cn)}</span> {_t(item.get('published_at','')[:16])}{' · ' + _t(meta) if meta else ''}</div>
  <p>{_t(summary)}</p>"""

        if level == "高" and why_worth:
            card += f'\n  <div class="why-worth">💡 为什么值得关注：{_t(why_worth)}</div>'

        elif level == "低":
            card += f'\n  <div class="why-worth" style="border-left-color:var(--low);">不看原因：{_t(summary)}</div>'

        card += '\n</div>'
        cards.append(card)

    return "\n".join(cards)


def _render_authors(profiles: list, items: list) -> str:
    if not profiles and not items:
        return '<div class="empty-state">没有博主数据</div>'

    # Build author→tweets map from items
    by_author: dict[str, list] = {}
    for item in items:
        author = item.get("author", "")
        by_author.setdefault(author, []).append(item)

    # If no profiles, build them from items
    if not profiles:
        for author, tweets in by_author.items():
            quals = [t.get("importance", "低") for t in tweets]
            quality = "高" if "高" in quals else "中" if "中" in quals else "低"
            profiles.append({
                "author": author,
                "tweet_count": len(tweets),
                "quality": quality,
                "one_liner": "",
            })

    rows = []
    for p in profiles:
        author = p.get("author", "")
        display = p.get("display_name", "") or author
        tweets = by_author.get(author, [])
        count = p.get("tweet_count", len(tweets))
        quality = p.get("quality", "")
        one_liner = p.get("one_liner", "")
        quality_badge = {"高": "badge high", "中": "badge medium", "低": "badge low"}.get(quality, "badge")
        has_high = any(t.get("importance") == "高" for t in tweets)
        all_low = all(t.get("importance") == "低" for t in tweets) and len(tweets) >= 2
        follower_count = tweets[0].get("followers", 0) if tweets else 0
        follower_str = f"{_compact(follower_count)} 粉丝" if follower_count else ""

        tweet_items = ""
        for t in tweets:
            imp = t.get("importance", "")
            imp_badge = {"高": "badge high", "中": "badge medium", "低": "badge low"}.get(imp, "badge")
            tweet_items += f"""<div class="author-tweet-item">
  <span class="{imp_badge}">{_t(imp)}</span>
  <a href="{_t(t.get('url',''))}" target="_blank" rel="noopener">{_t(t.get('summary', '无摘要')[:80])}</a>
</div>"""

        warning = ""
        if all_low:
            warning = ' <span class="warning-chip">⚠ 长期低质量，考虑取关</span>'

        rows.append(f"""<div class="author-row">
  <div class="author-name">{_t(display)} (@{_t(author)}){warning}</div>
  <div class="author-stats">
    <span class="{quality_badge}">{_t(quality)}</span>
    {_t(follower_str)} · 今日 {_t(count)} 条 · {_t(one_liner)}
  </div>
  <div class="author-tweets">{tweet_items or '<div style="padding:8px;color:var(--muted);">今日无推文数据</div>'}</div>
</div>""")

    return '<div class="author-list">' + "\n".join(rows) + "</div>"


def render_v2_index(history: list[dict]) -> str:
    """渲染历史归档索引页。

    history entries: {date, run, path, total_tweets, label}
    """
    items_html = ""
    if history:
        current_date = ""
        for h in history:
            date = h.get("date", "")
            run = h.get("run", "")
            path = h.get("path", "")
            label = h.get("label", "")
            count = h.get("total_tweets", 0)
            if date != current_date:
                if current_date:
                    items_html += '</ul></div>'
                current_date = date
                items_html += f'<div style="margin-bottom:16px;"><h3 style="margin-bottom:6px;">{_t(date)}</h3><ul style="margin:0;padding-left:18px;">'
            run_label = f" · {_t(label)}" if label else ""
            items_html += f"""<li style="margin-bottom:4px;">
  <a href="{_t(path)}">{_t(run)}</a>{run_label}
  <span style="color:var(--muted);font-size:13px;">— {_t(count)} 条</span>
</li>"""
        items_html += '</ul></div>'
    else:
        items_html = '<div class="empty-state">暂无历史记录</div>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>历史归档 · 每日简报</title>
  <style>
    :root {{
      --bg: #f6f8fa; --card: #ffffff; --text: #1f2328;
      --muted: #656d76; --border: #d0d7de; --link: #0969da;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
      line-height: 1.6; padding: 40px 20px;
    }}
    main {{ max-width: 700px; margin: 0 auto; }}
    h1 {{ font-size: 28px; margin-bottom: 8px; }}
    .card {{
      background: var(--card); border: 1px solid var(--border); border-radius: 6px;
      padding: 24px; margin-top: 20px;
    }}
    ul {{ list-style: none; }}
    a {{ color: var(--link); text-decoration: none; font-size: 16px; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
<main>
  <h1>📋 历史归档</h1>
  <p style="color:var(--muted);margin-bottom:8px;">点击日期查看当天的每日简报</p>
  <div class="card">
    <ul>{items_html}</ul>
  </div>
</main>
</body>
</html>"""
