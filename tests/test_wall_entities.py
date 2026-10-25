"""Wall panel payload uses Nook's real entity ids (needs HA test venv).

HA names Nook's climates itself (e.g. climate.nook_nook_home) while
climate.nook_home can be some other integration's thermostat.
"""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.nook.models import WallPanelConfig  # noqa: E402
from tests.test_schedule_ha import setup  # noqa: E402,F401


def _register(hass):
    reg = er.async_get(hass)
    # The user's old generic_thermostat owns the "obvious" name.
    reg.async_get_or_create("climate", "generic_thermostat", "boiler", suggested_object_id="nook_home")
    reg.async_get_or_create("climate", "nook", "nook_home", suggested_object_id="nook_nook_home")
    reg.async_get_or_create("climate", "nook", "nook_lounge", suggested_object_id="hallway_nook_nook_lounge")


async def _payload(hass, coord, primary):
    panel = WallPanelConfig.from_dict({"id": "hallway", "label": "Hallway", "primary_entity": primary})
    await coord.async_save_config({"wall_panels": [panel.to_dict()]})
    return coord.wall_panel_payload("hallway")


async def test_old_default_points_at_nooks_house_climate(hass, setup):
    coord, _calls = setup
    _register(hass)
    payload = await _payload(hass, coord, "climate.nook_home")
    assert payload["primary"]["entity"] == "climate.nook_nook_home"
    assert payload["rooms"] == [
        {"entity": "climate.hallway_nook_nook_lounge", "name": "Lounge", "id": "lounge"}
    ]


async def test_blank_primary_means_nook_house(hass, setup):
    coord, _calls = setup
    _register(hass)
    payload = await _payload(hass, coord, "")
    assert payload["primary"]["entity"] == "climate.nook_nook_home"


async def test_deliberate_other_climate_is_kept(hass, setup):
    coord, _calls = setup
    _register(hass)
    payload = await _payload(hass, coord, "climate.living_room_ac")
    assert payload["primary"]["entity"] == "climate.living_room_ac"


async def test_unregistered_room_falls_back_to_trv(hass, setup):
    coord, _calls = setup  # nothing registered
    payload = await _payload(hass, coord, "")
    assert payload["rooms"][0]["entity"] == coord.config.rooms[0].trv_entity
