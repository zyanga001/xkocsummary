from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html import unescape
import re
import time
from typing import Callable

from .content_cleaner import clean_jina_markdown
from .http import fetch_text as default_fetch_text
from .models import Failure, IntelligenceItem
from .url_normalizer import normalize_tweet_url


FetchText = Callable[[str, int], str]


def jina_url(url: str) -> str:
    return "https://r.jina.ai/" + url


def reader_source_urls(url: str) -> list[str]:
    try:
        normalized = normalize_tweet_url(url)
    except ValueError:
        return [url]
    return [
        normalized.canonical_url,
        f"https://xcancel.com/{normalized.username}/status/{normalized.tweet_id}",
        f"https://nitter.net/{normalized.username}/status/{normalized.tweet_id}",
    ]


def content_quality(markdown: str | None) -> str:
    return clean_jina_markdown(markdown).quality


def meaningful_content(markdown: str | None) -> str:
    if not markdown:
        return ""
    marker = "Markdown Content:"
    if marker in markdown:
        return markdown.split(marker, 1)[1].strip()
    return markdown.strip()


def rss_summary_to_text(summary: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", summary, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


@dataclass
class Reader:
    fetch_text: FetchText = default_fetch_text
    timeout: int = 6
    prefer_rss_summary: bool = False
    request_delay_seconds: float = 0.0
    sleep: Callable[[float], None] = time.sleep

    def fetch_item(self, item: IntelligenceItem) -> IntelligenceItem:
        if self.prefer_rss_summary and item.rss_summary:
            self._attach_content(item, rss_summary_to_text(item.rss_summary))
            item.fetch_status = "rss_summary"
            item.content_quality = "medium" if item.content_length >= 80 else "low"
            return item
        failures: list[Exception] = []
        try:
            markdown = ""
            for source_url in reader_source_urls(item.url):
                try:
                    if self.request_delay_seconds > 0:
                        self.sleep(self.request_delay_seconds)
                    candidate = self.fetch_text(jina_url(source_url), self.timeout)
                    if content_quality(candidate) == "empty":
                        failures.append(RuntimeError(f"{source_url}: empty Jina content"))
                        continue
                    markdown = candidate
                    break
                except Exception as exc:
                    failures.append(exc)
            if not markdown:
                message = "; ".join(str(failure) for failure in failures) or "Jina returned no meaningful Markdown body."
                return self._fallback_from_summary(
                    item,
                    Failure(
                        stage="reader",
                        error_type="EmptyJinaContent",
                        message=message,
                        fallback="rss_summary_used" if item.rss_summary else None,
                        can_continue=bool(item.rss_summary),
                    ),
                )
            self._attach_content(item, markdown)
            item.fetch_status = "success"
            return item
        except Exception as exc:
            return self._fallback_from_summary(
                item,
                Failure(
                    stage="reader",
                    error_type=exc.__class__.__name__,
                    message=str(exc),
                    fallback="rss_summary_used" if item.rss_summary else None,
                    can_continue=bool(item.rss_summary),
                ),
            )

    def _fallback_from_summary(self, item: IntelligenceItem, failure: Failure) -> IntelligenceItem:
        if item.rss_summary:
            self._attach_content(item, rss_summary_to_text(item.rss_summary))
            item.fetch_status = "fallback"
            item.content_quality = "low"
        else:
            item.fetch_status = "failed"
            item.content_quality = "empty"
        item.errors.append(failure)
        return item

    def _attach_content(self, item: IntelligenceItem, markdown: str) -> None:
        item.raw_content = markdown
        cleaned = clean_jina_markdown(markdown)
        item.content_markdown = cleaned.text
        item.content_length = cleaned.length
        item.content_quality = cleaned.quality
        item.content_preview = cleaned.preview
        item.content_hash = hashlib.sha256(cleaned.text.encode("utf-8")).hexdigest()
