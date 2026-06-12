import unittest


from koc.models import Failure, IntelligenceItem


class ModelsTest(unittest.TestCase):
    def test_failure_records_continuable_fallback(self):
        failure = Failure(
            stage="reader",
            error_type="jina_timeout",
            message="Jina request timed out",
            fallback="rss_summary_used",
            can_continue=True,
        )

        self.assertEqual(
            failure.to_dict(),
            {
                "status": "failed",
                "stage": "reader",
                "error_type": "jina_timeout",
                "message": "Jina request timed out",
                "fallback": "rss_summary_used",
                "can_continue": True,
            },
        )

    def test_intelligence_item_round_trips_core_contract(self):
        item = IntelligenceItem(
            account_id="sama",
            username="sama",
            url="https://xcancel.com/sama/status/123",
            tweet_id="123",
            published_at="2026-06-08T01:20:00Z",
            time_source="rss_pubDate",
            time_confidence="high",
            discovery_status="discovered",
        )

        data = item.to_dict()

        self.assertEqual(data["account_id"], "sama")
        self.assertEqual(data["fetch_status"], "not_started")
        self.assertIsNone(data["raw_content"])
        self.assertEqual(data["analysis_status"], "not_started")
        self.assertEqual(data["errors"], [])


if __name__ == "__main__":
    unittest.main()
