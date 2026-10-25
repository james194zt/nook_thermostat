"""A restart in the middle of a heating run must not lose the run (needs HA test venv).

13 Oct: HA restarted at 07:48 during a run that began at 06:30 (18.4 °C); the
start lived only in memory, so the morning's warm-up couldn't be learned.
"""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.coordinator import (  # noqa: E402
    NookCoordinator,
)
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401

START = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")


async def _at(hass, coord, freezer, minute, temp):
    freezer.move_to(START + timedelta(minutes=minute))
    hass.states.async_set("sensor.house", str(temp))
    return await _tick(hass, coord)


async def test_run_survives_a_restart(hass, setup, freezer):
    coord, _ = setup
    hass.states.async_set("climate.trv_lounge", "heat", {"temperature": 16, "current_temperature": 22})
    assert (await _at(hass, coord, freezer, 0, 18.0))["boiler_on"] is True
    await _at(hass, coord, freezer, 20, 18.6)
    await coord.intel.async_save()

    # HA restarts: a brand-new coordinator loads what was saved.
    fresh = NookCoordinator(hass, coord.entry)
    await fresh.async_initialize_intelligence()
    try:
        # 20.0 is above the cut-in (19.7): only a remembered run keeps going to 20.3.
        assert (await _at(hass, fresh, freezer, 40, 20.0))["boiler_on"] is True
        assert (await _at(hass, fresh, freezer, 60, 20.3))["boiler_on"] is False
        cycles = fresh.intel.state.recent_cycles
        assert len(cycles) == 1
        assert cycles[0]["start_temp"] == 18.0
        assert cycles[0]["duration_minutes"] == 60.0
        assert fresh.intel.state.warmup.samples == 1
        assert fresh.intel.state.heat_cycle == {}
    finally:
        await fresh.async_unload()
        await fresh.async_shutdown()


async def test_stale_run_is_dropped(hass, setup, freezer):
    coord, _ = setup
    await _at(hass, coord, freezer, 0, 18.0)
    await coord.intel.async_save()
    # Down for a day: whatever happened to that run, it can't be learned from.
    freezer.move_to(START + timedelta(days=1))
    fresh = NookCoordinator(hass, coord.entry)
    await fresh.async_initialize_intelligence()
    try:
        assert fresh._heat_cycle_start is None  # noqa: SLF001
        assert fresh.intel.state.heat_cycle == {}
    finally:
        await fresh.async_unload()
        await fresh.async_shutdown()
