import unittest

from koc.models import IntelligenceItem
from koc.reader import Reader, jina_url


def make_item():
    return IntelligenceItem(
        account_id="sama",
        username="sama",
        url="https://x.com/sama/status/123",
        tweet_id="123",
    )


class ReaderTest(unittest.TestCase):
    def test_jina_url_preserves_canonical_https_url(self):
        self.assertEqual(
            jina_url("https://x.com/sama/status/123"),
            "https://r.jina.ai/https://x.com/sama/status/123",
        )

    def test_reader_attaches_cleaned_content_quality_preview_and_hash(self):
        reader = Reader(
            fetch_text=lambda url, timeout: (
                "Title: Sam Altman on X\n\n"
                "URL Source: https://x.com/sama/status/123\n\n"
                "Markdown Content:\n# Sam Altman on X\n\nUseful markdown body for analysis.\n\nView replies"
            )
        )

        item = reader.fetch_item(make_item())

        self.assertEqual(item.fetch_status, "success")
        self.assertEqual(item.content_quality, "high")
        self.assertEqual(item.content_markdown, "Sam Altman on X\nUseful markdown body for analysis.")
        self.assertIn("URL Source: https://x.com/sama/status/123", item.raw_content)
        self.assertIn("Useful markdown body", item.content_preview)
        self.assertGreater(item.content_length, 10)
        self.assertTrue(item.content_hash)

    def test_reader_falls_back_to_rss_summary_on_failure(self):
        def fail(_url, _timeout):
            raise TimeoutError("timeout")

        item = make_item()
        item.rss_summary = "Short RSS summary"
        reader = Reader(fetch_text=fail)

        result = reader.fetch_item(item)

        self.assertEqual(result.fetch_status, "fallback")
        self.assertEqual(result.content_markdown, "Short RSS summary")
        self.assertEqual(result.content_quality, "low")
        self.assertEqual(result.errors[0].fallback, "rss_summary_used")

    def test_reader_can_use_rss_summary_without_external_fetch(self):
        calls = []
        source = IntelligenceItem(
            account_id="sample",
            username="sample",
            url="https://x.com/sample/status/1",
            tweet_id="1",
            rss_summary="OpenAI ships a useful agent feature for product teams.",
        )
        reader = Reader(
            fetch_text=lambda url, timeout: calls.append((url, timeout)) or "",
            prefer_rss_summary=True,
        )

        result = reader.fetch_item(source)

        self.assertEqual(result.fetch_status, "rss_summary")
        self.assertIn("OpenAI ships", result.content_markdown)
        self.assertIn(result.content_quality, {"medium", "low"})
        self.assertEqual(calls, [])
        self.assertEqual(result.errors, [])

    def test_reader_tries_backend_mirror_when_x_com_fetch_fails(self):
        requested = []

        def fetch(url, _timeout):
            requested.append(url)
            if "https://x.com/" in url:
                raise TimeoutError("x blocked")
            return "Markdown Content:\n\nMirror body with enough text."

        reader = Reader(fetch_text=fetch)

        result = reader.fetch_item(make_item())

        self.assertEqual(result.fetch_status, "success")
        self.assertEqual(result.content_markdown, "Mirror body with enough text.")
        self.assertIn("https://r.jina.ai/https://x.com/sama/status/123", requested)
        self.assertIn("https://r.jina.ai/https://xcancel.com/sama/status/123", requested)

    def test_reader_falls_back_when_jina_returns_empty_markdown_shell(self):
        item = make_item()
        item.rss_summary = "<p>真实推文正文<br>包含 Web3 内容</p>"
        reader = Reader(
            fetch_text=lambda url, timeout: (
                "Title: \n\nURL Source: https://nitter.net/x/status/1\n\nMarkdown Content:\n\n"
            )
        )

        result = reader.fetch_item(item)

        self.assertEqual(result.fetch_status, "fallback")
        self.assertIn("真实推文正文", result.content_markdown)
        self.assertEqual(result.errors[0].error_type, "EmptyJinaContent")


if __name__ == "__main__":
    unittest.main()
