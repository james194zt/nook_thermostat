"""True Radiant coast: measured after each run instead of guessed (needs HA test venv).

Run: <venv>/bin/python -m pytest tests/test_coast.py
"""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.intelligence import (  # noqa: E402
    DEFAULT_COAST_C,
    CoastWatch,
    IntelligenceState,
    WarmupModel,
    learn_coast,
    update_coast_watch,
    update_warmup_from_cycle,
)
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401

T0 = datetime(2026, 10, 13, 17, 0)


def _ticks(watch, model, start, minutes, temps, *, on, house=True, disturbed=False, learn=True):
    """Tick once a minute; temps(i) is the reading at minute i. Returns the last learned model."""
    learned = None
    for i in range(minutes + 1):
        result = update_coast_watch(
            watch,
            model,
            boiler_on=on,
            house_calling=house,
            current_temp=temps(i),
            disturbed=disturbed,
            learn=learn,
            now=start + timedelta(minutes=i),
        )
        if result is not None:
            learned = model = result
    return learned


def _run_then_coast(watch, model, *, run_minutes=30, house=True, coast_temps=None, **kw):
    """A heating run to 20.3 °C, then the boiler stops and the house coasts."""
    _ticks(watch, model, T0, run_minutes, lambda i: 18.5 + i * 0.06, on=True, house=house)
    off = T0 + timedelta(minutes=run_minutes + 1)
    # Default: rises 0.3 over 15 min, then cools 0.01/min.
    temps = coast_temps or (lambda i: 20.3 + min(i, 15) * 0.02 - max(0, i - 15) * 0.01)
    # Long enough to reach the give-up point (COAST_MAX_WATCH_MINUTES).
    return _ticks(watch, model, off, 125, temps, on=False, **kw)


def test_measures_the_rise_after_the_boiler_stops():
    watch = CoastWatch()
    learned = _run_then_coast(watch, WarmupModel())
    assert learned is not None
    assert learned.coast_samples == 1
    # Observed 0.3 °C blended with the 0.1 default (first run weighs 0.35).
    assert learned.coast_c == pytest.approx(DEFAULT_COAST_C * 0.65 + 0.3 * 0.35, abs=0.005)
    assert watch == CoastWatch()


def test_converges_on_the_real_coast():
    model = WarmupModel()
    for _ in range(12):
        model = _run_then_coast(CoastWatch(), model)
    assert model.coast_c == pytest.approx(0.3, abs=0.02)


def test_no_coast_lowers_the_estimate():
    model = WarmupModel(coast_c=0.4, coast_samples=5)
    learned = _run_then_coast(CoastWatch(), model, coast_temps=lambda i: 20.3 - i * 0.01)
    assert learned is not None and learned.coast_c < 0.4


def test_short_and_rooms_only_runs_are_ignored():
    assert _run_then_coast(CoastWatch(), WarmupModel(), run_minutes=10) is None
    assert _run_then_coast(CoastWatch(), WarmupModel(), house=False) is None


def test_boiler_back_on_before_the_peak_discards():
    watch = CoastWatch()
    _ticks(watch, WarmupModel(), T0, 30, lambda i: 19.0 + i * 0.04, on=True)
    _ticks(watch, WarmupModel(), T0 + timedelta(minutes=31), 5, lambda i: 20.2 + i * 0.02, on=False)
    assert watch.off_at is not None
    # Still rising when the boiler restarts: the measurement is thrown away.
    _ticks(watch, WarmupModel(), T0 + timedelta(minutes=37), 1, lambda i: 20.3, on=True)
    assert watch.off_at is None
    assert watch.run_started_at is not None  # the new run is tracked instead


def test_window_open_discards():
    watch = CoastWatch()
    _ticks(watch, WarmupModel(), T0, 30, lambda i: 19.0, on=True)
    _ticks(watch, WarmupModel(), T0 + timedelta(minutes=31), 3, lambda i: 20.0, on=False)
    assert _ticks(watch, WarmupModel(), T0 + timedelta(minutes=35), 60, lambda i: 19.0, on=False, disturbed=True) is None
    assert watch == CoastWatch()


def test_late_warming_is_not_coast():
    # Flat after the boiler stops, then the sun warms the house 80 min later.
    temps = lambda i: 20.3 + (0.5 if i >= 80 else 0.0)  # noqa: E731
    assert _run_then_coast(CoastWatch(), WarmupModel(), coast_temps=temps) is None


def test_fault_measures_but_does_not_learn():
    watch = CoastWatch()
    assert _run_then_coast(watch, WarmupModel(), learn=False) is None
    assert watch == CoastWatch()


def test_huge_coast_is_capped():
    assert learn_coast(WarmupModel(), 5.0).coast_c == pytest.approx(0.1 * 0.65 + 1.0 * 0.35)


def test_watch_and_coast_survive_a_restart():
    state = IntelligenceState()
    _ticks(state.coast_watch, state.warmup, T0, 30, lambda i: 19.0, on=True)
    _ticks(state.coast_watch, state.warmup, T0 + timedelta(minutes=31), 5, lambda i: 20.0 + i * 0.02, on=False)
    state.warmup = learn_coast(state.warmup, 0.3)
    restored = IntelligenceState.from_dict(state.to_dict())
    assert restored.coast_watch == state.coast_watch
    assert restored.coast_watch.off_at is not None
    assert restored.warmup == state.warmup
    # Stores written before 0.6.14 have neither.
    old = IntelligenceState.from_dict({"warmup": {"c_per_hour": 2.0, "samples": 3}})
    assert old.warmup.coast_c == DEFAULT_COAST_C and old.coast_watch == CoastWatch()


def test_warmup_learning_keeps_the_coast():
    model = WarmupModel(coast_c=0.35, coast_samples=4)
    model = update_warmup_from_cycle(model, start_temp=18.0, end_temp=20.0, duration_minutes=40)
    assert model.samples == 1
    assert (model.coast_c, model.coast_samples) == (0.35, 4)


# --- the real coordinator ---------------------------------------------------


async def test_coordinator_learns_coast_and_uses_it(hass, setup, freezer):
    coord, _ = setup
    # Only the house calls: the lounge is already warm.
    hass.states.async_set("climate.trv_lounge", "heat", {"temperature": 16, "current_temperature": 22})
    start = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")

    async def at(minute, temp):
        freezer.move_to(start + timedelta(minutes=minute))
        hass.states.async_set("sensor.house", str(temp))
        return await _tick(hass, coord)

    # 20 °C block, house 18 → 20.3 over 40 min (plain cut-off at target + 0.3).
    for m in range(0, 40, 5):
        assert (await at(m, round(18.0 + m * 0.055, 2)))["boiler_on"] is True
    assert (await at(40, 20.3))["boiler_on"] is False
    # Radiators push it to 20.6, then it cools.
    for m, t in ((45, 20.4), (50, 20.5), (55, 20.6), (60, 20.6), (70, 20.5), (80, 20.4)):
        await at(m, t)
    warmup = coord.intel.state.warmup
    assert warmup.coast_samples == 1
    assert warmup.coast_c == pytest.approx(0.1 * 0.65 + 0.3 * 0.35, abs=0.005)
    assert coord.data["intelligence"]["coast_c"] == warmup.coast_c

    # True Radiant now stops early by the learned coast.
    await coord.async_save_config({"true_radiant": True})
    coord.intel.state.warmup = learn_coast(WarmupModel(coast_c=0.3, coast_samples=9), 0.3)
    assert (await at(90, 19.6))["boiler_on"] is True
    assert (await at(95, 19.95))["boiler_on"] is True
    assert (await at(100, 20.0))["boiler_on"] is False

    await coord.async_reset_warmup()
    assert coord.intel.state.warmup == WarmupModel()
    assert coord.intel.state.coast_watch == CoastWatch()
