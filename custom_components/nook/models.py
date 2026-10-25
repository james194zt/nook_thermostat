"""Data models for Nook."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .kiosk import clean_settings
from .const import (
    DAYS,
    DEFAULT_ADAPTIVE_COMFORT,
    DEFAULT_AUTO_SCHEDULE,
    DEFAULT_AWAY_DELAY_MINUTES,
    DEFAULT_WINDOW_OPEN_DELAY_MINUTES,
    DEFAULT_AWAY_TEMP,
    DEFAULT_BOOST_TEMP,
    DEFAULT_COLD_TOLERANCE,
    DEFAULT_ECO_TEMP,
    DEFAULT_HOT_TOLERANCE,
    DEFAULT_LEAF_ENABLED,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_OFF_MINUTES,
    DEFAULT_MIN_ON_MINUTES,
    DEFAULT_MIN_TEMP,
    DEFAULT_NO_HEAT_ALERT,
    DEFAULT_NO_HEAT_ALERT_MINUTES,
    DEFAULT_SAFETY_MIN_TEMP,
    DEFAULT_SAFETY_TEMP_ENABLED,
    DEFAULT_SEASONAL_SAVINGS,
    DEFAULT_SENSOR_STALE_MINUTES,
    DEFAULT_WALL_PANEL_MODEL,
    DEFAULT_TARGET_TEMP,
    DEFAULT_TRUE_RADIANT,
    DEFAULT_WALL_PIN,
    ROOM_HOLD_ENDS,
    WALL_PANEL_SHAPES,
)


@dataclass
class RoomConfig:
    """One heated room (TRV climate wrapper)."""

    id: str
    name: str
    trv_entity: str
    temperature_sensor: str = ""
    extra_temperature_sensors: list[str] = field(default_factory=list)
    window_sensors: list[str] = field(default_factory=list)
    target_temp: float = DEFAULT_TARGET_TEMP
    eco_temp: float = DEFAULT_ECO_TEMP
    boost_temp: float = DEFAULT_BOOST_TEMP
    enabled: bool = True
    # When True, a cold room can call the boiler on (needed for most TRVs).
    calls_for_heat: bool = True
    # True: the room's target is the house target + house_offset (so the house
    # dial, schedule and presets move it). False: its own target/eco temps.
    follow_house: bool = True
    house_offset: float = 0.0
    # How long a change made on the room itself lasts (ROOM_HOLD_ENDS).
    hold_ends: str = "house_change"
    # Keep the TRV's own temperature offset at "room sensor − TRV" (needs a room sensor).
    calibrate_trv: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoomConfig:
        extras = list(data.get("extra_temperature_sensors") or [])
        return cls(
            id=str(data.get("id") or data.get("name", "room")).lower().replace(" ", "_"),
            name=str(data.get("name") or "Room"),
            trv_entity=str(data.get("trv_entity") or data.get("entity") or ""),
            temperature_sensor=str(data.get("temperature_sensor") or ""),
            extra_temperature_sensors=[str(x) for x in extras if x],
            window_sensors=list(data.get("window_sensors") or []),
            target_temp=float(data.get("target_temp", DEFAULT_TARGET_TEMP)),
            eco_temp=float(data.get("eco_temp", DEFAULT_ECO_TEMP)),
            boost_temp=float(data.get("boost_temp", DEFAULT_BOOST_TEMP)),
            enabled=bool(data.get("enabled", True)),
            calls_for_heat=bool(data.get("calls_for_heat", True)),
            follow_house=bool(data.get("follow_house", True)),
            house_offset=max(-5.0, min(5.0, float(data.get("house_offset") or 0.0))),
            hold_ends=(
                data.get("hold_ends")
                if data.get("hold_ends") in ROOM_HOLD_ENDS
                else "house_change"
            ),
            calibrate_trv=bool(data.get("calibrate_trv", False)),
        )


@dataclass
class ScheduleBlock:
    """One time block in a day schedule."""

    start: str  # HH:MM
    end: str
    temperature: float
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleBlock:
        return cls(
            start=str(data.get("start", "06:00")),
            end=str(data.get("end", "22:00")),
            temperature=float(data.get("temperature", DEFAULT_TARGET_TEMP)),
            enabled=bool(data.get("enabled", True)),
        )


def default_day_schedule() -> list[dict[str, Any]]:
    return [
        ScheduleBlock("06:30", "08:30", 20.0).to_dict(),
        ScheduleBlock("16:00", "22:00", 20.0).to_dict(),
    ]


def default_schedule() -> dict[str, list[dict[str, Any]]]:
    return {day: default_day_schedule() for day in DAYS}


def _wall_shape(value: Any) -> str:
    """Screen type; the pre-0.6.40 NSPanel Pro model id becomes the NSPanel Pro type."""
    shape = str(value or "")
    if shape == "nspanel_pro_gen2":
        return "nspanel_pro"
    return shape if shape in WALL_PANEL_SHAPES else DEFAULT_WALL_PANEL_MODEL


def _helper_host(value: Any) -> str:
    """Helper address override. Digits only is a pairing code typed in the wrong box
    (seen 14 Oct: "931710"), not an address: ignore it so the Fully address is used."""
    host = str(value or "").strip()
    return "" if host.isdigit() else host


@dataclass
class WallPanelConfig:
    """Central config for one physical wall screen."""

    id: str
    label: str
    primary_entity: str = ""
    rooms: list[dict[str, str]] = field(default_factory=list)
    sensors: dict[str, str] = field(default_factory=dict)
    display: dict[str, Any] = field(default_factory=dict)
    temperature_lock: bool = False
    model: str = DEFAULT_WALL_PANEL_MODEL
    # Fully Kiosk Browser device (HA device id) and settings that differ from the house defaults.
    kiosk_device: str = ""
    kiosk_overrides: dict[str, Any] = field(default_factory=dict)
    # Off for screens that don't run Fully Kiosk: Nook then leaves the panel alone,
    # but remembers the linked device for when it's switched back on.
    kiosk_enabled: bool = True
    # Nook Panel Helper address (NSPanel Pro); blank = the linked Fully device's address.
    helper_host: str = ""

    @property
    def linked_kiosk_device(self) -> str:
        """The Fully device Nook manages for this panel ("" = none)."""
        return self.kiosk_device if self.kiosk_enabled else ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WallPanelConfig:
        return cls(
            id=str(data.get("id") or "").lower().replace(" ", "-"),
            label=str(data.get("label") or data.get("id") or "Panel"),
            primary_entity=str(data.get("primary_entity") or ""),
            rooms=list(data.get("rooms") or []),
            sensors=dict(data.get("sensors") or {}),
            display=dict(data.get("display") or {"idleMs": 30000, "panelEntity": ""}),
            temperature_lock=bool(data.get("temperature_lock", False)),
            model=_wall_shape(data.get("model")),
            kiosk_device=str(data.get("kiosk_device") or ""),
            kiosk_overrides=clean_settings(data.get("kiosk_overrides")),
            kiosk_enabled=bool(data.get("kiosk_enabled", True)),
            helper_host=_helper_host(data.get("helper_host")),
        )


@dataclass
class NookConfig:
    """Full integration options stored on the config entry."""

    heater: str
    temperature_sensor: str
    window_sensors: list[str] = field(default_factory=list)
    rooms: list[RoomConfig] = field(default_factory=list)
    # How long a window or door must stay open before it stops the heat (0 = at once).
    window_open_delay_minutes: float = DEFAULT_WINDOW_OPEN_DELAY_MINUTES
    eco_temp: float = DEFAULT_ECO_TEMP
    boost_temp: float = DEFAULT_BOOST_TEMP
    away_temp: float = DEFAULT_AWAY_TEMP
    target_temp: float = DEFAULT_TARGET_TEMP
    cold_tolerance: float = DEFAULT_COLD_TOLERANCE
    hot_tolerance: float = DEFAULT_HOT_TOLERANCE
    min_temp: float = DEFAULT_MIN_TEMP
    max_temp: float = DEFAULT_MAX_TEMP
    min_on_minutes: float = DEFAULT_MIN_ON_MINUTES
    min_off_minutes: float = DEFAULT_MIN_OFF_MINUTES
    summer_mode: bool = False
    person_entity: str = ""
    presence_entities: list[str] = field(default_factory=list)
    schedule: dict[str, list[dict[str, Any]]] = field(default_factory=default_schedule)
    wall_panels: list[WallPanelConfig] = field(default_factory=list)
    schedule_enabled: bool = True
    true_radiant: bool = DEFAULT_TRUE_RADIANT
    auto_schedule: bool = DEFAULT_AUTO_SCHEDULE
    away_delay_minutes: int = DEFAULT_AWAY_DELAY_MINUTES
    outdoor_temp_sensor: str = ""
    leaf_enabled: bool = DEFAULT_LEAF_ENABLED
    safety_temp_enabled: bool = DEFAULT_SAFETY_TEMP_ENABLED
    safety_min_temp: float = DEFAULT_SAFETY_MIN_TEMP
    seasonal_savings: bool = DEFAULT_SEASONAL_SAVINGS
    adaptive_comfort: bool = DEFAULT_ADAPTIVE_COMFORT
    wall_pin: str = DEFAULT_WALL_PIN
    no_heat_alert: bool = DEFAULT_NO_HEAT_ALERT
    no_heat_alert_minutes: int = DEFAULT_NO_HEAT_ALERT_MINUTES
    # notify services (e.g. "mobile_app_my_phone") that get Nook's alerts.
    alert_notify: list[str] = field(default_factory=list)
    # Fully Kiosk settings every panel shares (a missing key = not managed).
    kiosk_defaults: dict[str, Any] = field(default_factory=dict)
    kiosk_auto_sync: bool = True
    # Used when the house sensor goes silent (dead battery, out of range).
    backup_temperature_sensor: str = ""
    # A sensor that hasn't reported for this long is treated as dead.
    sensor_stale_minutes: int = DEFAULT_SENSOR_STALE_MINUTES
    # Pre-0.6.81 house-sensors-only switch; kept so old saves migrate.
    fast_sensor_reporting: bool = False
    # Zigbee (ZHA) temperature sensors asked to report every 0.1 °C / 5 min
    # (Settings → Temperature Sensors, per sensor).
    fast_reporting_sensors: list[str] = field(default_factory=list)
    # Sensors Nook only watches (e.g. upstairs rooms without TRVs): listed with
    # their floor, not used for heating decisions (yet).
    watch_temperature_sensors: list[str] = field(default_factory=list)
    # Optional kWh meter for the heating (boiler or gas supply), for the usage page.
    energy_sensor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "heater": self.heater,
            "temperature_sensor": self.temperature_sensor,
            "window_sensors": self.window_sensors,
            "window_open_delay_minutes": self.window_open_delay_minutes,
            "rooms": [r.to_dict() for r in self.rooms],
            "eco_temp": self.eco_temp,
            "boost_temp": self.boost_temp,
            "away_temp": self.away_temp,
            "target_temp": self.target_temp,
            "cold_tolerance": self.cold_tolerance,
            "hot_tolerance": self.hot_tolerance,
            "min_temp": self.min_temp,
            "max_temp": self.max_temp,
            "min_on_minutes": self.min_on_minutes,
            "min_off_minutes": self.min_off_minutes,
            "summer_mode": self.summer_mode,
            "person_entity": self.person_entity,
            "presence_entities": self.presence_entities,
            "schedule": self.schedule,
            "wall_panels": [w.to_dict() for w in self.wall_panels],
            "schedule_enabled": self.schedule_enabled,
            "true_radiant": self.true_radiant,
            "auto_schedule": self.auto_schedule,
            "away_delay_minutes": self.away_delay_minutes,
            "outdoor_temp_sensor": self.outdoor_temp_sensor,
            "leaf_enabled": self.leaf_enabled,
            "safety_temp_enabled": self.safety_temp_enabled,
            "safety_min_temp": self.safety_min_temp,
            "seasonal_savings": self.seasonal_savings,
            "adaptive_comfort": self.adaptive_comfort,
            "wall_pin": self.wall_pin,
            "wall_pin_configured": bool(str(self.wall_pin or "").strip()),
            "no_heat_alert": self.no_heat_alert,
            "no_heat_alert_minutes": self.no_heat_alert_minutes,
            "alert_notify": self.alert_notify,
            "kiosk_defaults": self.kiosk_defaults,
            "kiosk_auto_sync": self.kiosk_auto_sync,
            "backup_temperature_sensor": self.backup_temperature_sensor,
            "sensor_stale_minutes": self.sensor_stale_minutes,
            "fast_sensor_reporting": self.fast_sensor_reporting,
            "fast_reporting_sensors": self.fast_reporting_sensors,
            "watch_temperature_sensors": self.watch_temperature_sensors,
            "energy_sensor": self.energy_sensor,
        }

    @classmethod
    def from_entry_data(cls, data: dict[str, Any]) -> NookConfig:
        rooms_raw = data.get("rooms") or []
        panels_raw = data.get("wall_panels") or []
        schedule = data.get("schedule") or default_schedule()
        presence = list(data.get("presence_entities") or [])
        person = str(data.get("person_entity") or "")
        if person and person not in presence:
            presence = [person, *presence]
        if "fast_reporting_sensors" in data:
            fast_sensors = [str(e) for e in (data.get("fast_reporting_sensors") or []) if e]
        elif data.get("fast_sensor_reporting"):
            # The old switch meant "the house sensor and its backup".
            fast_sensors = [
                str(e) for e in (data.get("temperature_sensor"), data.get("backup_temperature_sensor")) if e
            ]
        else:
            fast_sensors = []
        pin = str(data.get("wall_pin") or DEFAULT_WALL_PIN).strip()
        if pin and (not pin.isdigit() or len(pin) != 4):
            pin = DEFAULT_WALL_PIN
        return cls(
            heater=str(data.get("heater") or ""),
            temperature_sensor=str(data.get("temperature_sensor") or ""),
            window_sensors=list(data.get("window_sensors") or []),
            window_open_delay_minutes=min(
                30.0, max(0.0, float(data.get("window_open_delay_minutes", DEFAULT_WINDOW_OPEN_DELAY_MINUTES)))
            ),
            rooms=[RoomConfig.from_dict(r) for r in rooms_raw],
            eco_temp=float(data.get("eco_temp", DEFAULT_ECO_TEMP)),
            boost_temp=float(data.get("boost_temp", DEFAULT_BOOST_TEMP)),
            away_temp=float(data.get("away_temp", DEFAULT_AWAY_TEMP)),
            target_temp=float(data.get("target_temp", DEFAULT_TARGET_TEMP)),
            cold_tolerance=float(data.get("cold_tolerance", DEFAULT_COLD_TOLERANCE)),
            hot_tolerance=float(data.get("hot_tolerance", DEFAULT_HOT_TOLERANCE)),
            min_temp=float(data.get("min_temp", DEFAULT_MIN_TEMP)),
            max_temp=float(data.get("max_temp", DEFAULT_MAX_TEMP)),
            # Never 0: an unguarded relay can chatter the boiler on and off.
            min_on_minutes=min(30.0, max(1.0, float(data.get("min_on_minutes", DEFAULT_MIN_ON_MINUTES)))),
            min_off_minutes=min(30.0, max(1.0, float(data.get("min_off_minutes", DEFAULT_MIN_OFF_MINUTES)))),
            summer_mode=bool(data.get("summer_mode", False)),
            person_entity=person,
            presence_entities=presence,
            schedule=schedule,
            wall_panels=[WallPanelConfig.from_dict(p) for p in panels_raw],
            schedule_enabled=bool(data.get("schedule_enabled", True)),
            true_radiant=bool(data.get("true_radiant", DEFAULT_TRUE_RADIANT)),
            auto_schedule=bool(data.get("auto_schedule", DEFAULT_AUTO_SCHEDULE)),
            away_delay_minutes=int(
                data.get("away_delay_minutes", DEFAULT_AWAY_DELAY_MINUTES)
            ),
            outdoor_temp_sensor=str(data.get("outdoor_temp_sensor") or ""),
            leaf_enabled=bool(data.get("leaf_enabled", DEFAULT_LEAF_ENABLED)),
            safety_temp_enabled=bool(
                data.get("safety_temp_enabled", DEFAULT_SAFETY_TEMP_ENABLED)
            ),
            safety_min_temp=float(
                data.get("safety_min_temp", DEFAULT_SAFETY_MIN_TEMP)
            ),
            seasonal_savings=bool(
                data.get("seasonal_savings", DEFAULT_SEASONAL_SAVINGS)
            ),
            adaptive_comfort=bool(
                data.get("adaptive_comfort", DEFAULT_ADAPTIVE_COMFORT)
            ),
            wall_pin=pin,
            no_heat_alert=bool(data.get("no_heat_alert", DEFAULT_NO_HEAT_ALERT)),
            no_heat_alert_minutes=int(
                data.get("no_heat_alert_minutes", DEFAULT_NO_HEAT_ALERT_MINUTES)
            ),
            alert_notify=[
                str(s).removeprefix("notify.")
                for s in (data.get("alert_notify") or [])
                if str(s).strip()
            ],
            kiosk_defaults=clean_settings(data.get("kiosk_defaults")),
            kiosk_auto_sync=bool(data.get("kiosk_auto_sync", True)),
            backup_temperature_sensor=str(data.get("backup_temperature_sensor") or ""),
            sensor_stale_minutes=min(
                720, max(15, int(data.get("sensor_stale_minutes", DEFAULT_SENSOR_STALE_MINUTES)))
            ),
            fast_sensor_reporting=bool(data.get("fast_sensor_reporting", False)),
            fast_reporting_sensors=fast_sensors,
            watch_temperature_sensors=[str(e) for e in (data.get("watch_temperature_sensors") or []) if e],
            energy_sensor=str(data.get("energy_sensor") or ""),
        )
