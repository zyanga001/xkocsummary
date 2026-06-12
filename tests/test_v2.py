"""V2 pipeline 单元测试。"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from koc.v2_pipeline import (
    V2Pipeline,
    PipelineResult,
    build_stage1_prompt,
    build_stage2a_prompt,
    build_stage2b_prompt,
    build_stage2c_prompt,
    build_stage3_prompt,
    _normalize_importance,
    STAGE1_SYSTEM,
    STAGE2A_SYSTEM,
    STAGE2B_SYSTEM,
    STAGE2C_SYSTEM,
    STAGE3_SYSTEM,
)


class TestNormalize(unittest.TestCase):
    def test_importance_normalization(self):
        self.assertEqual(_normalize_importance("高"), "高")
        self.assertEqual(_normalize_importance("high"), "高")
        self.assertEqual(_normalize_importance("中"), "中")
        self.assertEqual(_normalize_importance("medium"), "中")
        self.assertEqual(_normalize_importance("低"), "低")
        self.assertEqual(_normalize_importance(""), "低")
        self.assertEqual(_normalize_importance("unknown"), "低")


class TestStage1Prompt(unittest.TestCase):
    def test_builds_with_items(self):
        items = [
            {"username": "alice", "正文": "BTC is crashing"},
            {"username": "bob", "content_markdown": "ETH to moon"},
        ]
        prompt = build_stage1_prompt(items)
        data = json.loads(prompt)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][0]["post_id"], "0")
        self.assertEqual(data["items"][0]["author"], "alice")
        self.assertEqual(data["items"][1]["post_id"], "1")
        self.assertEqual(data["items"][1]["author"], "bob")

    def test_truncates_long_content(self):
        long_text = "x" * 2000
        items = [{"username": "alice", "正文": long_text}]
        prompt = build_stage1_prompt(items)
        data = json.loads(prompt)
        self.assertLess(len(data["items"][0]["content"]), 1500)


class TestStage2aPrompt(unittest.TestCase):
    def test_builds_with_classifications(self):
        results = [
            {"post_id": "0", "author": "alice", "display_name": "Alice", "importance": "高", "summary": "Good post"},
            {"post_id": "1", "author": "bob", "display_name": "Bob", "importance": "低", "summary": "Bad post"},
        ]
        prompt = build_stage2a_prompt(results)
        data = json.loads(prompt)
        self.assertEqual(len(data["items"]), 2)
        self.assertNotIn("content_full", data["items"][0])


class TestStage2bPrompt(unittest.TestCase):
    def test_builds_for_profiles(self):
        results = [
            {"post_id": "0", "author": "alice", "display_name": "Alice", "importance": "高", "summary": "Good"},
            {"post_id": "1", "author": "alice", "display_name": "Alice", "importance": "中", "summary": "Mid"},
        ]
        prompt = build_stage2b_prompt(results)
        data = json.loads(prompt)
        self.assertEqual(data["total_authors"], 1)


class TestStage2cPrompt(unittest.TestCase):
    def test_only_medium_items(self):
        results = [
            {"post_id": "0", "author": "alice", "display_name": "Alice", "importance": "高", "summary": "Good"},
            {"post_id": "1", "author": "bob", "display_name": "Bob", "importance": "中", "summary": "Mid"},
            {"post_id": "2", "author": "charlie", "display_name": "Charlie", "importance": "低", "summary": "Low"},
        ]
        prompt = build_stage2c_prompt(results)
        data = json.loads(prompt)
        self.assertEqual(len(data["medium_items"]), 1)


class TestStage3Prompt(unittest.TestCase):
    def test_builds_only_for_high_value(self):
        items = [
            {"post_id": "0", "author": "alice", "content_full": "Full post 1", "content_markdown": "ignored"},
            {"post_id": "1", "author": "bob", "content_markdown": "Post 2"},
        ]
        prompt = build_stage3_prompt(items)
        data = json.loads(prompt)
        self.assertEqual(len(data["high_value_items"]), 2)
        # Should use content_full when available
        self.assertEqual(data["high_value_items"][0]["content"], "Full post 1")


class TestPipelineBatching(unittest.TestCase):
    def test_pipeline_splits_large_batches(self):
        llm = MagicMock()
        # Mock stage1 returns for each batch
        llm.chat_json.side_effect = [
            {"items": [{"post_id": "0", "importance": "高", "summary": "Good"}, {"post_id": "1", "importance": "低", "summary": "Bad"}]},
            {"items": [{"post_id": "0", "importance": "中", "summary": "Mid"}]},
            # 2a
            {"topics": []},
            # 2b
            {"profiles": []},
            # 2c
            {"medium_merge": ""},
            # 3
            {"analyses": []},
        ]

        pipeline = V2Pipeline(llm=llm)
        items = [
            {"username": "alice", "正文": "a" * 100},
            {"username": "bob", "正文": "b" * 100},
            {"username": "charlie", "正文": "c" * 100},
        ]
        # batch size = 2, 3 items → 2 batches
        result = pipeline.run(items, max_batch=2)

        # 2x stage1 + 2a + 2b + 2c + 3 = 6 calls
        self.assertGreaterEqual(llm.chat_json.call_count, 5)
        self.assertEqual(result.total_tweets, 3)
        self.assertEqual(result.high_count + result.medium_count + result.low_count, 3)


class TestPipelineResult(unittest.TestCase):
    def test_result_defaults(self):
        r = PipelineResult(
            run_id="test",
            created_at="now",
            window="12h",
            total_tweets=10,
            authors_count=5,
        )
        self.assertEqual(r.high_count, 0)
        self.assertEqual(r.items, [])
        self.assertEqual(r.errors, [])


class TestPromptTemplates(unittest.TestCase):
    def test_stage1_has_criteria(self):
        self.assertIn("判断价值", STAGE1_SYSTEM)
        self.assertIn("教程", STAGE1_SYSTEM)
        self.assertIn("软文", STAGE1_SYSTEM)

    def test_stage2a_has_what_they_said(self):
        self.assertIn("what_they_said", STAGE2A_SYSTEM)
        self.assertIn("话题", STAGE2A_SYSTEM)

    def test_stage2b_has_profiles(self):
        self.assertIn("profiles", STAGE2B_SYSTEM)
        self.assertIn("quality", STAGE2B_SYSTEM)

    def test_stage2c_has_medium(self):
        self.assertIn("medium_merge", STAGE2C_SYSTEM)

    def test_stage3_asks_why_worth(self):
        self.assertIn("为什么值得关注", STAGE3_SYSTEM)


if __name__ == "__main__":
    unittest.main()
