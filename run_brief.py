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
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from koc.archive import build_archive_history, next_run_dir
from koc.enrich import enrich_all
from koc.llm import LlmClient
from koc.reader import Reader
from koc.robust_scanner import RobustScanner
from koc.scanner_config import scanner_config_from_env
from koc.schedule import BEIJING, format_beijing, resolve_report_window
from koc.v2_pipeline import V2Pipeline
from koc.watchlist import load_authors, load_schedule
from koc.dedupe import dedupe_items, SeenStore
from koc.memory import MemoryLayer
from build_page import (
    TEMPLATE,
    calendar_days_from_history,
    extract_css,
    render_calendar_page,
    render_editorial_report,
)

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
WATCHLIST_PATH = os.getenv("WATCHLIST_FILE", "watchlist.txt")
SCHEDULE_PATH = os.getenv("SCHEDULE_FILE", "config/schedule.json")
ENABLE_ENRICH = os.getenv("ENABLE_ENRICH", "0") == "1"


def main(
    output_dir: str | Path | None = None,
    watchlist_path: str | None = None,
    schedule_path: str | None = None,
) -> int:
    output_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    watchlist_path = watchlist_path or WATCHLIST_PATH
    schedule_path = schedule_path or SCHEDULE_PATH
    started_at = datetime.now(timezone.utc)
    report_window = resolve_report_window(started_at)
    print(f"[brief] 读取关注列表: {watchlist_path}", flush=True)
    authors = load_authors(watchlist_path)
    schedule = load_schedule(schedule_path)
    window = str(schedule.get("window") or "12h")

    print(
        "[brief] 时间窗口: "
        f"{report_window.label} {format_beijing(report_window.window_start)}"
        f" - {format_beijing(report_window.window_end)}",
        flush=True,
    )
    print(f"[brief] 计划时间: {format_beijing(report_window.planned_at)}", flush=True)
    print(f"[brief] 关注博主: {len(authors)} 个", flush=True)

    scanner_config = scanner_config_from_env(os.environ)
    print(
        "[brief] 扫描参数: "
        f"timeout={scanner_config.timeout}s, "
        f"retries={scanner_config.max_retries}, "
        f"workers={scanner_config.max_workers}",
        flush=True,
    )
    scanner = RobustScanner(
        timeout=scanner_config.timeout,
        max_retries=scanner_config.max_retries,
        request_delay=scanner_config.request_delay,
    )
    reader = Reader(prefer_rss_summary=False, request_delay_seconds=0.3)

    all_items: list[dict] = []
    scan_ok = 0
    scan_no_posts_in_window = 0
    scan_empty_all_instances = 0
    scan_fail = 0
    scan_time_uncertain = 0
    reader_fail = 0
    reader_fallback = 0
    scan_errors: list[dict[str, str]] = []
    scan_accounts: list[dict] = []
    source_instances: dict[str, int] = {}
    t_start = time.time()

    scan_max_workers = min(scanner_config.max_workers, len(authors))

    def scan_one(author: str) -> dict:
        try:
            result = scanner.scan_user(
                author,
                window=window,
                now=report_window.window_end,
                window_start=report_window.window_start,
                window_end=report_window.window_end,
            )
            out: dict = {"author": author, "items": [], "error": None}
            reader_statuses: dict[str, int] = {}
            for item in result.items:
                fetched = reader.fetch_item(item)
                reader_statuses[fetched.fetch_status] = reader_statuses.get(fetched.fetch_status, 0) + 1
                content = fetched.content_markdown or ""
                if not content and fetched.rss_summary:
                    content = fetched.rss_summary
                if not content:
                    continue
                out["items"].append({
                    "username": author,
                    "url": fetched.url,
                    "content_markdown": content,
                    "published_at": fetched.published_at or "",
                    "rss_summary": fetched.rss_summary or "",
                })
            if result.errors:
                out["error"] = result.errors[0].message[:80]
            out["debug"] = {
                **result.debug,
                "discovered_items": len(result.items),
                "usable_items": len(out["items"]),
                "source_url": result.source_url,
                "reader_statuses": reader_statuses,
            }
            if result.items and not out["items"] and not out["error"]:
                out["error"] = "reader failed for every discovered item"
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
            count = len(out["items"])
            error = out.get("error")
            debug = out.get("debug") or {}
            discovery_status = debug.get("discovery_status") or (
                "updates_found" if count else "no_posts_in_window"
            )
            source_url = str(debug.get("source_url") or "")
            if source_url:
                source_instance = (
                    source_url.split("/", 3)[2] if "://" in source_url else source_url
                )
                source_instances[source_instance] = source_instances.get(source_instance, 0) + 1
            reader_statuses = debug.get("reader_statuses") or {}
            reader_fail += int(reader_statuses.get("failed", 0))
            reader_fallback += int(reader_statuses.get("fallback", 0))
            scan_time_uncertain += int(debug.get("time_uncertain", 0))
            scan_accounts.append({
                "author": author,
                "status": "failed" if error else discovery_status,
                "source_url": source_url,
                "feed_items": int(debug.get("rss_items_found", 0)),
                "inside_window": int(debug.get("inside_window", 0)),
                "outside_window": int(debug.get("outside_window", 0)),
                "time_uncertain": int(debug.get("time_uncertain", 0)),
                "usable_items": count,
                "reader_statuses": reader_statuses,
                "instance_attempts": debug.get("instance_attempts") or [],
                "error": str(error or ""),
            })
            if error:
                scan_fail += 1
                scan_errors.append({"author": author, "error": str(error)})
                print(f"[brief] [{done}/{len(authors)}] @{author} ❌ {error[:50]} | {elapsed:.0f}s eta {eta:.0f}s", flush=True)
            elif count == 0:
                if discovery_status == "empty_all_instances":
                    scan_empty_all_instances += 1
                    label = "所有实例空feed"
                else:
                    scan_no_posts_in_window += 1
                    label = "窗口内无帖"
                print(f"[brief] [{done}/{len(authors)}] @{author} {label} | {elapsed:.0f}s eta {eta:.0f}s", flush=True)
            else:
                scan_ok += 1
                all_items.extend(out["items"])
                print(f"[brief] [{done}/{len(authors)}] @{author} {count}条 | 累计{len(all_items)}条 | {elapsed:.0f}s eta {eta:.0f}s", flush=True)

    if not all_items:
        print("[brief] 没有抓取到任何推文，退出", flush=True)
        if scan_errors:
            error_summary = "; ".join(f"@{e['author']}: {e['error']}" for e in scan_errors[:5])
            print(f"[brief] 错误摘要: {error_summary}", flush=True)
        return 1

    print(
        "[brief] 扫描完成: "
        f"{scan_ok} 有内容 / {scan_no_posts_in_window} 窗口内无帖 / "
        f"{scan_empty_all_instances} 空feed / {scan_fail} 失败",
        flush=True,
    )
    t_scan_end = time.time()
    active_authors = len(set(item["username"] for item in all_items))
    print(f"[brief] 共 {len(all_items)} 条推文，{active_authors}/{len(authors)} 位博主有更新", flush=True)

    # ── 去重：窗口内 + 跨窗口（线上 V2 原本无去重，导致重复抓取） ──
    unique_items, dup_in = dedupe_items(all_items)
    seen_store = SeenStore(output_dir / "state" / "seen.json")
    if seen_store.errors:
        print(f"[brief] ⚠ 状态文件: {seen_store.errors[0]}", flush=True)
    unique_items, dup_cross = seen_store.filter_new(unique_items)
    print(f"[brief] 去重: 窗口内剔除 {dup_in} · 跨窗口剔除 {dup_cross} · 净新 {len(unique_items)}", flush=True)
    if not unique_items:
        print("[brief] 去重后无新内容，退出", flush=True)
        return 1
    all_items = unique_items

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
    # 记忆层：读上期判断让话题有连续性，跑完存新判断
    memory = MemoryLayer(output_dir / "state" / "memory.json")
    if memory.errors:
        print(f"[brief] ⚠ 记忆层: {memory.errors[0]}", flush=True)
    result = pipeline.run(all_items, memory_refs=memory.recent_context())
    print(f"[brief] AI分析完成 ({time.time() - t3:.0f}s) — 高{result.high_count} / 中{result.medium_count} / 低{result.low_count}", flush=True)

    if not result.publishable:
        failure_dir = output_dir / "failed"
        failure_dir.mkdir(parents=True, exist_ok=True)
        failure_path = failure_dir / f"{result.run_id or 'unknown-run'}.json"
        _atomic_write_text(
            failure_path,
            json.dumps(
                {
                    "run_id": result.run_id,
                    "status": "failed",
                    "total_tweets": result.total_tweets,
                    "authors_count": result.authors_count,
                    "stage_status": result.stage_status,
                    "stage_elapsed_seconds": result.stage_elapsed_seconds,
                    "quality_gate": result.quality_gate,
                    "errors": result.errors or [f"pipeline status: {result.status}"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        print(f"[brief] AI分析未通过，诊断已写入: {failure_path}", flush=True)
        return 1

    # Build run label — always Beijing time
    finished_at = datetime.now(timezone.utc)
    beijing_now = finished_at.astimezone(BEIJING)
    local_time_str = beijing_now.strftime("%m-%d %H:%M")
    time_str = beijing_now.strftime("%H:%M")
    date_str = report_window.planned_at.astimezone(BEIJING).strftime("%Y-%m-%d")

    archive_dir = output_dir / "archive"
    date_dir = archive_dir / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    run_num, run_dir = next_run_dir(date_dir)
    run_dir.mkdir(parents=True, exist_ok=False)

    run_label = f"{local_time_str} · 第{run_num}次更新"
    run_date_label = f"{date_str} {time_str} · 第{run_num}次更新"

    memory_diff = memory.preview_diff(result.daily_brief)
    run_dict = {
        "run_id": result.run_id,
        "status": "success",
        "slot": report_window.slot,
        "slot_label": report_window.label,
        "created_at": run_date_label,
        "window": window,
        "planned_at": format_beijing(report_window.planned_at),
        "started_at": format_beijing(started_at),
        "finished_at": format_beijing(finished_at),
        "window_start": format_beijing(report_window.window_start),
        "window_end": format_beijing(report_window.window_end),
        "delay_seconds": report_window.delay_seconds,
        "elapsed_seconds": round(time.time() - t_start, 1),
        "total_tweets": result.total_tweets,
        "authors_count": result.authors_count,
        "total_authors": len(authors),
        "dup_in_window": dup_in,
        "dup_cross": dup_cross,
        "high_count": result.high_count,
        "medium_count": result.medium_count,
        "low_count": result.low_count,
        "scan_ok": scan_ok,
        "scan_no_posts_in_window": scan_no_posts_in_window,
        "scan_empty_all_instances": scan_empty_all_instances,
        "scan_fail": scan_fail,
        "scan_time_uncertain": scan_time_uncertain,
        "reader_fail": reader_fail,
        "reader_fallback": reader_fallback,
        "engagement_status": "enabled" if ENABLE_ENRICH else "disabled",
        "source_instances": source_instances,
        "scan_accounts": scan_accounts,
        "scan_elapsed": round(t_scan_end - t_start, 1),
        "scan_errors": scan_errors,
        "items": result.items,
        "daily_brief": result.daily_brief,
        "author_profiles": result.author_profiles,
        "medium_merge": result.medium_merge,
        "errors": result.errors,
        "stage_status": result.stage_status,
        "stage_elapsed_seconds": result.stage_elapsed_seconds,
        "quality_gate": result.quality_gate,
        "no_material_events": result.no_material_events,
        "memory_diff": memory_diff,
    }

    editorial_css = extract_css(TEMPLATE)
    html = render_editorial_report(
        run_dict,
        editorial_css,
        archive_href="../../index.html",
        archive_date=date_str,
        archive_run=f"run-{run_num}",
    )

    _atomic_write_text(run_dir / "report.html", html)
    _atomic_write_text(
        run_dir / "run.json",
        json.dumps(run_dict, ensure_ascii=False, indent=2),
    )

    root_html = render_editorial_report(
        run_dict,
        editorial_css,
        archive_href="archive/index.html",
        archive_date=date_str,
        archive_run=f"run-{run_num}",
    )
    _atomic_write_text(output_dir / "index.html", root_html)

    # .nojekyll for GitHub Pages
    _atomic_write_text(output_dir / ".nojekyll", "")

    # Regenerate archive index
    history = build_archive_history(archive_dir)
    calendar_days = calendar_days_from_history(history)
    _atomic_write_text(
        archive_dir / "index.html",
        render_calendar_page(calendar_days, editorial_css),
    )

    # Only accepted, fully-written reports advance durable state. If state saving
    # fails, the next run may repeat content but will not silently lose it.
    for event in result.daily_brief:
        memory.update_event(event)
    memory.save()
    seen_store.mark_seen(unique_items)
    seen_store.save()

    elapsed_total = time.time() - t_start
    print(f"[brief] 完成 ({elapsed_total:.0f}s)", flush=True)
    print(f"  主页: {output_dir / 'index.html'}", flush=True)
    print(f"  运行: {run_dir}", flush=True)
    print(f"  归档: {archive_dir / 'index.html'}", flush=True)
    return 0


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, path)

if __name__ == "__main__":
    raise SystemExit(main())
