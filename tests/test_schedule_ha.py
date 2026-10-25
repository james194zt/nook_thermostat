"""Drive the real coordinator through a day of schedule times (needs HA test venv).

Run: <venv>/bin/python -m pytest tests/test_schedule_ha.py
"""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook.coordinator import (  # noqa: E402
    NookCoordinator,
)

MONDAY = "2026-09-28"  # BST (UTC+1)


@pytest.fixture
async def setup(hass, monkeypatch):
    await hass.config.async_set_time_zone("Europe/London")
    # Minimum on/off can't be 0 any more; these tests jump the clock around, so
    # switch the anti-short-cycle guard off here (test_control.py covers it).
    monkeypatch.setattr(
        "custom_components.nook.coordinator.boiler_cycle_guard",
        lambda want_on, is_on, seconds, **_kw: (want_on, 0.0),
    )
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))
        entity = call.data["entity_id"]
        if call.domain == "switch":
            hass.states.async_set(entity, "on" if call.service == "turn_on" else "off")

    for service in ("turn_on", "turn_off"):
        hass.services.async_register("switch", service, record)
    for service in ("set_temperature", "set_hvac_mode"):
        hass.services.async_register("climate", service, record)

    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set("sensor.house", "18.0")
    hass.states.async_set(
        "climate.trv_lounge", "heat", {"temperature": 16, "current_temperature": 18}
    )
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.house"},
        options={
            "true_radiant": False,
            "min_on_minutes": 0,
            "min_off_minutes": 0,
            "rooms": [
                {
                    "id": "lounge",
                    "name": "Lounge",
                    "trv_entity": "climate.trv_lounge",
                    "target_temp": 20,
                    "eco_temp": 16,
                }
            ],
        },
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    yield coord, calls
    # Cancel listeners and the refresh debouncer, or HA's harness flags lingering timers.
    await coord.async_unload()
    await coord.async_shutdown()


async def _tick(hass, coord):
    data = await coord._async_update_data()  # noqa: SLF001
    await hass.async_block_till_done(wait_background_tasks=True)  # TRV commands
    return data


def _room_target(coord):
    return coord.effective_room_target(coord.config.rooms[0])


async def test_setback_midday_keeps_boiler_off(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 12:00:00+01:00")
    data = await _tick(hass, coord)
    assert data["main"]["effective_target"] == 16.0
    assert _room_target(coord) == 16.0  # room follows the setback
    assert data["boiler_on"] is False


async def test_block_follows_bst_not_utc(hass, setup, freezer):
    coord, calls = setup
    # 16:10 BST is 15:10 UTC: a UTC clock would still be in setback.
    freezer.move_to(f"{MONDAY} 16:10:00+01:00")
    data = await _tick(hass, coord)
    assert data["main"]["effective_target"] == 20.0
    assert data["main"]["schedule_active"] is True
    assert _room_target(coord) == 20.0
    assert data["boiler_on"] is True
    assert ("switch", "turn_on", {"entity_id": "switch.boiler"}) in calls
    assert (
        "climate",
        "set_temperature",
        {"entity_id": "climate.trv_lounge", "temperature": 20.0},
    ) in calls


async def test_evening_block_ends_at_22(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 22:05:00+01:00")
    data = await _tick(hass, coord)
    assert data["main"]["effective_target"] == 16.0
    assert _room_target(coord) == 16.0


async def test_house_dial_holds_until_next_block(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 12:00:00+01:00")
    coord.set_main_temperature(21.0)
    data = await _tick(hass, coord)
    assert data["main"]["effective_target"] == 21.0
    assert data["boiler_on"] is True
    freezer.move_to(f"{MONDAY} 15:59:00+01:00")
    assert (await _tick(hass, coord))["main"]["effective_target"] == 21.0
    freezer.move_to(f"{MONDAY} 16:00:30+01:00")
    assert (await _tick(hass, coord))["main"]["effective_target"] == 20.0
    assert coord._manual_hold is None  # noqa: SLF001


async def test_room_dial_holds_until_next_block(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 12:00:00+01:00")
    coord.set_room_temperature("lounge", 19.0)
    await _tick(hass, coord)
    assert _room_target(coord) == 19.0
    assert coord.data["rooms"]["lounge"]["needs_heat"] is True
    freezer.move_to(f"{MONDAY} 22:30:00+01:00")
    await _tick(hass, coord)
    assert _room_target(coord) == 16.0


async def test_preheat_starts_before_block_and_clears(hass, setup, freezer):
    coord, _ = setup
    await coord.async_save_config({"true_radiant": True})
    # 18 -> 20 at 1.5C/h default = 80 min + 5 => preheat from 14:35.
    freezer.move_to(f"{MONDAY} 15:30:00+01:00")
    data = await _tick(hass, coord)
    assert data["preheat"]["preheating"] is True
    assert data["main"]["effective_target"] == 20.0
    assert _room_target(coord) == 20.0  # rooms preheat with the house
    freezer.move_to(f"{MONDAY} 16:05:00+01:00")
    data = await _tick(hass, coord)
    assert data["preheat"] is None  # used to stay stuck "preheating"


async def test_schedule_disabled_uses_dial(hass, setup, freezer):
    coord, _ = setup
    await coord.async_save_config({"schedule_enabled": False})
    freezer.move_to(f"{MONDAY} 03:00:00+01:00")
    coord.set_main_temperature(19.5)
    data = await _tick(hass, coord)
    assert data["main"]["effective_target"] == 19.5
    assert _room_target(coord) == 19.5  # rooms follow the house by default
    coord.config.rooms[0].follow_house = False
    assert _room_target(coord) == 20.0  # an independent room keeps its own
