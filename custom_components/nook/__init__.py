"""Nook — boiler + TRV coordination with HA sidebar and wall panels."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    from .websocket_api import async_register_ws_handlers

    async_register_ws_handlers(hass)

    async def _register_panel_on_start(_event: Event) -> None:
        if not hass.config_entries.async_entries(DOMAIN):
            return
        from .panel import async_register_panel

        try:
            await async_register_panel(hass)
        except Exception:
            _LOGGER.exception("Nook panel registration failed on HA start")

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_panel_on_start)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import NookCoordinator
    from .panel import async_register_panel

    coordinator = NookCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    device_reg = dr.async_get(hass)
    device_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Nook",
        model="Thermostat Hub",
    )

    await coordinator.async_initialize_intelligence()
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_setup_listeners()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    try:
        await async_register_panel(hass)
    except Exception:
        _LOGGER.exception("Nook panel registration failed")

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    old_room_ids = {r.id for r in coordinator.config.rooms}
    coordinator.update_config({**entry.data, **entry.options})
    new_room_ids = {r.id for r in coordinator.config.rooms}
    await coordinator.async_request_refresh()
    # Only reload platforms when the room climate set changes
    if old_room_ids != new_room_ids:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    await coordinator.async_unload()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
