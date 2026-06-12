from __future__ import annotations

import json


class Progress:
    def __init__(self, stage: str, enabled: bool = True) -> None:
        self.stage = stage
        self.enabled = enabled

    def log(self, message: str) -> None:
        if self.enabled:
            print(f"[{self.stage}] {message}", flush=True)


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
