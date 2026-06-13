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


if __name__ == "__main__":
    unittest.main()
