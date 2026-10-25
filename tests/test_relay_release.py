"""Releasing the boiler relay for a hand test; minimum on/off limits (needs HA test venv).

Run: <venv>/bin/python -m pytest tests/test_relay_release.py
"""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.models import NookConfig  # noqa: E402
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401

START = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")


def test_min_on_off_never_zero_or_huge():
    cfg = NookConfig.from_entry_data({"min_on_minutes": 0, "min_off_minutes": 99})
    assert (cfg.min_on_minutes, cfg.min_off_minutes) == (1.0, 30.0)
    assert NookConfig.from_entry_data({}).min_on_minutes == 3.0


async def test_released_relay_is_left_alone_then_taken_back(hass, setup, freezer):
    coord, calls = setup
    freezer.move_to(START)
    assert (await _tick(hass, coord))["boiler_on"] is True  # house 18 < 20

    until = await coord.async_release_control(60)
    assert until.startswith(f"{MONDAY}T16:10")  # 17:10 BST, in UTC
    assert coord.intel.state.control["released_until"] == until
    calls.clear()

    # Hand test: switch the relay off. Nook must not switch it back.
    freezer.move_to(START + timedelta(minutes=5))
    hass.states.async_set("switch.boiler", "off")
    data = await _tick(hass, coord)
    assert data["boiler_on"] is False  # what the relay is really doing
    assert data["control_released_until"] == until
    assert not [c for c in calls if c[0] == "switch"]
    assert coord._heat_cycle_start is None  # noqa: SLF001 — nothing learned from a test

    # An hour later Nook takes it back by itself.
    freezer.move_to(START + timedelta(minutes=61))
    data = await _tick(hass, coord)
    assert data["control_released_until"] is None
    assert ("switch", "turn_on", {"entity_id": "switch.boiler"}) in calls
    assert coord.intel.state.control["released_until"] is None


async def test_take_control_early(hass, setup, freezer):
    coord, calls = setup
    freezer.move_to(START)
    await _tick(hass, coord)
    await coord.async_release_control(30)
    hass.states.async_set("switch.boiler", "off")
    freezer.move_to(START + timedelta(minutes=3))
    await coord.async_take_control()
    data = await _tick(hass, coord)
    assert data["control_released_until"] is None
    assert data["boiler_on"] is True
    assert hass.states.get("switch.boiler").state == "on"


async def test_release_survives_restart(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(START)
    until = await coord.async_release_control(60)
    coord._released_until = None  # noqa: SLF001 — as if freshly started
    coord._restore_control()  # noqa: SLF001
    assert coord.data is not None
    assert coord._released_until.isoformat() == until  # noqa: SLF001
