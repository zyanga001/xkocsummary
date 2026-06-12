from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILES = (PROJECT_ROOT / ".env", PROJECT_ROOT / "config.local")


def get_config_value(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    if os.getenv("KOC_DISABLE_LOCAL_CONFIG"):
        return None
    local = load_local_config()
    return local.get(name)


def load_local_config() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in CONFIG_FILES:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in values:
                values[key] = value
    return values
