"""Wall panel room cog: Room Temperature fields + simple TRV settings (needs HA test venv)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import EntityCategory  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook.const import DOMAIN  # noqa: E402
from custom_components.nook.websocket_api import async_register_ws_handlers  # noqa: E402
from tests.test_schedule_ha import setup  # noqa: E402,F401

CONFIG = EntityCategory.CONFIG


def _trv_device(hass):
    """The lounge TRV as ZHA would file it: the climate plus its device entities."""
    entry = MockConfigEntry(domain="zha", title="Zigbee")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("zha", "84:27:12:00:00:00:00:01")}, name="Lounge Radiator"
    )
    reg = er.async_get(hass)
    trv_state = hass.states.get("climate.trv_lounge")
    hass.states.async_remove("climate.trv_lounge")  # free the id for the registry entry
    reg.async_get_or_create(
        "climate", "zha", "trv", config_entry=entry, device_id=device.id, suggested_object_id="trv_lounge"
    )
    hass.states.async_set("climate.trv_lounge", trv_state.state, trv_state.attributes)

    def add(domain, key, state, *, category=CONFIG, attrs=None, **extra):
        ent = reg.async_get_or_create(
            domain, "zha", key, config_entry=entry, device_id=device.id,
            suggested_object_id=f"lounge_radiator_{key}", entity_category=category, **extra,
        )
        name = key.replace("_", " ")
        hass.states.async_set(ent.entity_id, state, {"friendly_name": f"Lounge Radiator {name}", **(attrs or {})})
        return ent.entity_id

    ids = {
        "open": add("number", "valve_opening_degree", "100",
                    attrs={"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"}),
        "lock": add("switch", "child_lock", "off"),
        "boost": add("button", "boost", "unknown"),
        # Not for a wall panel: an option list, a diagnostic, a disabled and a hidden setting,
        # and a plain (non-configuration) number.
        "select": add("select", "temperature_control", "on"),
        "battery": add("sensor", "battery", "100", category=EntityCategory.DIAGNOSTIC),
        "disabled": add("number", "valve_closing_degree", "100", disabled_by=er.RegistryEntryDisabler.INTEGRATION),
        "hidden": add("number", "idle_steps", "3", hidden_by=er.RegistryEntryHider.USER),
        "plain": add("number", "local_setpoint", "20", category=None),
    }
    return ids


async def test_settings_list_only_simple_trv_config(hass, setup):
    coord, _ = setup
    ids = _trv_device(hass)
    data = coord.wall_room_settings("lounge")
    assert data["room"] == {
        "id": "lounge", "name": "Lounge", "follow_house": True, "house_offset": 0.0,
        "target_temp": 20.0, "eco_temp": 16.0, "hold_ends": "house_change",
    }
    assert data["trv"] == {"entity_id": "climate.trv_lounge", "available": True}
    # Sorted by name, buttons last; the device name is taken off the front.
    assert [(s["entity_id"], s["name"]) for s in data["settings"]] == [
        (ids["lock"], "Child lock"),
        (ids["open"], "Valve opening degree"),
        (ids["boost"], "Boost"),
    ]
    opening = data["settings"][1]
    assert (opening["min"], opening["max"], opening["step"], opening["unit"], opening["state"]) == (0, 100, 1, "%", "100")
    assert coord.wall_room_settings("nope") is None


async def test_settings_without_a_registered_trv(hass, setup):
    coord, _ = setup
    hass.states.async_set("climate.trv_lounge", "unavailable")
    data = coord.wall_room_settings("lounge")
    assert data["settings"] == [] and data["trv"]["available"] is False


async def test_update_saves_room_fields_without_reloading(hass, setup):
    coord, _ = setup
    entities_before = coord.config.rooms[0]
    data = await coord.async_update_wall_room(
        "lounge", {"follow_house": False, "target_temp": 21.5, "hold_ends": "manual", "name": "Hacked"}
    )
    room = coord.config.rooms[0]
    assert (room.follow_house, room.target_temp, room.hold_ends, room.name) == (False, 21.5, "manual", "Lounge")
    assert room.trv_entity == entities_before.trv_entity
    assert data["room"]["target_temp"] == 21.5
    assert await coord.async_update_wall_room("nope", {"eco_temp": 15}) is None


async def test_wall_payload_names_the_room(hass, setup):
    coord, _ = setup
    await coord.async_save_config({"wall_panels": [{"id": "hallway", "label": "Hallway"}]})
    rooms = coord.wall_panel_payload("hallway")["rooms"]
    assert rooms[0]["id"] == "lounge" and rooms[0]["name"] == "Lounge"


async def test_websocket_commands(hass, setup, hass_ws_client):
    coord, _ = setup
    _trv_device(hass)
    hass.data.setdefault(DOMAIN, {})[coord.entry.entry_id] = {"coordinator": coord}
    assert await async_setup_component(hass, "websocket_api", {})
    async_register_ws_handlers(hass)
    ws = await hass_ws_client(hass)

    await ws.send_json({"id": 1, "type": "nook/get_wall_room_settings", "room_id": "lounge"})
    msg = await ws.receive_json()
    assert msg["success"] and len(msg["result"]["settings"]) == 3

    await ws.send_json({"id": 2, "type": "nook/update_wall_room", "room_id": "lounge", "house_offset": -1.5})
    msg = await ws.receive_json()
    assert msg["success"] and msg["result"]["room"]["house_offset"] == -1.5
    assert coord.config.rooms[0].house_offset == -1.5

    # Out of range / unknown choices never reach the config.
    for i, bad in enumerate(({"house_offset": 9}, {"eco_temp": 2}, {"hold_ends": "forever"}), start=3):
        await ws.send_json({"id": i, "type": "nook/update_wall_room", "room_id": "lounge", **bad})
        assert not (await ws.receive_json())["success"]
    await ws.send_json({"id": 9, "type": "nook/get_wall_room_settings", "room_id": "nope"})
    assert (await ws.receive_json())["error"]["code"] == "not_found"
