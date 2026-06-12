from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Failure:
    stage: str
    error_type: str
    message: str
    fallback: str | None = None
    can_continue: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "failed",
            "stage": self.stage,
            "error_type": self.error_type,
            "message": self.message,
            "fallback": self.fallback,
            "can_continue": self.can_continue,
        }


@dataclass
class IntelligenceItem:
    account_id: str
    username: str
    url: str
    tweet_id: str | None = None
    published_at: str | None = None
    time_source: str | None = None
    time_confidence: str = "unknown"
    discovery_status: str = "not_started"
    rss_summary: str | None = None
    fetch_status: str = "not_started"
    raw_content: str | None = None
    content_markdown: str | None = None
    content_length: int = 0
    content_quality: str = "unknown"
    content_preview: str | None = None
    content_hash: str | None = None
    analysis_status: str = "not_started"
    topics: list[str] = field(default_factory=list)
    summary: str | None = None
    importance_score: int | None = None
    evidence: list[str] = field(default_factory=list)
    errors: list[Failure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["errors"] = [error.to_dict() for error in self.errors]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntelligenceItem":
        errors = data.get("errors", [])
        clean = {key: value for key, value in data.items() if key != "errors"}
        item = cls(**clean)
        item.errors = [
            Failure(
                stage=error.get("stage", "unknown"),
                error_type=error.get("error_type", "unknown"),
                message=error.get("message", ""),
                fallback=error.get("fallback"),
                can_continue=error.get("can_continue", True),
            )
            for error in errors
        ]
        return item


@dataclass
class ScanResult:
    username: str
    source_url: str
    window: str
    scan_from: str
    scan_to: str
    items: list[IntelligenceItem] = field(default_factory=list)
    time_uncertain: list[IntelligenceItem] = field(default_factory=list)
    errors: list[Failure] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "source_url": self.source_url,
            "window": self.window,
            "scan_from": self.scan_from,
            "scan_to": self.scan_to,
            "items": [item.to_dict() for item in self.items],
            "time_uncertain": [item.to_dict() for item in self.time_uncertain],
            "errors": [error.to_dict() for error in self.errors],
            "debug": self.debug,
        }
