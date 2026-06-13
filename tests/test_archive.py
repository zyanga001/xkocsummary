import json
import tempfile
import unittest
from pathlib import Path

from koc.archive import build_archive_history, next_run_dir


class ArchiveTest(unittest.TestCase):
    def test_next_run_dir_uses_numeric_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            date_dir = Path(tmp) / "archive" / "2026-06-13"
            (date_dir / "run-1").mkdir(parents=True)
            (date_dir / "run-10").mkdir()
            (date_dir / "run-2").mkdir()

            run_num, run_dir = next_run_dir(date_dir)

            self.assertEqual(run_num, 11)
            self.assertEqual(run_dir.name, "run-11")

    def test_build_archive_history_uses_paths_relative_to_archive_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "archive"
            run_dir = archive_dir / "2026-06-13" / "run-2"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({
                    "created_at": "2026-06-13 06-13 20:00 · 第2次更新",
                    "total_tweets": 42,
                }),
                encoding="utf-8",
            )

            history = build_archive_history(archive_dir)

            self.assertEqual(history[0]["run"], "2026-06-13 第2次更新")
            self.assertEqual(history[0]["path"], "2026-06-13/run-2/report.html")
            self.assertEqual(history[0]["total_tweets"], 42)


if __name__ == "__main__":
    unittest.main()
