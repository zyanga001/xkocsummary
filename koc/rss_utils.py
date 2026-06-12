from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree


def parse_window(value: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([hd])", value.strip().lower())
    if not match:
        raise ValueError("window must look like '12h' or '2d'")
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        raise ValueError("window must be positive")
    return timedelta(hours=amount) if unit == "h" else timedelta(days=amount)


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def extract_tweet_id(url: str) -> str | None:
    match = re.search(r"/status(?:es)?/(\d+)", url)
    return match.group(1) if match else None


def text_of(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()
