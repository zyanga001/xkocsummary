#!/usr/bin/env python3
"""DAZA Brief — standalone entry point for GitHub Actions deployment.

Reads watchlist.txt and config/schedule.json, runs the V2 pipeline,
and writes output to output/ with archive/YYYY-MM-DD/run-N/ structure.

Usage:
    python run_brief.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from koc.enrich import enrich_all
from koc.llm import LlmClient
from koc.reader import Reader
from koc.robust_scanner import RobustScanner
from koc.v2_pipeline import V2Pipeline
from koc.v2_report import render_v2_report, render_v2_index
from koc.watchlist import load_authors, load_schedule

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
WATCHLIST_PATH = os.getenv("WATCHLIST_FILE", "watchlist.txt")
SCHEDULE_PATH = os.getenv("SCHEDULE_FILE", "config/schedule.json")
ENABLE_ENRICH = os.getenv("ENABLE_ENRICH", "0") == "1"
BEIJING = timezone(timedelta(hours=8))


def _beijing_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(BEIJING)


def main() -> int:
    print(f"[brief] 读取关注列表: {WATCHLIST_PATH}", flush=True)
    authors = load_authors(WATCHLIST_PATH)
    schedule = load_schedule(SCHEDULE_PATH)
    window = str(schedule.get("window") or "12h")

    print(f"[brief] 时间窗口: 过去 {window}", flush=True)
    print(f"[brief] 关注博主: {len(authors)} 个", flush=True)

    scanner = RobustScanner(timeout=15, max_retries=3, request_delay=0.3)
    reader = Reader(prefer_rss_summary=True, request_delay_seconds=0.3)

    all_items: list[dict] = []
    scan_ok = 0
    scan_empty = 0
    scan_fail = 0
    scan_errors: list[str] = []
    t_start = time.time()

    scan_max_workers = min(4, len(authors))
    now_ts = datetime.now(timezone.utc)

    def scan_one(author: str) -> dict:
        try:
            result = scanner.scan_user(author, window=window, now=now_ts)
            out: dict = {"author": author, "items": [], "error": None}
            for item in result.items:
                fetched = reader.fetch_item(item)
                content = fetched.content_markdown or ""
                if not content and fetched.rss_summary:
                    content = fetched.rss_summary
                out["items"].append({
                    "username": author,
                    "url": fetched.url,
                    "content_markdown": content,
                    "published_at": fetched.published_at or "",
                    "rss_summary": fetched.rss_summary or "",
                })
            if result.errors:
                out["error"] = result.errors[0].message[:80]
            out["debug"] = {"items": len(result.items)}
            return out
        except Exception as exc:
            return {"author": author, "items": [], "error": f"{exc.__class__.__name__}: {str(exc)[:60]}", "debug": {"items": 0}}

    done = 0
    with ThreadPoolExecutor(max_workers=scan_max_workers) as pool:
        futures = {pool.submit(scan_one, a): a for a in authors}
        for future in as_completed(futures):
            try:
                out = future.result()
            except Exception:
                out = {"author": futures[future], "items": [], "error": "future failed", "debug": {"items": 0}}
            done += 1
            elapsed = time.time() - t_start
            avg_per = elapsed / done if done > 0 else 0
            eta = avg_per * (len(authors) - done)
            author = out["author"]
            count = out["debug"]["items"]
            error = out.get("error")
            if error:
                scan_fail += 1
                scan_errors.append(f"@{author}: {error}")
                print(f"[brief] [{done}/{len(authors)}] @{author} ❌ {error[:50]} | {elapsed:.0f}s eta {eta:.0f}s", flush=True)
            elif count == 0:
                scan_empty += 1
                print(f"[brief] [{done}/{len(authors)}] @{author} 0条 | {elapsed:.0f}s eta {eta:.0f}s", flush=True)
            else:
                scan_ok += 1
                all_items.extend(out["items"])
                print(f"[brief] [{done}/{len(authors)}] @{author} {count}条 | 累计{len(all_items)}条 | {elapsed:.0f}s eta {eta:.0f}s", flush=True)

    if not all_items:
        print("[brief] 没有抓取到任何推文，退出", flush=True)
        if scan_errors:
            print(f"[brief] 错误摘要: {'; '.join(scan_errors[:5])}", flush=True)
        return 1

    print(f"[brief] 扫描完成: {scan_ok} OK / {scan_empty} 无更新 / {scan_fail} 失败", flush=True)
    active_authors = len(set(item["username"] for item in all_items))
    print(f"[brief] 共 {len(all_items)} 条推文，{active_authors}/{len(authors)} 位博主有更新", flush=True)

    t2 = time.time()
    if ENABLE_ENRICH:
        print("[brief] 获取博主信息和互动数据...", flush=True)
        all_items = enrich_all(all_items)
        print(f"[brief] 数据获取完成 ({time.time() - t2:.0f}s)", flush=True)
    else:
        print("[brief] 跳过 enrich（ENABLE_ENRICH=0），节省 ~15-20 分钟", flush=True)

    print("[brief] 阶段1: 质量分类...", flush=True)
    t3 = time.time()
    pipeline = V2Pipeline()
    result = pipeline.run(all_items)
    print(f"[brief] AI分析完成 ({time.time() - t3:.0f}s) — 高{result.high_count} / 中{result.medium_count} / 低{result.low_count}", flush=True)

    # Build run label — always Beijing time
    beijing_now = _beijing_now()
    local_time_str = beijing_now.strftime("%m-%d %H:%M")
    date_str = beijing_now.strftime("%Y-%m-%d")

    archive_dir = OUTPUT_DIR / "archive"
    date_dir = archive_dir / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(
        [d for d in date_dir.iterdir() if d.is_dir() and d.name.startswith("run-")],
        key=lambda d: d.name,
    )
    run_num = len(existing) + 1
    run_dir = date_dir / f"run-{run_num}"
    run_dir.mkdir(parents=True, exist_ok=False)

    run_label = f"{local_time_str} · 第{run_num}次更新"
    run_date_label = f"{date_str} {local_time_str} · 第{run_num}次更新"

    run_dict = {
        "run_id": result.run_id,
        "created_at": run_date_label,
        "window": window,
        "total_tweets": result.total_tweets,
        "authors_count": result.authors_count,
        "total_authors": len(authors),
        "high_count": result.high_count,
        "medium_count": result.medium_count,
        "low_count": result.low_count,
        "scan_ok": scan_ok,
        "scan_empty": scan_empty,
        "scan_fail": scan_fail,
        "scan_elapsed": time.time() - t_start,
        "items": result.items,
        "daily_brief": result.daily_brief,
        "author_profiles": result.author_profiles,
        "medium_merge": result.medium_merge,
        "errors": result.errors,
    }

    html = render_v2_report(run_dict, run_label=run_label, page_depth=3)

    (run_dir / "report.html").write_text(html, encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps(run_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Root index.html — same report but link depth is 1 (site root), not 3 (archive/date/run/)
    root_html = render_v2_report(run_dict, run_label=run_label, page_depth=1)
    (OUTPUT_DIR / "index.html").write_text(root_html, encoding="utf-8")

    # .nojekyll for GitHub Pages
    (OUTPUT_DIR / ".nojekyll").write_text("")

    # Regenerate archive index
    history = _build_archive_history(archive_dir)
    (archive_dir / "index.html").write_text(
        render_v2_index(history), encoding="utf-8"
    )

    elapsed_total = time.time() - t_start
    print(f"[brief] 完成 ({elapsed_total:.0f}s)", flush=True)
    print(f"  主页: {OUTPUT_DIR / 'index.html'}", flush=True)
    print(f"  运行: {run_dir}", flush=True)
    print(f"  归档: {archive_dir / 'index.html'}", flush=True)
    return 0


def _build_archive_history(archive_dir: Path) -> list[dict]:
    history: list[dict] = []
    if not archive_dir.exists():
        return history
    for date_entry in sorted(archive_dir.iterdir(), reverse=True):
        if not date_entry.is_dir():
            continue
        runs = sorted(
            [d for d in date_entry.iterdir() if d.is_dir() and d.name.startswith("run-")],
            key=lambda d: d.name,
            reverse=True,
        )
        for run_index, run_dir in enumerate(runs):
            run_json = run_dir / "run.json"
            total = 0
            label = ""
            if run_json.exists():
                try:
                    data = json.loads(run_json.read_text(encoding="utf-8"))
                    total = data.get("total_tweets", 0)
                    label = str(data.get("created_at", ""))
                except Exception:
                    pass
            history.append({
                "date": date_entry.name,
                "run": f"{date_entry.name} 第{run_index+1}次更新",
                "path": f"archive/{date_entry.name}/{run_dir.name}/report.html",
                "total_tweets": total,
                "label": label,
            })
    return history


if __name__ == "__main__":
    raise SystemExit(main())
