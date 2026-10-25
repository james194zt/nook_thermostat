"""Gas or energy used by the heating, read from a meter's statistics in Home Assistant.

Any meter HA keeps statistics for works: a boiler's own kWh counter, a smart meter's
gas import in kWh, or a gas meter in m³ (or ft³ / CCF). Energy is shown in kWh; gas
volume stays in what the meter measures (litres become m³). A lifetime total or one
that resets daily both work: the recorder's "change" handles both, and it includes
the last few minutes (5-minute statistics), so "today" is current.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Volume units shown as they are; any other volume (L, gal…) is shown in m³.
KEEP_VOLUME_UNITS = {"m³", "ft³", "CCF", "MCF"}


def display_unit(unit_class: str | None, unit: str | None) -> tuple[str, dict[str, str]] | None:
    """(unit to show, recorder `units` conversion) for a meter, or None if it isn't one."""
    if unit_class == "energy":
        return "kWh", {"energy": "kWh"}
    if unit_class == "volume":
        shown = unit if unit in KEEP_VOLUME_UNITS else "m³"
        return shown, {"volume": shown}
    return None


def _change(hass, entity_id, start, end, units) -> float | None:
    from homeassistant.components.recorder.statistics import statistic_during_period

    value = statistic_during_period(hass, start, end, entity_id, {"change"}, units).get("change")
    return None if value is None else max(0.0, float(value))


def _meter_units(hass: HomeAssistant, entity_id: str) -> tuple[str, dict[str, str]] | None:
    from homeassistant.components.recorder.statistics import get_metadata

    meta = get_metadata(hass, statistic_ids={entity_id}).get(entity_id)
    if meta is None:
        return None  # no statistics for this sensor (no state_class, or not recorded)
    return display_unit(meta[1].get("unit_class"), meta[1].get("unit_of_measurement"))


def _read(hass: HomeAssistant, entity_id: str, now: datetime, hours: int) -> dict[str, Any] | None:
    from homeassistant.components.recorder.statistics import statistics_during_period

    shown = _meter_units(hass, entity_id)
    if shown is None:
        return None
    unit, units = shown

    since = now - timedelta(hours=hours)
    day_start = dt_util.start_of_local_day(dt_util.as_local(now))
    today = _change(hass, entity_id, day_start, None, units)
    # Yesterday up to the same time of day, for "vs yesterday".
    yesterday = _change(hass, entity_id, day_start - timedelta(days=1), now - timedelta(days=1), units)

    hour_start = now.replace(minute=0, second=0, microsecond=0)
    first = since.replace(minute=0, second=0, microsecond=0)
    rows = statistics_during_period(
        hass, first, hour_start, {entity_id}, "hour", units, {"change"}
    ).get(entity_id, [])
    hourly: list[dict[str, float]] = []
    for row in rows:
        start = row.get("start")
        change = row.get("change")
        if start is None or change is None:
            continue
        at = datetime.fromtimestamp(float(start), tz=dt_util.UTC)
        hourly.append({"m": round((at - since).total_seconds() / 60.0, 1), "v": round(max(0.0, float(change)), 3)})
    # The hour in progress isn't an hourly statistic yet.
    current = _change(hass, entity_id, hour_start, None, units)
    if current is not None:
        hourly.append({"m": round((hour_start - since).total_seconds() / 60.0, 1), "v": round(current, 3)})

    return {
        "unit": unit,
        "kind": "volume" if units.get("volume") else "energy",
        "today": None if today is None else round(today, 3),
        "yesterday": None if yesterday is None else round(yesterday, 3),
        "hourly": hourly,
        "last_24h": round(sum(h["v"] for h in hourly if h["m"] >= 0), 3),
    }


def _read_days(hass: HomeAssistant, entity_id: str, now: datetime, days: int) -> dict[str, Any] | None:
    """Per local day: the total and 24 hourly amounts (DST's extra hour adds to its hour)."""
    from homeassistant.components.recorder.statistics import statistics_during_period

    shown = _meter_units(hass, entity_id)
    if shown is None:
        return None
    unit, units = shown
    first_day = dt_util.start_of_local_day(dt_util.as_local(now)) - timedelta(days=days - 1)
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    rows = statistics_during_period(
        hass, first_day, hour_start, {entity_id}, "hour", units, {"change"}
    ).get(entity_id, [])
    by_day: dict[str, list[float]] = {}

    def add(at_utc: datetime, value: float) -> None:
        local = dt_util.as_local(at_utc)
        by_day.setdefault(local.date().isoformat(), [0.0] * 24)[local.hour] += max(0.0, value)

    for row in rows:
        if row.get("start") is not None and row.get("change") is not None:
            add(datetime.fromtimestamp(float(row["start"]), tz=dt_util.UTC), float(row["change"]))
    # The hour in progress isn't an hourly statistic yet.
    current = _change(hass, entity_id, hour_start, None, units)
    if current:
        add(hour_start, current)
    return {
        "unit": unit,
        "kind": "volume" if units.get("volume") else "energy",
        "days": {
            day: {"total": round(sum(hours), 3), "hours": [round(v, 3) for v in hours]}
            for day, hours in by_day.items()
        },
    }


async def _run(hass: HomeAssistant, entity_id: str, func, *args) -> dict[str, Any] | None:
    if not entity_id or "recorder" not in hass.config.components:
        return None
    from homeassistant.components.recorder import get_instance

    try:
        data = await get_instance(hass).async_add_executor_job(func, hass, entity_id, dt_util.utcnow(), *args)
    except Exception:  # noqa: BLE001 - a usage page must never break on a meter
        _LOGGER.debug("Nook: couldn't read statistics for %s", entity_id, exc_info=True)
        return None
    if data is None:
        return None
    state = hass.states.get(entity_id)
    data["entity_id"] = entity_id
    data["name"] = (state.attributes.get("friendly_name") if state else None) or entity_id
    return data


async def async_energy_days(hass: HomeAssistant, entity_id: str, days: int = 31) -> dict[str, Any] | None:
    """The meter per local day (total + hourly) for the Energy page; None if unknown."""
    return await _run(hass, entity_id, _read_days, days)


async def async_energy_usage(hass: HomeAssistant, entity_id: str, hours: int = 24) -> dict[str, Any] | None:
    """Used today, yesterday by now, and per hour over the window; None if unknown."""
    return await _run(hass, entity_id, _read, hours)