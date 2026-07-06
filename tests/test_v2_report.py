import unittest

from koc.v2_report import render_v2_index, render_v2_report


class V2ReportTest(unittest.TestCase):
    def test_report_archive_links_are_relative_to_page_depth(self):
        root_html = render_v2_report({"items": []}, run_label="06-13 20:00", page_depth=1)
        deep_html = render_v2_report({"items": []}, run_label="06-13 20:00", page_depth=3)

        self.assertIn('href="archive/index.html"', root_html)
        self.assertIn('href="../../index.html"', deep_html)
        self.assertNotIn('href="../../archive/index.html"', deep_html)

    def test_archive_index_uses_relative_report_links_and_cleans_old_labels(self):
        html = render_v2_index([{
            "date": "2026-06-13",
            "run": "2026-06-13 第1次更新",
            "path": "2026-06-13/run-1/report.html",
            "label": "2026-06-13 06-13 20:00 · 第1次更新",
            "total_tweets": 12,
        }])

        self.assertIn('href="2026-06-13/run-1/report.html"', html)
        self.assertNotIn('href="archive/2026-06-13/run-1/report.html"', html)
        self.assertIn("2026-06-13 20:00 · 第1次更新", html)
        self.assertNotIn("2026-06-13 06-13 20:00", html)

    def test_report_includes_collapsible_run_details(self):
        html = render_v2_report({
            "items": [],
            "status": "success",
            "slot_label": "早报",
            "planned_at": "2026-07-06 09:00",
            "started_at": "2026-07-06 13:05",
            "finished_at": "2026-07-06 13:13",
            "window_start": "2026-07-05 21:00",
            "window_end": "2026-07-06 09:00",
            "delay_seconds": 15180,
            "elapsed_seconds": 454,
            "scan_ok": 51,
            "scan_empty": 192,
            "scan_fail": 7,
            "scan_errors": [{"author": "alice", "error": "timeout"}],
        }, run_label="07-06 13:13 · 第1次更新", page_depth=1)

        self.assertIn("<details", html)
        self.assertIn("运行详情", html)
        self.assertIn("覆盖窗口", html)
        self.assertIn("2026-07-05 21:00 - 2026-07-06 09:00", html)
        self.assertIn("抓取失败", html)
        self.assertIn("@alice: timeout", html)


if __name__ == "__main__":
    unittest.main()
