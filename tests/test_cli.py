import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch

from koc import cli
from koc.models import IntelligenceItem, ScanResult
from koc.v2_pipeline import PipelineResult


class CliTest(unittest.TestCase):
    def run_cli(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cli.main(argv)
        return code, stdout.getvalue()

    def test_user_facing_commands_only_expose_v2_entrypoints(self):
        parser = cli.build_parser()
        subparsers_action = next(action for action in parser._actions if action.dest == "command")

        self.assertEqual(
            set(subparsers_action.choices),
            {"run-v2", "eval-v2"},
        )

    def test_run_v2_generates_report_without_label_order_crash(self):
        class FakeScanner:
            def __init__(self, *args, **kwargs):
                pass

            def scan_user(self, author, window, now):
                item = IntelligenceItem(
                    account_id=author,
                    username=author,
                    url=f"https://x.com/{author}/status/1",
                    tweet_id="1",
                    rss_summary="Useful RSS summary",
                )
                return ScanResult(
                    username=author,
                    source_url="",
                    window=window,
                    scan_from="2026-06-13T00:00:00Z",
                    scan_to="2026-06-13T12:00:00Z",
                    items=[item],
                )

        class FakeReader:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_item(self, item):
                item.content_markdown = item.rss_summary
                item.published_at = "2026-06-13T12:00:00Z"
                return item

        class FakePipeline:
            def run(self, items):
                return PipelineResult(
                    run_id="test",
                    created_at="now",
                    window="12h",
                    total_tweets=1,
                    authors_count=1,
                    high_count=1,
                    items=[{
                        "post_id": "0",
                        "author": "alice",
                        "display_name": "alice",
                        "importance": "高",
                        "summary": "Useful summary",
                        "url": "https://x.com/alice/status/1",
                    }],
                    daily_brief=[],
                    author_profiles=[],
                )

        with tempfile.TemporaryDirectory() as tmp:
            watchlist = f"{tmp}/watchlist.txt"
            output = f"{tmp}/output"
            with open(watchlist, "w", encoding="utf-8") as handle:
                handle.write("alice\n")

            with (
                patch.object(cli, "RobustScanner", FakeScanner),
                patch.object(cli, "Reader", FakeReader),
                patch.object(cli, "V2Pipeline", lambda: FakePipeline()),
            ):
                code, stdout = self.run_cli([
                    "run-v2",
                    "--watchlist",
                    watchlist,
                    "--schedule",
                    f"{tmp}/missing-schedule.json",
                    "--output",
                    output,
                ])

            self.assertEqual(code, 0, stdout)
            self.assertIn("首页入口", stdout)


if __name__ == "__main__":
    unittest.main()
