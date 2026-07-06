from datetime import datetime, timezone
import unittest

from koc.schedule import BEIJING, resolve_report_window


class ScheduleTest(unittest.TestCase):
    def test_morning_run_uses_previous_evening_to_morning_window(self):
        now = datetime(2026, 7, 6, 5, 13, tzinfo=timezone.utc)

        window = resolve_report_window(now)

        self.assertEqual(window.slot, "morning")
        self.assertEqual(window.label, "早报")
        self.assertEqual(window.planned_at.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-06 09:00")
        self.assertEqual(window.window_start.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-05 21:00")
        self.assertEqual(window.window_end.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-06 09:00")
        self.assertEqual(window.delay_seconds, 15180)

    def test_evening_run_uses_morning_to_evening_window(self):
        now = datetime(2026, 7, 6, 13, 20, tzinfo=timezone.utc)

        window = resolve_report_window(now)

        self.assertEqual(window.slot, "evening")
        self.assertEqual(window.label, "晚报")
        self.assertEqual(window.planned_at.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-06 21:00")
        self.assertEqual(window.window_start.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-06 09:00")
        self.assertEqual(window.window_end.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-06 21:00")
        self.assertEqual(window.delay_seconds, 1200)

    def test_before_morning_run_still_targets_previous_evening_report(self):
        now = datetime(2026, 7, 6, 0, 15, tzinfo=timezone.utc)

        window = resolve_report_window(now)

        self.assertEqual(window.slot, "evening")
        self.assertEqual(window.planned_at.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-05 21:00")
        self.assertEqual(window.window_start.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-05 09:00")
        self.assertEqual(window.window_end.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"), "2026-07-05 21:00")


if __name__ == "__main__":
    unittest.main()
