"""Minimum on/off time across HA restarts, and when it ends (needs HA test venv).

16 Oct: the boiler had run since 06:21; HA restarted at 06:30 (relay unavailable → on,
so a fresh last_changed) and the dial was turned down. Nook held the boiler on for
the full 3-minute minimum run again, while the panel said "Heating to 17".
"""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook import control  # noqa: E402
from tests.test_restart_hold import _restart  # noqa: E402
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401

# Monday 17:00, inside the default 16:00–22:00 comfort block (20 °C).
AT = datetime.fromisoformat(f"{MONDAY}T17:00:00+01:00")


def _warm(hass):
    """House and the lounge both well above 20 °C: nothing wants heat."""
    hass.states.async_set("sensor.house", "21.0")
    hass.states.async_set(
        "climate.trv_lounge", "heat", {"temperature": 16, "current_temperature": 21}
    )


@pytest.fixture
async def guarded(hass, setup, freezer, monkeypatch):
    """The real anti-short-cycle guard, 3 min on / 3 min off, boiler off since 17:00."""
    coord, calls = setup
    monkeypatch.setattr(
        "custom_components.nook.coordinator.boiler_cycle_guard",
        control.boiler_cycle_guard,
    )
    await coord.async_save_config({"min_on_minutes": 3, "min_off_minutes": 3})
    # Watch the relay like the running integration does (records its on/off times).
    coord._subscribe_state_changes()  # noqa: SLF001
    freezer.move_to(AT)
    hass.states.async_set("switch.boiler", "unavailable")
    hass.states.async_set("switch.boiler", "off")
    freezer.move_to(AT + timedelta(minutes=10))
    data = await _tick(hass, coord)  # house 18 °C, block wants 20: on at 17:10
    assert data["boiler_on"] is True
    assert hass.states.get("switch.boiler").state == "on"
    return coord, calls


async def test_turn_down_keeps_boiler_on_until_minimum_run_and_says_until_when(
    hass, guarded, freezer
):
    coord, _ = guarded
    freezer.move_to(AT + timedelta(minutes=11))
    _warm(hass)
    data = await _tick(hass, coord)
    assert data["boiler_on"] is True
    assert data["boiler_demand"] is False
    # Held until 17:13 (3 min after it went on at 17:10).
    until = datetime.fromisoformat(data["boiler_hold_until"])
    assert until == AT + timedelta(minutes=13)

    freezer.move_to(AT + timedelta(minutes=13, seconds=1))
    data = await _tick(hass, coord)
    assert data["boiler_on"] is False
    assert data["boiler_hold_until"] is None


async def test_restart_does_not_restart_the_minimum_run(hass, guarded, freezer):
    coord, _ = guarded
    # HA restarts at 17:20: the relay comes back "on" with a new last_changed.
    freezer.move_to(AT + timedelta(minutes=20))
    fresh = await _restart(hass, coord)
    try:
        hass.states.async_set("switch.boiler", "unavailable")
        hass.states.async_set("switch.boiler", "on")
        _warm(hass)
        freezer.move_to(AT + timedelta(minutes=20, seconds=30))
        data = await _tick(hass, fresh)
        # On since 17:10, well past 3 min: off straight away.
        assert data["boiler_on"] is False
        assert data["boiler_hold_until"] is None
        assert hass.states.get("switch.boiler").state == "off"
    finally:
        await fresh.async_unload()
        await fresh.async_shutdown()


async def test_relay_changed_while_ha_was_down_uses_its_own_time(hass, guarded, freezer):
    coord, _ = guarded
    # Nook saw it on at 17:10; while HA was down someone switched it off (17:30).
    freezer.move_to(AT + timedelta(minutes=30))
    fresh = await _restart(hass, coord)
    try:
        hass.states.async_set("switch.boiler", "off")
        freezer.move_to(AT + timedelta(minutes=31))
        data = await _tick(hass, fresh)  # still 18 °C: wants heat, off for only 1 min
        assert data["boiler_on"] is False
        assert data["boiler_demand"] is True
        assert datetime.fromisoformat(data["boiler_hold_until"]) == AT + timedelta(minutes=33)
    finally:
        await fresh.async_unload()
        await fresh.async_shutdown()
