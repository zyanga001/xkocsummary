from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ScannerConfig:
    timeout: int
    max_retries: int
    request_delay: float
    max_workers: int


LOCAL_SCANNER_CONFIG = ScannerConfig(
    timeout=15,
    max_retries=3,
    request_delay=0.3,
    max_workers=4,
)

GITHUB_ACTIONS_SCANNER_CONFIG = ScannerConfig(
    timeout=8,
    max_retries=1,
    request_delay=0.1,
    max_workers=8,
)


def scanner_config_from_env(env: Mapping[str, str]) -> ScannerConfig:
    if env.get("GITHUB_ACTIONS", "").lower() == "true":
        return GITHUB_ACTIONS_SCANNER_CONFIG
    return LOCAL_SCANNER_CONFIG
