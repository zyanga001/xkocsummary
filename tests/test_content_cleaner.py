import unittest

from koc.content_cleaner import clean_jina_markdown


class ContentCleanerTest(unittest.TestCase):
    def test_extracts_closest_body_from_jina_shell(self):
        raw = """Title: Sam Altman on X

URL Source: https://x.com/sama/status/123

Markdown Content:
# Sam Altman on X

OpenAI released a new agent workflow feature today.

View replies
"""

        cleaned = clean_jina_markdown(raw)

        self.assertEqual(cleaned.quality, "high")
        self.assertIn("OpenAI released", cleaned.text)
        self.assertNotIn("URL Source", cleaned.text)
        self.assertNotIn("View replies", cleaned.text)

    def test_marks_short_body_as_low_quality(self):
        cleaned = clean_jina_markdown("Markdown Content:\n\nok")

        self.assertEqual(cleaned.quality, "low")
        self.assertEqual(cleaned.text, "ok")

    def test_marks_antibot_page_as_empty(self):
        cleaned = clean_jina_markdown(
            "Markdown Content:\n\n"
            "**Sorry this pages exist in order to keep the service usable for everyone.**\n"
            "**If you can't pass the test, please whitelist your extensions on this website.**"
        )

        self.assertEqual(cleaned.quality, "empty")
        self.assertEqual(cleaned.text, "")

    def test_extracts_tweet_body_from_x_page_chrome(self):
        raw = """Markdown Content:

Don’t miss what’s happening
People on X are the first to know.
Log in
Sign up
Post
Conversation
Sam Altman
@sama
Here is our current plan for OpenAI:
Built to benefit everyone: our plan
From openai.com
8:55 PM · Jun 8, 2026
1.2M Views
New to X?
Trending now
"""

        cleaned = clean_jina_markdown(raw)

        self.assertEqual(cleaned.quality, "high")
        self.assertEqual(
            cleaned.text,
            "Here is our current plan for OpenAI:\nBuilt to benefit everyone: our plan\nFrom openai.com",
        )

    def test_extracts_tweet_body_from_markdown_x_page_chrome(self):
        raw = """Markdown Content:

[Log in](https://x.com/login)
[Sign up](https://x.com/i/flow/signup)
[](https://x.com/)
[Sam Altman ![Image 1](https://pbs.twimg.com/profile.jpg)](https://x.com/sama)
[@sama](https://x.com/sama)
Here is our current plan for OpenAI:
[![Image 2: card](https://pbs.twimg.com/card.jpg) Built to benefit everyone: our plan](https://t.co/r29FUUee3A)
[From openai.com](https://t.co/r29FUUee3A)
[8:55 PM · Jun 8, 2026](https://x.com/sama/status/2064088940932641225)
[1.2M Views](https://x.com/sama/status/2064088940932641225/analytics)
New to X?
Trending now
"""

        cleaned = clean_jina_markdown(raw)

        self.assertEqual(
            cleaned.text,
            "Here is our current plan for OpenAI:\nBuilt to benefit everyone: our plan\nFrom openai.com",
        )


if __name__ == "__main__":
    unittest.main()
