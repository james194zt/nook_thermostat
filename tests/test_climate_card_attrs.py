"""Climate entities: setpoint changes show at once; the house entity lists rooms in order (needs HA test venv)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.nook.climate import NookHomeClimate, NookRoomClimate  # noqa: E402
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401


def _attach(hass, entity, entity_id):
    entity.hass = hass
    entity.entity_id = entity_id
    return entity


async def test_set_temperature_writes_state_immediately(hass, setup, freezer):
    coord, _calls = setup
    freezer.move_to(f"{MONDAY} 12:00:00+01:00")
    await _tick(hass, coord)
    home = _attach(hass, NookHomeClimate(coord), "climate.nook_nook_home")
    await home.async_set_temperature(temperature=22.5)
    # No coordinator refresh awaited: the new target must already be in the state machine.
    assert hass.states.get("climate.nook_nook_home").attributes["temperature"] == 22.5

    await home.async_set_preset_mode("eco")
    assert hass.states.get("climate.nook_nook_home").attributes["preset_mode"] == "eco"


async def test_house_lists_room_entities_in_order_and_rooms_name_themselves(hass, setup, freezer):
    coord, _calls = setup
    freezer.move_to(f"{MONDAY} 12:00:00+01:00")
    await _tick(hass, coord)
    reg = er.async_get(hass)
    reg.async_get_or_create("climate", "nook", "nook_lounge", suggested_object_id="hallway_nook_nook_lounge")
    home = NookHomeClimate(coord)
    assert home.extra_state_attributes["room_entities"] == ["climate.hallway_nook_nook_lounge"]

    room = NookRoomClimate(coord, coord.config.rooms[0])
    attrs = room.extra_state_attributes
    assert attrs["room_name"] == "Lounge"
    assert attrs["room_id"] == "lounge"
    assert attrs["calls_for_heat"] is True
    assert attrs["hold_until"] is None


async def test_room_hold_until_for_the_radiators_card(hass, setup, freezer):
    coord, _calls = setup
    coord.config.schedule_enabled = True
    freezer.move_to(f"{MONDAY} 12:00:00+01:00")
    await _tick(hass, coord)
    room = coord.config.rooms[0]
    coord.set_room_temperature(room.id, 21.5)
    until = coord.room_hold_until(room)
    assert until is not None and until == coord.room_control(room.id)["hold"]["until"]
    assert NookRoomClimate(coord, room).extra_state_attributes["hold_until"] == until
    # A preset replaces the manual setpoint, so there's no hold to show.
    coord.set_room_preset(room.id, "boost")
    assert coord.room_hold_until(room) is None
