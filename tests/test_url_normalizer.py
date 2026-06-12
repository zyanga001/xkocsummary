import unittest

from koc.url_normalizer import normalize_tweet_url


class UrlNormalizerTest(unittest.TestCase):
    def test_normalizes_supported_tweet_hosts_to_x_com(self):
        cases = [
            ("https://x.com/sama/status/123456", "sama", "123456"),
            ("https://twitter.com/sama/status/123456?s=20", "sama", "123456"),
            ("https://mobile.twitter.com/sama/statuses/123456", "sama", "123456"),
            ("https://xcancel.com/sama/status/123456#m", "sama", "123456"),
            ("https://nitter.net/sama/status/123456", "sama", "123456"),
        ]

        for raw_url, username, tweet_id in cases:
            with self.subTest(raw_url=raw_url):
                normalized = normalize_tweet_url(raw_url)

                self.assertEqual(normalized.username, username)
                self.assertEqual(normalized.tweet_id, tweet_id)
                self.assertEqual(normalized.canonical_url, f"https://x.com/{username}/status/{tweet_id}")

    def test_rejects_non_tweet_url(self):
        with self.assertRaises(ValueError):
            normalize_tweet_url("https://example.com/sama/status/123456")


if __name__ == "__main__":
    unittest.main()
