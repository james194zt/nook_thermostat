"""House sensor health: spot a dead sensor, fall back to a backup, then to timed heating.

A battery sensor that dies keeps its last value in Home Assistant (a frozen
23 °C means no heat, ever). Zigbee sensors report on a heartbeat even when
the temperature doesn't change, and HA records every report in
``last_reported`` (not just changes), so silence is a reliable sign of a dead
sensor in any weather.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

SOURCE_MAIN = "main"
SOURCE_BACKUP = "backup"
SOURCE_NONE = "none"

# Learn the main-minus-backup difference at most this often, this gently,
# and only from reports this recent: a dying sensor repeats its last value
# for a while before it counts as dead, and that mustn't skew the offset.
OFFSET_SAMPLE_MINUTES = 10
OFFSET_WEIGHT = 0.05
OFFSET_FRESH_MINUTES = 16
# Sensors without a device "last seen" (anything but ZHA) may only update HA
# when their value changes, so silence means less: wait at least this long.
NO_HEARTBEAT_STALE_MINUTES = 180
# With no sensor at all: during comfort, this many minutes of heat per hour;
# outside comfort (frost safety), this many minutes every FROST_EVERY_HOURS.
FALLBACK_COMFORT_MINUTES = 20
FALLBACK_FROST_MINUTES = 15
FALLBACK_FROST_EVERY_HOURS = 4
FROST_OUTDOOR_C = 5.0


@dataclass
class SensorHealth:
    """Persisted: which sensor is in use and the learned backup offset."""

    source: str = SOURCE_MAIN
    since: str | None = None
    # main minus backup, while both report (added to the backup's reading).
    offset_c: float | None = None
    offset_samples: int = 0
    last_offset_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SensorHealth:
        if not data:
            return cls()
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        try:
            health = cls(**known)
        except TypeError:
            return cls()
        if health.source not in (SOURCE_MAIN, SOURCE_BACKUP, SOURCE_NONE):
            health.source = SOURCE_MAIN
        return health


def reading(
    state: Any,
    *,
    now_utc: datetime,
    stale_minutes: float,
    device_seen: datetime | None = None,
) -> float | None:
    """A sensor's value if it is alive and recent, else None.

    ``device_seen`` is the device's own last-heard time (ZHA's last_seen),
    which beats HA's last_reported: ZHA doesn't pass on unchanged readings.
    """
    if state is None or state.state in ("unknown", "unavailable", ""):
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    heard = device_seen or getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
    if heard is not None and now_utc - heard > timedelta(minutes=stale_minutes):
        return None
    return value


def choose(
    main: float | None, backup: float | None, health: SensorHealth
) -> tuple[float | None, str]:
    """(house temperature, source) from the main sensor, else the backup + offset."""
    if main is not None:
        return main, SOURCE_MAIN
    if backup is not None:
        return round(backup + (health.offset_c or 0.0), 2), SOURCE_BACKUP
    return None, SOURCE_NONE


def learn_offset(
    health: SensorHealth, main: float | None, backup: float | None, now: datetime
) -> bool:
    """Track how far apart the two sensors usually read. Returns True if it changed."""
    if main is None or backup is None:
        return False
    last = None
    if health.last_offset_at:
        try:
            last = datetime.fromisoformat(health.last_offset_at)
        except ValueError:
            last = None
    if last is not None and now - last < timedelta(minutes=OFFSET_SAMPLE_MINUTES):
        return False
    diff = main - backup
    if health.offset_c is None:
        health.offset_c = round(diff, 3)
    else:
        # Faster at first, then a slow average over days of readings.
        weight = max(OFFSET_WEIGHT, 1.0 / (health.offset_samples + 1))
        health.offset_c = round(health.offset_c * (1 - weight) + diff * weight, 3)
    health.offset_samples += 1
    health.last_offset_at = now.isoformat()
    return True


def fallback_heat(now: datetime, *, comfort: bool, frost: bool) -> bool:
    """Timed heating while no sensor works: comfort share of each hour, or frost runs."""
    if comfort:
        return now.minute < FALLBACK_COMFORT_MINUTES
    if frost:
        return now.hour % FALLBACK_FROST_EVERY_HOURS == 0 and now.minute < FALLBACK_FROST_MINUTES
    return False


def frost_risk(outdoor: float | None, *, summer_mode: bool) -> bool:
    """Is a frost-safety run worthwhile? Unknown outdoors: yes, unless it's summer."""
    if outdoor is not None:
        return outdoor < FROST_OUTDOOR_C
    return not summer_mode
