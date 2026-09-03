from __future__ import annotations

import argparse
import json
import sys

from .output import Progress
from .v2_eval import run_eval


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m koc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_v2 = subparsers.add_parser("run-v2", help="Generate the twice-daily intelligence report")
    run_v2.add_argument("--watchlist", default="watchlist.txt")
    run_v2.add_argument("--output", default="output")
    run_v2.add_argument("--schedule", default="config/schedule.json")
    run_v2.add_argument("--format", choices=("human", "json"), default="human")
    run_v2.set_defaults(func=command_run_v2)

    eval_v2 = subparsers.add_parser("eval-v2", help="Evaluate AI labels against human judgments")
    eval_v2.add_argument("--watchlist", default="watchlist.txt")
    eval_v2.add_argument("--golden", default="eval/data/评价结果.csv")
    eval_v2.add_argument("--output", default="data/v2")
    eval_v2.add_argument("--format", choices=("human", "json"), default="human")
    eval_v2.set_defaults(func=command_eval_v2)
    return parser


def command_run_v2(args: argparse.Namespace) -> int:
    from run_brief import main as run_brief_main

    return run_brief_main(
        output_dir=args.output,
        watchlist_path=args.watchlist,
        schedule_path=args.schedule,
    )


def command_eval_v2(args: argparse.Namespace) -> int:
    progress = Progress("eval-v2", enabled=args.format == "human")
    progress.log(f"金色数据集: {args.golden}")
    progress.log(f"评估输出目录: {args.output}")
    results = run_eval(
        watchlist_path=args.watchlist,
        golden_path=args.golden,
        output_dir=args.output,
    )
    if args.format == "json":
        from .output import print_json

        print_json(results)
        return 0
    if "error" in results:
        print(f"\n错误: {results['error']}")
        return 1

    from .v2_eval import optimize_prompt

    suggestions = optimize_prompt(results)
    if suggestions:
        print("\nPrompt优化建议:")
        for suggestion in suggestions:
            print(f"  {suggestion}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stage": "cli",
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                    "can_continue": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
