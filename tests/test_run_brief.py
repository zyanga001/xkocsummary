from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_brief
from koc.models import IntelligenceItem, ScanResult
from koc.v2_pipeline import PipelineResult


class RunBriefTransactionTest(unittest.TestCase):
    def test_failed_pipeline_does_not_publish_or_mark_items_seen(self):
        class FakeScanner:
            def __init__(self, *args, **kwargs):
                pass

            def scan_user(self, author, **kwargs):
                item = IntelligenceItem(
                    account_id=author,
                    username=author,
                    url=f"https://x.com/{author}/status/101",
                    tweet_id="101",
                    rss_summary="useful source",
                )
                return ScanResult(
                    username=author,
                    source_url="fixture",
                    window="12h",
                    scan_from="2026-08-06T00:00:00Z",
                    scan_to="2026-08-06T12:00:00Z",
                    items=[item],
                )

        class FakeReader:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_item(self, item):
                item.content_markdown = item.rss_summary
                item.published_at = "2026-08-06T10:00:00Z"
                return item

        class FailedPipeline:
            def run(self, items, memory_refs=None):
                return PipelineResult(
                    run_id="failed-run",
                    total_tweets=1,
                    authors_count=1,
                    errors=["事件生成失败"],
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watchlist = root / "watchlist.txt"
            schedule = root / "schedule.json"
            output = root / "output"
            watchlist.write_text("alice\n", encoding="utf-8")
            schedule.write_text('{"window":"12h"}', encoding="utf-8")

            with (
                patch.object(run_brief, "OUTPUT_DIR", output),
                patch.object(run_brief, "WATCHLIST_PATH", str(watchlist)),
                patch.object(run_brief, "SCHEDULE_PATH", str(schedule)),
                patch.object(run_brief, "RobustScanner", FakeScanner),
                patch.object(run_brief, "Reader", FakeReader),
                patch.object(run_brief, "V2Pipeline", FailedPipeline),
            ):
                code = run_brief.main()

            self.assertEqual(code, 1)
            self.assertFalse((output / "index.html").exists())
            self.assertFalse((output / "state" / "seen.json").exists())
            self.assertFalse((output / "state" / "memory.json").exists())
            self.assertTrue((output / "failed" / "failed-run.json").exists())

    def test_success_publishes_event_report_and_commits_state_afterwards(self):
        class FakeScanner:
            def __init__(self, *args, **kwargs):
                pass

            def scan_user(self, author, **kwargs):
                item = IntelligenceItem(
                    account_id=author,
                    username=author,
                    url=f"https://x.com/{author}/status/202",
                    tweet_id="202",
                    rss_summary="source one",
                )
                return ScanResult(
                    username=author,
                    source_url="https://nitter.net/alice/rss",
                    window="12h",
                    scan_from="2026-08-06T00:00:00Z",
                    scan_to="2026-08-06T12:00:00Z",
                    items=[item],
                    debug={
                        "discovery_status": "updates_found",
                        "rss_items_found": 1,
                        "inside_window": 1,
                        "outside_window": 0,
                        "time_uncertain": 0,
                        "instance_attempts": [],
                    },
                )

        class FakeReader:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_item(self, item):
                item.content_markdown = item.rss_summary
                item.published_at = "2026-08-06T10:00:00Z"
                item.fetch_status = "rss_summary"
                return item

        class FakePipeline:
            def run(self, items, memory_refs=None):
                return PipelineResult(
                    run_id="success-run",
                    status="success",
                    total_tweets=1,
                    authors_count=1,
                    low_count=1,
                    items=[{
                        "post_id": "tw:202",
                        "author": "alice",
                        "display_name": "Alice",
                        "url": "https://x.com/alice/status/202",
                        "content_full": "source one",
                        "published_at": "2026-08-06T10:00:00Z",
                        "importance": "低",
                        "presentation": "trace",
                        "event_ids": [],
                        "summary": "source one",
                        "why_worth": "缺少事件增量",
                    }],
                    daily_brief=[{
                        "event_id": "evt:test",
                        "title": "测试事件",
                        "canonical_topic": "测试",
                        "theme_path": ["测试"],
                        "source_ids": ["tw:202"],
                        "thesis": "核心判断",
                        "prior_state": "此前状态",
                        "new_evidence": [{
                            "post_id": "tw:202",
                            "quotes": ["source one"],
                            "claim": "新证据",
                        }],
                        "judgment_delta": "判断变化",
                        "unknowns": ["未知项"],
                        "topic_importance": "低",
                        "presentation": "brief",
                        "confidence": "低",
                    }],
                    author_profiles=[],
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watchlist = root / "watchlist.txt"
            schedule = root / "schedule.json"
            output = root / "output"
            watchlist.write_text("alice\n", encoding="utf-8")
            schedule.write_text('{"window":"12h"}', encoding="utf-8")

            with (
                patch.object(run_brief, "RobustScanner", FakeScanner),
                patch.object(run_brief, "Reader", FakeReader),
                patch.object(run_brief, "V2Pipeline", FakePipeline),
            ):
                code = run_brief.main(
                    output_dir=output,
                    watchlist_path=str(watchlist),
                    schedule_path=str(schedule),
                )

            self.assertEqual(code, 0)
            self.assertIn("测试事件", (output / "index.html").read_text(encoding="utf-8"))
            self.assertIn("此前状态", (output / "index.html").read_text(encoding="utf-8"))
            self.assertTrue((output / "archive" / "index.html").exists())
            self.assertTrue((output / "state" / "seen.json").exists())
            self.assertTrue((output / "state" / "memory.json").exists())


if __name__ == "__main__":
    unittest.main()
