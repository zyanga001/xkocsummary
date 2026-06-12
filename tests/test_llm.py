import unittest

from koc.llm import LlmClient


class LlmClientTest(unittest.TestCase):
    def test_health_check_reports_missing_api_key_without_network_call(self):
        called = False

        def post_json(_payload):
            nonlocal called
            called = True
            return {}

        client = LlmClient(api_key="", post_json=post_json)

        result = client.health_check()

        self.assertFalse(called)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "MissingApiKey")

    def test_health_check_uses_minimal_json_prompt(self):
        payloads = []

        def post_json(payload):
            payloads.append(payload)
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        client = LlmClient(api_key="test-key", model="test-model", post_json=post_json)

        result = client.health_check()

        self.assertTrue(result.ok)
        self.assertEqual(result.model, "test-model")
        self.assertLessEqual(payloads[0]["max_tokens"], 50)
        self.assertIn("json", payloads[0]["messages"][0]["content"].lower())
        self.assertIn('{"ok": true}', payloads[0]["messages"][0]["content"])

    def test_chat_json_retries_transient_timeout(self):
        calls = []
        sleeps = []

        def post_json(_payload):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("timed out")
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        client = LlmClient(api_key="test-key", post_json=post_json, max_retries=2, backoff_seconds=0.5, sleep=sleeps.append)

        result = client.chat_json("system", "user")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.5])

    def test_chat_json_raises_after_retry_limit(self):
        calls = []

        def post_json(_payload):
            calls.append(1)
            raise TimeoutError("timed out")

        client = LlmClient(api_key="test-key", post_json=post_json, max_retries=1, backoff_seconds=0, sleep=lambda _delay: None)

        with self.assertRaises(TimeoutError):
            client.chat_json("system", "user")

        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
