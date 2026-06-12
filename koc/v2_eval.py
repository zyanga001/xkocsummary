"""V2 Prompt 优化工具。

优化循环：跑V2 → 对AI判断 vs 人工标注 → 计算准确率 → 调整Prompt → 再跑
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def load_golden_dataset(csv_path: str | Path) -> list[dict]:
    """加载人工评价的推文作为基准数据集。

    返回: [{"用户名": ..., "推文链接": ..., "正文": ..., "人工质量": "高/中/低"}]
    """
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            val = r.get("信息价值", "").strip()
            if val in ("低", "中", "高"):
                rows.append({
                    "username": r.get("用户名", ""),
                    "url": r.get("推文链接", ""),
                    "content": r.get("正文", ""),
                    "human_label": val,
                })
    return rows


def classify_tweet(content: str, llm) -> str:
    """用当前V2阶段1的prompt对一条推文做质量判断。"""
    from .v2_pipeline import STAGE1_SYSTEM, build_stage1_prompt

    items = [{"username": "test", "content_markdown": content, "正文": content}]
    prompt = build_stage1_prompt(items)
    response = llm.chat_json(STAGE1_SYSTEM, prompt)

    items_out = response.get("items", []) if isinstance(response, dict) else []
    if items_out:
        imp = items_out[0].get("importance", "")
        if imp in ("高", "medium"):
            return "高"
        if imp in ("中",):
            return "中"
    return "低"


def compare(golden: list[dict]) -> dict:
    """对比AI判断 vs 人工标注，返回准确率矩阵。

    不调用AI，仅对比已有数据中的AI判断和人工标注。
    ai_label可从已运行的pipeline结果(JSON)中获取。
    """
    results = {
        "total": len(golden),
        "correct": 0,
        "matrix": {
            "低→低": 0, "低→中": 0, "低→高": 0,
            "中→低": 0, "中→中": 0, "中→高": 0,
            "高→低": 0, "高→中": 0, "高→高": 0,
        },
        "errors": [],
    }

    for item in golden:
        human = item.get("human_label", "?")
        ai = item.get("ai_label", "?")
        key = f"{human}→{ai}"
        if key in results["matrix"]:
            results["matrix"][key] += 1
        if human == ai:
            results["correct"] += 1
        else:
            results["errors"].append({
                "url": item.get("url", ""),
                "human": human,
                "ai": ai,
                "content_snippet": item.get("content", "")[:100],
            })

    results["accuracy"] = results["correct"] / results["total"] if results["total"] else 0
    return results


def run_eval(
    watchlist_path: str | Path,
    golden_path: str | Path,
    output_dir: str | Path,
) -> dict:
    """运行完整评估：V2 pipeline + golden dataset 对比。

    策略:
    1. 跑V2（同run-v2命令），得到AI判断的每条推文质量标签
    2. 加载人工评价的金色数据集
    3. 用推文链接做join，找到交集
    4. 对比AI标签 vs 人工标签，输出准确率矩阵
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load golden
    golden = load_golden_dataset(golden_path)
    golden_by_url = {g["url"]: g for g in golden}

    # Load latest V2 results
    latest_run = None
    v2_dir = output_dir
    for date_dir in sorted(v2_dir.iterdir(), reverse=True):
        if date_dir.is_dir():
            run_json = date_dir / "run.json"
            if run_json.exists():
                latest_run = run_json
                break

    if not latest_run:
        # Try latest.html's source data
        return {"error": "没有找到V2运行结果，请先运行 run-v2"}

    run_data = json.loads(latest_run.read_text(encoding="utf-8"))
    items = run_data.get("items", [])

    # Match by URL
    matched = []
    for item in items:
        url = item.get("url", "")
        if url in golden_by_url:
            g = golden_by_url[url]
            g["ai_label"] = item.get("importance", "")
            matched.append(g)

    if not matched:
        return {
            "error": f"V2结果中没有推文与评价数据集匹配。检查是否用同一批推文？",
            "v2_items": len(items),
            "golden_items": len(golden),
            "sample_v2_urls": [i.get("url","")[:60] for i in items[:3]],
            "sample_golden_urls": [g["url"][:60] for g in golden[:3]],
        }

    # Compare
    results = compare(matched)
    results["matched_count"] = len(matched)
    results["timestamp"] = datetime.now().isoformat()

    # Save evaluation report
    report_path = output_dir / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))

    print_eval_report(results)
    return results


def print_eval_report(results: dict) -> None:
    """打印可读的评估报告。"""
    print()
    print("=" * 50)
    print("AI 质量判断 vs 人工标注 对比报告")
    print("=" * 50)
    if "error" in results:
        print(f"错误: {results['error']}")
        return

    n = results["matched_count"]
    acc = results["accuracy"]
    print(f"匹配推文数: {n}")
    print(f"准确率: {acc:.0%} ({results['correct']}/{n})")
    print()
    print("混淆矩阵 (人工→AI):")
    m = results["matrix"]
    for key in ["低→低", "低→中", "低→高", "中→低", "中→中", "中→高", "高→低", "高→中", "高→高"]:
        count = m.get(key, 0)
        bar = "█" * count if key.endswith(key[0]) else "·" * min(count, 20)
        print(f"  {key}: {count:>3} {bar}")

    print()
    print("错误详情（前10条）:")
    for err in results.get("errors", [])[:10]:
        print(f"  [{err['human']}→{err['ai']}] {err['content_snippet'][:80]}...")


def optimize_prompt(results: dict) -> list[str]:
    """根据评估结果，自动生成prompt优化建议。

    分析AI判断最常见的错误类型，给出针对性的prompt修改建议。
    """
    suggestions = []
    errors = results.get("errors", [])
    if not errors:
        return ["准确率完美，无需优化。"]

    # 统计错误类型
    from collections import Counter
    error_types = Counter(f"{e['human']}→{e['ai']}" for e in errors)

    # 最多漏判的高价值（高→低 或 高→中）
    missed_high = error_types.get("高→低", 0) + error_types.get("高→中", 0)
    if missed_high > 0:
        suggestions.append(
            f"⚠ 漏判 {missed_high} 条高价值推文。"
            f"提高判断标准需要增加对'可操作内容'和'新项目首发'的敏感度。"
            f"可在提示词中增加正例关键词：空投、教程、注册入口、新功能、新品。"
        )

    # 最多误判的低价值（低→高 或 低→中）
    false_high = error_types.get("低→高", 0) + error_types.get("低→中", 0)
    if false_high > 0:
        suggestions.append(
            f"⚠ 误判 {false_high} 条低价值推文为有价值。"
            f"需要在判断标准中强化'情绪输出、段子、广告软文、个人生活'的过滤。"
            f"增加反例：什么也没说、证明某件事、吐槽、炫耀、广告推广。"
        )

    # 中低混淆
    mid_low_confusion = error_types.get("中→低", 0) + error_types.get("低→中", 0)
    if mid_low_confusion > 0:
        suggestions.append(
            f"ℹ 中/低混淆 {mid_low_confusion} 条。这两类的边界模糊，"
            f"调整摘要输出要求让AI更准确地概括信息实质，减少误判。"
        )

    if not suggestions:
        suggestions.append("错误分布均匀，建议逐条查看错误案例手动调整prompt。")

    return suggestions
