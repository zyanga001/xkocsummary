from datetime import datetime, timezone
import unittest

from koc.robust_scanner import RobustScanner
from koc.rss_utils import parse_window


RSS = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>New post</title>
    <link>https://xcancel.com/sama/status/3</link>
    <pubDate>Mon, 08 Jun 2026 11:00:00 GMT</pubDate>
    <description>new</description>
  </item>
  <item>
    <title>Old post</title>
    <link>https://xcancel.com/sama/status/1</link>
    <pubDate>Sun, 07 Jun 2026 10:00:00 GMT</pubDate>
    <description>old</description>
  </item>
  <item>
    <title>No time</title>
    <link>https://xcancel.com/sama/status/2</link>
    <description>unknown</description>
  </item>
</channel></rss>
"""

BLOCKED_RSS = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>RSS reader not yet whitelisted!</title>
    <link>https://rss.xcancel.com/sama/rss</link>
    <pubDate>Mon, 01 January 1971 00:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


class ScannerTest(unittest.TestCase):
    def test_parse_window_supports_hours(self):
        self.assertEqual(parse_window("12h").total_seconds(), 12 * 60 * 60)

    def test_scan_filters_by_utc_window_without_breaking_on_old_items(self):
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        scanner = RobustScanner(fetch_text=lambda url, timeout: RSS)

        result = scanner.scan_user("sama", window="12h", now=now)

        self.assertEqual([item.tweet_id for item in result.items], ["3"])
        self.assertEqual([item.url for item in result.items], ["https://x.com/sama/status/3"])
        self.assertEqual([item.tweet_id for item in result.time_uncertain], ["2"])
        self.assertEqual(result.debug["rss_items_found"], 3)
        self.assertEqual(result.debug["inside_window"], 1)
        self.assertEqual(result.debug["outside_window"], 1)
        self.assertEqual(result.debug["time_uncertain"], 1)

    def test_scan_tolerates_leading_whitespace_before_xml_declaration(self):
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        scanner = RobustScanner(fetch_text=lambda url, timeout: "\n " + RSS)

        result = scanner.scan_user("sama", window="12h", now=now)

        self.assertEqual(result.errors, [])
        self.assertEqual([item.tweet_id for item in result.items], ["3"])

    def test_scan_returns_structured_account_failure(self):
        def fail(_url, _timeout):
            raise TimeoutError("network timeout")

        scanner = RobustScanner(fetch_text=fail)

        result = scanner.scan_user("sama", window="12h")

        self.assertEqual(result.items, [])
        self.assertEqual(result.errors[0].stage, "scanner")
        self.assertIs(result.errors[0].can_continue, True)

    def test_scan_treats_blocked_rss_placeholder_as_failure(self):
        scanner = RobustScanner(fetch_text=lambda url, timeout: BLOCKED_RSS)

        result = scanner.scan_user("sama", window="12h")

        self.assertEqual(result.items, [])
        self.assertEqual(result.errors[0].error_type, "AllInstancesFailed")

    def test_scan_tries_backup_instance_when_first_returns_blocked_feed(self):
        requested = []

        def fetch(url, _timeout):
            requested.append(url)
            if "bad.example" in url:
                return BLOCKED_RSS
            return RSS

        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        scanner = RobustScanner(
            fetch_text=fetch,
        )
        scanner.INSTANCES = ("https://bad.example", "https://good.example")

        result = scanner.scan_user("sama", window="12h", now=now)

        self.assertEqual(result.source_url, "https://good.example/sama/rss")
        self.assertEqual(result.errors, [])
        self.assertEqual([item.tweet_id for item in result.items], ["3"])
        self.assertEqual([item.url for item in result.items], ["https://x.com/sama/status/3"])

    def test_scan_tries_backup_instance_when_first_fails(self):
        def fetch(url, _timeout):
            if "bad.example" in url:
                raise RuntimeError("403 Forbidden")
            return RSS

        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        scanner = RobustScanner(fetch_text=fetch)
        scanner.INSTANCES = ("https://bad.example", "https://good.example")

        result = scanner.scan_user("sama", window="12h", now=now)

        self.assertEqual(result.source_url, "https://good.example/sama/rss")
        self.assertEqual([item.tweet_id for item in result.items], ["3"])


if __name__ == "__main__":
    unittest.main()
