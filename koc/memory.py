"""记忆层 — 记住"这个主题之前怎么判断的"，让话题有连续性。

简单版设计（符合主人"不要复杂化"）：
- 一个 JSON 文件：{"topics": {"存储": {"last_judgment": "...", "updated": "..."}}}
- 每期生成时读上期判断，写进综合 prompt 作参考（话题能接上期）
- 判断变了就改写那条记录，不堆新（避免"1号3号像做日志"）
- 每期报告哪些主题被改写/新增/未变（让漂移可见）

文件损坏不炸管道：备份后重建，记入 errors（诚实降级）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class MemoryLayer:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.errors: list[str] = []
        self.topics: dict[str, dict] = {}
        self._changes: dict[str, list[str]] = {
            "new": [],
            "updated": [],
            "unchanged": [],
        }
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.topics = dict(data.get("topics") or {})
        except Exception as exc:
            backup = f"{self.path}.corrupt"
            try:
                if self.path.exists():
                    os.replace(self.path, backup)
            except Exception:
                pass
            self.errors.append(f"记忆文件损坏，已备份为 {backup}: {exc}")
            self.topics = {}

    def get_topic_judgment(self, topic: str) -> str:
        """取某个主题上期的判断，没有则空字符串。"""
        return (self.topics.get(topic) or {}).get("last_judgment", "")

    def recent_context(self, limit: int = 8) -> list[dict]:
        """Return structured event memory ordered by most recently updated."""
        entries = []
        for topic, record in self.topics.items():
            if record.get("last_judgment"):
                entries.append({"canonical_topic": topic, **record})
        entries.sort(key=lambda item: str(item.get("updated") or ""), reverse=True)
        return entries[:limit]

    def recent_judgments(self, limit: int = 5) -> list[str]:
        """最近几条主题判断，用于写进 prompt 作参考。"""
        entries: list[tuple[str, str]] = []
        for topic, rec in self.topics.items():
            judgment = rec.get("last_judgment", "")
            if judgment:
                entries.append((str(rec.get("updated") or ""), f"「{topic}」: {judgment}"))
        entries.sort(key=lambda item: item[0], reverse=True)
        return [text for _, text in entries[:limit]]

    def preview_diff(self, events: list[dict]) -> dict[str, list[str]]:
        changes = {"new": [], "updated": [], "unchanged": []}
        for event in events:
            key = str(event.get("canonical_topic") or "").strip()
            if not key:
                continue
            judgment = str(event.get("judgment_delta") or "").strip()
            previous = self.topics.get(key)
            if previous is None:
                kind = "new"
            elif previous.get("last_judgment") == judgment:
                kind = "unchanged"
            else:
                kind = "updated"
            if key not in changes[kind]:
                changes[kind].append(key)
        return changes

    def update_event(self, event: dict, now: datetime | None = None) -> str:
        title = str(event.get("title") or "").strip()
        canonical_topic = str(event.get("canonical_topic") or "").strip()
        judgment = str(event.get("judgment_delta") or "").strip()
        return self.update_topic(
            title,
            judgment,
            now=now,
            canonical_topic=canonical_topic,
            metadata={
                "theme_path": list(event.get("theme_path") or []),
                "thesis": str(event.get("thesis") or ""),
                "prior_state": str(event.get("prior_state") or ""),
                "unknowns": list(event.get("unknowns") or []),
                "source_ids": list(event.get("source_ids") or []),
                "confidence": str(event.get("confidence") or ""),
            },
        )

    def update_topic(
        self,
        topic: str,
        judgment: str,
        now: datetime | None = None,
        canonical_topic: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """更新某主题的判断。判断没变返回 'unchanged'，变了返回 'updated'，新主题返回 'new'。"""
        now = now or datetime.now(timezone.utc)
        iso = now.isoformat()
        key = (canonical_topic or topic).strip()
        if not key:
            raise ValueError("canonical topic must not be empty")
        prev = self.topics.get(key)
        if prev is None:
            self.topics[key] = {
                "title": topic,
                "last_judgment": judgment,
                "created": iso,
                "updated": iso,
                **(metadata or {}),
            }
            self._record_change("new", key)
            return "new"
        if prev.get("last_judgment") == judgment:
            prev["title"] = topic
            prev["updated"] = iso
            prev.update(metadata or {})
            self._record_change("unchanged", key)
            return "unchanged"
        prev["title"] = topic
        prev["last_judgment"] = judgment
        prev["updated"] = iso
        prev.update(metadata or {})
        self._record_change("updated", key)
        return "updated"

    def diff(self) -> dict[str, list[str]]:
        """本期哪些主题变了——让漂移可见。"""
        return {key: list(values) for key, values in self._changes.items()}

    def _record_change(self, kind: str, topic: str) -> None:
        if topic not in self._changes[kind]:
            self._changes[kind].append(topic)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"topics": self.topics}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
