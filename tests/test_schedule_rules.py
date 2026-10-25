"""Which schedule block is in charge: overlaps and blocks that cross midnight (needs HA test venv)."""

from datetime import datetime

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.intelligence import active_block_key  # noqa: E402
from custom_components.nook.schedule import (  # noqa: E402
    running_block,
    scheduled_temperature,
)

MON = "2026-10-12"  # a Monday
TUE = "2026-10-13"


def at(day: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00")


def block(start: str, end: str, temp: float, **kw) -> dict:
    return {"start": start, "end": end, "temperature": temp, "enabled": True, **kw}


def temp(schedule, when) -> tuple[float, bool]:
    return scheduled_temperature(schedule, schedule_enabled=True, eco_fallback=16.0, now=when)


def test_short_block_inside_a_long_one_takes_over_then_hands_back():
    schedule = {"mon": [block("16:00", "22:00", 20), block("18:00", "19:00", 22)]}
    assert temp(schedule, at(MON, "17:59")) == (20, True)
    assert temp(schedule, at(MON, "18:00")) == (22, True)
    assert temp(schedule, at(MON, "18:59")) == (22, True)
    assert temp(schedule, at(MON, "19:00")) == (20, True)  # the long block carries on
    assert temp(schedule, at(MON, "22:00")) == (16.0, False)
    assert active_block_key(schedule, at(MON, "18:30")) == "mon|18:00"
    assert active_block_key(schedule, at(MON, "19:30")) == "mon|16:00"


def test_order_in_the_list_doesnt_matter_and_partial_overlap_goes_to_the_later_start():
    schedule = {"mon": [block("21:00", "23:00", 18), block("16:00", "22:00", 20)]}
    assert temp(schedule, at(MON, "20:59")) == (20, True)
    assert temp(schedule, at(MON, "21:30")) == (18, True)
    assert temp(schedule, at(MON, "22:30")) == (18, True)
    assert temp(schedule, at(MON, "23:00")) == (16.0, False)


def test_overnight_block_runs_into_the_next_morning_not_its_own():
    schedule = {"mon": [block("22:00", "06:30", 18)], "tue": []}
    # Monday early morning: Sunday has nothing, so not this block (it starts Monday night).
    assert temp(schedule, at(MON, "02:00")) == (16.0, False)
    assert temp(schedule, at(MON, "22:00")) == (18, True)
    assert temp(schedule, at(TUE, "02:00")) == (18, True)
    assert temp(schedule, at(TUE, "06:29")) == (18, True)
    assert temp(schedule, at(TUE, "06:30")) == (16.0, False)
    # Seasonal Savings keys it to the day it belongs to.
    assert active_block_key(schedule, at(TUE, "02:00")) == "mon|22:00"


def test_sunday_night_runs_into_monday():
    schedule = {"sun": [block("23:00", "01:00", 19)]}
    assert temp(schedule, at(MON, "00:30")) == (19, True)
    assert running_block(schedule, at(MON, "00:30"))[0] == "sun"


def test_morning_block_takes_over_from_last_nights():
    schedule = {"mon": [block("22:00", "08:00", 17)], "tue": [block("06:30", "08:30", 20)]}
    assert temp(schedule, at(TUE, "06:00")) == (17, True)
    assert temp(schedule, at(TUE, "06:30")) == (20, True)
    assert temp(schedule, at(TUE, "08:15")) == (20, True)


def test_disabled_and_empty_blocks_are_ignored():
    schedule = {"mon": [block("16:00", "22:00", 20), block("18:00", "19:00", 22, enabled=False), block("12:00", "12:00", 25)]}
    assert temp(schedule, at(MON, "18:30")) == (20, True)
    assert temp(schedule, at(MON, "12:00")) == (16.0, False)


def test_same_start_first_listed_wins():
    schedule = {"mon": [block("16:00", "22:00", 20), block("16:00", "17:00", 23)]}
    assert temp(schedule, at(MON, "16:30")) == (20, True)
