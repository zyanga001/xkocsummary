from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


RUN_DIR_RE = re.compile(r"^run-(\d+)$")


def run_number(path: Path) -> int:
    match = RUN_DIR_RE.match(path.name)
    if not match:
        return 0
    return int(match.group(1))


def next_run_dir(date_dir: Path) -> tuple[int, Path]:
    date_dir.mkdir(parents=True, exist_ok=True)
    existing_numbers = [
        run_number(entry)
        for entry in date_dir.iterdir()
        if entry.is_dir() and run_number(entry) > 0
    ]
    next_num = max(existing_numbers, default=0) + 1
    return next_num, date_dir / f"run-{next_num}"


def build_archive_history(archive_dir: Path) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    if not archive_dir.exists():
        return history

    for date_entry in sorted(archive_dir.iterdir(), reverse=True):
        if not date_entry.is_dir():
            continue
        runs = sorted(
            [
                entry
                for entry in date_entry.iterdir()
                if entry.is_dir() and run_number(entry) > 0
            ],
            key=run_number,
            reverse=True,
        )
        for run_dir in runs:
            run_json = run_dir / "run.json"
            total = 0
            label = ""
            if run_json.exists():
                try:
                    data = json.loads(run_json.read_text(encoding="utf-8"))
                    total = int(data.get("total_tweets", 0) or 0)
                    label = str(data.get("created_at", ""))
                except Exception:
                    pass
            number = run_number(run_dir)
            history.append({
                "date": date_entry.name,
                "run": f"{date_entry.name} 第{number}次更新",
                "path": f"{date_entry.name}/{run_dir.name}/report.html",
                "total_tweets": total,
                "label": label,
            })
    return history
