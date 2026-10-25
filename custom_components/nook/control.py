"""Pure heat-demand decisions (stdlib only, unit-testable without HA)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .const import DAYS
from .schedule import _parse_hhmm

# Never let the cut-off get closer than this to the cut-in point, otherwise
# the boiler short-cycles on sensor noise.
MIN_HYSTERESIS_C = 0.2


def house_off_threshold(
    target: float,
    *,
    cold_tolerance: float,
    hot_tolerance: float,
    true_radiant: bool,
    coast_c: float,
) -> float:
    """Temperature at which a running house call stops.

    True Radiant pulls the cut-off down by ``coast_c``: how far the house is
    measured to keep warming after the boiler stops (see intelligence.py).
    """
    off_at = target + hot_tolerance
    if true_radiant:
        off_at -= max(0.0, coast_c)
    return max(off_at, target - cold_tolerance + MIN_HYSTERESIS_C)


def house_calls_for_heat(
    current: float | None,
    target: float,
    *,
    was_calling: bool,
    cold_tolerance: float,
    hot_tolerance: float,
    true_radiant: bool,
    coast_c: float,
) -> bool:
    """Hysteresis thermostat: cut in below target-cold, cut out at off threshold."""
    if current is None:
        return False
    if was_calling:
        return current < house_off_threshold(
            target,
            cold_tolerance=cold_tolerance,
            hot_tolerance=hot_tolerance,
            true_radiant=true_radiant,
            coast_c=coast_c,
        )
    return current <= target - cold_tolerance


def room_calls_for_heat(
    current: float | None,
    target: float,
    *,
    was_calling: bool,
    cold_tolerance: float,
    hot_tolerance: float,
) -> bool:
    """Same hysteresis for a room (no radiant coast: the TRV throttles itself)."""
    if current is None:
        return False
    if was_calling:
        return current < target + hot_tolerance
    return current <= target - cold_tolerance


def boiler_cycle_guard(
    want_on: bool,
    is_on: bool,
    seconds_in_state: float | None,
    *,
    min_on_seconds: float,
    min_off_seconds: float,
) -> tuple[bool, float]:
    """Anti-short-cycle: return (command_on, seconds_until_change_allowed).

    Once the boiler call starts it runs at least min_on; once it stops it
    stays off at least min_off, measured from the heater's own last change
    (so manual toggles count too).
    """
    if want_on == is_on or seconds_in_state is None:
        return want_on, 0.0
    minimum = min_on_seconds if is_on else min_off_seconds
    if minimum <= 0:
        return want_on, 0.0
    # A clock that jumped backwards must not stretch the hold.
    remaining = minimum - max(0.0, seconds_in_state)
    if remaining > 0:
        return is_on, remaining
    return want_on, 0.0


def next_schedule_change(
    schedule: dict[str, list[dict[str, Any]]],
    now: datetime,
) -> datetime | None:
    """Next block start or end after `now` (when a manual hold should expire)."""
    best: datetime | None = None
    for day_offset in range(-1, 8):
        day = (now + timedelta(days=day_offset)).date()
        for raw in schedule.get(DAYS[day.weekday()]) or []:
            if not raw.get("enabled", True):
                continue
            start = datetime.combine(day, _parse_hhmm(str(raw.get("start", "06:00"))))
            end = datetime.combine(day, _parse_hhmm(str(raw.get("end", "22:00"))))
            if end <= start:
                end += timedelta(days=1)
            for edge in (start, end):
                if edge > now and (best is None or edge < best):
                    best = edge
    return best
