"""Auto-Schedule, preheat weather fit and Leaf baseline (needs HA test venv).

Run: <venv>/bin/python -m pytest tests/test_learning.py
"""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.intelligence import (  # noqa: E402
    IntelligenceState,
    WarmupModel,
    estimate_preheat_minutes,
    learn_schedule_from_adjustments,
    outdoor_rate_factor,
    record_manual_adjustment,
)
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401

MON = datetime(2026, 10, 12)  # a Monday


def _sched(blocks=None):
    base = blocks if blocks is not None else [
        {"start": "06:30", "end": "08:30", "temperature": 20.0, "enabled": True},
        {"start": "16:00", "end": "22:00", "temperature": 20.0, "enabled": True},
    ]
    return {d: [dict(b) for b in base] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def _adjust(state, when, temp):
    record_manual_adjustment(state, temp, now=when)


def _learn(state, schedule=None, now=None):
    return learn_schedule_from_adjustments(
        schedule or _sched(), state, auto_schedule=True, eco_temp=16.0, now=now or MON + timedelta(days=8)
    )


# --- Auto-Schedule ------------------------------------------------------------


def test_dial_taps_on_one_day_learn_nothing():
    state = IntelligenceState()
    for minute, temp in ((0, 20.0), (2, 20.5), (5, 21.0)):
        _adjust(state, MON + timedelta(hours=12, minutes=minute), temp)
    assert _learn(state, now=MON + timedelta(hours=13)) == (_sched(), False)


def test_same_change_on_two_mondays_adds_a_block_in_the_gap():
    state = IntelligenceState()
    _adjust(state, MON + timedelta(hours=12, minutes=5), 20.0)
    _adjust(state, MON + timedelta(hours=12, minutes=6), 21.0)  # last tap that day wins
    _adjust(state, MON + timedelta(days=7, hours=12, minutes=10), 21.0)
    schedule, changed = _learn(state, now=MON + timedelta(days=7, hours=12, minutes=11))
    assert changed
    assert schedule["mon"][1] == {"start": "12:15", "end": "14:15", "temperature": 21.0, "enabled": True}
    assert schedule["tue"] == _sched()["tue"]


def test_new_block_stops_at_the_next_block():
    state = IntelligenceState()
    for week in (0, 7):
        _adjust(state, MON + timedelta(days=week, hours=15, minutes=5), 21.0)
    schedule, changed = _learn(state, now=MON + timedelta(days=7, hours=16))
    assert changed
    assert [b["start"] + "-" + b["end"] for b in schedule["mon"]] == ["06:30-08:30", "15:15-16:00", "16:00-22:00"]


def test_change_near_a_block_start_only_changes_its_temperature():
    state = IntelligenceState()
    for week in (0, 7):
        _adjust(state, MON + timedelta(days=week, hours=6, minutes=40), 21.5)
    schedule, changed = _learn(state, now=MON + timedelta(days=7, hours=7))
    assert changed
    assert schedule["mon"][0] == {"start": "06:30", "end": "08:30", "temperature": 21.5, "enabled": True}
    # Learning again changes nothing more.
    assert _learn(state, schedule, now=MON + timedelta(days=7, hours=7))[1] is False


def test_change_mid_block_is_left_to_the_hold():
    state = IntelligenceState()
    for week in (0, 7):
        _adjust(state, MON + timedelta(days=week, hours=19), 21.0)
    assert _learn(state, now=MON + timedelta(days=7, hours=20))[1] is False


def test_turn_downs_and_disagreements_are_not_learned():
    state = IntelligenceState()
    for week in (0, 7):
        _adjust(state, MON + timedelta(days=week, hours=12), 16.0)  # down to Eco
    assert _learn(state, now=MON + timedelta(days=7, hours=13))[1] is False
    state = IntelligenceState()
    _adjust(state, MON + timedelta(hours=12), 18.0)
    _adjust(state, MON + timedelta(days=7, hours=12), 22.0)
    assert _learn(state, now=MON + timedelta(days=7, hours=13))[1] is False


def test_old_changes_are_forgotten():
    state = IntelligenceState()
    _adjust(state, MON - timedelta(days=35), 21.0)  # five weeks before: too old to count
    _adjust(state, MON + timedelta(hours=12), 21.0)
    assert _learn(state, now=MON + timedelta(hours=13))[1] is False
    assert len(state.adjustments) == 1
    _learn(state, now=MON + timedelta(days=50))
    assert state.adjustments == []


def test_off_does_nothing():
    state = IntelligenceState()
    for week in (0, 7):
        _adjust(state, MON + timedelta(days=week, hours=12), 21.0)
    assert learn_schedule_from_adjustments(_sched(), state, auto_schedule=False) == (_sched(), False)


# --- preheat weather fit --------------------------------------------------------


def _cycle(outdoor, rate, minutes=60):
    return {
        "start_temp": 18.0,
        "end_temp": 18.0 + rate * minutes / 60,
        "duration_minutes": minutes,
        "outdoor_temp": outdoor,
    }


def test_no_weather_factor_without_evidence():
    # Too few runs, too narrow a range, or no outdoor reading: plain learned rate.
    assert outdoor_rate_factor([_cycle(0, 1.0), _cycle(10, 2.0)], 0) == 1.0
    assert outdoor_rate_factor([_cycle(8 + i % 2, 1.5) for i in range(10)], 0) == 1.0
    assert outdoor_rate_factor([_cycle(i * 2, 1.0 + i * 0.2) for i in range(8)], None) == 1.0


def test_fit_from_real_runs_slows_cold_mornings():
    cycles = [_cycle(o, 1.0 + o * 0.1) for o in (0, 2, 4, 6, 8, 10)]  # 1.0..2.0 °C/h
    cold = outdoor_rate_factor(cycles, 0)
    mild = outdoor_rate_factor(cycles, 10)
    assert cold == pytest.approx(1.0 / 1.5)
    assert mild == pytest.approx(2.0 / 1.5)
    # Never extrapolated past the weather seen.
    assert outdoor_rate_factor(cycles, -10) == cold
    # Colder-is-faster is noise, not physics.
    assert outdoor_rate_factor([_cycle(o, 2.0 - o * 0.1) for o in (0, 2, 4, 6, 8, 10)], 0) == 1.0
    # Junk runs (too short, no rise) don't count.
    assert outdoor_rate_factor(cycles[:5] + [_cycle(20, 4.0, minutes=5)], 0) == 1.0


def test_preheat_uses_the_fit():
    cycles = [_cycle(o, 1.0 + o * 0.1) for o in (0, 2, 4, 6, 8, 10)]
    warm = WarmupModel(c_per_hour=1.5, samples=6)
    plain = estimate_preheat_minutes(current_temp=18.0, target_temp=19.5, warmup=warm, outdoor_temp=0)
    fitted = estimate_preheat_minutes(current_temp=18.0, target_temp=19.5, warmup=warm, outdoor_temp=0, cycles=cycles)
    assert plain == 65  # 1.5 °C at 1.5 °C/h + 5 min; no made-up cold factor
    assert abs(fitted - 95) <= 1  # 1.5 °C at 1.0 °C/h + 5 min


# --- the real coordinator -----------------------------------------------------


async def test_turning_down_keeps_the_leaf_baseline(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 12:00:00+01:00")
    coord.set_main_temperature(20.5)
    coord.set_main_temperature(15.0)  # below Eco (16)
    await hass.async_block_till_done()
    assert coord.intel.state.leaf.comfort_samples == [20.5]
    assert len(coord.intel.state.adjustments) == 2


async def test_summer_mode_earns_the_leaf_like_off(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 17:00:00+01:00")  # in a 20 °C block: no Leaf normally
    assert (await _tick(hass, coord))["leaf"]["active"] is False
    await coord.async_save_config({"summer_mode": True})
    assert (await _tick(hass, coord))["leaf"]["active"] is True


async def test_rooms_only_runs_are_not_recorded(hass, setup, freezer):
    coord, _ = setup
    start = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")
    # House warm, the lounge TRV (18 < 20) alone runs the boiler, then is satisfied.
    for m in range(0, 45, 5):
        freezer.move_to(start + timedelta(minutes=m))
        hass.states.async_set("sensor.house", str(21.0 + m * 0.01))
        assert (await _tick(hass, coord))["boiler_on"] is True
    hass.states.async_set("climate.trv_lounge", "heat", {"temperature": 20, "current_temperature": 21})
    freezer.move_to(start + timedelta(minutes=50))
    data = await _tick(hass, coord)
    assert data["boiler_on"] is False
    assert coord.intel.state.recent_cycles == []
    assert coord.intel.state.warmup.samples == 0
