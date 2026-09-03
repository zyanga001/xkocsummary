"""Event-first intelligence pipeline for the twice-daily X report.

The pipeline treats posts as evidence, not isolated report sections:

1. Extract claims and event hints from every post without scoring them.
2. Combine related evidence into traceable events with historical context.
3. Audit each event against its cited source posts.
4. Score each post inside the accepted event context.

Malformed model output is a failed run. The publisher decides whether durable
state and the public index may advance.
"""

from __future__ import annotations

import json
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dedupe import global_post_id
from .llm import LlmClient


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUBRIC_PATH = PROJECT_ROOT / "rubric.md"

EXTRACTION_TYPES = {"fact", "analysis", "experience", "opinion", "promotion", "emotion"}
ITEM_IMPORTANCE = {"高", "中", "低"}
ITEM_PRESENTATION = {"focus", "merged", "trace"}
EVENT_IMPORTANCE = {"高", "中", "低"}
EVENT_PRESENTATION = {"focus", "brief", "trace"}
EVENT_CONFIDENCE = {"高", "中", "低"}


STAGE1_SYSTEM = """你是 X/Twitter 情报证据抽取器。这里不判断高中低，也不决定是否值得关注。

逐条忠实抽取：
- summary: 原文说了什么，保留数字、时间、主体和动作，不补外部事实
- event_hint: 它指向的具体事件；纯情绪/推广也如实注明
- theme_path: 从用户的大兴趣到细分主题，例如 ["美股投资", "半导体", "存储"]
- evidence_type: fact|analysis|experience|opinion|promotion|emotion
- claims: 可被后续事件引用的原文主张列表；纯情绪可以为空
- quote_ids: 从输入 evidence_segments 选择支持主张的片段 ID。不得自己重写引句

不要把同批其他推文的内容写到本条。post_id 必须原样返回。
返回 JSON: {"items":[{"post_id":"...","summary":"...","event_hint":"...","theme_path":["..."],"evidence_type":"fact","claims":["..."],"quote_ids":["post_id:q0"]}]}"""


STAGE2A_SYSTEM = """你是事件级情报分析器。输入是逐条证据抽取和历史判断。

核心原则：推文只是证据，事件才是判断单元。先把指向同一个具体变化的证据合并，再判断这件事在用户兴趣和市场上下文中的位置。不同项目、不同主体、不同变化不能因为都属于“空投”“AI”“存储”就硬塞进一个事件。

每个事件必须回答：
1. 之前是什么状态；历史材料没有提供时，明确写“本期材料没有足够历史基线”
2. 本期出现了哪些新证据，每条证据引用真实 post_id
3. 新证据让原判断发生了什么变化；没有变化也要直说
4. 还缺什么证据，当前结论不能越过哪里
5. 事件本身有多重要，以及应该作为焦点、简讯还是仅留痕

条目贡献、话题重要性、页面呈现是三根独立的轴。单一来源可以形成事件，但只有在证据具体、落在用户主线且确实改变判断时才能成为 focus；不要为了凑多作者合并无关内容。

canonical_topic 使用可跨期复用的稳定主题名，例如“存储”“AI Agent基础设施”“撸毛”，不要使用每天变化的新闻标题。theme_path 必须体现它最终服务的兴趣或市场，例如存储消息通常放在美股投资下，而不是孤立成行业新闻。

返回 JSON:
{
  "no_material_events": false,
  "reason": "有事件时可为空；没有事件时说明原因",
  "events": [{
    "title": "具体变化",
    "canonical_topic": "跨期主题键",
    "theme_path": ["大兴趣", "子主题"],
    "source_ids": ["post_id"],
    "thesis": "这件事的核心判断",
    "prior_state": "此前状态或诚实边界",
    "new_evidence": [{"post_id":"...","quote_ids":["post_id:q0"],"claim":"所选片段支持的新证据；不得扩展简称"}],
    "judgment_delta": "新证据改变了什么",
    "unknowns": ["仍缺的证据"],
    "topic_importance": "高|中|低",
    "presentation": "focus|brief|trace",
    "confidence": "高|中|低"
  }]
}"""


STAGE_AUDIT_SYSTEM = """你是发布前的事件证据审计员。只做审计，不润色，不新增事件。

逐个检查：
- source_ids 是否真的讨论同一主体、同一变化，而不是只共享宽泛标签
- new_evidence 是否能从对应原文直接找到，数字和主体是否串线
- prior_state 是历史材料支持的状态，还是伪装成事实的猜测
- judgment_delta 是否由新证据推出，而不是点评文体或重复原文
- unknowns 是否约束了结论边界
- 单来源 focus 是否真的有具体证据并落在用户主线

有一项不成立就 accepted=false，并写具体原因。event_id 必须原样返回。
返回 JSON: {"verdicts":[{"event_id":"...","accepted":true,"reason":"证据如何支撑"}]}"""


STAGE_ITEM_AUDIT_SYSTEM = """你是发布前的逐条事实审计员。只检查输出是否被原文和已审计事件支持。

逐条检查 summary 和 why_worth：
- 新出现的公司、人名、项目名、股票代码、数字、日期是否在 source_segments 或对应事件中
- 原文只有简称或股票代码时，输出擅自展开公司全名也算不支持，即使常识上看似合理
- event_ids 是否真是该条贡献的事件；纯情绪或推广是否被错误包装成事件增量
- importance 和 presentation 是否符合用户标尺，且二者没有混为一谈

support_quotes 只是核对入口，不代表输出中新增的所有事实都自动成立。有一项不成立就 accepted=false，指出输出中的具体错误文本。post_id 必须原样返回。
返回 JSON: {"verdicts":[{"post_id":"...","accepted":true,"reason":"事实与判断如何被支持"}]}"""


STAGE3_SYSTEM = """你是条目价值判断器。事件已经先于条目完成分析，现在把每条推文放回事件上下文中判断。

价值轴来自用户标尺：落不落在用户关心的东西上 + 用户能不能学到。事实数字多、可以直接行动、行业意义大，都不自动等于高价值。

对每条输出：
- importance: 高|中|低，这是该条对事件判断的贡献价值
- presentation: focus|merged|trace，这是页面怎么呈现，和价值档独立
- event_ids: 它贡献的事件；高中价值条目必须属于至少一个已审计事件
- summary: 保留具体主体、数字、动作的原文摘要
- why_worth: 说明它在事件链里补了哪块证据、改变了什么；低价值则说明缺少什么
- support_quote_ids: 从输入 evidence_segments 选择支撑判断的片段 ID，不得自己重写引句

同事件第 2..N 个来源通常 presentation=merged，它们是交叉验证或参与证明，不要重复占一个焦点位置。纯情绪、口号、广告通常为低和 trace。post_id 必须原样返回。
返回 JSON: {"items":[{"post_id":"...","importance":"高","presentation":"merged","event_ids":["..."],"summary":"...","why_worth":"...","support_quote_ids":["post_id:q0"]}]}。presentation 只能使用 focus、merged、trace 这三个英文值。"""


@dataclass
class PipelineResult:
    run_id: str = ""
    created_at: str = ""
    window: str = "12h"
    status: str = "failed"
    total_tweets: int = 0
    authors_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    daily_brief: list[dict[str, Any]] = field(default_factory=list)
    author_profiles: list[dict[str, Any]] = field(default_factory=list)
    medium_merge: str = ""
    no_material_events: bool = False
    stage_status: dict[str, str] = field(default_factory=dict)
    stage_elapsed_seconds: dict[str, float] = field(default_factory=dict)
    quality_gate: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return self.status == "success" and not self.errors


class PipelineContractError(RuntimeError):
    pass


class V2Pipeline:
    def __init__(
        self,
        llm: LlmClient | None = None,
        rubric_path: str | Path = DEFAULT_RUBRIC_PATH,
    ) -> None:
        self.llm = llm or LlmClient(timeout=120, max_retries=1)
        self.rubric = _load_rubric(Path(rubric_path))

    def run(
        self,
        items: list[dict],
        max_batch: int = 20,
        memory_refs: list[Any] | None = None,
    ) -> PipelineResult:
        now = datetime.now(timezone.utc)
        result = PipelineResult(
            run_id=now.strftime("event-%Y%m%d-%H%M%S"),
            created_at=now.isoformat(),
            total_tweets=len(items),
            authors_count=len(
                {
                    item.get("username") or item.get("用户名", "")
                    for item in items
                    if item.get("username") or item.get("用户名", "")
                }
            ),
        )
        if not items:
            result.errors.append("没有推文数据")
            return result
        if max_batch <= 0:
            result.errors.append("max_batch 必须大于 0")
            return result

        prepared = [dict(item) for item in items]
        for item in prepared:
            item["post_id"] = _post_id(item)
        post_ids = [item["post_id"] for item in prepared]
        if len(post_ids) != len(set(post_ids)):
            result.errors.append("输入包含重复 post_id，已停止分析")
            return result

        try:
            stage_started = time.monotonic()
            extractions: list[dict[str, Any]] = []
            for offset in range(0, len(prepared), max_batch):
                batch = prepared[offset : offset + max_batch]
                extractions.extend(self._extract_batch(batch))
                if offset + max_batch < len(prepared):
                    time.sleep(1.0)
            result.stage_status["evidence_extraction"] = "success"
            result.stage_elapsed_seconds["evidence_extraction"] = round(
                time.monotonic() - stage_started, 3
            )

            stage_started = time.monotonic()
            events, no_material_events, event_repair_count = self._synthesize_events(
                extractions, memory_refs or []
            )
            result.daily_brief = events
            result.no_material_events = no_material_events
            result.stage_status["event_synthesis"] = (
                "success_after_repair" if event_repair_count else "success"
            )
            result.stage_elapsed_seconds["event_synthesis"] = round(
                time.monotonic() - stage_started, 3
            )

            stage_started = time.monotonic()
            event_audit_repair_count = 0
            if events:
                event_rejections = self._audit_events(
                    events, extractions, memory_refs or []
                )
                if event_rejections:
                    event_audit_repair_count = len(event_rejections)
                    events = self._repair_audited_events(
                        events,
                        extractions,
                        memory_refs or [],
                        event_rejections,
                    )
                    result.daily_brief = events
                    repaired_rejections = self._audit_events(
                        events, extractions, memory_refs or []
                    )
                    if repaired_rejections:
                        details = "；".join(
                            f"{event_id}: {reason}"
                            for event_id, reason in repaired_rejections.items()
                        )
                        raise PipelineContractError(
                            "事件审计修正后仍未通过: " + details
                        )
            result.stage_status["event_audit"] = (
                "success_after_repair" if event_audit_repair_count else "success"
            )
            result.stage_elapsed_seconds["event_audit"] = round(
                time.monotonic() - stage_started, 3
            )

            stage_started = time.monotonic()
            judged: list[dict[str, Any]] = []
            item_contract_repair_count = 0
            for offset in range(0, len(extractions), max_batch):
                batch = extractions[offset : offset + max_batch]
                batch_judged, batch_repair_count = self._judge_batch_with_contract_repair(
                    batch,
                    events,
                )
                judged.extend(batch_judged)
                item_contract_repair_count += batch_repair_count
                if offset + max_batch < len(extractions):
                    time.sleep(1.0)
            result.stage_status["item_judgment"] = (
                "success_after_repair"
                if item_contract_repair_count
                else "success"
            )
            result.stage_elapsed_seconds["item_judgment"] = round(
                time.monotonic() - stage_started, 3
            )
            result.items = judged

            stage_started = time.monotonic()
            rejected = self._audit_items(judged, extractions, events)
            repair_count = len(rejected)
            if rejected:
                repair_sources = [
                    item for item in extractions if item["post_id"] in rejected
                ]
                repaired, repair_contract_count = self._judge_batch_with_contract_repair(
                    repair_sources,
                    events,
                    audit_feedback=rejected,
                )
                item_contract_repair_count += repair_contract_count
                repaired_rejections = self._audit_items(
                    repaired,
                    repair_sources,
                    events,
                )
                if repaired_rejections:
                    details = "；".join(
                        f"{post_id}: {reason}"
                        for post_id, reason in repaired_rejections.items()
                    )
                    raise PipelineContractError("条目审计修正后仍未通过: " + details)
                repaired_by_id = {item["post_id"]: item for item in repaired}
                judged = [repaired_by_id.get(item["post_id"], item) for item in judged]
                result.items = judged
                result.stage_status["item_audit"] = "success_after_repair"
            else:
                result.stage_status["item_audit"] = "success"
            result.stage_elapsed_seconds["item_audit"] = round(
                time.monotonic() - stage_started, 3
            )

            result.author_profiles = _build_author_profiles(judged)
            result.medium_merge = _build_medium_merge(events)
            result.high_count = sum(item["importance"] == "高" for item in judged)
            result.medium_count = sum(item["importance"] == "中" for item in judged)
            result.low_count = sum(item["importance"] == "低" for item in judged)
            result.quality_gate = {
                "input_posts": len(prepared),
                "extracted_posts": len(extractions),
                "judged_posts": len(judged),
                "accepted_events": len(events),
                "event_repair_count": event_repair_count,
                "event_audit_repair_count": event_audit_repair_count,
                "item_contract_repair_count": item_contract_repair_count,
                "all_posts_covered": len(judged) == len(prepared),
                "all_events_audited": True,
                "all_items_audited": True,
                "item_repair_count": repair_count,
            }
            result.status = "success"
        except Exception as exc:
            result.errors.append(f"{exc.__class__.__name__}: {exc}")

        return result

    def _extract_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self.llm.chat_json(STAGE1_SYSTEM, build_stage1_prompt(items))
        raw_items = response.get("items", []) if isinstance(response, dict) else []
        by_id = _unique_records_by_id(raw_items, "post_id", "证据抽取")
        expected_ids = {_post_id(item) for item in items}
        _require_exact_ids(set(by_id), expected_ids, "证据抽取")

        extracted: list[dict[str, Any]] = []
        for item in items:
            post_id = _post_id(item)
            raw = by_id[post_id]
            summary = _required_text(raw, "summary", f"证据抽取 {post_id}")
            event_hint = _required_text(raw, "event_hint", f"证据抽取 {post_id}")
            theme_path = _string_list(raw.get("theme_path"), f"证据抽取 {post_id}.theme_path")
            evidence_type = str(raw.get("evidence_type") or "").strip()
            if evidence_type not in EXTRACTION_TYPES:
                raise PipelineContractError(
                    f"证据抽取 {post_id}.evidence_type 非法: {evidence_type}"
                )
            claims = _string_list(
                raw.get("claims"),
                f"证据抽取 {post_id}.claims",
                allow_empty=True,
            )
            content_full = _source_content(item)
            segments = _source_segments(post_id, content_full)
            segment_map = {segment["quote_id"]: segment["text"] for segment in segments}
            quote_ids = _string_list(
                raw.get("quote_ids"),
                f"证据抽取 {post_id}.quote_ids",
            )
            _require_known_quote_ids(
                quote_ids,
                segment_map,
                f"证据抽取 {post_id}",
            )
            extracted.append(
                {
                    "post_id": post_id,
                    "author": item.get("username") or item.get("用户名", ""),
                    "display_name": item.get("display_name", "")
                    or item.get("username")
                    or item.get("用户名", ""),
                    "url": item.get("url") or item.get("推文链接", ""),
                    "published_at": item.get("published_at")
                    or item.get("发布时间", ""),
                    "content": content_full[:700],
                    "content_full": content_full,
                    "summary": summary,
                    "event_hint": event_hint,
                    "theme_path": theme_path,
                    "evidence_type": evidence_type,
                    "claims": claims,
                    "quote_ids": quote_ids,
                    "quotes": [segment_map[quote_id] for quote_id in quote_ids],
                    "evidence_segments": segments,
                    "followers": item.get("followers", 0),
                    "views": item.get("views", 0),
                    "likes": item.get("likes", 0),
                    "retweets": item.get("retweets", 0),
                }
            )
        return extracted

    def _synthesize_events(
        self,
        extractions: list[dict[str, Any]],
        memory_refs: list[Any],
    ) -> tuple[list[dict[str, Any]], bool, int]:
        prompt = build_stage2a_prompt(extractions, memory_refs, self.rubric)
        response = self.llm.chat_json(STAGE2A_SYSTEM, prompt)
        try:
            events, no_material_events = self._parse_event_response(
                response,
                extractions,
            )
            return events, no_material_events, 0
        except PipelineContractError as first_error:
            repair_payload = json.loads(prompt)
            repair_payload.update(
                {
                    "invalid_response": response,
                    "validation_errors": [str(first_error)],
                    "repair_instruction": (
                        "按 validation_errors 修正，重新返回完整 JSON；不得删除有效证据，"
                        "不得填默认空值，字段含义与原契约相同。"
                    ),
                }
            )
            repaired_response = self.llm.chat_json(
                STAGE2A_SYSTEM,
                json.dumps(repair_payload, ensure_ascii=False, indent=2),
            )
            try:
                events, no_material_events = self._parse_event_response(
                    repaired_response,
                    extractions,
                )
                return events, no_material_events, 1
            except PipelineContractError as repair_error:
                raise PipelineContractError(
                    f"事件首次校验失败: {first_error}；修正后仍失败: {repair_error}"
                ) from repair_error

    def _parse_event_response(
        self,
        response: Any,
        extractions: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        if not isinstance(response, dict):
            raise PipelineContractError("事件生成没有返回 JSON 对象")
        raw_events = response.get("events")
        if not isinstance(raw_events, list):
            raise PipelineContractError("事件生成缺少 events 列表")
        no_material_events = response.get("no_material_events") is True
        materialized_events = _materialize_event_quotes(raw_events, extractions)
        identified_events = _assign_event_identity(materialized_events)
        source_contents = {
            item["post_id"]: item["content_full"] for item in extractions
        }
        valid_events, validation_errors = validate_events(
            identified_events,
            {item["post_id"] for item in extractions},
            source_contents,
        )
        if validation_errors:
            raise PipelineContractError("；".join(validation_errors))
        if not valid_events and not no_material_events:
            raise PipelineContractError("没有生成事件，也没有声明 no_material_events")
        if valid_events and no_material_events:
            raise PipelineContractError("events 非空时 no_material_events 不能为 true")
        return valid_events, no_material_events

    def _audit_events(
        self,
        events: list[dict[str, Any]],
        extractions: list[dict[str, Any]],
        memory_refs: list[Any],
    ) -> dict[str, str]:
        prompt = build_event_audit_prompt(events, extractions, memory_refs)
        response = self.llm.chat_json(STAGE_AUDIT_SYSTEM, prompt)
        verdicts = response.get("verdicts", []) if isinstance(response, dict) else []
        by_id = _unique_records_by_id(verdicts, "event_id", "事件审计")
        expected = {event["event_id"] for event in events}
        _require_exact_ids(set(by_id), expected, "事件审计")
        rejected: dict[str, str] = {}
        for event in events:
            verdict = by_id[event["event_id"]]
            reason = _required_text(verdict, "reason", f"事件审计 {event['event_id']}")
            if verdict.get("accepted") is not True:
                rejected[event["event_id"]] = reason
            event["audit_reason"] = reason
        return rejected

    def _repair_audited_events(
        self,
        events: list[dict[str, Any]],
        extractions: list[dict[str, Any]],
        memory_refs: list[Any],
        audit_feedback: dict[str, str],
    ) -> list[dict[str, Any]]:
        payload = json.loads(
            build_stage2a_prompt(extractions, memory_refs, self.rubric)
        )
        payload.update(
            {
                "current_events": events,
                "audit_feedback": audit_feedback,
                "repair_instruction": (
                    "只修正 audit_feedback 指出的来源归属、事实或推导错误。"
                    "重新返回完整 events；quote_ids 只能从 evidence_segments 选择。"
                ),
            }
        )
        response = self.llm.chat_json(
            STAGE2A_SYSTEM,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        repaired_events, no_material_events = self._parse_event_response(
            response,
            extractions,
        )
        if no_material_events and events:
            raise PipelineContractError("事件审计修正不能把已有事件全部改成无事件")
        return repaired_events

    def _judge_batch_with_contract_repair(
        self,
        items: list[dict[str, Any]],
        events: list[dict[str, Any]],
        audit_feedback: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        prompt = build_stage3_prompt(
            items,
            events,
            self.rubric,
            audit_feedback=audit_feedback,
        )
        response = self.llm.chat_json(STAGE3_SYSTEM, prompt)
        try:
            return self._parse_judgment_response(response, items, events), 0
        except PipelineContractError as first_error:
            repair_payload = json.loads(prompt)
            repair_payload.update(
                {
                    "invalid_response": response,
                    "validation_errors": [str(first_error)],
                    "repair_instruction": (
                        "只修正 validation_errors 指出的字段契约错误，重新返回完整 items；"
                        "不得改变未报错条目的事实、价值和事件归属。"
                    ),
                }
            )
            repaired_response = self.llm.chat_json(
                STAGE3_SYSTEM,
                json.dumps(repair_payload, ensure_ascii=False, indent=2),
            )
            try:
                return self._parse_judgment_response(
                    repaired_response,
                    items,
                    events,
                ), 1
            except PipelineContractError as repair_error:
                raise PipelineContractError(
                    f"条目首次校验失败: {first_error}；修正后仍失败: {repair_error}"
                ) from repair_error

    def _parse_judgment_response(
        self,
        response: Any,
        items: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        raw_items = response.get("items", []) if isinstance(response, dict) else []
        by_id = _unique_records_by_id(raw_items, "post_id", "条目判断")
        expected_ids = {item["post_id"] for item in items}
        _require_exact_ids(set(by_id), expected_ids, "条目判断")
        event_ids = {event["event_id"] for event in events}

        judged: list[dict[str, Any]] = []
        for item in items:
            post_id = item["post_id"]
            raw = by_id[post_id]
            importance = str(raw.get("importance") or "").strip()
            presentation = str(raw.get("presentation") or "").strip()
            if importance not in ITEM_IMPORTANCE:
                raise PipelineContractError(f"条目判断 {post_id}.importance 非法")
            if presentation not in ITEM_PRESENTATION:
                raise PipelineContractError(f"条目判断 {post_id}.presentation 非法")
            linked_events = _string_list(
                raw.get("event_ids"),
                f"条目判断 {post_id}.event_ids",
                allow_empty=True,
            )
            unknown_events = sorted(set(linked_events) - event_ids)
            if unknown_events:
                raise PipelineContractError(
                    f"条目判断 {post_id} 引用了未知事件 {', '.join(unknown_events)}"
                )
            if importance in {"高", "中"} and not linked_events:
                raise PipelineContractError(
                    f"条目判断 {post_id} 为{importance}但没有事件上下文"
                )
            judged_item = dict(item)
            judged_item.update(
                {
                    "importance": importance,
                    "presentation": presentation,
                    "event_ids": linked_events,
                    "summary": _required_text(raw, "summary", f"条目判断 {post_id}"),
                    "why_worth": _required_text(
                        raw, "why_worth", f"条目判断 {post_id}"
                    ),
                }
            )
            support_quote_ids = _string_list(
                raw.get("support_quote_ids"),
                f"条目判断 {post_id}.support_quote_ids",
            )
            segment_map = {
                segment["quote_id"]: segment["text"]
                for segment in item["evidence_segments"]
            }
            _require_known_quote_ids(
                support_quote_ids,
                segment_map,
                f"条目判断 {post_id}",
            )
            judged_item["support_quote_ids"] = support_quote_ids
            judged_item["support_quotes"] = [
                segment_map[quote_id] for quote_id in support_quote_ids
            ]
            judged.append(judged_item)
        return judged

    def _audit_items(
        self,
        judged: list[dict[str, Any]],
        extractions: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> dict[str, str]:
        response = self.llm.chat_json(
            STAGE_ITEM_AUDIT_SYSTEM,
            build_item_audit_prompt(judged, extractions, events),
        )
        verdicts = response.get("verdicts", []) if isinstance(response, dict) else []
        by_id = _unique_records_by_id(verdicts, "post_id", "条目审计")
        expected = {item["post_id"] for item in judged}
        _require_exact_ids(set(by_id), expected, "条目审计")
        rejected: dict[str, str] = {}
        for item in judged:
            verdict = by_id[item["post_id"]]
            reason = _required_text(verdict, "reason", f"条目审计 {item['post_id']}")
            if verdict.get("accepted") is not True:
                rejected[item["post_id"]] = reason
            item["audit_reason"] = reason
        return rejected


def build_stage1_prompt(items: list[dict]) -> str:
    payload = []
    for item in items:
        content = _source_content(item)
        payload.append(
            {
                "post_id": _post_id(item),
                "author": item.get("username") or item.get("用户名", ""),
                "evidence_segments": _source_segments(_post_id(item), content),
            }
        )
    return json.dumps({"items": payload}, ensure_ascii=False, indent=2)


def build_stage2a_prompt(
    extractions: list[dict],
    memory_refs: list[Any] | None = None,
    rubric: str = "",
) -> str:
    items = []
    for item in extractions:
        items.append(
            {
                "post_id": item.get("post_id"),
                "author": item.get("display_name") or item.get("author"),
                "summary": item.get("summary"),
                "event_hint": item.get("event_hint"),
                "theme_path": item.get("theme_path"),
                "evidence_type": item.get("evidence_type"),
                "claims": item.get("claims"),
                "quote_ids": item.get("quote_ids"),
                "evidence_segments": item.get("evidence_segments"),
            }
        )
    return json.dumps(
        {
            "owner_rubric": rubric,
            "previous_judgments": memory_refs or [],
            "items": items,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_event_audit_prompt(
    events: list[dict],
    extractions: list[dict],
    memory_refs: list[Any] | None = None,
) -> str:
    sources = {
        item["post_id"]: {
            "author": item.get("display_name") or item.get("author"),
            "content": str(item.get("content_full") or "")[:1400],
        }
        for item in extractions
        if any(item["post_id"] in event["source_ids"] for event in events)
    }
    return json.dumps(
        {
            "events": events,
            "sources": sources,
            "previous_judgments": memory_refs or [],
        },
        ensure_ascii=False,
        indent=2,
    )


def build_stage3_prompt(
    items: list[dict],
    events: list[dict] | None = None,
    rubric: str = "",
    audit_feedback: dict[str, str] | None = None,
) -> str:
    batch_ids = {item["post_id"] for item in items}
    relevant_events = [
        event
        for event in events or []
        if batch_ids.intersection(event.get("source_ids") or [])
    ]
    payload = [
        {
            "post_id": item["post_id"],
            "author": item.get("display_name") or item.get("author"),
            "content": str(item.get("content_full") or item.get("content") or "")[:1400],
            "evidence_segments": item.get("evidence_segments"),
            "extracted_summary": item.get("summary"),
            "event_hint": item.get("event_hint"),
        }
        for item in items
    ]
    return json.dumps(
        {
            "owner_rubric": rubric,
            "events": relevant_events,
            "items": payload,
            "audit_feedback": audit_feedback or {},
            "repair_instruction": (
                "只修正 audit_feedback 指出的事实或关联错误，字段契约不变。"
                if audit_feedback
                else ""
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def build_item_audit_prompt(
    judged: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    sources = {
        item["post_id"]: {
            "author": item.get("display_name") or item.get("author"),
            "source_segments": item.get("evidence_segments"),
        }
        for item in extractions
    }
    audit_items = [
        {
            "post_id": item["post_id"],
            "importance": item["importance"],
            "presentation": item["presentation"],
            "event_ids": item["event_ids"],
            "summary": item["summary"],
            "why_worth": item["why_worth"],
            "support_quotes": item["support_quotes"],
        }
        for item in judged
    ]
    return json.dumps(
        {"items": audit_items, "sources": sources, "events": events},
        ensure_ascii=False,
        indent=2,
    )


EVENT_REQUIRED_STRINGS = (
    "event_id",
    "title",
    "canonical_topic",
    "thesis",
    "prior_state",
    "judgment_delta",
    "topic_importance",
    "presentation",
    "confidence",
)


def validate_events(
    events: list[dict[str, Any]],
    known_post_ids: set[str],
    source_contents: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_event_ids: set[str] = set()

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append(f"event[{index}]: 不是 JSON 对象")
            continue
        label = str(event.get("event_id") or f"event[{index}]")
        event_errors: list[str] = []
        for field_name in EVENT_REQUIRED_STRINGS:
            if not str(event.get(field_name) or "").strip():
                event_errors.append(f"{label}: 缺少 {field_name}")

        event_id = str(event.get("event_id") or "").strip()
        if event_id in seen_event_ids:
            event_errors.append(f"{label}: event_id 重复")
        if event_id:
            seen_event_ids.add(event_id)

        try:
            _string_list(event.get("theme_path"), f"{label}.theme_path")
        except PipelineContractError as exc:
            event_errors.append(str(exc))

        source_ids = event.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            event_errors.append(f"{label}: source_ids 为空")
            normalized_sources: list[str] = []
        else:
            normalized_sources = [str(post_id).strip() for post_id in source_ids]
            unknown_sources = sorted(set(normalized_sources) - known_post_ids)
            if unknown_sources:
                event_errors.append(f"{label}: 未知来源 {', '.join(unknown_sources)}")
            if len(normalized_sources) != len(set(normalized_sources)):
                event_errors.append(f"{label}: source_ids 重复")

        evidence = event.get("new_evidence")
        evidence_ids: set[str] = set()
        if not isinstance(evidence, list) or not evidence:
            event_errors.append(f"{label}: new_evidence 为空")
        else:
            for item in evidence:
                if not isinstance(item, dict):
                    event_errors.append(f"{label}: new_evidence 格式错误")
                    continue
                post_id = str(item.get("post_id") or "").strip()
                quote_ids = item.get("quote_ids")
                quotes = item.get("quotes")
                claim = str(item.get("claim") or "").strip()
                if (
                    not post_id
                    or not isinstance(quote_ids, list)
                    or not quote_ids
                    or not isinstance(quotes, list)
                    or not quotes
                    or not claim
                ):
                    event_errors.append(f"{label}: 证据缺少 post_id、quote_ids、quotes 或 claim")
                    continue
                evidence_ids.add(post_id)
                if source_contents is not None and post_id in source_contents:
                    for quote in quotes:
                        try:
                            _require_source_quote(
                                str(quote),
                                source_contents[post_id],
                                f"{label} 证据 {post_id}",
                            )
                        except PipelineContractError as exc:
                            event_errors.append(str(exc))
            missing_evidence = sorted(set(normalized_sources) - evidence_ids)
            if missing_evidence:
                event_errors.append(f"{label}: 来源缺少证据 {', '.join(missing_evidence)}")
            extra_evidence = sorted(evidence_ids - set(normalized_sources))
            if extra_evidence:
                event_errors.append(f"{label}: 证据不属于来源 {', '.join(extra_evidence)}")

        try:
            _string_list(event.get("unknowns"), f"{label}.unknowns")
        except PipelineContractError as exc:
            event_errors.append(str(exc))
        if event.get("topic_importance") not in EVENT_IMPORTANCE:
            event_errors.append(f"{label}: topic_importance 非法")
        if event.get("presentation") not in EVENT_PRESENTATION:
            event_errors.append(f"{label}: presentation 非法")
        if event.get("confidence") not in EVENT_CONFIDENCE:
            event_errors.append(f"{label}: confidence 非法")

        if event_errors:
            errors.extend(event_errors)
        else:
            normalized = dict(event)
            normalized["event_id"] = event_id
            normalized["source_ids"] = normalized_sources
            valid.append(normalized)

    return valid, errors


def _assign_event_identity(events: Any) -> list[Any]:
    if not isinstance(events, list):
        return events
    identified: list[Any] = []
    for event in events:
        if not isinstance(event, dict):
            identified.append(event)
            continue
        normalized = dict(event)
        theme_path = event.get("theme_path")
        source_ids = event.get("source_ids")
        if isinstance(theme_path, list) and theme_path:
            normalized["canonical_topic"] = str(theme_path[-1]).strip()
        if isinstance(source_ids, list) and source_ids:
            identity = json.dumps(
                {
                    "topic": normalized.get("canonical_topic", ""),
                    "sources": sorted(str(value) for value in source_ids),
                    "title": normalized.get("title", ""),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
            normalized["event_id"] = f"evt:{digest}"
        identified.append(normalized)
    return identified


def _materialize_event_quotes(
    events: Any,
    extractions: list[dict[str, Any]],
) -> list[Any]:
    if not isinstance(events, list):
        return events
    segment_maps = {
        item["post_id"]: {
            segment["quote_id"]: segment["text"]
            for segment in item["evidence_segments"]
        }
        for item in extractions
    }
    materialized: list[Any] = []
    for event in events:
        if not isinstance(event, dict):
            materialized.append(event)
            continue
        normalized_event = dict(event)
        normalized_evidence = []
        evidence = event.get("new_evidence")
        if isinstance(evidence, list):
            for index, raw in enumerate(evidence):
                if not isinstance(raw, dict):
                    normalized_evidence.append(raw)
                    continue
                normalized = dict(raw)
                post_id = str(raw.get("post_id") or "").strip()
                quote_ids = _string_list(
                    raw.get("quote_ids"),
                    f"事件证据 {post_id or index}.quote_ids",
                )
                segment_map = segment_maps.get(post_id, {})
                _require_known_quote_ids(
                    quote_ids,
                    segment_map,
                    f"事件证据 {post_id or index}",
                )
                normalized["quote_ids"] = quote_ids
                normalized["quotes"] = [
                    segment_map[quote_id] for quote_id in quote_ids
                ]
                normalized_evidence.append(normalized)
        normalized_event["new_evidence"] = normalized_evidence
        materialized.append(normalized_event)
    return materialized


def _build_author_profiles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get("author") or ""), []).append(item)
    rank = {"高": 2, "中": 1, "低": 0}
    profiles = []
    for author, author_items in grouped.items():
        best = max(author_items, key=lambda item: rank[item["importance"]])
        profiles.append(
            {
                "author": author,
                "display_name": best.get("display_name") or author,
                "tweet_count": len(author_items),
                "quality": best["importance"],
                "one_liner": best["summary"][:40],
                "warning": all(item["importance"] == "低" for item in author_items),
            }
        )
    return sorted(profiles, key=lambda profile: (-rank[profile["quality"]], profile["author"]))


def _build_medium_merge(events: list[dict[str, Any]]) -> str:
    briefs = [
        f"{event['title']}：{event['judgment_delta']}"
        for event in events
        if event.get("presentation") == "brief"
    ]
    return "\n".join(briefs)


def _load_rubric(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"owner rubric not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"owner rubric is empty: {path}")
    return text


def _post_id(item: dict[str, Any]) -> str:
    return str(item.get("post_id") or global_post_id(item)).strip()


def _source_content(item: dict[str, Any]) -> str:
    return str(
        item.get("content_full")
        or item.get("content_markdown")
        or item.get("content")
        or item.get("正文")
        or ""
    ).strip()


def _source_segments(post_id: str, source: str, max_chars: int = 360) -> list[dict[str, str]]:
    segments: list[str] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if len(line) <= max_chars:
            segments.append(line)
            continue
        for start in range(0, len(line), max_chars):
            text = line[start : start + max_chars].strip()
            if text:
                segments.append(text)
    return [
        {"quote_id": f"{post_id}:q{index}", "text": text}
        for index, text in enumerate(segments)
    ]


def _require_known_quote_ids(
    quote_ids: list[str],
    segment_map: dict[str, str],
    label: str,
) -> None:
    unknown = sorted(set(quote_ids) - set(segment_map))
    if unknown:
        raise PipelineContractError(
            f"{label} 引用了未知 quote_id: {', '.join(unknown)}"
        )


def _require_source_quote(quote: str, source: str, label: str) -> None:
    normalized_quote = " ".join(quote.split())
    normalized_source = " ".join(source.split())
    if not normalized_quote or normalized_quote not in normalized_source:
        raise PipelineContractError(f"{label} 的 quote 不是原文逐字引句")


def _required_text(record: dict[str, Any], field_name: str, label: str) -> str:
    value = str(record.get(field_name) or "").strip()
    if not value:
        raise PipelineContractError(f"{label} 缺少 {field_name}")
    return value


def _string_list(value: Any, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise PipelineContractError(f"{label} 必须是字符串列表")
    normalized = [str(item).strip() for item in value]
    if any(not item for item in normalized):
        raise PipelineContractError(f"{label} 包含空值")
    if not allow_empty and not normalized:
        raise PipelineContractError(f"{label} 不能为空")
    return normalized


def _unique_records_by_id(
    records: Any,
    field_name: str,
    stage: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        raise PipelineContractError(f"{stage} 缺少列表结果")
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise PipelineContractError(f"{stage} 包含非对象结果")
        record_id = str(record.get(field_name) or "").strip()
        if not record_id:
            raise PipelineContractError(f"{stage} 结果缺少 {field_name}")
        if record_id in by_id:
            raise PipelineContractError(f"{stage} 返回重复 {field_name}: {record_id}")
        by_id[record_id] = record
    return by_id


def _require_exact_ids(actual: set[str], expected: set[str], stage: str) -> None:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    messages = []
    if missing:
        messages.append(f"缺少 {', '.join(missing)}")
    if extra:
        messages.append(f"多出 {', '.join(extra)}")
    if messages:
        raise PipelineContractError(f"{stage} ID 覆盖错误: {'；'.join(messages)}")


def _normalize_importance(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"高", "high"}:
        return "高"
    if normalized in {"中", "medium"}:
        return "中"
    return "低"
