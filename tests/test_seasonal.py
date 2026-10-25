"""Seasonal Savings and cold-weather preheat (needs HA test venv).

Run: <venv>/bin/python -m pytest tests/test_seasonal.py
"""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.intelligence import (  # noqa: E402
    LONG_PREHEAT_MINUTES,
    MAX_PREHEAT_MINUTES,
    IntelligenceState,
    SeasonalSavingsState,
    WarmupModel,
    estimate_preheat_minutes,
    preheat_status,
    seasonal_bake,
    seasonal_push_back,
    seasonal_savings_step,
)
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401

START = datetime(2026, 10, 12, 12, 0)  # a Monday
BLOCKS = [
    {"start": "06:30", "end": "08:30", "temperature": 20.0, "enabled": True},
    {"start": "16:00", "end": "22:00", "temperature": 21.0, "enabled": True},
]
SCHEDULE = {d: [dict(b) for b in BLOCKS] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def _step(state, day, enabled=True):
    return seasonal_savings_step(state, SCHEDULE, enabled=enabled, now=START + timedelta(days=day))


def test_lowers_every_block_a_step_every_three_days_up_to_the_max():
    state = SeasonalSavingsState()
    info, changed = _step(state, 0)
    assert changed and info["active"] and not info["finished"]
    assert set(state.offsets.values()) == {-0.1}
    assert len(state.offsets) == 14
    assert _step(state, 1)[1] is False  # not due yet
    for day in (3, 6, 9, 12, 15, 18):
        _step(state, day)
    assert set(state.offsets.values()) == {-0.5}
    info, _ = _step(state, 21)
    assert info["finished"] and info["offset_c"] == -0.5 and info["blocks_lowered"] == 14


def test_turning_a_block_up_eases_it_off_for_good():
    state = SeasonalSavingsState()
    for day in (0, 3, 6):
        _step(state, day)
    assert seasonal_push_back(state, "mon|16:00")
    assert state.offsets["mon|16:00"] == -0.2
    assert not seasonal_push_back(state, "mon|16:00")  # only once
    for day in (9, 12):
        _step(state, day)
    assert state.offsets["mon|16:00"] == -0.2
    assert state.offsets["tue|16:00"] == -0.5
    assert _step(state, 12)[0]["blocks_kept"] == 1


def test_bake_writes_the_result_into_the_schedule():
    state = SeasonalSavingsState()
    for day in (0, 3, 6):
        _step(state, day)
    seasonal_push_back(state, "mon|06:30")
    schedule, count = seasonal_bake(SCHEDULE, state)
    assert count == 14
    assert schedule["mon"][0]["temperature"] == 19.8
    assert schedule["tue"][0]["temperature"] == 19.7
    assert schedule["tue"][1]["temperature"] == 20.7
    assert SCHEDULE["tue"][1]["temperature"] == 21.0  # input untouched


def test_off_does_nothing_and_state_survives_restart():
    state = SeasonalSavingsState()
    info, changed = _step(state, 0, enabled=False)
    assert not info["active"] and not changed and state.offsets == {}
    _step(state, 0)
    seasonal_push_back(state, "wed|06:30")
    whole = IntelligenceState(seasonal=state)
    assert IntelligenceState.from_dict(whole.to_dict()).seasonal == state
    # A run started by 0.6.15 or older only had started_at.
    old = IntelligenceState.from_dict({"seasonal": {"started_at": START.isoformat()}}).seasonal
    assert old.started_at == START.isoformat() and old.offsets == {}


def test_preheat_aims_for_the_lowered_temperature():
    status = preheat_status(
        SCHEDULE,
        schedule_enabled=True,
        true_radiant=True,
        current_temp=18.5,
        warmup=WarmupModel(c_per_hour=2.0),
        outdoor_temp=None,
        away_eco_active=False,
        offsets={"mon|16:00": -0.5},
        now=datetime(2026, 10, 12, 15, 0),
    )
    # 18.5 → 20.5 (not 21) at 2 °C/h = 60 min + 5 → from 14:55.
    assert status["preheating"] is True
    assert status["temperature"] == 20.5
    assert status["block_key"] == "mon|16:00"
    assert status["preheat_minutes"] == 65


def test_cold_weather_preheat_allows_four_hours():
    slow = WarmupModel(c_per_hour=1.0)
    kw = dict(current_temp=16.0, target_temp=20.0, warmup=slow)
    assert estimate_preheat_minutes(**kw) == MAX_PREHEAT_MINUTES == 120
    assert estimate_preheat_minutes(**kw, max_minutes=LONG_PREHEAT_MINUTES) == 240


# --- the real coordinator -----------------------------------------------------


async def test_coordinator_runs_seasonal_savings_to_the_end(hass, setup, freezer):
    coord, _ = setup
    start = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")
    freezer.move_to(start)
    await coord.async_save_config({"seasonal_savings": True})
    data = await _tick(hass, coord)
    assert data["main"]["effective_target"] == 19.9
    assert data["seasonal_savings"]["active"] is True

    # Too cool: the dial goes up during the evening block.
    freezer.move_to(start + timedelta(minutes=10))
    coord.set_main_temperature(20.5)
    await hass.async_block_till_done()
    assert coord.intel.state.seasonal.kept == ["mon|16:00"]

    for day in (3, 6, 9, 12, 15, 18):
        freezer.move_to(start + timedelta(days=day, hours=1))
        await _tick(hass, coord)
    freezer.move_to(start + timedelta(days=21, hours=1))
    await _tick(hass, coord)
    await hass.async_block_till_done()

    assert coord.config.seasonal_savings is False
    mon = coord.config.schedule["mon"]
    assert [b["temperature"] for b in mon] == [19.5, 20.0]  # morning lowered, evening kept
    assert [b["temperature"] for b in coord.config.schedule["tue"]] == [19.5, 19.5]
    assert coord.intel.state.seasonal == SeasonalSavingsState()
    assert any("seasonal" in key for key in hass.data["persistent_notification"])


async def test_stop_puts_the_temperatures_back(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 16:10:00+01:00")
    await coord.async_save_config({"seasonal_savings": True})
    assert (await _tick(hass, coord))["main"]["effective_target"] == 19.9
    await coord.async_stop_seasonal_savings()
    assert (await _tick(hass, coord))["main"]["effective_target"] == 20.0
    assert coord.config.schedule["mon"][1]["temperature"] == 20
