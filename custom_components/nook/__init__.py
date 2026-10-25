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


async def _async_import_from_old(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Moving from the integration's old name: wait while it's still configured,
    copy its learned data once it has gone. See migrate.py."""
    from homeassistant.components import persistent_notification
    from homeassistant.exceptions import ConfigEntryNotReady

    from . import migrate

    old_id = entry.data.get(migrate.IMPORTED_FROM)
    if not old_id:
        return
    old = hass.config_entries.async_get_entry(old_id)
    if old is not None:
        mapping = {**(entry.data.get(migrate.RENAMED) or {}), **migrate.rename_old_entities(hass)}
        data, options = migrate.imported_config(old, mapping)
        # Keep Nook's copy current while the old one still runs (it follows the renames).
        hass.config_entries.async_update_entry(
            entry, data={**data, migrate.STORES_IMPORTED: False}, options=options
        )
        persistent_notification.async_create(
            hass,
            "Nook has copied your settings and moved your heating entities to their new names. "
            "To finish, remove the old **Neat Thermostat** integration (Settings → Devices & services). "
            "Nook won't control the heating until then, so two controllers never fight over the boiler; "
            "it takes over within a minute or two of the removal, with your learned data.",
            title="Nook: one step left",
            notification_id=migrate.NOTIFICATION_ID,
        )
        raise ConfigEntryNotReady("waiting for the old Neat Thermostat integration to be removed")
    if not entry.data.get(migrate.STORES_IMPORTED):
        copied = await migrate.async_copy_stores(hass, old_id, entry.entry_id)
        _LOGGER.info("Nook: took over from Neat Thermostat (copied %s)", ", ".join(copied) or "nothing")
        hass.config_entries.async_update_entry(entry, data={**entry.data, migrate.STORES_IMPORTED: True})
        persistent_notification.async_create(
            hass,
            "Nook is now running your heating, with your settings and learned data. "
            "You can remove Neat Thermostat from HACS too.",
            title="Nook has taken over",
            notification_id=migrate.NOTIFICATION_ID,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import NookCoordinator
    from .panel import async_register_panel

    await _async_import_from_old(hass, entry)
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
