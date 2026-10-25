"""One-time move from the integration's old name (neat_thermostat) to Nook.

1. Adding Nook while the old integration is installed offers an import of its
   settings (config flow).
2. While the old integration is still configured, Nook renames its climate
   entities to Nook's entity ids (HA carries their history across a rename),
   keeps its copy of the settings current, and does NOT start: two controllers
   on one boiler relay would fight.
3. Once the old integration has been removed, Nook copies its learned data
   (left on disk) and takes over under the same entity ids.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .intelligence import STORAGE_KEY as INTEL_KEY
from .intelligence import STORAGE_VERSION as INTEL_VERSION

_LOGGER = logging.getLogger(__name__)

OLD_DOMAIN = "neat_thermostat"
OLD_UNIQUE_PREFIX = "neat_"
IMPORTED_FROM = "imported_from"
STORES_IMPORTED = "stores_imported"
NOTIFICATION_ID = f"{DOMAIN}_import"


def old_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """The old integration's config entry, if it is still configured."""
    entries = hass.config_entries.async_entries(OLD_DOMAIN)
    return entries[0] if entries else None


def nook_entity_id(old_unique_id: str) -> str | None:
    """neat_home → climate.nook_home, neat_<room> → climate.nook_<room>."""
    if not old_unique_id.startswith(OLD_UNIQUE_PREFIX):
        return None
    return f"climate.{DOMAIN}_{old_unique_id[len(OLD_UNIQUE_PREFIX):]}"


def nook_unique_id(old_unique_id: str) -> str:
    return f"{DOMAIN}_{old_unique_id[len(OLD_UNIQUE_PREFIX):]}"


@callback
def rename_old_entities(hass: HomeAssistant) -> dict[str, str]:
    """Give the old climate entities Nook's entity ids. {old id: new id}, including
    ones renamed on an earlier pass (looked up by unique id)."""
    reg = er.async_get(hass)
    mapping: dict[str, str] = {}
    for entry in list(reg.entities.values()):
        if entry.platform != OLD_DOMAIN or entry.domain != "climate":
            continue
        target = nook_entity_id(str(entry.unique_id))
        if target is None:
            continue
        if entry.entity_id != target:
            if reg.async_get(target) is not None:
                _LOGGER.warning("Nook: can't rename %s — %s already exists", entry.entity_id, target)
                continue
            _LOGGER.info("Nook: renaming %s → %s (history moves with it)", entry.entity_id, target)
            mapping[entry.entity_id] = target
            reg.async_update_entity(entry.entity_id, new_entity_id=target)
    return mapping


def swap_ids(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [swap_ids(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: swap_ids(v, mapping) for k, v in value.items()}
    return value


RENAMED = "renamed_entities"


def imported_config(old: ConfigEntry, mapping: dict[str, str]) -> tuple[dict, dict]:
    """(data, options) for Nook from the old entry, with renamed entity ids. The
    mapping is kept in the data: on later passes the entities are already renamed."""
    data = swap_ids({k: v for k, v in old.data.items()}, mapping)
    data[IMPORTED_FROM] = old.entry_id
    data[RENAMED] = dict(mapping)
    return data, swap_ids(dict(old.options), mapping)


async def async_copy_stores(hass: HomeAssistant, old_entry_id: str, new_entry_id: str) -> list[str]:
    """Copy the old integration's learned data and wall-panel store (left on disk after
    its removal). Never overwrites Nook data that already exists."""
    copied: list[str] = []
    for old_key, new_key, version in (
        (f"{OLD_DOMAIN}.intelligence.{old_entry_id}", f"{INTEL_KEY}.{new_entry_id}", INTEL_VERSION),
        (f"{OLD_DOMAIN}.kiosk_{old_entry_id}", f"{DOMAIN}.kiosk_{new_entry_id}", 1),
    ):
        new_store: Store = Store(hass, version, new_key)
        if await new_store.async_load() is not None:
            continue
        data = await Store(hass, version, old_key).async_load()
        if data is None:
            continue
        await new_store.async_save(data)
        copied.append(new_key)
    return copied
