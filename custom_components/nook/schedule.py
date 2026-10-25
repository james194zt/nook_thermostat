"""7-day schedule helpers for Nook."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .const import DAYS, DEFAULT_ECO_TEMP
from .models import ScheduleBlock


def _parse_hhmm(value: str) -> time:
    parts = (value or "00:00").split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return time(hour=hour, minute=minute)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def day_key(now: datetime) -> str:
    # Monday=0 → mon
    return DAYS[now.weekday()]


def running_block(
    schedule: dict[str, list[dict[str, Any]]],
    now: datetime | None = None,
) -> tuple[str, ScheduleBlock] | None:
    """(day it belongs to, block) in charge at `now`, if any.

    - A block that crosses midnight (end before start) runs on into the next
      morning: Monday 22:00–06:30 covers Monday night and Tuesday until 06:30.
    - When blocks overlap, the one that started last is in charge, so a short
      block inside a longer one takes over and the longer one carries on after.
      Same start: the first listed wins. Start == end: an empty block.
    """
    now = now or datetime.now()
    current = _minutes(now.time())
    yesterday = DAYS[(now.weekday() - 1) % 7]
    best: tuple[int, str, ScheduleBlock] | None = None
    for day, offset in ((day_key(now), 0), (yesterday, 24 * 60)):
        for raw in schedule.get(day) or []:
            block = ScheduleBlock.from_dict(raw)
            if not block.enabled:
                continue
            start = _minutes(_parse_hhmm(block.start))
            end = _minutes(_parse_hhmm(block.end))
            if start == end:
                continue
            length = (end - start) % (24 * 60)
            since = current + offset - start  # minutes since this block started
            if 0 <= since < length and (best is None or since < best[0]):
                best = (since, day, block)
    return (best[1], best[2]) if best else None


def active_block(
    schedule: dict[str, list[dict[str, Any]]],
    now: datetime | None = None,
) -> ScheduleBlock | None:
    """Return the schedule block active at `now`, if any (see running_block)."""
    found = running_block(schedule, now)
    return found[1] if found else None


def scheduled_temperature(
    schedule: dict[str, list[dict[str, Any]]],
    *,
    schedule_enabled: bool,
    eco_fallback: float = DEFAULT_ECO_TEMP,
    now: datetime | None = None,
) -> tuple[float, bool]:
    """Return (temperature, schedule_active)."""
    if not schedule_enabled:
        return eco_fallback, False
    block = active_block(schedule, now)
    if block is None:
        return eco_fallback, False
    return block.temperature, True
