from __future__ import annotations

import json
from pathlib import Path
from typing import Any


WATCHLIST_CONFIG = Path("watchlist.txt")
SCHEDULE_CONFIG = Path("config/schedule.json")

DEFAULT_SCHEDULE: dict[str, Any] = {
    "interval_minutes": 360,
    "window": "12h",
}


def load_authors(path: str | Path = WATCHLIST_CONFIG) -> list[str]:
    """Read a plain-text watchlist file, one @username per line."""
    authors = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name = line.strip().lstrip("@")
        if name:
            authors.append(name)
    if not authors:
        raise ValueError(f"watchlist file {path} is empty — add at least one username")
    return authors


def load_schedule(path: str | Path = SCHEDULE_CONFIG) -> dict[str, Any]:
    """Load schedule config, returning defaults if the file is missing."""
    config_path = Path(path)
    if not config_path.exists():
        return dict(DEFAULT_SCHEDULE)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return dict(DEFAULT_SCHEDULE)
    merged = dict(DEFAULT_SCHEDULE)
    merged.update({k: v for k, v in data.items() if k in merged})
    return merged
