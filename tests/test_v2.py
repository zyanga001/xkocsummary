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
    build_event_audit_prompt,
    build_stage3_prompt,
    _normalize_importance,
    STAGE1_SYSTEM,
    STAGE2A_SYSTEM,
    STAGE_AUDIT_SYSTEM,
    STAGE3_SYSTEM,
    validate_events,
    _assign_event_identity,
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
            {"post_id": "tw:1", "username": "alice", "正文": "BTC is crashing"},
            {"post_id": "tw:2", "username": "bob", "content_markdown": "ETH to moon"},
        ]
        prompt = build_stage1_prompt(items)
        data = json.loads(prompt)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][0]["post_id"], "tw:1")
        self.assertEqual(data["items"][0]["author"], "alice")
        self.assertEqual(data["items"][1]["post_id"], "tw:2")
        self.assertEqual(data["items"][1]["author"], "bob")

    def test_uses_global_post_ids_instead_of_batch_indexes(self):
        items = [
            {"post_id": "tw:101", "username": "alice", "正文": "first"},
            {"post_id": "tw:202", "username": "bob", "正文": "second"},
        ]
        data = json.loads(build_stage1_prompt(items))
        self.assertEqual(
            [item["post_id"] for item in data["items"]],
            ["tw:101", "tw:202"],
        )

    def test_truncates_long_content(self):
        long_text = "x" * 2000
        items = [{"username": "alice", "正文": long_text}]
        prompt = build_stage1_prompt(items)
        data = json.loads(prompt)
        segments = data["items"][0]["evidence_segments"]
        self.assertTrue(segments)
        self.assertTrue(all(len(segment["text"]) <= 360 for segment in segments))


class TestStage2aPrompt(unittest.TestCase):
    def test_builds_with_classifications(self):
        results = [
            {"post_id": "tw:1", "author": "alice", "display_name": "Alice", "summary": "Good post", "event_hint": "event", "theme_path": ["AI"], "evidence_type": "fact", "claims": ["claim"], "quote_ids": ["tw:1:q0"], "evidence_segments": [{"quote_id": "tw:1:q0", "text": "source"}]},
            {"post_id": "tw:2", "author": "bob", "display_name": "Bob", "summary": "Mid post", "event_hint": "event", "theme_path": ["AI"], "evidence_type": "analysis", "claims": ["claim"], "quote_ids": ["tw:2:q0"], "evidence_segments": [{"quote_id": "tw:2:q0", "text": "source"}]},
        ]
        prompt = build_stage2a_prompt(results)
        data = json.loads(prompt)
        self.assertEqual(len(data["items"]), 2)
        self.assertNotIn("content_full", data["items"][0])
        self.assertEqual(data["items"][0]["post_id"], "tw:1")

    def test_includes_memory_refs(self):
        results = [{"post_id": "tw:1", "author": "a", "summary": "s"}]
        prompt = build_stage2a_prompt(results, memory_refs=["「存储」: 存储可能反弹"])
        data = json.loads(prompt)
        self.assertEqual(data["previous_judgments"], ["「存储」: 存储可能反弹"])

    def test_no_memory_refs_when_none(self):
        results = [{"post_id": "tw:1", "author": "a", "summary": "s"}]
        prompt = build_stage2a_prompt(results)
        data = json.loads(prompt)
        self.assertEqual(data["previous_judgments"], [])


class TestEventAuditPrompt(unittest.TestCase):
    def test_only_includes_sources_used_by_events(self):
        events = [{"event_id": "e1", "source_ids": ["tw:1"]}]
        items = [
            {"post_id": "tw:1", "author": "alice", "content_full": "source one"},
            {"post_id": "tw:2", "author": "bob", "content_full": "source two"},
        ]
        data = json.loads(build_event_audit_prompt(events, items))
        self.assertEqual(set(data["sources"]), {"tw:1"})


class TestStage3Prompt(unittest.TestCase):
    def test_builds_with_event_context(self):
        items = [
            {"post_id": "tw:1", "author": "alice", "content_full": "Full post 1"},
            {"post_id": "tw:2", "author": "bob", "content": "Post 2"},
        ]
        events = [{"event_id": "e1", "source_ids": ["tw:1"]}]
        prompt = build_stage3_prompt(items, events)
        data = json.loads(prompt)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][0]["content"], "Full post 1")
        self.assertEqual([event["event_id"] for event in data["events"]], ["e1"])


class TestPipelineBatching(unittest.TestCase):
    def test_pipeline_splits_large_batches(self):
        llm = MagicMock()
        llm.chat_json.side_effect = [
            {"items": [self.extraction("tw:1"), self.extraction("tw:2")]},
            {"items": [self.extraction("tw:3")]},
            {"no_material_events": True, "reason": "quiet", "events": []},
            {"items": [self.judgment("tw:1"), self.judgment("tw:2")]},
            {"items": [self.judgment("tw:3")]},
            {"verdicts": [
                {"post_id": "tw:1", "accepted": True, "reason": "grounded"},
                {"post_id": "tw:2", "accepted": True, "reason": "grounded"},
                {"post_id": "tw:3", "accepted": True, "reason": "grounded"},
            ]},
        ]

        pipeline = V2Pipeline(llm=llm)
        items = [
            {"post_id": "tw:1", "username": "alice", "正文": "source one"},
            {"post_id": "tw:2", "username": "bob", "正文": "source two"},
            {"post_id": "tw:3", "username": "charlie", "正文": "source three"},
        ]
        # batch size = 2, 3 items → 2 batches
        result = pipeline.run(items, max_batch=2)

        self.assertEqual(llm.chat_json.call_count, 6)
        self.assertEqual(result.total_tweets, 3)
        self.assertEqual(result.high_count + result.medium_count + result.low_count, 3)

    @staticmethod
    def extraction(post_id):
        return {
            "post_id": post_id,
            "summary": f"Summary {post_id}",
            "event_hint": "quiet item",
            "theme_path": ["其他"],
            "evidence_type": "opinion",
            "claims": [],
            "quote_ids": [f"{post_id}:q0"],
        }

    @staticmethod
    def judgment(post_id, why=None):
        return {
            "post_id": post_id,
            "importance": "低",
            "presentation": "trace",
            "event_ids": [],
            "summary": f"Summary {post_id}",
            "why_worth": why or f"Reason {post_id}",
            "support_quote_ids": [f"{post_id}:q0"],
        }

    @patch("koc.v2_pipeline.time.sleep", return_value=None)
    def test_ids_stay_unique_across_batches_and_stage3_cannot_cross_assign(self, _sleep):
        llm = MagicMock()
        llm.chat_json.side_effect = [
            {"items": [self.extraction("tw:101")]},
            {"items": [self.extraction("tw:202")]},
            {"no_material_events": True, "reason": "quiet", "events": []},
            {"items": [self.judgment("tw:101", "Reason for first")]},
            {"items": [self.judgment("tw:202", "Reason for second")]},
            {"verdicts": [
                {"post_id": "tw:101", "accepted": True, "reason": "grounded"},
                {"post_id": "tw:202", "accepted": True, "reason": "grounded"},
            ]},
        ]
        pipeline = V2Pipeline(llm=llm)
        result = pipeline.run([
            {"post_id": "tw:101", "username": "alice", "url": "https://x.com/alice/status/101", "正文": "first"},
            {"post_id": "tw:202", "username": "bob", "url": "https://x.com/bob/status/202", "正文": "second"},
        ], max_batch=1)

        self.assertEqual([item["post_id"] for item in result.items], ["tw:101", "tw:202"])
        self.assertEqual([item["why_worth"] for item in result.items], ["Reason for first", "Reason for second"])

    def test_rejected_item_is_repaired_once_and_reaudited(self):
        llm = MagicMock()
        bad = self.judgment("tw:1") | {"summary": "Expanded company name"}
        fixed = self.judgment("tw:1") | {"summary": "source one"}
        llm.chat_json.side_effect = [
            {"items": [self.extraction("tw:1")]},
            {"no_material_events": True, "reason": "quiet", "events": []},
            {"items": [bad]},
            {"verdicts": [{"post_id": "tw:1", "accepted": False, "reason": "unsupported expansion"}]},
            {"items": [fixed]},
            {"verdicts": [{"post_id": "tw:1", "accepted": True, "reason": "grounded"}]},
        ]

        result = V2Pipeline(llm=llm).run([
            {"post_id": "tw:1", "username": "alice", "正文": "source one"}
        ])

        self.assertTrue(result.publishable, result.errors)
        self.assertEqual(result.items[0]["summary"], "source one")
        self.assertEqual(result.quality_gate["item_repair_count"], 1)
        self.assertEqual(result.stage_status["item_audit"], "success_after_repair")

    def test_malformed_item_response_is_repaired_once(self):
        llm = MagicMock()
        malformed = self.judgment("tw:1") | {"presentation": "brief"}
        llm.chat_json.side_effect = [
            {"items": [self.extraction("tw:1")]},
            {"no_material_events": True, "reason": "quiet", "events": []},
            {"items": [malformed]},
            {"items": [self.judgment("tw:1")]},
            {"verdicts": [{"post_id": "tw:1", "accepted": True, "reason": "grounded"}]},
        ]

        result = V2Pipeline(llm=llm).run([
            {"post_id": "tw:1", "username": "alice", "正文": "source one"}
        ])

        self.assertTrue(result.publishable, result.errors)
        self.assertEqual(result.quality_gate["item_contract_repair_count"], 1)
        self.assertEqual(result.stage_status["item_judgment"], "success_after_repair")

    def test_malformed_event_response_is_repaired_once(self):
        llm = MagicMock()
        llm.chat_json.side_effect = [
            {"items": [self.extraction("tw:1")]},
            {"no_material_events": False, "events": [{}]},
            {"no_material_events": True, "reason": "quiet", "events": []},
            {"items": [self.judgment("tw:1")]},
            {"verdicts": [{"post_id": "tw:1", "accepted": True, "reason": "grounded"}]},
        ]

        result = V2Pipeline(llm=llm).run([
            {"post_id": "tw:1", "username": "alice", "正文": "source one"}
        ])

        self.assertTrue(result.publishable, result.errors)
        self.assertEqual(result.quality_gate["event_repair_count"], 1)
        self.assertEqual(result.stage_status["event_synthesis"], "success_after_repair")

    def test_rejected_event_is_repaired_once_and_reaudited(self):
        llm = MagicMock()
        event = {
            "title": "Source event",
            "canonical_topic": "其他",
            "theme_path": ["其他"],
            "source_ids": ["tw:1"],
            "thesis": "Source event happened",
            "prior_state": "No baseline",
            "new_evidence": [{
                "post_id": "tw:1",
                "quote_ids": ["tw:1:q0"],
                "claim": "unsupported claim",
            }],
            "judgment_delta": "No change",
            "unknowns": ["More evidence"],
            "topic_importance": "低",
            "presentation": "trace",
            "confidence": "低",
        }
        fixed_event = dict(event)
        fixed_event["new_evidence"] = [{
            "post_id": "tw:1",
            "quote_ids": ["tw:1:q0"],
            "claim": "source one",
        }]
        event_id = _assign_event_identity([event])[0]["event_id"]
        llm.chat_json.side_effect = [
            {"items": [self.extraction("tw:1")]},
            {"no_material_events": False, "reason": "", "events": [event]},
            {"verdicts": [{"event_id": event_id, "accepted": False, "reason": "claim mismatch"}]},
            {"no_material_events": False, "reason": "", "events": [fixed_event]},
            {"verdicts": [{"event_id": event_id, "accepted": True, "reason": "grounded"}]},
            {"items": [self.judgment("tw:1")]},
            {"verdicts": [{"post_id": "tw:1", "accepted": True, "reason": "grounded"}]},
        ]

        result = V2Pipeline(llm=llm).run([
            {"post_id": "tw:1", "username": "alice", "正文": "source one"}
        ])

        self.assertTrue(result.publishable, result.errors)
        self.assertEqual(result.quality_gate["event_audit_repair_count"], 1)
        self.assertEqual(result.stage_status["event_audit"], "success_after_repair")


class TestEventValidation(unittest.TestCase):
    def valid_event(self):
        return {
            "event_id": "evt-storage",
            "title": "存储价格继续上行",
            "canonical_topic": "存储",
            "theme_path": ["美股投资", "半导体", "存储"],
            "source_ids": ["tw:101", "tw:202"],
            "thesis": "存储价格证据仍在上行。",
            "prior_state": "市场此前担心存储周期见顶。",
            "new_evidence": [
                {"post_id": "tw:101", "quote_ids": ["tw:101:q0"], "quotes": ["DRAM 上涨"], "claim": "DRAM 合同价上涨。"},
                {"post_id": "tw:202", "quote_ids": ["tw:202:q0"], "quotes": ["拒绝降价"], "claim": "厂商拒绝降价。"},
            ],
            "judgment_delta": "价格证据削弱了立即见顶的判断。",
            "unknowns": ["下一季报价能否延续"],
            "topic_importance": "高",
            "presentation": "focus",
            "confidence": "中",
        }

    def test_accepts_traceable_event(self):
        valid, errors = validate_events([self.valid_event()], {"tw:101", "tw:202"})
        self.assertEqual(len(valid), 1)
        self.assertEqual(errors, [])

    def test_rejects_unknown_sources_and_incomplete_evidence(self):
        event = self.valid_event()
        event["source_ids"] = ["tw:101", "tw:999"]
        event["new_evidence"] = [{"post_id": "tw:101", "quote_ids": ["tw:101:q0"], "quotes": ["DRAM 上涨"], "claim": "DRAM 合同价上涨。"}]
        valid, errors = validate_events([event], {"tw:101", "tw:202"})
        self.assertEqual(valid, [])
        self.assertTrue(any("tw:999" in error for error in errors))

    def test_rejects_evidence_quote_that_is_not_in_source(self):
        event = self.valid_event()
        event["source_ids"] = ["tw:101"]
        event["new_evidence"] = [
            {"post_id": "tw:101", "quote_ids": ["tw:101:q0"], "quotes": ["SK 海力士"], "claim": "擅自扩展了代码"}
        ]
        valid, errors = validate_events(
            [event],
            {"tw:101"},
            {"tw:101": "原文只写了 sndk 财报 110 分"},
        )
        self.assertEqual(valid, [])
        self.assertTrue(any("不是原文逐字引句" in error for error in errors))


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
        self.assertIn("不判断高中低", STAGE1_SYSTEM)
        self.assertIn("claims", STAGE1_SYSTEM)

    def test_stage2a_has_reasoning_contract(self):
        self.assertIn("prior_state", STAGE2A_SYSTEM)
        self.assertIn("judgment_delta", STAGE2A_SYSTEM)
        self.assertIn("unknowns", STAGE2A_SYSTEM)

    def test_audit_rejects_unrelated_grouping(self):
        self.assertIn("同一主体、同一变化", STAGE_AUDIT_SYSTEM)

    def test_stage3_asks_why_worth(self):
        self.assertIn("事件已经先于条目", STAGE3_SYSTEM)


if __name__ == "__main__":
    unittest.main()
