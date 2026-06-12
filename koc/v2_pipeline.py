"""V2.1 Pipeline — 重写 prompt 解决五大问题

问题:
1. 日报话题空洞(gist为空)
2. 博主画像覆盖率低(23/81)
3. 话题只有讨论者没有具体观点
4. 中质总结太笼统
5. Token 浪费(阶段2同时做3个任务导致不稳定)

改进:
- 阶段1 增强判断准确性，加上具体判断案例
- 阶段2a 独立日报生成(只专注日报)
- 阶段2b 独立博主画像(只专注画像，覆盖所有人)
- 阶段2c 中质量逐条合并总结
- 阶段3 不变
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .llm import LlmClient

# ── 阶段 1: 质量分类 ────────────────────────────

STAGE1_SYSTEM = """你是 X/Twitter 信息筛选助手。对每条推文判断价值：低 / 中 / 高，并附一句话摘要。

## 判断标准

高价值：信息有行动导向
- 具体可操作的步骤、教程、入口（如"访问链接→登记→领空投"）
- 新功能/产品首发消息，且说了影响
- 可以学习的方法或思路，且说了怎么用

中价值：信息有增量但不需要看原文
- 观点+分析但缺乏具体证据
- 背景介绍/规则说明但细节不需要展开
- 行业消息+数字，但不涉及自己的操作

低价值：信息没有实质内容
- 纯情绪、吐槽、抱怨、段子
- 广告/软文/营销推广无实质内容
- 个人生活流水账
- "XX很火/XX涨了"等无分析的感受分享

## 关键区分（重要）

区分"参与证明"（低）vs "参与教程"（高）：
  - "我参加了XX活动"→低
  - "参加XX活动的步骤：1.打开链接 2.填表 3.领取"→高

区分"感受"（低）vs "观点+证据"（中）：
  - "BTC跌了，好惨"→低
  - "BTC跌到X价位，原因是Y，影响的方面有Z"→中

区分"消息转发"（中）vs"带了分析的消息"（高）：
  - "Visa要做稳定币结算"→中
  - "Visa做稳定币结算→意味着合规资金入局→利好合规稳定币→建议关注XX"→高

不确定时标中，不要标高。

返回 JSON: {"items": [{"post_id": "数字index", "importance": "低|中|高", "summary": "一句话中文摘要"}]}"""


def build_stage1_prompt(items: list[dict]) -> str:
    payload = []
    for i, item in enumerate(items):
        content = (item.get("content_markdown") or item.get("正文") or "").strip()
        if len(content) > 800:
            content = content[:800] + "..."
        payload.append({
            "post_id": str(i),
            "author": item.get("username") or item.get("用户名", ""),
            "content": content,
        })
    return json.dumps({"items": payload}, ensure_ascii=False, indent=2)


# ── 阶段 2a: 日报生成 ────────────────────────────

STAGE2A_SYSTEM = """基于推文的分类结果和摘要，写一份日报。

## 要求

1. 识别 3-5 个主要话题
2. 每个话题必须包含:
   - topic: 话题名称(10字以内)
   - who: 讨论该话题的博主(用他们的display_name，不是@handle)
   - what_they_said: 每位博主在这个话题上的具体观点。格式: "name: 观点"。
     比如 "余烬: 认为SpaceX首日涨幅有限。BlockBeats: 报道了中签率数据。"
   - gist: 一段话概括这个话题的核心信息(80-150字)，让不了解背景的人也能看懂
3. 话题按热度排序。热度=讨论人数。
4. 如果一个话题只有一个博主在说，不应该成为话题。合并到相似话题。
5. 如果某个博主的推文不属于任何热门话题，放"其他"部分一笔带过。

## 日报示例

{
  "topics": [
    {
      "topic": "SpaceX IPO打新",
      "who": "余烬, BlockBeats, RK_Bitcoin, lumaogou_web3",
      "sentiment": "多数参与但理性",
      "what_they_said": "余烬: 分析首日涨幅历史数据，认为不宜追高。BlockBeats: 报道币安中签率低于10%。RK_Bitcoin: 对比了各交易平台的打新规则。lumaogou_web3: 整理了打新操作流程。",
      "gist": "SpaceX今晚挂牌，引发全民打新热。币安SPCX募资5.57亿USDC中签率不足10%。多个平台(Bitget/Gate/OKX)推出不同打新规则。理性声音提醒：历次热门IPO首日涨幅与长期回报相关性低。"
    }
  ]
}

返回 JSON: {"topics": [...]}"""  # noqa


def build_stage2a_prompt(stage1_results: list[dict]) -> str:
    """构建日报提示词——传全部分类结果"""
    return json.dumps({
        "instruction": "生成日报。每个话题必须包含what_they_said字段，写出每位博主的具体观点。",
        "items": stage1_results,
    }, ensure_ascii=False, indent=2)


# ── 阶段 2b: 博主画像 ────────────────────────────

STAGE2B_SYSTEM = """基于推文分类结果，为所有在今天发过推文的博主生成一句话画像。

## 要求
- 覆盖率: 所有发过推的博主都需要画像，不能遗漏
- 每个画像: quality(今日整体质量高/中/低) + one_liner(15字内)
- 质量判断: 全高→高，至少1高→偏高，全低→低，其余→中
- 如果有博主连续多天低质量，标注 warning: true

## 输出示例
{"profiles": [{"author": "wublockchain12", "display_name": "吴说区块链", "tweet_count": 19, "quality": "高", "one_liner": "加密行业动态日报", "warning": false}]}

返回 JSON: {"profiles": [...]}"""


def build_stage2b_prompt(stage1_results: list[dict]) -> str:
    """只传author+summary+importance，确保覆盖所有人"""
    items = []
    for r in stage1_results:
        items.append({
            "author": r.get("author", ""),
            "display_name": r.get("display_name", "") or r.get("author", ""),
            "importance": r.get("importance", ""),
            "summary": r.get("summary", ""),
        })
    return json.dumps({"items": items, "total_authors": len(set(r.get("author","") for r in stage1_results))}, ensure_ascii=False, indent=2)


# ── 阶段 2c: 中质量合并总结 ──────────────────────

STAGE2C_SYSTEM = """基于标注为"中"的推文，生成合并总结。

## 要求
- 按话题组织，2-3段
- 每段概括同一话题下所有中等价值推文的核心信息
- 让读者不用点开原文也能获取信息增量
- 不要只说"这些内容一般"

## 输出示例
{"medium_merge": "在加密市场方面: hanking66认为当前是最恐慌时刻应该买入... murphy分析了矿工收益创历史新低的影响... 在行业进展方面: wublockchain12报道了Uniswap销毁近600万UNI..."}

返回 JSON: {"medium_merge": "..."}"""  # noqa


def build_stage2c_prompt(stage1_results: list[dict]) -> str:
    medium_items = [
        {"author": r.get("display_name","") or r.get("author",""),
         "summary": r.get("summary","")}
        for r in stage1_results if r.get("importance") == "中"
    ]
    return json.dumps({"medium_items": medium_items}, ensure_ascii=False, indent=2)


# ── 阶段 3: 高价值深读 ──────────────────────────

STAGE3_SYSTEM = """你是 X/Twitter 深度分析助手。解释"为什么值得关注"。

每条推文输出 why_worth(30-60字)，解释:
- 这条信息为什么重要
- 对读者的实际价值是什么

返回 JSON: {"analyses": [{"post_id": "...", "why_worth": "..."}]}"""


def build_stage3_prompt(high_value_items: list[dict]) -> str:
    payload = []
    for item in high_value_items:
        content = (item.get("content_full") or item.get("content_markdown") or item.get("正文") or "").strip()
        author = item.get("display_name") or item.get("author") or ""
        payload.append({"post_id": item.get("post_id", ""), "author": author, "content": content})
    return json.dumps({"high_value_items": payload}, ensure_ascii=False, indent=2)


# ── Pipeline Runner ─────────────────────────────

@dataclass
class PipelineResult:
    run_id: str = ""
    created_at: str = ""
    window: str = "12h"
    total_tweets: int = 0
    authors_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    daily_brief: list[dict[str, Any]] = field(default_factory=list)
    author_profiles: list[dict[str, Any]] = field(default_factory=list)
    medium_merge: str = ""
    errors: list[str] = field(default_factory=list)


class V2Pipeline:
    """V2.1 流水线: 阶段1→阶段2a(日报)→阶段2b(画像)→阶段2c(中质)→阶段3(深读)。"""

    def __init__(self, llm: LlmClient | None = None):
        self.llm = llm or LlmClient(timeout=90, max_retries=1)

    def run(self, items: list[dict], max_batch: int = 60) -> PipelineResult:
        now = datetime.now(timezone.utc)
        result = PipelineResult(
            run_id=now.strftime("v2-%Y%m%d-%H%M%S"),
            created_at=now.strftime("%Y-%m-%d %H:%M UTC+8"),
            window="12h",
            total_tweets=len(items),
            authors_count=len(set(
                item.get("username") or item.get("用户名", "") for item in items
            )),
        )
        if not items:
            result.errors.append("没有推文数据")
            return result

        try:
            # 阶段1: 分批质量分类
            all_classifications = []
            for i in range(0, len(items), max_batch):
                batch = items[i:i + max_batch]
                batch_result = PipelineResult()
                self._run_stage1(batch, batch_result)
                all_classifications.extend(batch_result.items)
                result.high_count += batch_result.high_count
                result.medium_count += batch_result.medium_count
                result.low_count += batch_result.low_count
                if i + max_batch < len(items):
                    import time
                    time.sleep(1.0)

            result.items = all_classifications

            # 阶段2a: 日报
            self._run_stage2a(all_classifications, result)
            # 阶段2b: 博主画像
            self._run_stage2b(all_classifications, result)
            # 阶段2c: 中质量总结
            self._run_stage2c(all_classifications, result)
            # 阶段3: 高价值深读
            self._run_stage3(result)
        except Exception as exc:
            result.errors.append(f"流水线异常: {exc}")

        return result

    def _run_stage1(self, items: list[dict], result: PipelineResult):
        prompt = build_stage1_prompt(items)
        response = self.llm.chat_json(STAGE1_SYSTEM, prompt)

        raw_items = response.get("items", []) if isinstance(response, dict) else []
        by_id = {}
        for raw in raw_items:
            pid = str(raw.get("post_id", "")).strip()
            if pid:
                by_id[pid] = raw

        for i, item in enumerate(items):
            pid = str(i)
            raw = by_id.get(pid, {})
            importance = _normalize_importance(raw.get("importance", ""))
            summary = (raw.get("summary") or "").strip() or "无内容"
            classification = {
                "post_id": pid,
                "author": item.get("username") or item.get("用户名", ""),
                "display_name": item.get("display_name", "") or item.get("username") or "",
                "url": item.get("url") or item.get("推文链接", ""),
                "content": (item.get("content_markdown") or item.get("正文", ""))[:500],
                "content_full": (item.get("content_markdown") or item.get("正文", "")),
                "published_at": item.get("published_at") or item.get("发布时间", ""),
                "importance": importance,
                "summary": summary,
                "followers": item.get("followers", 0),
                "views": item.get("views", 0),
                "likes": item.get("likes", 0),
                "retweets": item.get("retweets", 0),
            }
            result.items.append(classification)
            if importance == "高":
                result.high_count += 1
            elif importance == "中":
                result.medium_count += 1
            else:
                result.low_count += 1

    def _run_stage2a(self, classifications: list[dict], result: PipelineResult):
        """只做日报"""
        prompt = build_stage2a_prompt(classifications)
        response = self.llm.chat_json(STAGE2A_SYSTEM, prompt)
        topics = response.get("topics", []) if isinstance(response, dict) else []
        result.daily_brief = [{
            "topic": t.get("topic", ""),
            "who": t.get("who", ""),
            "sentiment": t.get("sentiment", ""),
            "what_they_said": t.get("what_they_said", ""),
            "gist": t.get("gist", ""),
        } for t in topics if isinstance(t, dict)]

    def _run_stage2b(self, classifications: list[dict], result: PipelineResult):
        """只做博主画像"""
        prompt = build_stage2b_prompt(classifications)
        response = self.llm.chat_json(STAGE2B_SYSTEM, prompt)
        profiles = response.get("profiles", []) if isinstance(response, dict) else []
        result.author_profiles = [{
            "author": p.get("author", ""),
            "display_name": p.get("display_name", "") or p.get("author", ""),
            "tweet_count": p.get("tweet_count", 0),
            "quality": p.get("quality", ""),
            "one_liner": p.get("one_liner", ""),
            "warning": p.get("warning", False),
        } for p in profiles if isinstance(p, dict)]

    def _run_stage2c(self, classifications: list[dict], result: PipelineResult):
        """只做中质量总结"""
        mids = [c for c in classifications if c.get("importance") == "中"]
        if not mids:
            return
        prompt = build_stage2c_prompt(classifications)
        response = self.llm.chat_json(STAGE2C_SYSTEM, prompt)
        result.medium_merge = str(response.get("medium_merge", "")) if isinstance(response, dict) else ""

    def _run_stage3(self, result: PipelineResult):
        high_items = [item for item in result.items if item.get("importance") == "高"]
        if not high_items:
            return
        prompt = build_stage3_prompt(high_items)
        response = self.llm.chat_json(STAGE3_SYSTEM, prompt)
        analyses = response.get("analyses", []) if isinstance(response, dict) else []
        by_id = {}
        for a in analyses:
            pid = str(a.get("post_id", "")).strip()
            if pid:
                by_id[pid] = a.get("why_worth", "")
        for item in result.items:
            if item.get("importance") == "高":
                item["why_worth"] = by_id.get(item["post_id"], "")


def _normalize_importance(val: str) -> str:
    v = val.strip()
    if v in ("高", "high"):
        return "高"
    if v in ("中", "medium"):
        return "中"
    return "低"
