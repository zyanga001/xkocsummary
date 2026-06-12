"""增强版 Scanner：带超时控制、自动重试、滚动实例、进度输出。"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Callable

from .http import fetch_text as default_fetch_text
from .models import Failure, IntelligenceItem, ScanResult
from .rss_utils import parse_window, to_utc_iso, parse_pub_date, extract_tweet_id, text_of
from .url_normalizer import normalize_tweet_url


class RobustScanner:
    """带完整容错能力的扫描器。

    - 多实例滚动：优先nitter.net，失败自动切换
    - 超时控制：每个RSS请求最多 N 秒
    - 409/429/5xx 自动退避重试
    - 进度输出：每完成一个用户输出终端状态
    """

    INSTANCES = (
        "https://nitter.net",          # 主，最稳定
        "https://xcancel.com",          # 备选
        "https://nitter.poast.org",     # 备选2
        "https://nitter.privacydev.net", # 备选3
    )

    def __init__(
        self,
        fetch_text: Callable = default_fetch_text,
        timeout: int = 10,
        max_retries: int = 2,
        request_delay: float = 0.3,
        log_fn: Callable[[str], None] | None = None,
    ):
        self.fetch_text = fetch_text
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_delay = request_delay
        self.log = log_fn or (lambda msg: None)

    def scan_user(
        self,
        username: str,
        window: str = "12h",
        now: datetime | None = None,
    ) -> ScanResult:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        scan_from = now - parse_window(window)
        result = ScanResult(
            username=username,
            source_url="",
            window=window,
            scan_from=to_utc_iso(scan_from),
            scan_to=to_utc_iso(now),
            debug={"rss_items_found": 0, "inside_window": 0, "outside_window": 0, "time_uncertain": 0},
        )

        rss_items = None
        errors: list[str] = []
        used_instance = ""

        # 随机打乱实例顺序，把负载分散到多个 nitter 实例
        shuffled_instances = list(self.INSTANCES)
        random.shuffle(shuffled_instances)

        for instance in shuffled_instances:
            source_url = f"{instance.rstrip('/')}/{username}/rss"
            for attempt in range(self.max_retries + 1):
                try:
                    rss_text = self.fetch_text(source_url, self.timeout)
                    items = self._parse_rss_items(rss_text)
                    if self._is_blocked_feed(items):
                        errors.append(f"{source_url}: blocked (whitelist required)")
                        break  # 这个实例封了，切下一个
                    rss_items = items
                    used_instance = source_url
                    break
                except Exception as exc:
                    err_msg = str(exc)[:100]
                    err_lower = err_msg.lower()
                    is_perm_error = any(x in err_lower for x in ("403", "404", "blocked", "not found"))
                    is_transient = any(x in err_lower for x in ("429", "502", "503", "504", "timeout", "timed out", "network error", "connection"))
                    if is_perm_error:
                        errors.append(f"{source_url}: {err_msg}")
                        break  # 不可恢复，换实例
                    if is_transient and attempt < self.max_retries:
                        delay = 1.5 * (2 ** attempt) + random.uniform(0, 0.5)
                        self.log(f"  ⏳ @{username} {source_url.split('/')[2]} 重试 {attempt+1}/{self.max_retries}（{delay:.1f}s后）")
                        time.sleep(delay)
                    elif attempt < self.max_retries:
                        delay = 1.0 * (2 ** attempt)
                        self.log(f"  ⏳ @{username} {source_url.split('/')[2]} 重试 {attempt+1}/{self.max_retries}（{delay:.0f}s后）")
                        time.sleep(delay)
                    else:
                        errors.append(f"{source_url}: {err_msg}")
            if rss_items:
                break

        if rss_items is None:
            result.errors.append(Failure(
                stage="scanner",
                error_type="AllInstancesFailed",
                message="; ".join(errors) or "无可用RSS实例",
                can_continue=True,
            ))
            return result

        result.source_url = used_instance
        result.debug["rss_items_found"] = len(rss_items)

        for raw in rss_items:
            try:
                normalized = normalize_tweet_url(raw["url"])
                item_url = normalized.canonical_url
                tweet_id = normalized.tweet_id
            except Exception:
                item_url = raw["url"]
                tweet_id = extract_tweet_id(raw["url"])

            item = IntelligenceItem(
                account_id=username,
                username=username,
                url=item_url,
                tweet_id=tweet_id,
                rss_summary=raw.get("summary"),
                discovery_status="discovered",
            )

            published_at = parse_pub_date(raw.get("published_at"))
            if published_at is None:
                item.time_source = "missing"
                item.time_confidence = "unknown"
                result.time_uncertain.append(item)
                result.debug["time_uncertain"] += 1
                continue

            item.published_at = to_utc_iso(published_at)
            item.time_source = "rss_pubDate"
            item.time_confidence = "high"
            if scan_from <= published_at <= now:
                result.items.append(item)
                result.debug["inside_window"] += 1
            else:
                result.debug["outside_window"] += 1

        # 延迟，每个用户加 10%随机抖动，避免多线程同步脉冲
        if self.request_delay > 0:
            jittered = self.request_delay * (0.9 + random.random() * 0.2)
            time.sleep(jittered)

        return result

    def _parse_rss_items(self, rss_text: str) -> list[dict]:
        from xml.etree import ElementTree
        root = ElementTree.fromstring(rss_text.lstrip("﻿ \t\r\n"))
        items = []
        for element in root.findall(".//item"):
            url = text_of(element, "link")
            if not url:
                continue
            items.append({
                "url": url,
                "title": text_of(element, "title"),
                "published_at": text_of(element, "pubDate"),
                "summary": text_of(element, "description"),
            })
        return items

    def _is_blocked_feed(self, rss_items: list[dict]) -> bool:
        if len(rss_items) != 1:
            return False
        title = (rss_items[0].get("title") or "").lower()
        url = rss_items[0].get("url") or ""
        return "not yet whitelisted" in title or url.startswith("https://rss.xcancel.com/")
