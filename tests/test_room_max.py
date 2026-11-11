"""A room's maximum temperature, and a turned-down preheat no longer showing as one.

11 Nov 2026 live: the living room was held at 18 °C "as a maximum" (stop following
the house, keep until changed), so it was kept at 18 all night and ran the boiler
02:55–03:45. Then the 06:32 preheat was turned down within a minute and the pill
still said "Preheating".
"""

from datetime import timedelta  # noqa: F401

import pytest

from custom_components.nook.intelligence import PreheatRoom
from custom_components.nook.models import RoomConfig
from tests.test_room_preheat import _status

pytest.importorskip("pytest_homeassistant_custom_component")

from tests.test_room_preheat import TRV, _tick, coord  # noqa: E402,F401


def test_max_temp_is_read_from_config():
    base = {"id": "lr", "name": "LR", "trv_entity": TRV}
    assert RoomConfig.from_dict(base).max_temp is None
    assert RoomConfig.from_dict({**base, "max_temp": ""}).max_temp is None
    assert RoomConfig.from_dict({**base, "max_temp": "18"}).max_temp == 18.0
    assert RoomConfig.from_dict({**base, "max_temp": 40}).max_temp == 30.0
    assert RoomConfig.from_dict(RoomConfig.from_dict({**base, "max_temp": 18}).to_dict()).max_temp == 18.0


def test_preheat_aims_a_capped_room_at_its_maximum():
    plain = _status(rooms=[PreheatRoom(name="Living Room", current_temp=17.0)])
    capped = _status(rooms=[PreheatRoom(name="Living Room", current_temp=17.0, max_temp=18.0)])
    assert capped["preheat_minutes"] < plain["preheat_minutes"]
    # 18.6 is already above an 18 maximum: the room doesn't lead the preheat.
    warm = _status(rooms=[PreheatRoom(name="Living Room", current_temp=18.6, max_temp=18.0)])
    assert warm["preheat_room"] is None


async def _cap_living_room(coord, max_temp):  # noqa: F811
    rooms = [r.to_dict() for r in coord.config.rooms]
    rooms[0]["max_temp"] = max_temp
    await coord.async_save_config({"rooms": rooms})


async def test_capped_room_follows_the_house_below_its_maximum(hass, coord, freezer):  # noqa: F811
    await _cap_living_room(coord, 18.0)
    room = coord.config.rooms[0]
    freezer.move_to("2026-10-22 07:00:00+01:00")  # in the 06:30 block at 20
    await _tick(hass, coord)
    assert coord.effective_room_target(room) == 18.0
    freezer.move_to("2026-10-22 23:30:00+01:00")  # overnight Eco
    await _tick(hass, coord)
    assert coord.effective_room_target(room) == 16.0  # not held at 18 all night
    hass.states.async_set("sensor.lr", "17.0")
    await _tick(hass, coord)
    assert coord._room_states["living_room"]["needs_heat"] is False  # noqa: SLF001
    # A change made on the room itself can still go above it.
    coord.set_room_temperature("living_room", 20.0)
    assert coord.effective_room_target(room) == 20.0


async def test_turning_down_a_running_preheat_stops_showing_it(hass, coord, freezer):  # noqa: F811
    freezer.move_to("2026-10-22 05:40:00+01:00")  # living room preheat running
    await _tick(hass, coord)
    assert coord.data["preheat"]["preheating"] is True
    coord.set_main_temperature(16.0)
    await _tick(hass, coord)
    assert coord.data["preheat"]["preheating"] is False
    assert coord.effective_main_target()[0] == 16.0
    assert hass.states.get("switch.boiler").state == "off"
    # A second change during that preheat still beats it (it doesn't restart).
    coord.set_main_temperature(18.0)
    await _tick(hass, coord)
    assert coord.effective_main_target()[0] == 18.0
    assert coord.data["preheat"]["preheating"] is False
