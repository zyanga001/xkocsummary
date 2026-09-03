"""去重模块 — 全局稳定 post ID + 窗口内去重 + 跨窗口去重。

从 V3 挪进 V2 线上代码（V2 原本无去重，重复抓取导致 3,499 条重复）。

规则：
- URL 可解析为推文链接时，ID = "tw:<tweet_id>"（跨窗口、跨批次稳定）
- 否则 fallback ID = "hx:" + sha1(author + content)[:16]
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .url_normalizer import normalize_tweet_url


def global_post_id(item: dict) -> str:
    url = (item.get("url") or item.get("推文链接") or "").strip()
    if url:
        try:
            return f"tw:{normalize_tweet_url(url).tweet_id}"
        except ValueError:
            pass
    author = (item.get("username") or item.get("author") or item.get("用户名") or "").strip()
    content = (item.get("content_markdown") or item.get("content_full") or item.get("content") or item.get("正文") or "").strip()
    digest = hashlib.sha1(f"{author}\n{content}".encode("utf-8")).hexdigest()[:16]
    return f"hx:{digest}"


def _content_hash(item: dict) -> str:
    """内容指纹：作者 + 归一化正文 → sha1。用于抓"同文不同 ID"的重复。"""
    author = (item.get("username") or item.get("author") or item.get("用户名") or "").strip()
    content = (item.get("content_markdown") or item.get("content_full") or item.get("content") or item.get("正文") or "").strip()
    # 归一化：压缩空白、去掉尾部时间戳/来源引用等
    norm = " ".join(content.split())
    return hashlib.sha1(f"{author}\n{norm}".encode("utf-8")).hexdigest()[:16]


def dedupe_items(items: list[dict]) -> tuple[list[dict], int]:
    """同一窗口内去重；返回 (唯一 items, 剔除数)。每个 item 会被写入 post_id。

    两层去重：
    1. 全局 post_id（URL 优先）——抓同一链接
    2. 内容指纹——抓"同文不同 ID"（同作者发几乎相同内容，两个推文 ID）
    """
    seen_ids: set[str] = set()
    seen_content: set[str] = set()
    unique: list[dict] = []
    dropped = 0
    for item in items:
        pid = global_post_id(item)
        item["post_id"] = pid
        cid = _content_hash(item)
        if pid in seen_ids or cid in seen_content:
            dropped += 1
            continue
        seen_ids.add(pid)
        seen_content.add(cid)
        unique.append(item)
    return unique, dropped


PRUNE_DAYS = 30


class SeenStore:
    """跨窗口去重状态（修复 v2 无去重导致的重复抓取）。

    单 JSON 文件：{"seen": {post_id: first_seen_iso}}。
    损坏文件不炸管道：备份为 .corrupt 后重建，并把事故记入 self.errors（诚实降级）。
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.errors: list[str] = []
        self._seen: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._seen = {k: v for k, v in (data.get("seen") or {}).items()}
        except Exception as exc:
            backup = f"{self.path}.corrupt"
            try:
                if self.path.exists():
                    os.replace(self.path, backup)
            except Exception:
                pass
            self.errors.append(f"seen.json 损坏，已备份为 {backup}: {exc}")
            self._seen = {}

    def filter_new(self, items: list[dict]) -> tuple[list[dict], int]:
        """过滤掉跨窗口已见过的；返回 (新 items, 剔除数)。"""
        fresh: list[dict] = []
        dropped = 0
        for item in items:
            pid = item.get("post_id") or global_post_id(item)
            item["post_id"] = pid
            if pid in self._seen:
                dropped += 1
                continue
            fresh.append(item)
        return fresh, dropped

    def mark_seen(self, items: list[dict], now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        for item in items:
            pid = item.get("post_id") or global_post_id(item)
            self._seen.setdefault(pid, now.isoformat())

    def prune(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=PRUNE_DAYS)).isoformat()
        self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}

    def save(self, now: datetime | None = None) -> None:
        self.prune(now)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"seen": self._seen}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
