"""WebSocket API for Nook panel + wall devices."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from . import energy_meter, kiosk, panel_helper
from .const import DOMAIN, HEATER_DOMAINS, ROOM_HOLD_ENDS, WALL_ROOM_FIELDS
from .models import RoomConfig, WallPanelConfig, default_schedule

_LOGGER = logging.getLogger(__name__)


def _coordinator(hass: HomeAssistant, entry_id: str | None = None):
    domain_data = hass.data.get(DOMAIN) or {}
    if entry_id and entry_id in domain_data:
        return domain_data[entry_id]["coordinator"]
    for data in domain_data.values():
        if isinstance(data, dict) and "coordinator" in data:
            return data["coordinator"]
    return None


@callback
def async_register_ws_handlers(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_get_state)
    websocket_api.async_register_command(hass, ws_update_settings)
    websocket_api.async_register_command(hass, ws_update_schedule)
    websocket_api.async_register_command(hass, ws_update_rooms)
    websocket_api.async_register_command(hass, ws_reorder_rooms)
    websocket_api.async_register_command(hass, ws_list_wall_panels)
    websocket_api.async_register_command(hass, ws_upsert_wall_panel)
    websocket_api.async_register_command(hass, ws_delete_wall_panel)
    websocket_api.async_register_command(hass, ws_get_wall_panel_config)
    websocket_api.async_register_command(hass, ws_get_energy_history)
    websocket_api.async_register_command(hass, ws_get_wall_usage)
    websocket_api.async_register_command(hass, ws_get_wall_room_settings)
    websocket_api.async_register_command(hass, ws_update_wall_room)
    websocket_api.async_register_command(hass, ws_verify_wall_pin)
    websocket_api.async_register_command(hass, ws_stop_seasonal_savings)
    websocket_api.async_register_command(hass, ws_reset_warmup)
    websocket_api.async_register_command(hass, ws_release_control)
    websocket_api.async_register_command(hass, ws_take_control)
    websocket_api.async_register_command(hass, ws_kiosk_status)
    websocket_api.async_register_command(hass, ws_kiosk_apply)
    websocket_api.async_register_command(hass, ws_kiosk_read)
    websocket_api.async_register_command(hass, ws_kiosk_reload)
    websocket_api.async_register_command(hass, ws_helper_pair)
    websocket_api.async_register_command(hass, ws_helper_unpair)
    websocket_api.async_register_command(hass, ws_helper_config)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/get_state",
        vol.Optional("entry_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_get_state(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    connection.send_result(
        msg["id"],
        {
            "config": coordinator.config.to_dict(),
            "live": coordinator.data,
            "entry_id": coordinator.entry.entry_id,
            "wall_screens": await coordinator.async_wall_screens(),
            "wall_helpers": await coordinator.async_helpers_state(),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/helper_pair",
        vol.Optional("entry_id"): cv.string,
        vol.Required("panel_id"): cv.string,
        vol.Required("code"): cv.string,
    }
)
@websocket_api.async_response
async def ws_helper_pair(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    try:
        result = await coordinator.async_helper_pair(msg["panel_id"], msg["code"])
    except panel_helper.HelperError as err:
        connection.send_error(msg["id"], "helper_error", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/helper_unpair",
        vol.Optional("entry_id"): cv.string,
        vol.Required("panel_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_helper_unpair(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    await coordinator.async_helper_unpair(msg["panel_id"])
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/helper_config",
        vol.Optional("entry_id"): cv.string,
        vol.Required("panel_id"): cv.string,
        vol.Optional("hide_return_button"): cv.boolean,
        vol.Optional("cpu_lock"): cv.boolean,
        vol.Optional("wifi_lock"): cv.boolean,
    }
)
@websocket_api.async_response
async def ws_helper_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    settings = {k: msg[k] for k in ("hide_return_button", "cpu_lock", "wifi_lock") if k in msg}
    try:
        result = await coordinator.async_helper_config(msg["panel_id"], settings)
    except panel_helper.HelperError as err:
        connection.send_error(msg["id"], "helper_error", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/update_settings",
        vol.Optional("entry_id"): cv.string,
        vol.Optional("heater"): cv.entity_id,
        vol.Optional("temperature_sensor"): cv.entity_id,
        vol.Optional("eco_temp"): vol.Coerce(float),
        vol.Optional("boost_temp"): vol.Coerce(float),
        vol.Optional("away_temp"): vol.Coerce(float),
        vol.Optional("target_temp"): vol.Coerce(float),
        vol.Optional("summer_mode"): cv.boolean,
        vol.Optional("schedule_enabled"): cv.boolean,
        vol.Optional("person_entity"): cv.string,
        vol.Optional("presence_entities"): [cv.entity_id],
        vol.Optional("window_sensors"): [cv.entity_id],
        vol.Optional("window_open_delay_minutes"): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
        vol.Optional("cold_tolerance"): vol.Coerce(float),
        vol.Optional("hot_tolerance"): vol.Coerce(float),
        vol.Optional("min_on_minutes"): vol.All(vol.Coerce(float), vol.Range(min=1, max=30)),
        vol.Optional("min_off_minutes"): vol.All(vol.Coerce(float), vol.Range(min=1, max=30)),
        vol.Optional("true_radiant"): cv.boolean,
        vol.Optional("auto_schedule"): cv.boolean,
        vol.Optional("leaf_enabled"): cv.boolean,
        vol.Optional("away_delay_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=180)),
        vol.Optional("outdoor_temp_sensor"): cv.string,
        vol.Optional("safety_temp_enabled"): cv.boolean,
        vol.Optional("safety_min_temp"): vol.All(vol.Coerce(float), vol.Range(min=5, max=12)),
        vol.Optional("seasonal_savings"): cv.boolean,
        vol.Optional("adaptive_comfort"): cv.boolean,
        vol.Optional("wall_pin"): cv.string,
        vol.Optional("no_heat_alert"): cv.boolean,
        vol.Optional("no_heat_alert_minutes"): vol.All(vol.Coerce(int), vol.Range(min=20, max=240)),
        vol.Optional("alert_notify"): [cv.string],
        vol.Optional("kiosk_defaults"): dict,
        vol.Optional("kiosk_auto_sync"): cv.boolean,
        vol.Optional("backup_temperature_sensor"): cv.string,
        vol.Optional("sensor_stale_minutes"): vol.All(vol.Coerce(int), vol.Range(min=15, max=720)),
        vol.Optional("fast_sensor_reporting"): cv.boolean,
        vol.Optional("fast_reporting_sensors"): [cv.string],
        vol.Optional("watch_temperature_sensors"): [cv.string],
        vol.Optional("energy_sensor"): cv.string,
    }
)
@websocket_api.async_response
async def ws_update_settings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    updates = {
        k: msg[k]
        for k in (
            "heater",
            "temperature_sensor",
            "eco_temp",
            "boost_temp",
            "away_temp",
            "target_temp",
            "summer_mode",
            "schedule_enabled",
            "person_entity",
            "presence_entities",
            "window_sensors",
            "window_open_delay_minutes",
            "cold_tolerance",
            "hot_tolerance",
            "min_on_minutes",
            "min_off_minutes",
            "true_radiant",
            "auto_schedule",
            "leaf_enabled",
            "away_delay_minutes",
            "outdoor_temp_sensor",
            "safety_temp_enabled",
            "safety_min_temp",
            "seasonal_savings",
            "adaptive_comfort",
            "wall_pin",
            "no_heat_alert",
            "no_heat_alert_minutes",
            "alert_notify",
            "kiosk_defaults",
            "kiosk_auto_sync",
            "backup_temperature_sensor",
            "sensor_stale_minutes",
            "fast_sensor_reporting",
            "fast_reporting_sensors",
            "watch_temperature_sensors",
            "energy_sensor",
        )
        if k in msg
    }
    if "alert_notify" in updates:
        updates["alert_notify"] = [
            s.removeprefix("notify.") for s in updates["alert_notify"] if s.strip()
        ]
    if "kiosk_defaults" in updates:
        updates["kiosk_defaults"] = kiosk.clean_settings(updates["kiosk_defaults"])
    if "heater" in updates and updates["heater"].split(".", 1)[0] not in HEATER_DOMAINS:
        connection.send_error(
            msg["id"], "invalid", "heater must be a switch, input_boolean or climate"
        )
        return
    if "wall_pin" in updates:
        pin = str(updates["wall_pin"] or "").strip()
        if pin and (not pin.isdigit() or len(pin) != 4):
            connection.send_error(msg["id"], "invalid", "wall_pin must be 4 digits")
            return
        updates["wall_pin"] = pin
    pin_changed = "wall_pin" in updates and updates["wall_pin"] != str(coordinator.config.wall_pin or "").strip()
    config = await coordinator.async_save_config(updates)
    # Fully's menu PIN follows the wall PIN.
    synced = await coordinator.async_kiosk_apply() if "kiosk_defaults" in updates or pin_changed else {}
    connection.send_result(msg["id"], {"config": config.to_dict(), "kiosk_synced": synced})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/update_schedule",
        vol.Optional("entry_id"): cv.string,
        vol.Required("schedule"): dict,
        vol.Optional("schedule_enabled"): cv.boolean,
    }
)
@websocket_api.async_response
async def ws_update_schedule(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    updates: dict[str, Any] = {"schedule": msg.get("schedule") or default_schedule()}
    if "schedule_enabled" in msg:
        updates["schedule_enabled"] = msg["schedule_enabled"]
    coordinator.clear_holds()
    config = await coordinator.async_save_config(updates)
    connection.send_result(msg["id"], {"config": config.to_dict()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/update_rooms",
        vol.Optional("entry_id"): cv.string,
        vol.Required("rooms"): [dict],
    }
)
@websocket_api.async_response
async def ws_update_rooms(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    rooms = [RoomConfig.from_dict(r).to_dict() for r in msg.get("rooms") or []]
    config = await coordinator.async_save_config({"rooms": rooms})
    await hass.config_entries.async_reload(coordinator.entry.entry_id)
    connection.send_result(msg["id"], {"config": config.to_dict()})


def reorder_rooms(rooms: list[dict[str, Any]], room_ids: list[str]) -> list[dict[str, Any]]:
    """Put rooms in `room_ids` order; unknown ids are ignored, unlisted rooms keep their order at the end."""
    by_id = {r["id"]: r for r in rooms}
    ordered = [by_id[i] for i in dict.fromkeys(room_ids) if i in by_id]
    listed = {r["id"] for r in ordered}
    return ordered + [r for r in rooms if r["id"] not in listed]


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/reorder_rooms",
        vol.Optional("entry_id"): cv.string,
        vol.Required("room_ids"): [cv.string],
    }
)
@websocket_api.async_response
async def ws_reorder_rooms(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Change room order only. Same rooms, so no entry reload (heating keeps running)."""
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    rooms = reorder_rooms([r.to_dict() for r in coordinator.config.rooms], msg["room_ids"])
    config = await coordinator.async_save_config({"rooms": rooms})
    connection.send_result(msg["id"], {"room_ids": [r.id for r in config.rooms]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/list_wall_panels",
        vol.Optional("entry_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_list_wall_panels(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    panels = [p.to_dict() for p in coordinator.config.wall_panels]
    connection.send_result(msg["id"], {"wall_panels": panels})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/upsert_wall_panel",
        vol.Optional("entry_id"): cv.string,
        vol.Required("panel"): dict,
    }
)
@websocket_api.async_response
async def ws_upsert_wall_panel(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    panel = WallPanelConfig.from_dict(msg["panel"])
    if not panel.id:
        connection.send_error(msg["id"], "invalid", "panel.id required")
        return
    panels = [p for p in coordinator.config.wall_panels if p.id != panel.id]
    panels.append(panel)
    config = await coordinator.async_save_config(
        {"wall_panels": [p.to_dict() for p in panels]}
    )
    synced = await coordinator.async_kiosk_apply(panel.id) if panel.linked_kiosk_device else {}
    connection.send_result(
        msg["id"],
        {"wall_panels": [p.to_dict() for p in config.wall_panels], "panel": panel.to_dict(), "kiosk_synced": synced},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/delete_wall_panel",
        vol.Optional("entry_id"): cv.string,
        vol.Required("panel_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_delete_wall_panel(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    panel_id = msg["panel_id"]
    panels = [p.to_dict() for p in coordinator.config.wall_panels if p.id != panel_id]
    config = await coordinator.async_save_config({"wall_panels": panels})
    connection.send_result(
        msg["id"], {"wall_panels": [p.to_dict() for p in config.wall_panels]}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/get_wall_panel_config",
        vol.Required("panel_id"): cv.string,
        vol.Optional("entry_id"): cv.string,
        # The wall app's real screen (CSS px), shown in Nook's Wall panels tab.
        vol.Optional("screen"): dict,
    }
)
@websocket_api.async_response
async def ws_get_wall_panel_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    payload = coordinator.wall_panel_payload(msg["panel_id"])
    if payload is None:
        connection.send_error(msg["id"], "not_found", f"Unknown panel {msg['panel_id']}")
        return
    if msg.get("screen"):
        await coordinator.async_report_wall_screen(msg["panel_id"], msg["screen"])
    connection.send_result(msg["id"], {"config": payload})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/get_energy_history",
        vol.Optional("entry_id"): cv.string,
        vol.Optional("days"): vol.All(vol.Coerce(int), vol.Range(min=7, max=60)),
    }
)
@websocket_api.async_response
async def ws_get_energy_history(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    days = int(msg.get("days") or 31)
    connection.send_result(
        msg["id"],
        {
            "history": coordinator.energy_history(days=days),
            # Gas/energy per day and hour from the heating meter (Settings), if one is set.
            "meter": await energy_meter.async_energy_days(hass, coordinator.config.energy_sensor, days),
            "seasonal_savings": coordinator.data.get("seasonal_savings")
            if coordinator.data
            else {},
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/get_wall_usage",
        vol.Optional("entry_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_get_wall_usage(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The wall panel's usage page: last 24 h of heating, kWh and Leaf."""
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    connection.send_result(msg["id"], await coordinator.async_wall_usage())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/get_wall_room_settings",
        vol.Optional("entry_id"): cv.string,
        vol.Required("room_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_get_wall_room_settings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The wall panel's room cog: Room Temperature fields + simple TRV settings."""
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    result = coordinator.wall_room_settings(msg["room_id"])
    if result is None:
        connection.send_error(msg["id"], "not_found", f"Unknown room {msg['room_id']}")
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/update_wall_room",
        vol.Optional("entry_id"): cv.string,
        vol.Required("room_id"): cv.string,
        vol.Optional("follow_house"): cv.boolean,
        vol.Optional("house_offset"): vol.All(vol.Coerce(float), vol.Range(min=-5, max=5)),
        vol.Optional("target_temp"): vol.All(vol.Coerce(float), vol.Range(min=5, max=30)),
        vol.Optional("eco_temp"): vol.All(vol.Coerce(float), vol.Range(min=5, max=30)),
        vol.Optional("hold_ends"): vol.In(ROOM_HOLD_ENDS),
    }
)
@websocket_api.async_response
async def ws_update_wall_room(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    changes = {k: msg[k] for k in WALL_ROOM_FIELDS if k in msg}
    result = await coordinator.async_update_wall_room(msg["room_id"], changes)
    if result is None:
        connection.send_error(msg["id"], "not_found", f"Unknown room {msg['room_id']}")
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/verify_wall_pin",
        vol.Required("pin"): cv.string,
        vol.Optional("entry_id"): cv.string,
        vol.Optional("panel_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_verify_wall_pin(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    ok = coordinator.verify_wall_pin(msg.get("pin") or "")
    connection.send_result(msg["id"], {"ok": ok})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/stop_seasonal_savings",
        vol.Optional("entry_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_stop_seasonal_savings(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    config = await coordinator.async_stop_seasonal_savings()
    connection.send_result(msg["id"], {"config": config.to_dict()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/reset_warmup",
        vol.Optional("entry_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_reset_warmup(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    await coordinator.async_reset_warmup()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/release_control",
        vol.Optional("entry_id"): cv.string,
        vol.Optional("minutes", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
    }
)
@websocket_api.async_response
async def ws_release_control(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    until = await coordinator.async_release_control(msg["minutes"])
    connection.send_result(msg["id"], {"released_until": until})


@websocket_api.websocket_command(
    {vol.Required("type"): "nook/take_control", vol.Optional("entry_id"): cv.string}
)
@websocket_api.async_response
async def ws_take_control(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    await coordinator.async_take_control()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {vol.Required("type"): "nook/kiosk_status", vol.Optional("entry_id"): cv.string}
)
@websocket_api.async_response
async def ws_kiosk_status(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Fully Kiosk devices, house defaults, and target-vs-actual for every wall panel."""
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    connection.send_result(msg["id"], coordinator.kiosk_status())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/kiosk_apply",
        vol.Optional("entry_id"): cv.string,
        vol.Optional("panel_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_kiosk_apply(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Push settings now to one panel, or every linked panel."""
    coordinator = _coordinator(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Nook not loaded")
        return
    synced = await coordinator.async_kiosk_apply(msg.get("panel_id"))
    connection.send_result(msg["id"], {"synced": synced, **coordinator.kiosk_status()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/kiosk_read",
        vol.Optional("entry_id"): cv.string,
        vol.Required("device_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_kiosk_read(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """A Fully device's current values (for "Import from panel"). Unreadable ones are left out."""
    connection.send_result(msg["id"], {"settings": kiosk.read_current(hass, msg["device_id"])})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nook/kiosk_reload",
        vol.Optional("entry_id"): cv.string,
        vol.Required("panel_id"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_kiosk_reload(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Reload the wall app on a panel."""
    coordinator = _coordinator(hass, msg.get("entry_id"))
    panel = coordinator.get_wall_panel(msg["panel_id"]) if coordinator else None
    if panel is None or not panel.linked_kiosk_device:
        connection.send_error(msg["id"], "not_found", "That wall panel isn't linked to a Fully Kiosk device")
        return
    status = kiosk.panel_status(hass, panel, coordinator.config.kiosk_defaults, pin=coordinator._kiosk_pin)  # noqa: SLF001
    if not status.get("online") or not status.get("expected_url"):
        connection.send_error(msg["id"], "offline", "The panel is offline")
        return
    await kiosk.async_fresh_load(hass, panel.linked_kiosk_device, status["expected_url"])
    connection.send_result(msg["id"], {"ok": True})
