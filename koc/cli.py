from __future__ import annotations

import argparse
import json as json_module
import os
import sys
import time
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))


def _beijing_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(BEIJING)
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from .enrich import enrich_all
from .llm import LlmClient
from .output import Progress
from .reader import Reader
from .robust_scanner import RobustScanner
from .v2_eval import run_eval
from .v2_pipeline import V2Pipeline
from .v2_report import render_v2_report, render_v2_index
from .watchlist import load_authors, load_schedule


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m koc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_v2 = subparsers.add_parser("run-v2", help="Run V2 pipeline and generate 4-segment report")
    run_v2.add_argument("--watchlist", default="watchlist.txt")
    run_v2.add_argument("--output", default="output")
    run_v2.add_argument("--schedule", default="config/schedule.json")
    run_v2.add_argument("--format", choices=("human", "json"), default="human")
    run_v2.set_defaults(func=command_run_v2)

    eval_v2 = subparsers.add_parser("eval-v2", help="Compare AI quality labels against human evaluations")
    eval_v2.add_argument("--watchlist", default="watchlist.txt")
    eval_v2.add_argument("--golden", default="eval/data/评价结果.csv")
    eval_v2.add_argument("--output", default="data/v2")
    eval_v2.add_argument("--format", choices=("human", "json"), default="human")
    eval_v2.set_defaults(func=command_eval_v2)

    return parser


def command_run_v2(args: argparse.Namespace) -> int:
    progress = Progress("v2-run", enabled=args.format == "human")

    authors = load_authors(args.watchlist)
    schedule = load_schedule(args.schedule)
    window = str(schedule.get("window") or "12h")

    progress.log(f"时间窗口：过去 {window}")
    progress.log(f"关注博主：{len(authors)} 个")

    scanner = RobustScanner(
        timeout=15,
        max_retries=3,
        request_delay=0.3,
        log_fn=lambda msg: progress.log(msg),
    )
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
                    "正文": content,
                    "发布时间": fetched.published_at or "",
                    "content_markdown": content,
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
                progress.log(f"[{done}/{len(authors)}] @{author} ❌ {error[:40]} | 已用{elapsed:.0f}s 剩余{eta:.0f}s")
            elif count == 0:
                scan_empty += 1
                progress.log(f"[{done}/{len(authors)}] @{author} 0条 | 已用{elapsed:.0f}s 剩余{eta:.0f}s")
            else:
                scan_ok += 1
                all_items.extend(out["items"])
                progress.log(f"[{done}/{len(authors)}] @{author} {count}条 | 累计{len(all_items)}条 | 已用{elapsed:.0f}s 剩余{eta:.0f}s")

    if not all_items:
        progress.log("没有抓取到任何推文，终止")
        if scan_errors:
            progress.log(f"扫描错误摘要: {'; '.join(scan_errors[:5])}")
        return 1

    progress.log(f"扫描完成：{scan_ok} OK / {scan_empty} 无更新 / {scan_fail} 失败")
    active_authors = len(set(item["username"] for item in all_items))
    progress.log(f"抓取完成：{len(all_items)} 条推文，来自 {active_authors}/{len(authors)} 位博主有更新")

    t2 = time.time()
    progress.log("正在获取博主信息和互动数据...")
    if os.environ.get("ENABLE_ENRICH", "0") == "1":
        all_items = enrich_all(all_items)
        progress.log(f"博主信息和互动数据获取完成 ({time.time() - t2:.0f}s)")
    else:
        progress.log("跳过 enrich（ENABLE_ENRICH=0），节省 ~15-20 分钟")

    progress.log("阶段1: 质量分类...")
    t3 = time.time()
    pipeline = V2Pipeline()
    result = pipeline.run(all_items)
    progress.log(f"阶段1完成 ({time.time() - t3:.0f}s)：高 {result.high_count} / 中 {result.medium_count} / 低 {result.low_count}")

    progress.log("阶段2: 聚合日报+博主画像...")
    progress.log("阶段3: 高价值深读...")
    progress.log(f"AI分析总耗时 {time.time() - t3:.0f}s")

    progress.log("生成HTML报告...")

    beijing_now = _beijing_now()
    local_time_str = beijing_now.strftime("%m-%d %H:%M")
    date_str = beijing_now.strftime("%Y-%m-%d")

    run_dict = {
        "run_id": result.run_id,
        "created_at": local_time_str,
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

    output_dir = Path(args.output)
    archive_dir = output_dir / "archive"
    date_dir = archive_dir / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(
        [d for d in date_dir.iterdir() if d.is_dir() and d.name.startswith("run-")],
        key=lambda d: d.name,
    )
    run_num = len(existing) + 1
    run_dir = date_dir / f"run-{run_num}"
    run_dir.mkdir(parents=True, exist_ok=False)

    run_label = f"{date_str} {local_time_str} · 第{run_num}次更新"

    html = render_v2_report(run_dict, run_label=run_label, page_depth=3)

    (run_dir / "report.html").write_text(html, encoding="utf-8")
    (run_dir / "run.json").write_text(
        json_module.dumps(run_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (output_dir / "index.html").write_text(
        render_v2_report(run_dict, run_label=run_label, page_depth=1), encoding="utf-8"
    )

    history = _build_archive_history(archive_dir)
    (archive_dir / "index.html").write_text(
        render_v2_index(history), encoding="utf-8"
    )

    progress.log(f"报告生成完成 ({time.time() - t_start:.0f}s)")
    print()
    print(f"共关注 {len(authors)} 位博主，{active_authors} 位有更新，共 {len(all_items)} 条推文")
    print(f"扫描: {scan_ok} OK / {scan_empty} 无更新 / {scan_fail} 失败")
    print(f"高 {result.high_count} / 中 {result.medium_count} / 低 {result.low_count}")
    if scan_errors:
        print(f"扫描异常: {'; '.join(scan_errors[:3])}")
    print()
    print("输出文件：")
    print(f"  本期报告: {run_dir}/report.html")
    print(f"  首页入口: {output_dir / 'index.html'}")
    print(f"  历史归档: {archive_dir}/index.html")

    return 0


def command_eval_v2(args: argparse.Namespace) -> int:
    progress = Progress("eval-v2", enabled=args.format == "human")
    progress.log(f"金色数据集: {args.golden}")
    progress.log(f"V2输出目录: {args.output}")

    results = run_eval(
        watchlist_path=args.watchlist,
        golden_path=args.golden,
        output_dir=args.output,
    )

    if args.format == "json":
        from .output import print_json
        print_json(results)
        return 0

    if "error" in results:
        print(f"\n错误: {results['error']}")
        return 1

    from .v2_eval import optimize_prompt
    suggestions = optimize_prompt(results)
    if suggestions:
        print()
        print("Prompt优化建议:")
        for s in suggestions:
            print(f"  {s}")

    return 0


def _build_archive_history(archive_dir: Path) -> list[dict]:
    history: list[dict] = []
    if not archive_dir.exists():
        return history
    for date_entry in sorted(archive_dir.iterdir(), reverse=True):
        if not date_entry.is_dir() or date_entry.name == "index.html":
            continue
        runs = sorted(
            [d for d in date_entry.iterdir() if d.is_dir() and d.name.startswith("run-")],
            key=lambda d: d.name,
            reverse=True,
        )
        for run_index, run_dir in enumerate(runs):
            run_json = run_dir / "run.json"
            total = 0
            if run_json.exists():
                try:
                    data = json_module.loads(run_json.read_text(encoding="utf-8"))
                    total = data.get("total_tweets", 0)
                except Exception:
                    pass
            history.append({
                "date": date_entry.name,
                "run": f"{date_entry.name} 第{run_index+1}次更新",
                "path": f"archive/{date_entry.name}/{run_dir.name}/report.html",
                "total_tweets": total,
                "label": _run_label_from_json(run_json),
            })
    return history


def _run_label_from_json(run_json: Path) -> str:
    if not run_json.exists():
        return ""
    try:
        data = json_module.loads(run_json.read_text(encoding="utf-8"))
        return str(data.get("created_at", ""))
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(
            json_module.dumps(
                {
                    "status": "failed",
                    "stage": "cli",
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                    "can_continue": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
