from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone


BEIJING = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class ReportWindow:
    slot: str
    label: str
    planned_at: datetime
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    delay_seconds: int


def resolve_report_window(now: datetime | None = None) -> ReportWindow:
    """Resolve the fixed Beijing-time report slot for a run."""
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_now = generated_at.astimezone(BEIJING)
    local_date = local_now.date()

    if local_now.time() < time(9, 0):
        planned_local = datetime.combine(local_date - timedelta(days=1), time(21, 0), tzinfo=BEIJING)
        window_start_local = datetime.combine(local_date - timedelta(days=1), time(9, 0), tzinfo=BEIJING)
        slot = "evening"
        label = "晚报"
    elif local_now.time() < time(21, 0):
        planned_local = datetime.combine(local_date, time(9, 0), tzinfo=BEIJING)
        window_start_local = datetime.combine(local_date - timedelta(days=1), time(21, 0), tzinfo=BEIJING)
        slot = "morning"
        label = "早报"
    else:
        planned_local = datetime.combine(local_date, time(21, 0), tzinfo=BEIJING)
        window_start_local = datetime.combine(local_date, time(9, 0), tzinfo=BEIJING)
        slot = "evening"
        label = "晚报"

    planned_at = planned_local.astimezone(timezone.utc)
    return ReportWindow(
        slot=slot,
        label=label,
        planned_at=planned_at,
        window_start=window_start_local.astimezone(timezone.utc),
        window_end=planned_at,
        generated_at=generated_at,
        delay_seconds=max(0, int((generated_at - planned_at).total_seconds())),
    )


def format_beijing(value: datetime) -> str:
    return value.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
