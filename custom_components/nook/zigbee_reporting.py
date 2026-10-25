"""Ask a Zigbee (ZHA) temperature sensor to report more often.

ZHA's default for temperature sensors (zha 2.3.x, Temperature entity) is a
report every 0.5 °C or 15 min, so a thermostat sees the house in coarse,
late steps. ZHA has no public API for changing this, so this reaches the
zigpy cluster through ZHA's gateway (checked against HA 2026.10.1: zha
2.3.1, zigpy 2.3.0); any failure (ZHA changed, device asleep, not a ZHA
sensor) is reported back as ReportingError, never crashes Nook.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

TEMPERATURE_CLUSTER = 0x0402
# (min s, max s, change in 0.01 °C)
FAST = (30, 300, 10)
ZHA_DEFAULT = (30, 900, 50)
TIMEOUT_S = 30


class ReportingError(Exception):
    """Couldn't configure reporting (message is shown to the user)."""

    def __init__(self, message: str, *, not_ready: bool = False) -> None:
        super().__init__(message)
        # ZHA is still starting (normal right after an HA restart): retry soon, quietly.
        self.not_ready = not_ready


def zha_ieee(hass: HomeAssistant, entity_id: str) -> str | None:
    """The ZHA IEEE address behind a sensor entity, or None if it isn't a ZHA entity."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != "zha" or not entry.device_id:
        return None
    device = dr.async_get(hass).async_get(entry.device_id)
    if device is None:
        return None
    for domain, ident in device.identifiers:
        if domain == "zha":
            return str(ident)
    return None


def zha_loaded(hass: HomeAssistant) -> bool:
    """ZHA has finished setting up: radio, devices and entities are all up.

    Not "zha" in hass.config.components: HA adds that *before* ZHA's config
    entry starts setting up (HA 2026.10.1 setup.py), and ZHA's gateway exists
    while it's still initialising devices — too early to send anything.
    """
    return any(
        entry.state is ConfigEntryState.LOADED
        for entry in hass.config_entries.async_entries("zha")
    )


def _zha_device(hass: HomeAssistant, ieee: str) -> Any:
    # Importing ZHA's modules ourselves before HA has loaded ZHA makes HA log
    # "blocking call ... by integration 'zha'" (its import reads package
    # metadata in the event loop). Wait until HA has loaded it.
    if not zha_loaded(hass):
        raise ReportingError("waiting for ZHA to start", not_ready=True)
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway
        from zigpy.types import EUI64
    except ImportError as err:
        raise ReportingError("ZHA isn't available") from err
    try:
        gateway = get_zha_gateway(hass)
    except ValueError as err:
        raise ReportingError("waiting for ZHA to start", not_ready=True) from err
    zha_device = gateway.get_device(EUI64.convert(ieee))
    if zha_device is None:
        raise ReportingError("waiting for ZHA to load this device", not_ready=True)
    return zha_device


def zha_last_seen(hass: HomeAssistant, entity_id: str) -> datetime | None:
    """When ZHA last heard anything from the sensor's device (UTC), else None.

    ZHA only passes a reading to HA when it changes, so HA's last_reported
    can't tell a steady sensor from a dead one; ZHA's own last_seen can.
    """
    ieee = zha_ieee(hass, entity_id)
    if ieee is None:
        return None
    try:
        seen = _zha_device(hass, ieee).last_seen
    except Exception:  # noqa: BLE001 — ZHA not ready / changed: fall back to HA's timestamps
        return None
    if seen is None:
        return None
    return datetime.fromtimestamp(float(seen), tz=timezone.utc)


def _temperature_cluster(hass: HomeAssistant, ieee: str) -> Any:
    zha_device = _zha_device(hass, ieee)
    for endpoint_id, endpoint in zha_device.device.endpoints.items():
        if endpoint_id == 0:  # ZDO
            continue
        cluster = endpoint.in_clusters.get(TEMPERATURE_CLUSTER)
        if cluster is not None:
            return cluster
    raise ReportingError("no temperature cluster on this device")


def _succeeded(result: Any) -> bool:
    """Did every attribute get configured? Status 0 is success.

    zigpy 2.x returns {attribute: Status}; older versions returned
    ConfigureReportingResponse records.
    """
    if isinstance(result, dict):
        return bool(result) and all(int(status) == 0 for status in result.values())
    records = result
    if isinstance(result, (list, tuple)) and result and isinstance(result[0], (list, tuple)):
        records = result[0]
    if not isinstance(records, (list, tuple)):
        return result is not None
    return all(int(getattr(rec, "status", 0)) == 0 for rec in records)


async def async_configure(hass: HomeAssistant, entity_id: str, *, fast: bool) -> None:
    """Set a ZHA temperature sensor's reporting. Raises ReportingError on failure."""
    ieee = zha_ieee(hass, entity_id)
    if ieee is None:
        raise ReportingError("not a Zigbee (ZHA) sensor")
    cluster = _temperature_cluster(hass, ieee)
    min_s, max_s, change = FAST if fast else ZHA_DEFAULT
    try:
        result = await asyncio.wait_for(
            cluster.configure_reporting("measured_value", min_s, max_s, change), TIMEOUT_S
        )
    except asyncio.TimeoutError as err:
        raise ReportingError("the sensor didn't answer (it may be asleep) — will retry") from err
    except Exception as err:  # noqa: BLE001 — zigpy raises many kinds
        raise ReportingError(f"Zigbee error: {err}") from err
    if not _succeeded(result):
        raise ReportingError(f"the sensor refused the setting ({result})")
    _LOGGER.info(
        "Nook: %s now reports every %.1f °C / %d min",
        entity_id,
        change / 100,
        max_s // 60,
    )
