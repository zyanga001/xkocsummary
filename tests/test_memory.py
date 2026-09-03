"""记忆层测试。"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from koc.memory import MemoryLayer


class MemoryLayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "memory.json"

    def test_new_topic_returns_new(self):
        m = MemoryLayer(self.path)
        now = datetime(2026, 8, 6, tzinfo=timezone.utc)
        self.assertEqual(m.update_topic("存储", "存储可能反弹", now=now), "new")
        self.assertEqual(m.get_topic_judgment("存储"), "存储可能反弹")

    def test_same_judgment_returns_unchanged(self):
        m = MemoryLayer(self.path)
        now = datetime(2026, 8, 6, tzinfo=timezone.utc)
        m.update_topic("存储", "存储可能反弹", now=now)
        self.assertEqual(m.update_topic("存储", "存储可能反弹", now=now), "unchanged")

    def test_changed_judgment_returns_updated(self):
        m = MemoryLayer(self.path)
        now = datetime(2026, 8, 6, tzinfo=timezone.utc)
        m.update_topic("存储", "存储可能反弹", now=now)
        self.assertEqual(m.update_topic("存储", "存储确认见顶", now=now), "updated")
        self.assertEqual(m.get_topic_judgment("存储"), "存储确认见顶")

    def test_persist_and_reload(self):
        m = MemoryLayer(self.path)
        now = datetime(2026, 8, 6, tzinfo=timezone.utc)
        m.update_topic("存储", "存储可能反弹", now=now)
        m.save()
        m2 = MemoryLayer(self.path)
        self.assertEqual(m2.get_topic_judgment("存储"), "存储可能反弹")

    def test_corrupt_file_backs_up(self):
        self.path.write_text("{broken json", encoding="utf-8")
        m = MemoryLayer(self.path)
        self.assertEqual(len(m.errors), 1)
        self.assertTrue(Path(f"{self.path}.corrupt").exists())

    def test_recent_judgments_limited(self):
        m = MemoryLayer(self.path)
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        for i in range(7):
            m.update_topic(f"主题{i}", f"判断{i}", now=now.replace(day=i + 1))
        refs = m.recent_judgments(limit=5)
        self.assertEqual(len(refs), 5)
        self.assertIn("主题6", refs[0])
        self.assertNotIn("主题0", "\n".join(refs))

    def test_stable_canonical_topic_prevents_title_fragmentation(self):
        m = MemoryLayer(self.path)
        now = datetime(2026, 8, 6, tzinfo=timezone.utc)
        m.update_topic("存储涨价与脱钩", "涨价仍在继续", canonical_topic="存储", now=now)
        result = m.update_topic(
            "闪迪财报验证存储周期",
            "财报确认需求仍强",
            canonical_topic="存储",
            now=now,
        )
        self.assertEqual(result, "updated")
        self.assertEqual(list(m.topics), ["存储"])
        self.assertEqual(m.get_topic_judgment("存储"), "财报确认需求仍强")

    def test_diff_records_changes_for_current_run(self):
        m = MemoryLayer(self.path)
        now = datetime(2026, 8, 6, tzinfo=timezone.utc)
        m.update_topic("存储", "判断一", now=now)
        m.update_topic("存储", "判断二", now=now)
        m.update_topic("AI", "判断三", now=now)
        self.assertEqual(m.diff(), {
            "new": ["存储", "AI"],
            "updated": ["存储"],
            "unchanged": [],
        })

    def test_event_memory_keeps_sources_and_unknowns(self):
        m = MemoryLayer(self.path)
        event = {
            "title": "存储价格继续上行",
            "canonical_topic": "存储",
            "theme_path": ["美股投资", "存储"],
            "thesis": "涨价仍在延续",
            "prior_state": "此前担心见顶",
            "judgment_delta": "见顶判断被削弱",
            "unknowns": ["下一季报价"],
            "source_ids": ["tw:101"],
            "confidence": "中",
        }
        m.update_event(event, now=datetime(2026, 8, 6, tzinfo=timezone.utc))
        context = m.recent_context()
        self.assertEqual(context[0]["canonical_topic"], "存储")
        self.assertEqual(context[0]["source_ids"], ["tw:101"])
        self.assertEqual(context[0]["unknowns"], ["下一季报价"])

    def test_preview_diff_does_not_mutate_memory(self):
        m = MemoryLayer(self.path)
        m.update_topic("存储", "判断一", now=datetime(2026, 8, 6, tzinfo=timezone.utc))
        changes = m.preview_diff([
            {"canonical_topic": "存储", "judgment_delta": "判断二"},
            {"canonical_topic": "AI", "judgment_delta": "判断三"},
        ])
        self.assertEqual(changes, {
            "new": ["AI"],
            "updated": ["存储"],
            "unchanged": [],
        })
        self.assertNotIn("AI", m.topics)


if __name__ == "__main__":
    unittest.main()
