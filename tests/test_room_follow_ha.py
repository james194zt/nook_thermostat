"""Rooms that follow the house vs independent rooms, and how long a room change lasts (needs HA test venv)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.models import RoomConfig  # noqa: E402
from tests.test_schedule_ha import MONDAY, _room_target, _tick, setup  # noqa: E402,F401

# Default schedule, Monday: comfort 06:30–08:30 and 16:00–22:00 at 20 °C, Eco 16 °C otherwise.


def _room(coord):
    return coord.config.rooms[0]


async def test_follower_tracks_house_dial_with_offset(hass, setup, freezer):
    coord, _ = setup
    _room(coord).house_offset = -1.0
    freezer.move_to(f"{MONDAY} 12:00:00+01:00")
    await _tick(hass, coord)
    assert _room_target(coord) == 15.0  # house Eco 16 − 1
    coord.set_main_temperature(21.0)
    assert _room_target(coord) == 20.0  # straight away, no tick needed


async def test_room_change_ends_at_next_house_change(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 16:30:00+01:00")
    await _tick(hass, coord)
    coord.set_room_temperature("lounge", 22.0)
    await _tick(hass, coord)
    assert _room_target(coord) == 22.0
    assert coord.room_held(_room(coord))
    coord.set_main_temperature(19.0)  # someone turns the house down
    assert _room_target(coord) == 19.0
    assert not coord.room_held(_room(coord))


async def test_room_change_also_ends_at_next_block(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 16:30:00+01:00")
    coord.set_room_temperature("lounge", 22.0)
    freezer.move_to(f"{MONDAY} 22:05:00+01:00")
    await _tick(hass, coord)
    assert _room_target(coord) == 16.0


async def test_block_change_hold_survives_house_dial(hass, setup, freezer):
    coord, _ = setup
    _room(coord).hold_ends = "block_change"
    freezer.move_to(f"{MONDAY} 16:30:00+01:00")
    coord.set_room_temperature("lounge", 22.0)
    coord.set_main_temperature(19.0)
    assert _room_target(coord) == 22.0
    freezer.move_to(f"{MONDAY} 22:05:00+01:00")
    await _tick(hass, coord)
    assert _room_target(coord) == 16.0


async def test_manual_hold_lasts_until_the_room_is_changed(hass, setup, freezer):
    coord, _ = setup
    _room(coord).hold_ends = "manual"
    freezer.move_to(f"{MONDAY} 16:30:00+01:00")
    coord.set_room_temperature("lounge", 22.0)
    coord.set_main_temperature(19.0)
    freezer.move_to(f"{MONDAY} 23:30:00+01:00")
    await _tick(hass, coord)
    assert _room_target(coord) == 22.0
    assert coord.room_hold_until(_room(coord)) is None  # no end time to show
    assert coord.room_held(_room(coord))
    coord.set_room_temperature("lounge", 18.0)
    assert _room_target(coord) == 18.0


async def test_independent_room_ignores_house_dial(hass, setup, freezer):
    coord, _ = setup
    _room(coord).follow_house = False
    freezer.move_to(f"{MONDAY} 16:30:00+01:00")
    await _tick(hass, coord)
    assert _room_target(coord) == 20.0  # its own comfort temp
    coord.set_main_temperature(23.0)
    assert _room_target(coord) == 20.0
    freezer.move_to(f"{MONDAY} 22:30:00+01:00")
    await _tick(hass, coord)
    assert _room_target(coord) == 16.0  # its own Eco temp between blocks


async def test_independent_room_calls_boiler_above_house_target(hass, setup, freezer):
    coord, _ = setup
    _room(coord).follow_house = False
    hass.states.async_set("sensor.house", "21.0")  # house is warm enough
    freezer.move_to(f"{MONDAY} 16:30:00+01:00")
    coord.set_room_temperature("lounge", 23.0)  # TRV reads 18
    data = await _tick(hass, coord)
    assert data["rooms"]["lounge"]["needs_heat"] is True
    assert data["boiler_on"] is True


async def test_house_off_turns_followers_off_not_independent_rooms(hass, setup, freezer):
    coord, calls = setup
    freezer.move_to(f"{MONDAY} 16:30:00+01:00")
    coord.set_main_hvac_mode("off")
    data = await _tick(hass, coord)
    assert data["rooms"]["lounge"]["needs_heat"] is False
    assert ("climate", "set_hvac_mode", {"entity_id": "climate.trv_lounge", "hvac_mode": "off"}) in calls

    _room(coord).follow_house = False
    data = await _tick(hass, coord)
    assert data["rooms"]["lounge"]["needs_heat"] is True  # TRV 18 < own 20


async def test_house_change_counter_survives_restart(hass, setup, freezer):
    coord, _ = setup
    freezer.move_to(f"{MONDAY} 16:30:00+01:00")
    coord.set_room_temperature("lounge", 22.0)
    coord.set_main_temperature(19.0)
    saved = coord.intel.state.control
    assert saved["main"]["house_rev"] == coord._house_rev  # noqa: SLF001
    assert saved["rooms"]["lounge"]["hold"]["house_rev"] == coord._house_rev - 1  # noqa: SLF001
    coord._house_rev = 0  # noqa: SLF001  (fresh coordinator)
    coord._restore_control()  # noqa: SLF001
    assert not coord.room_held(_room(coord))  # still ended after a restart


def test_room_config_defaults_and_bad_values():
    room = RoomConfig.from_dict({"id": "a", "name": "A", "trv_entity": "climate.a"})
    assert (room.follow_house, room.house_offset, room.hold_ends) == (True, 0.0, "house_change")
    room = RoomConfig.from_dict(
        {"id": "a", "name": "A", "trv_entity": "climate.a", "house_offset": 9, "hold_ends": "never"}
    )
    assert (room.house_offset, room.hold_ends) == (5.0, "house_change")
