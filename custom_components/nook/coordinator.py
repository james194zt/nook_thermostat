"""Coordinator: boiler demand + house intelligence."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_OPEN, EntityCategory
from homeassistant.core import CoreState, HomeAssistant, State, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_ECO,
    PRESET_NONE,
    WALL_ROOM_FIELDS,
    WALL_TRV_SETTING_DOMAINS,
)
from . import intelligence
from .intelligence import (
    LONG_PREHEAT_MINUTES,
    MAX_PREHEAT_MINUTES,
    HeatCheck,
    IntelligenceStore,
    PreheatRoom,
    WarmupModel,
    accrue_leaf_minutes,
    active_block_key,
    energy_history_payload,
    estimate_time_to_temp_minutes,
    evaluate_leaf,
    leaf_week_stats,
    learn_schedule_from_adjustments,
    note_comfort_setpoint,
    note_setpoint_event,
    preheat_status,
    presence_anyone_home,
    record_manual_adjustment,
    seasonal_bake,
    seasonal_offset,
    seasonal_push_back,
    seasonal_savings_step,
    stop_seasonal_savings,
    track_heat_interval,
    update_away_tracking,
    update_coast_watch,
    update_heat_check,
    update_warmup_from_cycle,
    wall_usage_payload,
)
from .control import boiler_cycle_guard, house_calls_for_heat, next_schedule_change, room_calls_for_heat
from . import energy_meter, kiosk, panel_helper, zigbee_reporting
from .sensor_health import (
    NO_HEARTBEAT_STALE_MINUTES,
    OFFSET_FRESH_MINUTES,
    SOURCE_BACKUP,
    SOURCE_MAIN,
    SOURCE_NONE,
    choose,
    fallback_heat,
    frost_risk,
    learn_offset,
    reading,
)
from .models import NookConfig, RoomConfig, WallPanelConfig
from .schedule import scheduled_temperature

_LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = timedelta(seconds=30)
# A sensor change must last this long before Nook switches source and alerts.
SENSOR_SWITCH_CONFIRM = timedelta(minutes=3)
# Re-send fast reporting this often (a ZHA "Reconfigure" resets it), and retry
# a sleeping sensor this soon.
REPORTING_REFRESH = timedelta(hours=24)
REPORTING_RETRY = timedelta(minutes=30)
# ZHA still starting after an HA restart: try again shortly.
REPORTING_RETRY_SOON = timedelta(minutes=2)
# Once ZHA is loaded it still polls every mains device in the background; send
# nothing to the radio until that has had time to finish.
ZIGBEE_SETTLE = timedelta(minutes=3)
# A TRV that doesn't answer (asleep, out of range, flat battery) is tried again
# after 1, 2, 4 … up to 30 min — not every tick: ZHA queues each command for
# ~30 s+, and on 17 Oct 2026 21 of them were still waiting when HA stopped.
TRV_RETRY_MIN = timedelta(minutes=1)
TRV_RETRY_MAX = timedelta(minutes=30)
# The same command isn't repeated sooner than this even when it went through: a
# TRV that clamps the setpoint (min/max limit) would otherwise get it every tick.
TRV_REPEAT_AFTER = timedelta(minutes=10)
# TRV calibration: a TRV reads the air at its own hot radiator (21 Oct 2026: the
# hall TRV read 21.3 °C and shut while the room sensor beside it read 19), so its
# own temperature offset is kept at "room sensor − TRV". Written at most this
# often, only when it moves by at least CALIBRATE_MIN_CHANGE, and only once the
# TRV has reported a reading taken with the last offset (or WAIT has passed).
# The over-read depends on how hot the radiator is (21 Oct live: ~0.5 °C cold,
# ~3 °C hot), so while the room is below its target the offset only ever moves
# down — easing it back then would let the valve shut again as the radiator
# warms — and those corrections may go out every CALIBRATE_EVERY_HEATING.
CALIBRATE_EVERY = timedelta(minutes=15)
CALIBRATE_EVERY_HEATING = timedelta(minutes=5)
CALIBRATE_MIN_CHANGE = 0.3
# Never above 0: a TRV only under-reads with its radiator cold, which harms nothing,
# and a positive offset made it shut early at the next warm-up (21 Oct: +2.5 overnight).
CALIBRATE_MAX_OFFSET = 0.0
# A room sensor moving faster than this isn't measuring the room yet — e.g. a new
# one settling (21 Oct: placed at 25.0 °C, fell 3.7 °C in 25 min ≈ 9 °C/h). A real
# warm-up reached 3.6 °C/h (23 Oct, living room with Faster updates on).
CALIBRATE_SETTLING_C_PER_HOUR = 6.0
CALIBRATE_SETTLING_WINDOW = timedelta(minutes=15)
# A TRV can over-read by more than its offset can correct (22 Oct: living room
# TRVs read 20.0 at −2.5 with the room at 17.8, and shut). Then the setpoint is
# raised by what's left, at most this much, only while the room sensor is below
# target; it only grows during a warm-up and drops back once the room is there.
# 24 Oct: +3 ran out — hot radiators made the hall (23 Oct) and living-room front
# (24 Oct) TRVs read ~5.7–6 °C over the room even at −2.5.
TRV_TOPUP_MAX = 6.0
# Added while the room warms (26 Oct: the hall's valve eased off near target and the last
# 0.6 °C took over an hour — the boiler ran 2 h 53 min and upstairs reached 25 °C).
TRV_TOPUP_MARGIN = 2.0
CALIBRATE_WAIT_FOR_TRV = timedelta(minutes=60)
# A "run" longer than this (e.g. HA was down while it ended) teaches nothing.
MAX_LEARN_RUN_HOURS = 6


class NookCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Own heating logic and shared config for climates + panel."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.entry = entry
        self.config = NookConfig.from_entry_data({**entry.data, **entry.options})
        self._unsubs: list[Any] = []
        # State-change subscription, rebuilt when the watched entities change.
        self._state_unsub: Any = None
        self._watched: tuple[str, ...] = ()
        # Fully Kiosk panels: watched entities, pending syncs and back-off (transient by design:
        # after a restart everything is simply re-checked against the saved config).
        self._kiosk_unsub: Any = None
        self._kiosk_watched: dict[str, str] = {}
        self._kiosk_timers: dict[str, Any] = {}
        self._kiosk_attempts: dict[str, int] = {}
        # Wall app version the panels were last given a cache-clearing reload for,
        # and the screen each wall panel last reported ("screens").
        self._kiosk_store: Store = Store(hass, 1, f"{DOMAIN}.kiosk_{entry.entry_id}")
        self._wall_screens: dict[str, dict[str, Any]] | None = None
        # A panel coming back changes several entities at once: one version refresh at a time.
        self._version_refresh_lock = asyncio.Lock()
        # Nook Panel Helper: last status per panel (display only), last update request sent.
        self._helper_status: dict[str, dict[str, Any]] = {}
        self._helper_update_sent: dict[str, tuple[Any, datetime]] = {}
        # Last seen heater availability, so a dropout is logged once.
        self._heater_available = True
        self._main_hvac_mode = "heat"
        self._main_preset = PRESET_NONE
        self._main_target = self.config.target_temp
        # The house target as last worked out; rooms that follow the house use it.
        self._house_target = self.config.target_temp
        # Bumped on every manual house change (dial, preset, mode): room holds
        # set to end "at the next house change" compare against it.
        self._house_rev = 0
        self._room_states: dict[str, dict[str, Any]] = {}
        for room in self.config.rooms:
            self._room_states[room.id] = {
                "hvac_mode": "heat",
                "preset": PRESET_NONE,
                "target": room.target_temp,
                "needs_heat": False,
            }
        intelligence.clock = self._now
        self.intel = IntelligenceStore(hass, entry.entry_id)
        self._away_eco_active = False
        self._preheat: dict[str, Any] | None = None
        # The schedule block whose preheat has begun (persisted): it runs on until
        # the block starts instead of being re-estimated off as the house warms.
        self._preheat_started: str | None = None
        self._heat_cycle_start: datetime | None = None
        self._heat_cycle_start_temp: float | None = None
        self._heat_cycle_house_called = False
        self._last_boiler_on = False
        # Hysteresis state: is the house currently calling for heat?
        self._house_calling = False
        # Manual setpoint while the schedule runs: {"temperature", "until"}.
        self._manual_hold: dict[str, Any] | None = None
        # Relay released for a hand test until this time (UTC); Nook leaves it alone.
        self._released_until: datetime | None = None
        # Last on/off change of the relay Nook has seen: {"on", "since" (UTC ISO)}.
        # HA restarts the relay's last_changed at start-up; the anti-short-cycle
        # timer must not start again from there.
        self._relay_seen: dict[str, Any] | None = None
        # A different sensor source seen but not yet confirmed (debounce blips,
        # e.g. "unavailable" for seconds while HA starts): (source, since UTC).
        self._sensor_pending: tuple[str, datetime] | None = None
        # Fast-reporting results per sensor, for Settings (rebuilt after a restart).
        self._reporting_status: dict[str, dict[str, Any]] = {}
        self._reporting_next_try: dict[str, datetime] = {}
        self._reporting_task: asyncio.Task | None = None
        # When Zigbee requests may start (UTC): set once HA is running and ZHA
        # is loaded, plus ZIGBEE_SETTLE; cleared whenever either stops being true.
        self._zigbee_ok_after: datetime | None = None
        # TRV commands: the one in flight per TRV, back-off after a failure
        # {"failures", "at"}, and the last batch sent (signature, when). Transient by
        # design: after a restart every TRV simply gets one fresh try.
        self._trv_tasks: dict[str, asyncio.Task] = {}
        self._trv_retry: dict[str, dict[str, Any]] = {}
        self._trv_last_sent: dict[str, tuple[Any, datetime]] = {}
        # Last calibration written per TRV: {"offset", "reading", "at"} — so the next
        # one waits for a TRV reading taken with it. Lost on restart, which is safe:
        # the offset entity's own last_changed then spaces the writes.
        self._trv_calibration: dict[str, dict[str, Any]] = {}
        # Recent room-sensor readings (UTC, °C) for the settling check; refills
        # within CALIBRATE_SETTLING_WINDOW after a restart.
        self._room_sensor_samples: dict[str, list[tuple[datetime, float]]] = {}
        # Setpoint top-up per room in this warm-up (see TRV_TOPUP_MAX). Rebuilt
        # from live readings after a restart.
        self._trv_topups: dict[str, float] = {}
        # False while the house schedule is in setback (rooms drop to Eco).
        self._house_comfort = True
        self._dirty_intel = False
        self._leaf: dict[str, Any] = {"active": False}
        self._safety_active = False
        self._time_to_temp: int | None = None
        self._seasonal_info: dict[str, Any] = {"active": False, "offset_c": 0.0}
        self._last_logged_setpoint: float | None = None
        self.data = self._snapshot()

    async def async_initialize_intelligence(self) -> None:
        await self.intel.async_load()
        self._restore_control()
        self._restore_heat_cycle()

    def _restore_control(self) -> None:
        """Bring back mode/preset/setpoints so a restart doesn't flip Off to Heat."""
        saved = self.intel.state.control or {}
        main = saved.get("main") or {}
        if main.get("hvac_mode") in ("heat", "off"):
            self._main_hvac_mode = main["hvac_mode"]
        if main.get("preset") in (PRESET_NONE, PRESET_ECO, PRESET_BOOST, PRESET_AWAY):
            self._main_preset = main["preset"]
        if isinstance(main.get("target"), (int, float)):
            self._main_target = float(main["target"])
        hold = main.get("manual_hold")
        if isinstance(hold, dict) and isinstance(hold.get("temperature"), (int, float)):
            self._manual_hold = hold
        if isinstance(main.get("house_rev"), int):
            self._house_rev = main["house_rev"]
        self._released_until = dt_util.parse_datetime(str(saved.get("released_until") or ""))
        # Mid-run after a restart: keep heating to the cut-off, not the cut-in.
        self._house_calling = bool(saved.get("house_calling"))
        self._preheat_started = str(saved.get("preheat_started") or "") or None
        relay = saved.get("relay")
        if isinstance(relay, dict) and dt_util.parse_datetime(str(relay.get("since") or "")):
            self._relay_seen = {"on": bool(relay.get("on")), "since": relay["since"]}
        for room_id, room in (saved.get("rooms") or {}).items():
            st = self._room_states.get(room_id)
            if st is None or not isinstance(room, dict):
                continue
            if room.get("hvac_mode") in ("heat", "off"):
                st["hvac_mode"] = room["hvac_mode"]
            if room.get("preset") in (PRESET_NONE, PRESET_ECO, PRESET_BOOST):
                st["preset"] = room["preset"]
            if isinstance(room.get("target"), (int, float)):
                st["target"] = float(room["target"])
            if isinstance(room.get("hold"), dict):
                st["hold"] = room["hold"]
            st["needs_heat"] = bool(room.get("needs_heat"))

    def _persist_control(self) -> None:
        self.intel.state.control = {
            "released_until": self._released_until.isoformat() if self._released_until else None,
            "house_calling": self._house_calling,
            "preheat_started": self._preheat_started,
            "relay": self._relay_seen,
            "main": {
                "hvac_mode": self._main_hvac_mode,
                "preset": self._main_preset,
                "target": self._main_target,
                "manual_hold": self._manual_hold,
                "house_rev": self._house_rev,
            },
            "rooms": {
                room_id: {
                    "hvac_mode": st.get("hvac_mode", "heat"),
                    "preset": st.get("preset", PRESET_NONE),
                    "target": st.get("target"),
                    "hold": st.get("hold"),
                    "needs_heat": bool(st.get("needs_heat")),
                }
                for room_id, st in self._room_states.items()
            },
        }
        self.intel.async_delay_save()

    def update_config(self, data: dict[str, Any]) -> None:
        self.config = NookConfig.from_entry_data(data)
        for room in self.config.rooms:
            if room.id not in self._room_states:
                self._room_states[room.id] = {
                    "hvac_mode": "heat",
                    "preset": PRESET_NONE,
                    "target": room.target_temp,
                    "needs_heat": False,
                }
        # A new heater/sensor must be watched, or its changes go unnoticed
        # until the next 30s tick.
        if self._state_unsub is not None:
            self._subscribe_state_changes()
        if self._kiosk_unsub is not None:
            self._kiosk_subscribe()

    async def async_save_config(self, updates: dict[str, Any]) -> NookConfig:
        if updates.get("seasonal_savings") is False:
            stop_seasonal_savings(self.intel.state.seasonal)
            self._dirty_intel = True
            await self.intel.async_save()
            self._dirty_intel = False
        old_heater = self.config.heater
        new_heater = updates.get("heater")
        if new_heater and old_heater and new_heater != old_heater:
            # Don't leave the old relay calling for heat once Nook lets go of it.
            await self._async_switch_heater(old_heater, False)
        current = {**self.entry.data, **self.entry.options}
        merged = {**current, **updates}
        data_keys = {"heater", "temperature_sensor"}
        new_data = {k: merged[k] for k in data_keys if k in merged}
        new_options = {k: v for k, v in merged.items() if k not in data_keys}
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, **new_data}, options=new_options
        )
        self.update_config({**self.entry.data, **new_options})
        await self.async_request_refresh()
        return self.config

    @callback
    def _async_follow_rename(self, old: str, new: str) -> bool:
        """An entity Nook uses got a new entity id in HA: use the new one everywhere
        (house/backup sensors, relay, rooms' TRVs and sensors, windows, watch and
        Faster-updates lists, wall panels). True if anything changed.

        23 Oct 2026: renaming the bedroom 1 sensor left Nook watching an id that
        no longer existed.
        """

        def swap(value: Any) -> Any:
            if isinstance(value, str):
                return new if value == old else value
            if isinstance(value, list):
                return [swap(v) for v in value]
            if isinstance(value, dict):
                return {k: swap(v) for k, v in value.items()}
            return value

        data, options = swap(dict(self.entry.data)), swap(dict(self.entry.options))
        if data == dict(self.entry.data) and options == dict(self.entry.options):
            return False
        _LOGGER.info("Nook: %s was renamed to %s — following it", old, new)
        # Straight to the entry (not async_save_config): a renamed relay is the same
        # relay, so it mustn't be switched off as if it had been replaced.
        self.hass.config_entries.async_update_entry(self.entry, data=data, options=options)
        self.update_config({**data, **options})
        if self._state_unsub is not None:
            self._subscribe_state_changes()
        return True

    def verify_wall_pin(self, pin: str) -> bool:
        expected = str(self.config.wall_pin or "").strip()
        if not expected:
            return False
        return str(pin or "").strip() == expected

    async def async_stop_seasonal_savings(self) -> NookConfig:
        stop_seasonal_savings(self.intel.state.seasonal)
        self._dirty_intel = True
        await self.intel.async_save()
        self._dirty_intel = False
        return await self.async_save_config({"seasonal_savings": False})

    async def async_reset_warmup(self) -> None:
        """Forget the learned warm-up rate and coast (e.g. learned while the boiler was faulty)."""
        self.intel.state.warmup = WarmupModel()
        self.intel.state.coast_watch.clear()
        self.intel.state.recent_cycles = []
        self.intel.state.room_warmup = {}
        self.intel.state.room_runs = {}
        await self.intel.async_save()
        await self.async_request_refresh()

    async def async_release_control(self, minutes: int = 60) -> str:
        """Stop switching the relay so it can be tested by hand; taken back automatically."""
        self._released_until = dt_util.utcnow() + timedelta(minutes=max(1, min(60, minutes)))
        _LOGGER.info("Nook: boiler relay released until %s", self._released_until.isoformat())
        self._persist_control()
        await self.intel.async_save()
        await self.async_request_refresh()
        return self._released_until.isoformat()

    async def async_take_control(self) -> None:
        if self._released_until is None:
            return
        self._released_until = None
        _LOGGER.info("Nook: took the boiler relay back")
        self._persist_control()
        await self.intel.async_save()
        await self.async_request_refresh()

    def _relay_released(self) -> bool:
        """Is the relay released right now? Ends the release once its time is up."""
        if self._released_until is None:
            return False
        if dt_util.utcnow() < self._released_until:
            return True
        _LOGGER.info("Nook: relay test time is up; taking the boiler relay back")
        self._released_until = None
        self._persist_control()
        return False

    def energy_history(self, days: int = 31) -> dict[str, Any]:
        return energy_history_payload(
            self.intel.state.energy,
            self.intel.state.leaf,
            days=days,
        )

    async def async_wall_usage(self) -> dict[str, Any]:
        """The wall panel's usage page: last 24 h of boiler runs, kWh and Leaf."""
        usage = wall_usage_payload(self.intel.state.energy)
        leaf = dict(self._leaf)
        week = leaf.get("week_days") or []
        usage["leaf"] = {
            "enabled": self.config.leaf_enabled,
            "active": bool(leaf.get("active")),
            "minutes_today": week[-1]["minutes"] if week else 0.0,
            "goal_minutes": intelligence.LEAF_DAY_MEANINGFUL_MINUTES,
            "days_streak": leaf.get("days_streak", 0),
            "hours_week": leaf.get("hours_week", 0.0),
            "hours_total": leaf.get("hours_total", 0.0),
            "week_days": week,
        }
        usage["energy"] = await energy_meter.async_energy_usage(self.hass, self.config.energy_sensor)
        usage["energy_sensor"] = self.config.energy_sensor
        return usage
    def _snapshot(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "main": {
                "hvac_mode": self._main_hvac_mode,
                "preset": self._main_preset,
                "target": self._main_target,
                "manual_hold": self._manual_hold,
            },
            "rooms": {k: dict(v) for k, v in self._room_states.items()},
            "away": self._away_eco_active,
            "window_open": self._any_window_open(self.config.window_sensors),
            "summer_mode": self.config.summer_mode,
            "preheat": self._preheat,
            "leaf": self._leaf,
            "safety_active": self._safety_active,
            "time_to_temp_minutes": self._time_to_temp,
            "heating_fault": self._heating_fault_info(),
            "house_sensor": self._sensor_info(),
            "temperature_sensors": self.temperature_sensors_info(),
            "room_floors": self.room_floors(),
            "room_warmup": self.room_warmup_info(),
            "control_released_until": (
                self._released_until.isoformat() if self._released_until else None
            ),
            "seasonal_savings": self._seasonal_info,
            "intelligence": {
                "true_radiant": self.config.true_radiant,
                "auto_schedule": self.config.auto_schedule,
                "away_delay_minutes": self.config.away_delay_minutes,
                "warmup_c_per_hour": self.intel.state.warmup.c_per_hour,
                "warmup_samples": self.intel.state.warmup.samples,
                "coast_c": self.intel.state.warmup.coast_c,
                "coast_samples": self.intel.state.warmup.coast_samples,
                "leaf_enabled": self.config.leaf_enabled,
                "safety_temp_enabled": self.config.safety_temp_enabled,
                "seasonal_savings": self.config.seasonal_savings,
                "adaptive_comfort": self.config.adaptive_comfort,
            },
        }

    def _heating_fault_info(self) -> dict[str, Any] | None:
        check = self.intel.state.heat_check
        if not check.fault_since:
            return None
        return {
            "since": check.fault_since,
            "on_minutes": round(check.fault_on_minutes),
            "rise_c": round(check.fault_rise_c, 1),
            "trvs_offline": list(check.fault_offline),
            "trvs_closed": list(check.fault_closed),
        }

    def _state_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", ""):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _sensor_value(self, entity_id: str, stale_minutes: float, *, strict: bool = False) -> float | None:
        if not entity_id:
            return None
        seen = zigbee_reporting.zha_last_seen(self.hass, entity_id)
        if seen is None and not strict:
            # No device heartbeat to go on: HA may only hear about changes.
            stale_minutes = max(stale_minutes, NO_HEARTBEAT_STALE_MINUTES)
        return reading(
            self.hass.states.get(entity_id),
            now_utc=dt_util.utcnow(),
            stale_minutes=stale_minutes,
            device_seen=seen,
        )

    def _sensor_values(self, stale_minutes: float | None = None) -> tuple[float | None, float | None]:
        """(main, backup) house readings; None for a sensor that's dead or silent.

        An explicit ``stale_minutes`` (offset learning) is applied strictly.
        """
        strict = stale_minutes is not None
        stale = stale_minutes or self.config.sensor_stale_minutes
        main_id = self.config.temperature_sensor
        backup_id = self.config.backup_temperature_sensor
        main = self._sensor_value(main_id, stale, strict=strict)
        backup = self._sensor_value(backup_id, stale, strict=strict) if backup_id != main_id else None
        return main, backup

    def _house_reading(self) -> tuple[float | None, str]:
        """(house temperature, source): main sensor, else backup + learned offset, else none."""
        main, backup = self._sensor_values()
        return choose(main, backup, self.intel.state.sensor_health)

    def _house_temp(self) -> float | None:
        return self._house_reading()[0]

    def _sensor_settled_none(self) -> bool:
        """No working sensor, confirmed (not a blip): time for timed heating."""
        return (
            bool(self.config.temperature_sensor)
            and self.intel.state.sensor_health.source == SOURCE_NONE
        )

    def _sensor_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id) if entity_id else None
        return str(state.attributes.get("friendly_name") or entity_id) if state else entity_id

    async def _async_check_house_sensor(self) -> None:
        """Learn the backup offset; switch source (and alert) once a change has lasted."""
        health = self.intel.state.sensor_health
        if learn_offset(health, *self._sensor_values(OFFSET_FRESH_MINUTES), self._now()):
            self._dirty_intel = True
        main, backup = self._sensor_values()
        _, source = choose(main, backup, health)
        if not self.config.temperature_sensor or source == health.source:
            self._sensor_pending = None
            return
        now = dt_util.utcnow()
        if self._sensor_pending is None or self._sensor_pending[0] != source:
            self._sensor_pending = (source, now)
        # Coming back to the main sensor needs no wait; losing it does.
        if source != SOURCE_MAIN and now - self._sensor_pending[1] < SENSOR_SWITCH_CONFIRM:
            return
        previous = health.source
        health.source = source
        health.since = self._now().isoformat()
        self._sensor_pending = None
        await self.intel.async_save()
        await self._async_alert_sensor(previous, source)

    async def _async_alert_sensor(self, previous: str, source: str) -> None:
        main = self._sensor_name(self.config.temperature_sensor)
        backup = self._sensor_name(self.config.backup_temperature_sensor)
        minutes = self.config.sensor_stale_minutes
        notification_id = f"{DOMAIN}_sensor_{self.entry.entry_id}"
        if source == SOURCE_MAIN:
            title = "Nook: house sensor is back"
            message = f"{main} is reporting again; Nook is using it."
            persistent_notification.async_dismiss(self.hass, notification_id)
        elif source == SOURCE_BACKUP:
            offset = self.intel.state.sensor_health.offset_c or 0.0
            title = "Nook: house sensor isn't reporting"
            message = (
                f"{main} hasn't reported for over {minutes} min (flat battery or out of range?). "
                f"Nook is using {backup} instead"
                + (f", adjusted by {offset:+.1f}°C to match" if abs(offset) >= 0.05 else "")
                + "."
            )
        else:
            title = "Nook: no house temperature sensor is working"
            silent = main + (f" and {backup}" if self.config.backup_temperature_sensor else "")
            message = (
                f"{silent} haven't reported for over {minutes} min, so Nook can't tell how warm "
                "the house is. It is heating on a timer until a sensor is back: 20 min in every "
                "hour during schedule times, plus short frost-protection runs. "
                "Check the sensor's battery."
            )
        _LOGGER.warning("Nook: %s — %s", title, message)
        if source != SOURCE_MAIN:
            persistent_notification.async_create(
                self.hass, message, title=title, notification_id=notification_id
            )
        self.hass.bus.async_fire(
            f"{DOMAIN}_sensor_source", {"source": source, "previous": previous}
        )
        await self._async_notify_phones(title, message)

    async def _async_sync_sensor_reporting(self) -> None:
        """Keep house sensors on the reporting the user chose (declarative, re-applied).

        Runs in the background: a sleeping sensor can take 30 s to answer and
        the control loop mustn't wait for it. Nothing is sent while HA or ZHA
        is starting or stopping: ZHA is busiest with the radio then, and a
        restart sometimes left ZHA stuck until the host was rebooted.
        """
        task = self._reporting_task
        if task is not None and not task.done():
            return
        if not self._zigbee_settled():
            return
        targets: dict[str, bool] = {e: True for e in self.config.fast_reporting_sensors if e}
        for entity_id in self.intel.state.fast_reporting:
            targets.setdefault(entity_id, False)  # put it back to ZHA's default
        now = dt_util.utcnow()
        due = {
            entity_id: fast
            for entity_id, fast in targets.items()
            if (self._reporting_status.get(entity_id) or {}).get("fast") != fast
            or now >= self._reporting_next_try.get(entity_id, now)
        }
        for entity_id in list(self._reporting_status):
            if entity_id not in targets:
                self._reporting_status.pop(entity_id)
        if due:
            self._reporting_task = self.hass.async_create_background_task(
                self._async_apply_reporting(due), f"{DOMAIN}_sensor_reporting"
            )

    def _zigbee_settled(self) -> bool:
        """HA running, ZHA loaded, and both have been for ZIGBEE_SETTLE."""
        if self.hass.state is not CoreState.running or not zigbee_reporting.zha_loaded(self.hass):
            self._zigbee_ok_after = None
            return False
        now = dt_util.utcnow()
        if self._zigbee_ok_after is None:
            self._zigbee_ok_after = now + ZIGBEE_SETTLE
        return now >= self._zigbee_ok_after

    async def _async_apply_reporting(self, targets: dict[str, bool]) -> None:
        applied = self.intel.state.fast_reporting
        for entity_id, fast in targets.items():
            if self.hass.is_stopping:
                break
            now = dt_util.utcnow()
            if zigbee_reporting.zha_ieee(self.hass, entity_id) is None:
                self._reporting_status[entity_id] = {"supported": False, "fast": fast}
                self._reporting_next_try[entity_id] = now + REPORTING_REFRESH
                if entity_id in applied and not fast:
                    applied.remove(entity_id)
                    self._dirty_intel = True
                continue
            try:
                await zigbee_reporting.async_configure(self.hass, entity_id, fast=fast)
            except zigbee_reporting.ReportingError as err:
                if err.not_ready:
                    _LOGGER.debug("Nook: %s reporting: %s", entity_id, err)
                else:
                    _LOGGER.warning("Nook: couldn't set %s reporting: %s", entity_id, err)
                self._reporting_status[entity_id] = {
                    "supported": True, "fast": fast, "ok": False, "error": str(err),
                    "pending": err.not_ready, "at": now.isoformat(),
                    # Set on the sensor earlier (kept across restarts): only this
                    # re-check missed it, e.g. a sleepy sensor (23 Oct, SNZB-02P).
                    "applied": entity_id in applied,
                }
                self._reporting_next_try[entity_id] = now + (
                    REPORTING_RETRY_SOON if err.not_ready else REPORTING_RETRY
                )
                continue
            self._reporting_status[entity_id] = {
                "supported": True, "fast": fast, "ok": True, "at": now.isoformat(),
            }
            self._reporting_next_try[entity_id] = now + REPORTING_REFRESH
            if fast and entity_id not in applied:
                applied.append(entity_id)
                self._dirty_intel = True
            elif not fast and entity_id in applied:
                applied.remove(entity_id)
                self._dirty_intel = True
        if self._dirty_intel:
            self.intel.async_delay_save()
            self._dirty_intel = False

    def _sensor_info(self) -> dict[str, Any]:
        health = self.intel.state.sensor_health
        return {
            "source": health.source,
            "since": health.since,
            "offset_c": health.offset_c,
            "main": self.config.temperature_sensor,
            "backup": self.config.backup_temperature_sensor,
            "reporting": self._reporting_status,
        }

    def temperature_sensors_info(self) -> list[dict[str, Any]]:
        """Every temperature sensor Nook reads, what for, and its faster-updates state
        (Settings → Temperature Sensors)."""
        uses: dict[str, list[str]] = {}
        for entity_id, use in (
            (self.config.temperature_sensor, "house"),
            (self.config.backup_temperature_sensor, "backup"),
        ):
            if entity_id:
                uses.setdefault(entity_id, []).append(use)
        for room in self.config.rooms:
            for entity_id in self._room_sensor_ids(room):
                uses.setdefault(entity_id, []).append(f"room:{room.name}")
        for entity_id in self.config.watch_temperature_sensors:
            uses.setdefault(entity_id, []).append("watch")
        fast = set(self.config.fast_reporting_sensors)
        sensors = [
            {
                "entity_id": entity_id,
                "uses": used_for,
                "floor": self.entity_floor(entity_id),
                "zigbee": zigbee_reporting.zha_ieee(self.hass, entity_id) is not None,
                "fast": entity_id in fast,
                "reporting": self._reporting_status.get(entity_id),
            }
            for entity_id, used_for in uses.items()
        ]
        # Lowest floor first; sensors without a floor last.
        sensors.sort(key=lambda s: (s["floor"] is None, (s["floor"] or {}).get("level") or 0))
        return sensors

    def entity_floor(self, entity_id: str) -> dict[str, Any] | None:
        """The HA floor an entity is on, through its own area or its device's
        (Settings → Areas & zones). None when no area/floor is set."""
        entry = er.async_get(self.hass).async_get(entity_id) if entity_id else None
        if entry is None:
            return None
        area_id = entry.area_id
        if not area_id and entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            area_id = device.area_id if device else None
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        if area is None or not area.floor_id:
            return None
        floor = fr.async_get(self.hass).async_get_floor(area.floor_id)
        if floor is None:
            return None
        return {"id": floor.floor_id, "name": floor.name, "level": floor.level, "area": area.name}

    def room_floors(self) -> dict[str, dict[str, Any] | None]:
        """Each room's floor, from its TRV."""
        return {room.id: self.entity_floor(room.trv_entity) for room in self.config.rooms}

    def _is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and state.state in (STATE_ON, "heat", "heating")

    def _any_window_open(self, sensors: list[str], *, delayed: bool = True) -> bool:
        """A window or door that has stayed open for the set delay (Settings → Windows & Doors).

        Timed from the sensor's own last change in HA, so a door opened for a moment never stops the
        heating and nothing has to be remembered across a restart. The 30-second tick picks up the
        moment the delay runs out. delayed=False: open at all (a brief opening still spoils a
        radiator-coast measurement).
        """
        delay = timedelta(minutes=float(self.config.window_open_delay_minutes)) if delayed else timedelta(0)
        now = dt_util.utcnow()
        for entity_id in sensors:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            if state.state in (STATE_OPEN, STATE_ON, "on", "open") and now - state.last_changed >= delay:
                return True
        return False

    def _presence_entities(self) -> list[str]:
        entities = list(self.config.presence_entities or [])
        if self.config.person_entity and self.config.person_entity not in entities:
            entities.append(self.config.person_entity)
        return entities

    def _refresh_away(self) -> None:
        anyone = presence_anyone_home(
            self.hass.states.get, self._presence_entities()
        )
        prev_since = self.intel.state.away_since
        self.intel.state, self._away_eco_active = update_away_tracking(
            self.intel.state,
            anyone_home=anyone,
            delay_minutes=self.config.away_delay_minutes,
        )
        if self.intel.state.away_since != prev_since:
            self._dirty_intel = True

    def _eco_target(self, base: float) -> float:
        """Eco/Away setpoint, never within 1 °C of the safety floor."""
        floor = float(self.config.safety_min_temp) + 1.0
        return max(floor, round(base, 1))

    def effective_main_target(self) -> tuple[float, bool]:
        """Return (target_temp, schedule_or_preheat_active)."""
        target, active = self._compute_main_target()
        self._house_target = float(target)
        return target, active

    def _compute_main_target(self) -> tuple[float, bool]:
        outdoor = self._state_float(self.config.outdoor_temp_sensor)
        seasonal = self.intel.state.seasonal
        # Seasonal Savings only lowers schedule blocks; it needs the schedule.
        self._seasonal_info, stepped = seasonal_savings_step(
            seasonal,
            self.config.schedule,
            enabled=self.config.seasonal_savings and self.config.schedule_enabled,
            now=self._now(),
        )
        if stepped:
            self._dirty_intel = True

        self._preheat = None
        self._house_comfort = True
        if self._main_preset == PRESET_BOOST:
            return self.config.boost_temp, False

        self._house_comfort = False
        if self._away_eco_active or self._main_preset == PRESET_AWAY:
            return self._eco_target(self.config.away_temp), False
        if self._main_preset == PRESET_ECO:
            return self._eco_target(self.config.eco_temp), False

        if self.config.schedule_enabled and self._main_preset == PRESET_NONE:
            now = self._now()
            hold = self._active_hold(self._manual_hold, now)
            if hold is None and self._manual_hold is not None:
                self._manual_hold = None
                self._persist_control()
            temp, active = scheduled_temperature(
                self.config.schedule,
                schedule_enabled=True,
                eco_fallback=self.config.eco_temp,
                now=now,
            )
            if hold is not None and active:
                self._house_comfort = True
                return hold, False
            if active:
                self._house_comfort = True
                if self._preheat_started is not None:
                    self._preheat_started = None  # its block is running
                    self._persist_control()
                key = active_block_key(self.config.schedule, now)
                return round(temp + seasonal_offset(seasonal, key), 1), True

            status = preheat_status(
                self.config.schedule,
                schedule_enabled=True,
                true_radiant=self.config.true_radiant,
                current_temp=self._house_temp(),
                warmup=self.intel.state.warmup,
                outdoor_temp=outdoor,
                away_eco_active=self._away_eco_active,
                cycles=self.intel.state.recent_cycles,
                max_minutes=(
                    LONG_PREHEAT_MINUTES if self.config.adaptive_comfort else MAX_PREHEAT_MINUTES
                ),
                offsets=seasonal.offsets if seasonal.started_at else None,
                now=now,
                started_block=self._preheat_started,
                rooms=self._preheat_rooms(),
            )
            self._preheat = status
            preheating = bool(status and status.get("preheating"))
            started = status.get("block_key") if preheating else None
            if started != self._preheat_started:
                self._preheat_started = started
                self._persist_control()
            during_this_preheat = bool(
                preheating
                and self._manual_hold
                and status.get("block_key") is not None
                and self._manual_hold.get("preheat_block") == status.get("block_key")
            )
            if hold is not None and (
                during_this_preheat
                or not (preheating and float(status["temperature"]) > hold)
            ):
                # A manual setting between blocks lasts until the next block,
                # but turning down overnight mustn't cancel the morning warm-up.
                # Turning down while that warm-up is already running does stop it.
                self._house_comfort = True
                return hold, False
            if preheating:
                self._house_comfort = True
                return float(status["temperature"]), True
            # Schedule eco fallback
            return self._eco_target(float(temp)), False

        self._house_comfort = True
        return self._main_target, False

    def _room_has_own_sensor(self, room: RoomConfig) -> bool:
        """The room has a sensor of its own (not just the house sensor, not the TRV)."""
        ids = self._room_sensor_ids(room)
        return bool(ids) and ids != [self.config.temperature_sensor]

    def _preheat_rooms(self) -> list[PreheatRoom]:
        """Rooms that will call for heat when the next block starts, for preheat timing."""
        if self.config.summer_mode:
            return []
        rooms = []
        for room in self.config.rooms:
            st = self._room_states.get(room.id, {})
            if (
                not room.enabled
                or not room.calls_for_heat
                or not self._room_has_own_sensor(room)
                or st.get("hvac_mode") != "heat"
                or st.get("preset", PRESET_NONE) != PRESET_NONE
                or self._any_window_open(room.window_sensors)
            ):
                continue
            current = self.room_current_temp(room)
            if current is None:
                continue
            rooms.append(
                PreheatRoom(
                    name=room.name,
                    current_temp=current,
                    warmup=self.intel.state.room_warmup.get(room.id),
                    house_offset=room.house_offset if room.follow_house else None,
                    target_temp=room.target_temp,
                )
            )
        return rooms

    def _track_room_runs(self, heating: bool, *, learnable: bool) -> None:
        """Learn each room's own warm-up rate from the runs where it called for heat.

        A run is the time the boiler is on while the room calls; the rate is its
        sensor's rise over that time, filtered like the house rate.
        """
        now = self._now()
        runs = self.intel.state.room_runs
        before = {k: dict(v) for k, v in runs.items()}
        faulty = self.intel.state.heat_check.fault_since is not None
        ids = {room.id for room in self.config.rooms}
        for room_id in [k for k in runs if k not in ids]:
            runs.pop(room_id)
        for room_id in [k for k in self.intel.state.room_warmup if k not in ids]:
            self.intel.state.room_warmup.pop(room_id)
            self._dirty_intel = True
        for room in self.config.rooms:
            current = self.room_current_temp(room) if self._room_has_own_sensor(room) else None
            calling = (
                heating
                and learnable
                and current is not None
                and bool(self._room_states.get(room.id, {}).get("needs_heat"))
            )
            run = runs.get(room.id)
            if calling and run is None:
                runs[room.id] = {"start": now.isoformat(), "start_temp": current}
            elif not calling and run is not None:
                runs.pop(room.id)
                start = dt_util.parse_datetime(str(run.get("start")))
                start_temp = run.get("start_temp")
                if start is None or not isinstance(start_temp, (int, float)):
                    continue
                duration = (now - start).total_seconds() / 60.0
                if current is None or faulty or not 0 < duration <= MAX_LEARN_RUN_HOURS * 60:
                    continue
                prior = self.intel.state.room_warmup.get(room.id) or WarmupModel()
                learned = update_warmup_from_cycle(
                    prior,
                    start_temp=float(start_temp),
                    end_temp=current,
                    duration_minutes=duration,
                    outdoor_temp=self._state_float(self.config.outdoor_temp_sensor),
                )
                if learned is not prior:  # a run too short or too small is skipped
                    self.intel.state.room_warmup[room.id] = learned
                    self._dirty_intel = True
        if runs != before:
            self._dirty_intel = True

    def room_warmup_info(self) -> dict[str, dict[str, Any]]:
        return {
            room_id: {"c_per_hour": model.c_per_hour, "samples": model.samples}
            for room_id, model in self.intel.state.room_warmup.items()
        }

    def _seasonal_block_now(self) -> str | None:
        """The schedule block Seasonal Savings is lowering right now (running or preheating)."""
        if not self.intel.state.seasonal.started_at or self._main_preset != PRESET_NONE:
            return None
        key = active_block_key(self.config.schedule, self._now())
        if key is None and (self._preheat or {}).get("preheating"):
            key = self._preheat.get("block_key")
        return key

    async def _async_finish_seasonal(self) -> None:
        """Seasonal Savings ran its course: keep the result in the schedule."""
        seasonal = self.intel.state.seasonal
        schedule, count = seasonal_bake(self.config.schedule, seasonal)
        lowest = min(seasonal.offsets.values(), default=0.0)
        kept = len(seasonal.kept)
        await self.async_save_config({"schedule": schedule, "seasonal_savings": False})
        message = (
            f"Seasonal Savings has finished. {count} schedule block"
            f"{'' if count == 1 else 's'} now run up to {abs(lowest):.1f}°C cooler"
            + (f"; {kept} you turned up were eased off and left there" if kept else "")
            + ". The new temperatures are in your schedule — change them there any time."
        )
        _LOGGER.info("Nook: %s", message)
        persistent_notification.async_create(
            self.hass,
            message,
            title="Nook: Seasonal Savings finished",
            notification_id=f"{DOMAIN}_seasonal_{self.entry.entry_id}",
        )

    @staticmethod
    def _now() -> datetime:
        """Wall-clock time in HA's configured zone (the OS clock may be UTC)."""
        return dt_util.now().replace(tzinfo=None)

    @staticmethod
    def _active_hold(hold: dict[str, Any] | None, now: datetime) -> float | None:
        """Manual setpoint that overrides the schedule until its next change."""
        if not hold:
            return None
        until = hold.get("until")
        if until:
            try:
                if now >= datetime.fromisoformat(until):
                    return None
            except ValueError:
                return None
        return float(hold["temperature"])

    def _new_hold(self, temperature: float) -> dict[str, Any]:
        until = next_schedule_change(self.config.schedule, self._now())
        return {
            "temperature": temperature,
            "until": until.isoformat() if until else None,
        }

    def clear_holds(self) -> None:
        """Drop manual holds (their expiry was computed from the old schedule)."""
        self._manual_hold = None
        for st in self._room_states.values():
            st.pop("hold", None)
        self._persist_control()

    def _new_room_hold(self, room: RoomConfig, temperature: float) -> dict[str, Any]:
        """A change made on the room itself; how long it lasts is the room's choice."""
        until = None
        if room.hold_ends != "manual" and self.config.schedule_enabled:
            change = next_schedule_change(self.config.schedule, self._now())
            until = change.isoformat() if change else None
        return {"temperature": temperature, "until": until, "house_rev": self._house_rev}

    def _room_hold(self, room: RoomConfig) -> float | None:
        """The room's own setpoint while it is still in force, else None."""
        hold = self._room_states.get(room.id, {}).get("hold")
        temp = self._active_hold(hold, self._now())
        if temp is None:
            return None
        if room.hold_ends == "house_change" and hold.get("house_rev", self._house_rev) != self._house_rev:
            return None
        return temp

    def _uses_room_holds(self, room: RoomConfig) -> bool:
        # Independent rooms without a schedule just keep their last setpoint.
        return room.follow_house or self.config.schedule_enabled

    def effective_room_target(self, room: RoomConfig) -> float:
        st = self._room_states.get(room.id, {})
        preset = st.get("preset", PRESET_NONE)
        if preset == PRESET_BOOST:
            return room.boost_temp
        if preset == PRESET_ECO or self._away_eco_active:
            return self._eco_target(room.eco_temp)
        if room.follow_house:
            hold = self._room_hold(room)
            if hold is not None:
                return hold
            target = self._house_target + room.house_offset
            return round(max(self.config.min_temp, min(self.config.max_temp, target)), 1)
        if not self.config.schedule_enabled:
            return float(st.get("target", room.target_temp))
        # Rooms follow the house schedule: own comfort temp while the house is
        # in a comfort block (or preheating / held), own Eco temp in setback.
        hold = self._room_hold(room)
        if hold is not None:
            return hold
        if self._house_comfort:
            return float(room.target_temp)
        return self._eco_target(room.eco_temp)

    def room_hold_until(self, room: RoomConfig) -> str | None:
        """When a manual room setpoint hands back (ISO), if one is in force and has a time."""
        st = self._room_states.get(room.id, {})
        if not self.room_held(room):
            return None
        return st["hold"].get("until")

    def room_held(self, room: RoomConfig) -> bool:
        """Is a change made on the room itself in force right now?"""
        st = self._room_states.get(room.id, {})
        if not self._uses_room_holds(room) or st.get("preset", PRESET_NONE) != PRESET_NONE:
            return False
        if self._away_eco_active:
            return False
        return self._room_hold(room) is not None

    def _room_follows_house_off(self, room: RoomConfig) -> bool:
        """A room that follows the house is off while the house is off."""
        return room.follow_house and self._main_hvac_mode != "heat"

    def _room_sensor_ids(self, room: RoomConfig) -> list[str]:
        return [e for e in [room.temperature_sensor, *(room.extra_temperature_sensors or [])] if e]

    def room_current_temp(self, room: RoomConfig) -> float | None:
        readings = [t for e in self._room_sensor_ids(room) if (t := self._state_float(e)) is not None]
        if readings:
            return sum(readings) / len(readings)
        state = self.hass.states.get(room.trv_entity)
        if state is None:
            return None
        raw = state.attributes.get("current_temperature")
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def room_needs_heat(self, room: RoomConfig) -> bool:
        st = self._room_states.get(room.id, {})
        if st.get("hvac_mode") != "heat" or not room.enabled or self._room_follows_house_off(room):
            return False
        # Opt-out rooms never demand the boiler (TRV setpoint sync still runs).
        if not bool(getattr(room, "calls_for_heat", True)):
            return False
        if self.config.summer_mode or self._any_window_open(room.window_sensors):
            return False
        current = self.room_current_temp(room)
        if current is None:
            return False
        if self._room_sensor_ids(room) == [self.config.temperature_sensor]:
            # The room the house sensor is in: same cut-off as the house (True
            # Radiant included). 21 Oct 2026: the hall room called on to 20.3
            # after the house had stopped at ~20.1, and coast took it past 20.5.
            return house_calls_for_heat(
                current,
                self.effective_room_target(room),
                was_calling=bool(st.get("needs_heat")),
                cold_tolerance=self.config.cold_tolerance,
                hot_tolerance=self.config.hot_tolerance,
                true_radiant=self.config.true_radiant,
                coast_c=self.intel.state.warmup.coast_c,
            )
        return room_calls_for_heat(
            current,
            self.effective_room_target(room),
            was_calling=bool(st.get("needs_heat")),
            cold_tolerance=self.config.cold_tolerance,
            hot_tolerance=self.config.hot_tolerance,
        )

    def room_valve_shut(self, room: RoomConfig) -> bool:
        """The room's TRV says its valve is shut (idle/off): the boiler can't heat it.

        21 Oct 2026: the kitchen's sensor read 19.4 while its TRV read 21 and had
        shut, so the boiler ran on for the kitchen and the heat went upstairs.
        Unknown (no TRV, offline, no hvac_action) counts as open.
        """
        trv = self.hass.states.get(room.trv_entity) if room.trv_entity else None
        if trv is None or trv.state in ("unknown", "unavailable"):
            return False
        return trv.attributes.get("hvac_action") in ("idle", "off")

    def safety_needs_heat(self) -> bool:
        if not self.config.safety_temp_enabled:
            return False
        current = self._house_temp()
        if current is None:
            # No working sensor: short timed runs so pipes can't freeze.
            return self._sensor_settled_none() and fallback_heat(
                self._now(),
                comfort=False,
                frost=frost_risk(
                    self._state_float(self.config.outdoor_temp_sensor),
                    summer_mode=self.config.summer_mode,
                ),
            )
        return current <= float(self.config.safety_min_temp)

    def main_needs_heat(self) -> bool:
        """House call for heat (safety floor handled separately)."""
        if self._main_hvac_mode != "heat" or self.config.summer_mode:
            return False
        if self._any_window_open(self.config.window_sensors):
            return False
        current = self._house_temp()
        target, _ = self.effective_main_target()
        if current is None:
            if not self._sensor_settled_none():
                # A blip (e.g. HA starting): carry on as before until it's confirmed.
                return self._house_calling
            # No working sensor: heat on a timer while the house should be comfortable.
            return fallback_heat(self._now(), comfort=self._house_comfort, frost=False)
        return house_calls_for_heat(
            current,
            target,
            was_calling=self._house_calling,
            cold_tolerance=self.config.cold_tolerance,
            hot_tolerance=self.config.hot_tolerance,
            true_radiant=self.config.true_radiant,
            coast_c=self.intel.state.warmup.coast_c,
        )

    def _heater_is_available(self) -> bool:
        if not self.config.heater:
            return False
        state = self.hass.states.get(self.config.heater)
        return state is not None and state.state not in ("unknown", "unavailable")

    async def _async_set_heater(self, turn_on: bool) -> None:
        heater = self.config.heater
        if not heater or not self._heater_is_available():
            return
        if self._is_on(heater) == turn_on:
            return
        await self._async_switch_heater(heater, turn_on)

    async def _async_switch_heater(self, heater: str, turn_on: bool) -> None:
        _LOGGER.info(
            "Nook: turning heater %s %s", heater, "on" if turn_on else "off"
        )
        domain = heater.split(".", 1)[0]
        if domain == "climate":
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {
                    "entity_id": heater,
                    "hvac_mode": "heat" if turn_on else "off",
                },
                blocking=False,
            )
            return
        await self.hass.services.async_call(
            domain,
            "turn_on" if turn_on else "turn_off",
            {"entity_id": heater},
            blocking=False,
        )

    async def _async_sync_room_trv(self, room: RoomConfig) -> None:
        if not room.trv_entity:
            return
        st = self._room_states.get(room.id, {})
        mode = st.get("hvac_mode", "heat")
        target = self.effective_room_target(room)
        window = self._any_window_open(room.window_sensors)
        trv = self.hass.states.get(room.trv_entity)
        if trv is None or trv.state in ("unknown", "unavailable"):
            return
        # Only send commands when the TRV differs: TRVs are in our listener
        # list, so unconditional calls every tick loop back into refreshes
        # and flood battery Zigbee valves.
        calls: list[tuple[str, dict[str, Any]]] = []
        try:
            trv_target = float(trv.attributes.get("temperature"))
        except (TypeError, ValueError):
            trv_target = None
        if self.config.summer_mode or window or mode != "heat" or self._room_follows_house_off(room):
            if trv.state != "off":
                calls.append(("set_hvac_mode", {"hvac_mode": "off"}))
        else:
            target = target + self._trv_topup(room, trv, target)
            if trv_target is None or abs(trv_target - target) >= 0.05:
                calls.append(("set_temperature", {"temperature": target}))
            if trv.state != "heat":
                calls.append(("set_hvac_mode", {"hvac_mode": "heat"}))
        # What the TRV reported is part of the signature: turned by hand, it's
        # put back at once; clamping the same setpoint, it waits TRV_REPEAT_AFTER.
        self._trv_send(room.trv_entity, calls, (trv.state, trv_target))
        if not calls:
            self._calibrate_room_trv(room, trv)

    def trv_offset_entity(self, trv_entity: str) -> str | None:
        """The TRV's own temperature offset/calibration setting (a number on its device)."""
        ent_reg = er.async_get(self.hass)
        trv_entry = ent_reg.async_get(trv_entity) if trv_entity else None
        if trv_entry is None or not trv_entry.device_id:
            return None
        for entry in er.async_entries_for_device(ent_reg, trv_entry.device_id):
            if entry.domain != "number" or entry.disabled_by is not None:
                continue
            words = " ".join(
                str(x or "") for x in (entry.translation_key, entry.entity_id, entry.original_name)
            ).lower()
            if "temperature" in words and ("offset" in words or "calibration" in words):
                return entry.entity_id
        return None

    def _calibrate_room_trv(self, room: RoomConfig, trv: State) -> None:
        """Keep the TRV's own offset at room sensor − TRV, so it shows the room's real
        temperature and closes when the room (not its radiator) reaches the setpoint."""
        if not room.calibrate_trv or self.hass.state is not CoreState.running:
            return
        sensors = self._room_sensor_ids(room)
        readings = [self._sensor_value(e, self.config.sensor_stale_minutes) for e in sensors]
        if not readings or any(r is None for r in readings):
            return  # no room sensor, or one is silent: leave the TRV as it is
        room_temp = sum(readings) / len(readings)
        if not self._room_sensor_settled(room.id, room_temp):
            return
        try:
            trv_temp = float(trv.attributes.get("current_temperature"))
        except (TypeError, ValueError):
            return
        offset_id = self.trv_offset_entity(room.trv_entity)
        offset_state = self.hass.states.get(offset_id) if offset_id else None
        if offset_state is None:
            return
        try:
            offset = float(offset_state.state)
        except (TypeError, ValueError):
            return
        now = dt_util.utcnow()
        last = self._trv_calibration.get(room.trv_entity)
        if (
            last is not None
            and abs(last["offset"] - offset) < 0.05
            and abs(last["reading"] - trv_temp) < 0.05
            and now - last["at"] < CALIBRATE_WAIT_FOR_TRV
        ):
            return  # the TRV hasn't reported a reading with the new offset yet
        attrs = offset_state.attributes
        lo = float(attrs.get("min", -5.0))
        hi = float(attrs.get("max", 5.0))
        step = float(attrs.get("step") or 0.1)
        wanted = round(round((offset + room_temp - trv_temp) / step) * step, 2)
        wanted = min(hi, CALIBRATE_MAX_OFFSET, max(lo, wanted))
        # The last step onto the TRV's limit is always taken: the setpoint top-up only
        # starts there (23 Oct: two TRVs sat at −2.2, wanting −2.5 — a 0.29999… step).
        to_limit = wanted <= lo + 0.01 and offset > lo + 0.05
        if abs(wanted - offset) < CALIBRATE_MIN_CHANGE - 1e-6 and not to_limit:
            return
        warming = self._room_warming(room, room_temp, self.effective_room_target(room))
        if warming and wanted > offset:
            return  # would read higher and shut while the room still needs heat
        spacing = CALIBRATE_EVERY_HEATING if warming else CALIBRATE_EVERY
        if now - offset_state.last_changed < spacing:
            return
        if self._trv_send(
            room.trv_entity,
            [("number.set_value", {"entity_id": offset_id, "value": wanted})],
            (offset, trv_temp),
        ):
            _LOGGER.info(
                "Nook: %s reads %.1f °C, room %.1f °C — offset %s → %s",
                room.trv_entity, trv_temp, room_temp, offset, wanted,
            )
            self._trv_calibration[room.trv_entity] = {"offset": wanted, "reading": trv_temp, "at": now}

    def _trv_topup(self, room: RoomConfig, trv: State, target: float) -> float:
        """Extra setpoint for a calibrated TRV still reading above the room at its
        offset limit, so its valve stays open until the room sensor reaches target."""
        extra = self._trv_topups.get(room.id, 0.0)
        readings = [self._sensor_value(e, self.config.sensor_stale_minutes) for e in self._room_sensor_ids(room)]
        if not room.calibrate_trv or not readings or any(r is None for r in readings):
            self._trv_topups.pop(room.id, None)
            return 0.0
        room_temp = sum(readings) / len(readings)
        if not self._room_warming(room, room_temp, target):
            self._trv_topups.pop(room.id, None)  # the room is there: the TRV may shut
            return 0.0
        offset_id = self.trv_offset_entity(room.trv_entity)
        offset_state = self.hass.states.get(offset_id) if offset_id else None
        try:
            offset = float(offset_state.state)
            lo = float(offset_state.attributes.get("min", -5.0))
            trv_temp = float(trv.attributes.get("current_temperature"))
        except (AttributeError, TypeError, ValueError):
            return extra
        if self._room_sensor_settled(room.id, room_temp):
            step = float(trv.attributes.get("target_temp_step") or 0.5)
            # What the offset can't correct (only once it's at its limit) …
            residual = max(0.0, trv_temp - room_temp) if offset <= lo + 0.05 else 0.0
            # … plus a margin: TRVs open in proportion to (setpoint − reading), so a setpoint
            # that only just matches the room lets the valve close down as the room nears target.
            wanted = min(TRV_TOPUP_MAX, math.ceil(residual / step - 1e-9) * step) + TRV_TOPUP_MARGIN
            if wanted > extra:
                _LOGGER.info(
                    "Nook: %s reads %.1f °C (offset %.1f), room %.1f °C — setpoint +%.1f while it warms",
                    room.trv_entity, trv_temp, offset, room_temp, wanted,
                )
                extra = wanted
        if extra > 0:
            self._trv_topups[room.id] = extra
        return extra

    def _room_warming(self, room: RoomConfig, room_temp: float, target: float) -> bool:
        """Is this room still being heated towards its target?

        The room the house sensor is in follows the house call: the house heats on
        to its own cut-off (target + hot tolerance − coast). 23 Oct: the hall's
        top-up ended at 20.0, its TRV shut, and the house kept the boiler on for
        a hall that couldn't warm the last 0.1 °C — the heat went upstairs.
        """
        if self._room_sensor_ids(room) == [self.config.temperature_sensor]:
            return self._house_calling or room_temp < target
        if room.calls_for_heat:
            # The room's own call (cut-in target − cold, cut-out target + hot). 23 Oct: the
            # living room still called at 20.1 while its top-up had ended at 20.0, so the
            # tiles said "Heating" with both valves shut, and the TRVs reopened (and the
            # boiler fired) at 19.9 with no hysteresis.
            return bool(self._room_states.get(room.id, {}).get("needs_heat"))
        return room_temp < target

    def _room_sensor_settled(self, room_id: str, value: float) -> bool:
        """Has the room reading moved slower than CALIBRATE_SETTLING_C_PER_HOUR over
        a full CALIBRATE_SETTLING_WINDOW? (No full window yet = not settled.)"""
        now = dt_util.utcnow()
        samples = self._room_sensor_samples.setdefault(room_id, [])
        samples.append((now, value))
        cutoff = now - CALIBRATE_SETTLING_WINDOW
        while len(samples) > 1 and samples[1][0] <= cutoff:
            samples.pop(0)
        first_at, first = samples[0]
        if first_at > cutoff:
            return False
        hours = (now - first_at).total_seconds() / 3600
        return abs(value - first) / hours < CALIBRATE_SETTLING_C_PER_HOUR

    def _trv_send(
        self, entity_id: str, calls: list[tuple[str, dict[str, Any]]], seen: tuple[Any, ...]
    ) -> bool:
        """Send TRV commands in the background: one batch per TRV at a time, with back-off.

        A service named "domain.service" (e.g. the TRV's offset number) carries its
        own entity_id; plain names are climate services on the TRV. True if sent.
        """
        if not calls or self.hass.is_stopping:
            return False
        task = self._trv_tasks.get(entity_id)
        if task is not None and not task.done():
            return False  # the last command is still waiting for the TRV
        now = dt_util.utcnow()
        retry = self._trv_retry.get(entity_id)
        if retry is not None and now < retry["at"]:
            return False
        signature = (tuple((service, tuple(sorted(data.items()))) for service, data in calls), seen)
        last = self._trv_last_sent.get(entity_id)
        if last is not None and last[0] == signature and now - last[1] < TRV_REPEAT_AFTER:
            return False
        self._trv_last_sent[entity_id] = (signature, now)
        # A background task: HA cancels it as soon as it starts stopping, so no
        # command is left queued at the radio while ZHA shuts down.
        self._trv_tasks[entity_id] = self.hass.async_create_background_task(
            self._async_trv_commands(entity_id, calls), f"{DOMAIN}_trv_{entity_id}"
        )
        return True

    async def _async_trv_commands(
        self, entity_id: str, calls: list[tuple[str, dict[str, Any]]]
    ) -> None:
        for service, data in calls:
            domain, _, name = service.rpartition(".")
            try:
                await self.hass.services.async_call(
                    domain or "climate", name, {"entity_id": entity_id, **data}, blocking=True
                )
            except Exception as err:  # noqa: BLE001 — the TRV failed, not the loop
                failures = (self._trv_retry.get(entity_id) or {}).get("failures", 0) + 1
                wait = min(TRV_RETRY_MIN * 2 ** min(failures - 1, 6), TRV_RETRY_MAX)
                self._trv_retry[entity_id] = {"failures": failures, "at": dt_util.utcnow() + wait}
                self._trv_last_sent.pop(entity_id, None)  # the retry must go out
                (_LOGGER.warning if failures == 1 else _LOGGER.debug)(
                    "Nook: %s didn't take %s (%s) — trying again in %d min",
                    entity_id, service, err or type(err).__name__, wait.total_seconds() // 60,
                )
                return
        if self._trv_retry.pop(entity_id, None) is not None:
            _LOGGER.info("Nook: %s is answering again", entity_id)

    def _apply_cycle_guard(self, demand: bool) -> tuple[bool, float]:
        """Hold the boiler in its current state until min on/off time has passed."""
        state = self.hass.states.get(self.config.heater) if self.config.heater else None
        if state is None or state.state in ("unknown", "unavailable"):
            return demand, 0.0
        is_on = self._is_on(self.config.heater)
        since = self._relay_since(is_on, state.last_changed)
        seconds = (dt_util.utcnow() - since).total_seconds()
        command, wait = boiler_cycle_guard(
            demand,
            is_on,
            seconds,
            min_on_seconds=self.config.min_on_minutes * 60.0,
            min_off_seconds=self.config.min_off_minutes * 60.0,
        )
        if command != demand:
            _LOGGER.debug(
                "Nook: boiler %s held for %.0fs (anti-short-cycle)",
                "on" if command else "off",
                wait,
            )
        return command, wait

    def _relay_since(self, is_on: bool, last_changed: datetime) -> datetime:
        """When the relay really went on/off, across HA restarts.

        At start-up the relay goes unavailable → on/off and HA stamps a new
        last_changed, so a boiler that had run for 10 minutes would look fresh and
        be held on for the whole minimum run time again. The saved change wins
        while the relay is still in that state.
        """
        seen = self._relay_seen
        if seen is not None and seen["on"] == is_on:
            saved = dt_util.parse_datetime(seen["since"])
            if saved is not None and saved < last_changed:
                return saved
            return last_changed
        self._relay_seen = {"on": is_on, "since": last_changed.isoformat()}
        self._persist_control()
        return last_changed

    def _track_heat_cycle(self, want_heat: bool) -> None:
        now = self._now()
        current = self._house_temp()
        outdoor = self._state_float(self.config.outdoor_temp_sensor)
        if want_heat and not self._last_boiler_on:
            self._heat_cycle_start = now
            self._heat_cycle_start_temp = current
            self._heat_cycle_house_called = False
        if want_heat and (self._house_calling or self._safety_active):
            self._heat_cycle_house_called = True
        elif not want_heat and self._last_boiler_on and self._heat_cycle_start:
            # A boiler that isn't heating would teach Nook a bogus warm-up rate,
            # and a run only the rooms wanted may not reach the house sensor.
            faulty = self.intel.state.heat_check.fault_since is not None
            duration = (now - self._heat_cycle_start).total_seconds() / 60.0
            if (
                current is not None
                and self._heat_cycle_start_temp is not None
                and not faulty
                and self._heat_cycle_house_called
                and 0 < duration <= MAX_LEARN_RUN_HOURS * 60
            ):
                self.intel.state.warmup = update_warmup_from_cycle(
                    self.intel.state.warmup,
                    start_temp=self._heat_cycle_start_temp,
                    end_temp=current,
                    duration_minutes=duration,
                    outdoor_temp=outdoor,
                )
                self.intel.state.recent_cycles.append(
                    {
                        "started_at": self._heat_cycle_start.isoformat(),
                        "ended_at": now.isoformat(),
                        "start_temp": self._heat_cycle_start_temp,
                        "end_temp": current,
                        "outdoor_temp": outdoor,
                        "duration_minutes": round(duration, 1),
                    }
                )
                self.intel.state.recent_cycles = self.intel.state.recent_cycles[-40:]
                self._dirty_intel = True
            self._heat_cycle_start = None
            self._heat_cycle_start_temp = None
        self._last_boiler_on = want_heat
        # Persist the run in progress: a restart mid-run must not lose its start.
        cycle = (
            {
                "start": self._heat_cycle_start.isoformat(),
                "start_temp": self._heat_cycle_start_temp,
                "house_called": self._heat_cycle_house_called,
            }
            if self._heat_cycle_start is not None
            else {}
        )
        if cycle != self.intel.state.heat_cycle:
            self.intel.state.heat_cycle = cycle
            self._dirty_intel = True

    def _restore_heat_cycle(self) -> None:
        """Pick up a run that was in progress when HA stopped (if recent)."""
        cycle = self.intel.state.heat_cycle or {}
        try:
            start = datetime.fromisoformat(str(cycle["start"]))
        except (KeyError, TypeError, ValueError):
            self.intel.state.heat_cycle = {}
            return
        if self._now() - start > timedelta(hours=MAX_LEARN_RUN_HOURS):
            self.intel.state.heat_cycle = {}
            return
        self._heat_cycle_start = start
        temp = cycle.get("start_temp")
        self._heat_cycle_start_temp = float(temp) if isinstance(temp, (int, float)) else None
        self._heat_cycle_house_called = bool(cycle.get("house_called"))
        self._last_boiler_on = True

    def _track_coast(self, heating: bool, *, disturbed: bool = False) -> None:
        """Measure how far the house keeps warming after each run (True Radiant)."""
        watch = self.intel.state.coast_watch
        before = watch.to_dict()
        learned = update_coast_watch(
            watch,
            self.intel.state.warmup,
            boiler_on=heating,
            house_calling=self._house_calling or self._safety_active,
            current_temp=self._house_temp(),
            disturbed=disturbed or self._any_window_open(self.config.window_sensors, delayed=False),
            # A boiler that isn't heating has no coast to learn.
            learn=self.intel.state.heat_check.fault_since is None,
            now=self._now(),
        )
        if learned is not None:
            _LOGGER.info(
                "Nook: radiator coast now %.2f°C (%d runs)",
                learned.coast_c,
                learned.coast_samples,
            )
            self.intel.state.warmup = learned
        if learned is not None or watch.to_dict() != before:
            self._dirty_intel = True

    async def _async_check_warming(self, house_heating: bool) -> None:
        """Flag (and notify) when boiler time isn't warming the house."""
        check = self.intel.state.heat_check
        before = {k: v for k, v in check.to_dict().items() if k != "last_tick"}
        current = self._house_temp()
        target, _ = self.effective_main_target()
        event = update_heat_check(
            check,
            heating=house_heating,
            current_temp=current,
            alert_minutes=(
                self.config.no_heat_alert_minutes if self.config.no_heat_alert else 0
            ),
            target=float(target) if target is not None else None,
            now=self._now(),
        )
        if check.fault_since is not None and house_heating:
            # Why it isn't warming, as of this run (shown with the alert).
            check.fault_offline, check.fault_closed = self._trv_diagnosis()
        if event is not None:
            # Alerts must survive a restart straight after they fire.
            await self.intel.async_save()
        elif {k: v for k, v in check.to_dict().items() if k != "last_tick"} != before:
            self._dirty_intel = True
        if event == "fault":
            await self._async_alert_not_warming(current)
        elif event == "recovered":
            await self._async_alert_warming_again(current)

    def _trv_diagnosis(self) -> tuple[list[str], list[str]]:
        """Rooms whose TRV is offline, and — when no online TRV is open — those
        whose TRV has shut its valve (its own sensor reads the set point)."""
        offline: list[str] = []
        closed: list[str] = []
        any_open = False
        for room in self.config.rooms:
            if not room.enabled or not room.trv_entity:
                continue
            state = self.hass.states.get(room.trv_entity)
            if state is None or state.state in ("unavailable", "unknown"):
                offline.append(room.name)
                continue
            if state.state == "off":
                closed.append(room.name)
                continue
            action = state.attributes.get("hvac_action")
            if action is None:
                try:
                    action = (
                        "idle"
                        if float(state.attributes["current_temperature"])
                        >= float(state.attributes["temperature"])
                        else "heating"
                    )
                except (KeyError, TypeError, ValueError):
                    action = "heating"  # can't tell: don't blame it
            if action == "heating":
                any_open = True
            else:
                closed.append(room.name)
        return offline, [] if any_open else closed

    @staticmethod
    def _join_names(names: list[str]) -> str:
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]

    def _not_warming_cause(self, check: HeatCheck) -> str:
        """The advice part of the alert: TRVs first, the boiler only if they look fine."""
        parts = []
        if check.fault_offline:
            names = self._join_names(check.fault_offline)
            verb = "is" if len(check.fault_offline) == 1 else "are"
            parts.append(
                f"The {names} TRV{'' if len(check.fault_offline) == 1 else 's'} {verb} "
                "offline, so Nook can't open the radiator valve."
            )
        if check.fault_closed:
            parts.append(
                "The TRVs that are online have all closed their valves "
                f"({self._join_names(check.fault_closed)}): their own sensor by the "
                "radiator reads the set temperature, so the heat isn't reaching "
                "the room the house sensor is in."
            )
        if not parts:
            parts.append(
                "Check the boiler is firing: power, pressure, any fault code, "
                "and the call-for-heat relay wiring."
            )
        return " ".join(parts)

    def _alert_id(self) -> str:
        return f"{DOMAIN}_not_warming_{self.entry.entry_id}"

    async def _async_alert_not_warming(self, current: float | None) -> None:
        check = self.intel.state.heat_check
        check.fault_offline, check.fault_closed = self._trv_diagnosis()
        target, _ = self.effective_main_target()
        minutes = round(check.fault_on_minutes)
        rise = round(check.fault_rise_c, 1)
        title = "Nook: the house isn't warming up"
        message = (
            f"The boiler has been called for {minutes} minutes but the house has "
            f"only warmed {rise:.1f}°C"
            + (f" (now {current:.1f}°C, target {target:.1f}°C)" if current is not None else "")
            + ". "
            + self._not_warming_cause(check)
        )
        _LOGGER.warning("Nook: %s — %s", title, message)
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=self._alert_id()
        )
        self.hass.bus.async_fire(
            f"{DOMAIN}_heating_fault",
            {"on_minutes": minutes, "rise_c": rise, "temperature": current, "target": target},
        )
        await self._async_notify_phones(title, message)

    async def _async_alert_warming_again(self, current: float | None) -> None:
        title = "Nook: heating is working again"
        message = "The house is warming up again" + (
            f" ({current:.1f}°C now)." if current is not None else "."
        )
        _LOGGER.info("Nook: %s", message)
        persistent_notification.async_dismiss(self.hass, self._alert_id())
        self.hass.bus.async_fire(f"{DOMAIN}_heating_recovered", {"temperature": current})
        await self._async_notify_phones(title, message)

    async def _async_notify_phones(self, title: str, message: str) -> None:
        for service in self.config.alert_notify:
            if not self.hass.services.has_service("notify", service):
                _LOGGER.warning("Nook: notify.%s doesn't exist — alert not sent there", service)
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    service,
                    # Same tag: the "working again" message replaces the alert.
                    {"title": title, "message": message, "data": {"tag": "nook_heating"}},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001 — one bad phone mustn't stop the loop
                _LOGGER.exception("Nook: couldn't send alert via notify.%s", service)

    async def _maybe_learn_schedule(self) -> None:
        if not self.config.auto_schedule:
            return
        before = len(self.intel.state.adjustments)
        new_schedule, changed = learn_schedule_from_adjustments(
            self.config.schedule,
            self.intel.state,
            auto_schedule=True,
            eco_temp=self.config.eco_temp,
        )
        if len(self.intel.state.adjustments) != before:
            self.intel.async_delay_save()  # old adjustments were forgotten
        if changed:
            _LOGGER.info("Auto-Schedule updated house weekly schedule from adjustments")
            await self.async_save_config({"schedule": new_schedule})

    async def _async_update_data(self) -> dict[str, Any]:
        self._refresh_away()
        await self._async_check_house_sensor()
        await self._async_sync_sensor_reporting()
        self.effective_main_target()
        if self._seasonal_info.get("finished"):
            await self._async_finish_seasonal()
            self.effective_main_target()

        calling_before = (
            self._house_calling,
            tuple(bool(st.get("needs_heat")) for st in self._room_states.values()),
        )
        for room in self.config.rooms:
            needs = self.room_needs_heat(room)
            self._room_states.setdefault(room.id, {})["needs_heat"] = needs
            await self._async_sync_room_trv(room)

        self._safety_active = self.safety_needs_heat()
        self._house_calling = self.main_needs_heat()
        if calling_before != (
            self._house_calling,
            tuple(bool(st.get("needs_heat")) for st in self._room_states.values()),
        ):
            self._persist_control()  # a restart mid-run must carry on to the cut-off
        # A room only keeps the boiler on while its valve is open to take the heat.
        rooms_calling = any(
            self._room_states.get(r.id, {}).get("needs_heat") and not self.room_valve_shut(r)
            for r in self.config.rooms
        )
        demand = self._safety_active or (
            not self.config.summer_mode and (self._house_calling or rooms_calling)
        )
        want_heat, cycle_wait = self._apply_cycle_guard(demand)

        heater_available = self._heater_is_available()
        if heater_available != self._heater_available:
            if heater_available:
                _LOGGER.info("Nook: heater %s is available again", self.config.heater)
            else:
                _LOGGER.warning(
                    "Nook: heater %s is unavailable — the boiler cannot be switched",
                    self.config.heater or "(none set)",
                )
            self._heater_available = heater_available
        # An unavailable relay can't be switched: don't report or learn from
        # heat that never happened. A relay released for a hand test isn't
        # Nook's heating either, and a half-finished run teaches nothing.
        released = self._relay_released()
        heating = want_heat and heater_available and not released
        # Only learn the house from the main sensor (a backup is offset, a
        # timed run has no reading at all).
        learnable = not released and self._house_reading()[1] == SOURCE_MAIN
        if not learnable:
            self._heat_cycle_start = None

        self._track_heat_cycle(heating)
        self._track_room_runs(heating, learnable=not released)
        if track_heat_interval(self.intel.state.energy, want_heat=heating):
            self._dirty_intel = True
        await self._async_check_warming(
            heating and (self._house_calling or self._safety_active)
        )
        self._track_coast(heating, disturbed=not learnable)

        if not released:
            await self._async_set_heater(want_heat)

        target, _sched = self.effective_main_target()
        if note_setpoint_event(self.intel.state.energy, float(target)):
            self._dirty_intel = True

        eco_or_away = (
            self._main_hvac_mode == "off"
            # Summer mode stops all heating too (the mode just stays Heat).
            or self.config.summer_mode
            or self._away_eco_active
            or self._main_preset in (
                PRESET_ECO,
                PRESET_AWAY,
            )
        )
        leaf = self.intel.state.leaf
        prev_total = leaf.minutes_total
        prev_baseline = leaf.baseline
        prev_samples = len(leaf.comfort_samples)
        prev_started = leaf.coaching_started_at

        if _sched and not eco_or_away and self._main_preset == PRESET_NONE:
            noted = float(target)
            if getattr(self, "_last_noted_comfort", None) != noted:
                note_comfort_setpoint(leaf, noted)
                self._last_noted_comfort = noted

        leaf_info = evaluate_leaf(
            leaf=leaf,
            effective_target=float(target),
            eco_or_away=eco_or_away,
            leaf_enabled=self.config.leaf_enabled,
        )
        accrue_leaf_minutes(
            leaf,
            leaf_active=bool(leaf_info.get("active")),
            default_delta_minutes=UPDATE_INTERVAL.total_seconds() / 60.0,
        )
        self._leaf = {**leaf_info, **leaf_week_stats(leaf)}
        if (
            leaf.minutes_total != prev_total
            or leaf.baseline != prev_baseline
            or len(leaf.comfort_samples) != prev_samples
            or leaf.coaching_started_at != prev_started
        ):
            self._dirty_intel = True

        current = self._house_temp()
        preheating = bool((self._preheat or {}).get("preheating"))
        self._time_to_temp = estimate_time_to_temp_minutes(
            current_temp=current,
            target_temp=float(target),
            warmup=self.intel.state.warmup,
            heating=heating or (preheating and heater_available),
            hvac_mode=self._main_hvac_mode,
        )

        if self._dirty_intel:
            self.intel.async_delay_save()
            self._dirty_intel = False

        self.data = self._snapshot()
        # While released, show what the relay is really doing.
        self.data["boiler_on"] = (
            heater_available and self._is_on(self.config.heater) if released else heating
        )
        self.data["boiler_demand"] = demand
        self.data["boiler_cycle_wait_seconds"] = round(cycle_wait)
        # The boiler is held against the demand (min on/off time) until then.
        self.data["boiler_hold_until"] = (
            (dt_util.utcnow() + timedelta(seconds=cycle_wait)).isoformat()
            if cycle_wait > 0 and heater_available and not released
            else None
        )
        self.data["heater_available"] = heater_available
        self.data["main"]["effective_target"] = target
        self.data["main"]["schedule_active"] = _sched
        return self.data

    def _house_changed(self) -> None:
        """A manual house change: end room holds that last until one, re-aim followers now."""
        self._house_rev += 1
        self.effective_main_target()

    @callback
    def set_main_hvac_mode(self, mode: str) -> None:
        self._main_hvac_mode = mode
        self._house_changed()
        self._persist_control()
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def set_main_temperature(self, temperature: float) -> None:
        before, _ = self.effective_main_target()
        if temperature > before and seasonal_push_back(
            self.intel.state.seasonal, self._seasonal_block_now()
        ):
            _LOGGER.info("Nook: Seasonal Savings eases off this block (turned up)")
        self._main_target = temperature
        self._main_preset = PRESET_NONE
        if self.config.schedule_enabled:
            # A dial change holds until the next schedule change.
            self._manual_hold = self._new_hold(temperature)
            if (self._preheat or {}).get("preheating"):
                # Set during a preheat: it beats that preheat (see _compute_main_target).
                self._manual_hold["preheat_block"] = self._preheat.get("block_key")
        self._house_changed()
        self._persist_control()
        record_manual_adjustment(self.intel.state, temperature)
        if temperature > self.config.eco_temp:
            # Turning down to save energy mustn't drag the comfort baseline down.
            note_comfort_setpoint(self.intel.state.leaf, temperature)
        self._dirty_intel = True
        self.hass.async_create_task(self._after_manual_setpoint())

    async def _after_manual_setpoint(self) -> None:
        await self.intel.async_save()
        await self._maybe_learn_schedule()
        await self.async_request_refresh()

    @callback
    def set_main_preset(self, preset: str) -> None:
        self._main_preset = preset or PRESET_NONE
        if preset == PRESET_ECO:
            self._main_target = self.config.eco_temp
        elif preset == PRESET_BOOST:
            self._main_target = self.config.boost_temp
        elif preset == PRESET_AWAY:
            self._main_target = self.config.away_temp
        self._manual_hold = None
        self._house_changed()
        self._persist_control()
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def set_room_hvac_mode(self, room_id: str, mode: str) -> None:
        self._room_states.setdefault(room_id, {})["hvac_mode"] = mode
        self._persist_control()
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def set_room_temperature(self, room_id: str, temperature: float) -> None:
        st = self._room_states.setdefault(room_id, {})
        st["target"] = temperature
        st["preset"] = PRESET_NONE
        room = next((r for r in self.config.rooms if r.id == room_id), None)
        if room is not None and self._uses_room_holds(room):
            st["hold"] = self._new_room_hold(room, temperature)
        self._persist_control()
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def set_room_preset(self, room_id: str, preset: str) -> None:
        self._room_states.setdefault(room_id, {})["preset"] = preset or PRESET_NONE
        self._persist_control()
        self.hass.async_create_task(self.async_request_refresh())

    def get_wall_panel(self, panel_id: str) -> WallPanelConfig | None:
        for panel in self.config.wall_panels:
            if panel.id == panel_id:
                return panel
        return None

    # Live control values: entities read these so a change shows at once,
    # not after the next (debounced) coordinator refresh.
    @property
    def main_hvac_mode(self) -> str:
        return self._main_hvac_mode

    @property
    def main_preset(self) -> str:
        return self._main_preset

    def room_control(self, room_id: str) -> dict[str, Any]:
        return self._room_states.get(room_id, {})

    def nook_entity_id(self, unique_id: str) -> str | None:
        """Real entity id of a Nook climate. HA picks the id (e.g. climate.nook_nook_home),
        so never assume climate.nook_<x> — that name can belong to some other integration."""
        return er.async_get(self.hass).async_get_entity_id("climate", DOMAIN, unique_id)

    def _wall_primary(self, configured: str) -> str:
        """The panel's main climate. Blank, or the old hard-coded default "climate.nook_home"
        when that isn't actually Nook's entity, means Nook's house climate."""
        home = self.nook_entity_id("nook_home")
        if not configured:
            return home or "climate.nook_home"
        if configured == "climate.nook_home" and home and home != configured:
            entry = er.async_get(self.hass).async_get(configured)
            if entry is None or entry.platform != DOMAIN:
                return home
        return configured

    async def async_wall_screens(self) -> dict[str, dict[str, Any]]:
        """Screen size each wall panel last reported (CSS px), by panel id."""
        if self._wall_screens is None:
            stored = await self._kiosk_store.async_load() or {}
            self._wall_screens = dict(stored.get("screens") or {})
        return self._wall_screens

    async def async_report_wall_screen(self, panel_id: str, screen: dict[str, Any]) -> None:
        """Remember a panel's real screen, so Nook can say which shape it is.
        Saved only when the size changes (the app reports on every start)."""
        if self.get_wall_panel(panel_id) is None:
            return
        try:
            width = round(float(screen["width"]))
            height = round(float(screen["height"]))
            scale = round(float(screen.get("scale") or 1), 2)
        except (KeyError, TypeError, ValueError):
            return
        if not (0 < width <= 10000 and 0 < height <= 10000):
            return
        screens = await self.async_wall_screens()
        new = {"width": width, "height": height, "scale": scale}
        old = screens.get(panel_id) or {}
        if {k: old.get(k) for k in new} == new:
            return
        screens[panel_id] = {**new, "reported_at": dt_util.utcnow().isoformat()}
        stored = await self._kiosk_store.async_load() or {}
        await self._kiosk_store.async_save({**stored, "screens": screens})

    # ---- Nook Panel Helper (NSPanel Pro) ----
    async def _async_helper_keys(self) -> dict[str, str]:
        """Pairing keys by panel id (kept in .storage, never in the config entry)."""
        stored = await self._kiosk_store.async_load() or {}
        return dict(stored.get("helper_keys") or {})

    async def _async_save_helper_key(self, panel_id: str, key: str | None) -> None:
        stored = await self._kiosk_store.async_load() or {}
        keys = dict(stored.get("helper_keys") or {})
        if key:
            keys[panel_id] = key
        else:
            keys.pop(panel_id, None)
        await self._kiosk_store.async_save({**stored, "helper_keys": keys})

    def _helper_panels(self, keys: dict[str, str] | None = None) -> list[WallPanelConfig]:
        """NSPanel Pro panels, plus any panel already paired (pairing can come before the
        Screen type is saved — the dialog shows the section as soon as it's picked)."""
        keys = keys or {}
        return [p for p in self.config.wall_panels if p.model == panel_helper.HELPER_MODEL or p.id in keys]

    async def async_helper_pair(self, panel_id: str, code: str) -> dict[str, Any]:
        panel = self.get_wall_panel(panel_id)
        if panel is None:
            raise panel_helper.HelperError(f"unknown panel {panel_id}")
        key = await panel_helper.async_pair(self.hass, panel_helper.helper_host(self.hass, panel), code)
        await self._async_save_helper_key(panel_id, key)
        if panel.model != panel_helper.HELPER_MODEL:
            # Only an NSPanel Pro has a helper to pair with: record the type too.
            panels = [
                {**p.to_dict(), "model": panel_helper.HELPER_MODEL} if p.id == panel_id else p.to_dict()
                for p in self.config.wall_panels
            ]
            await self.async_save_config({"wall_panels": panels})
        await self.async_helper_poll(panel_id)
        return (await self.async_helpers_state()).get(panel_id) or {"paired": True}

    async def async_helper_unpair(self, panel_id: str) -> None:
        await self._async_save_helper_key(panel_id, None)
        self._helper_status.pop(panel_id, None)

    async def async_helper_config(self, panel_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Change the helper's own settings (hide the return button, stay-awake locks)."""
        panel = self.get_wall_panel(panel_id)
        key = (await self._async_helper_keys()).get(panel_id, "")
        if panel is None or not key:
            raise panel_helper.HelperError("pair with the helper first")
        body: dict[str, Any] = {}
        if "hide_return_button" in settings:
            # null = automatic (Sonoff's return button), [] = leave every service alone
            body["blocked_services"] = None if settings["hide_return_button"] else []
        for flag in ("cpu_lock", "wifi_lock"):
            if flag in settings:
                body[flag] = bool(settings[flag])
        await panel_helper.async_request(
            self.hass, panel_helper.helper_host(self.hass, panel), "POST", "/config", key=key, body=body
        )
        await self.async_helper_poll(panel_id)
        return (await self.async_helpers_state()).get(panel_id) or {"paired": True}

    async def async_helper_poll(self, panel_id: str | None = None) -> None:
        """Read each paired helper's status; give it the shipped version when it's behind."""
        from .panel import WWW_DIR

        keys = await self._async_helper_keys()
        bundled = await self.hass.async_add_executor_job(panel_helper.bundled_helper, WWW_DIR)
        for panel in self._helper_panels(keys):
            if panel_id and panel.id != panel_id:
                continue
            key = keys.get(panel.id)
            if not key:
                continue
            host = panel_helper.helper_host(self.hass, panel)
            entry: dict[str, Any] = {"checked_at": dt_util.utcnow().isoformat()}
            try:
                status = await panel_helper.async_request(self.hass, host, "GET", "/status", key=key)
                entry["summary"] = panel_helper.summary(status)
                entry["error"] = ""
            except panel_helper.HelperError as err:
                entry["summary"] = (self._helper_status.get(panel.id) or {}).get("summary") or {}
                entry["error"] = str(err)
            self._helper_status[panel.id] = entry
            have = (entry.get("summary") or {}).get("version_code")
            if not entry["error"] and bundled and have is not None and int(have) < int(bundled["version_code"]):
                await self._async_helper_update(panel, host, key, bundled)

    async def _async_helper_update(
        self, panel: WallPanelConfig, host: str, key: str, bundled: dict[str, Any]
    ) -> None:
        """Ask a helper to install the shipped version (at most once an hour per version)."""
        last = self._helper_update_sent.get(panel.id)
        now = dt_util.utcnow()
        if last and last[0] == bundled["version_code"] and now - last[1] < timedelta(hours=1):
            return
        url = panel_helper.apk_url(self.hass, panel)
        if not url:
            return
        self._helper_update_sent[panel.id] = (bundled["version_code"], now)
        try:
            await panel_helper.async_request(
                self.hass, host, "POST", "/update", key=key,
                body={"url": url, "sha256": bundled["sha256"], "version_code": bundled["version_code"]},
            )
            _LOGGER.info("Nook: asked the helper on %s to update to %s", panel.id, bundled.get("version"))
        except panel_helper.HelperError as err:
            _LOGGER.warning("Nook: couldn't update the helper on %s: %s", panel.id, err)

    async def async_helpers_state(self) -> dict[str, dict[str, Any]]:
        """Per NSPanel Pro panel: paired?, address, last status, and the version Nook ships."""
        from .panel import WWW_DIR

        keys = await self._async_helper_keys()
        bundled = await self.hass.async_add_executor_job(panel_helper.bundled_helper, WWW_DIR)
        out: dict[str, dict[str, Any]] = {}
        for panel in self._helper_panels(keys):
            cached = self._helper_status.get(panel.id) or {}
            out[panel.id] = {
                "paired": bool(keys.get(panel.id)),
                "host": panel_helper.helper_host(self.hass, panel),
                "summary": cached.get("summary") or {},
                "error": cached.get("error") or "",
                "checked_at": cached.get("checked_at"),
                "shipped_version": (bundled or {}).get("version"),
            }
        return out

    def wall_panel_payload(self, panel_id: str) -> dict[str, Any] | None:
        panel = self.get_wall_panel(panel_id)
        if panel is None:
            return None
        primary = self._wall_primary(panel.primary_entity)
        # Always mirror current Nook rooms so newly added rooms show on panels
        # without re-saving the wall panel. Prefer Nook room climates; fall back
        # to the TRV entity if a room climate isn't registered.
        rooms = []
        for room in self.config.rooms:
            if room.enabled is False:
                continue
            entity = (self.nook_entity_id(f"nook_{room.id}") if room.id else None) or room.trv_entity or ""
            if not entity:
                continue
            rooms.append({"entity": entity, "name": room.name, "id": room.id})
        defaults = {
            "insideTemp": self.config.temperature_sensor or "",
            "insideHumidity": "",
            "outsideTemp": self.config.outdoor_temp_sensor or "",
            "weather": "weather.home",
            "sun": "sun.sun",
        }
        sensors = {**defaults, **dict(panel.sensors or {})}
        # Don't let blank panel values wipe house-level outdoor/temp defaults
        for key, value in defaults.items():
            if not str(sensors.get(key) or "").strip():
                sensors[key] = value
        display = panel.display or {"idleMs": 30000, "panelEntity": ""}
        lock_on = bool(panel.temperature_lock) and bool(
            str(self.config.wall_pin or "").strip()
        )
        return {
            "deviceId": panel.id,
            "deviceLabel": panel.label,
            "primary": {
                "entity": primary,
                # The whole house, like the dashboard card (the panel's label is
                # where it hangs, e.g. "Hallway" — also a room name).
                "name": "Home",
                "step": 0.5,
            },
            "rooms": rooms,
            "sensors": sensors,
            "display": display,
            "screensaverIdleMs": display.get("idleMs", 30000),
            "temperatureLock": lock_on,
            "pinConfigured": bool(str(self.config.wall_pin or "").strip()),
            "time_to_temp_minutes": self._time_to_temp
            or (self.data or {}).get("time_to_temp_minutes"),
        }

    def wall_room_settings(self, room_id: str) -> dict[str, Any] | None:
        """A room's settings for the wall panel's cog: its Room Temperature
        fields, and the TRV's simple device settings (numbers, switches,
        buttons the integration files under Configuration — like the room
        dialog's TRV Configuration, minus lists and text a wall can't type)."""
        room = next((r for r in self.config.rooms if r.id == room_id), None)
        if room is None:
            return None
        settings: list[dict[str, Any]] = []
        trv = self.hass.states.get(room.trv_entity) if room.trv_entity else None
        ent_reg = er.async_get(self.hass)
        trv_entry = ent_reg.async_get(room.trv_entity) if room.trv_entity else None
        if trv_entry is not None and trv_entry.device_id:
            device = dr.async_get(self.hass).async_get(trv_entry.device_id)
            device_name = (device.name_by_user or device.name or "") if device else ""
            for entry in er.async_entries_for_device(ent_reg, trv_entry.device_id):
                domain = entry.entity_id.split(".")[0]
                if (
                    entry.entity_id == room.trv_entity
                    or domain not in WALL_TRV_SETTING_DOMAINS
                    or entry.entity_category != EntityCategory.CONFIG
                    or entry.disabled_by is not None
                    or entry.hidden_by is not None
                ):
                    continue
                state = self.hass.states.get(entry.entity_id)
                if state is None:
                    continue
                name = str(state.attributes.get("friendly_name") or entry.entity_id)
                if device_name and name.startswith(f"{device_name} "):
                    name = name[len(device_name) + 1 :]
                item: dict[str, Any] = {
                    "entity_id": entry.entity_id,
                    "domain": domain,
                    "name": name[:1].upper() + name[1:],
                    "state": state.state,
                }
                if domain == "number":
                    for key in ("min", "max", "step"):
                        if state.attributes.get(key) is not None:
                            item[key] = state.attributes[key]
                    item["unit"] = state.attributes.get("unit_of_measurement") or ""
                settings.append(item)
        settings.sort(key=lambda s: (s["domain"] == "button", s["name"].lower()))
        return {
            "room": {
                "id": room.id,
                "name": room.name,
                "follow_house": room.follow_house,
                "house_offset": room.house_offset,
                "target_temp": room.target_temp,
                "eco_temp": room.eco_temp,
                "hold_ends": room.hold_ends,
            },
            "trv": {
                "entity_id": room.trv_entity,
                "available": trv is not None and trv.state not in ("unavailable", "unknown"),
            },
            "settings": settings,
        }

    async def async_update_wall_room(self, room_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Change a room's Room Temperature fields from a wall panel (same rooms,
        so nothing reloads and the heating carries on)."""
        rooms = [r.to_dict() for r in self.config.rooms]
        room = next((r for r in rooms if r["id"] == room_id), None)
        if room is None:
            return None
        room.update({k: v for k, v in changes.items() if k in WALL_ROOM_FIELDS})
        await self.async_save_config({"rooms": [RoomConfig.from_dict(r).to_dict() for r in rooms]})
        return self.wall_room_settings(room_id)

    def _tracked_entities(self) -> tuple[str, ...]:
        entities = [
            self.config.heater,
            self.config.temperature_sensor,
            self.config.backup_temperature_sensor,
        ]
        entities.extend(self.config.window_sensors)
        entities.extend(self._presence_entities())
        if self.config.outdoor_temp_sensor:
            entities.append(self.config.outdoor_temp_sensor)
        for room in self.config.rooms:
            entities.append(room.trv_entity)
            if room.temperature_sensor:
                entities.append(room.temperature_sensor)
            entities.extend(room.extra_temperature_sensors or [])
            entities.extend(room.window_sensors)
        # Faster-updates sensors too (watched ones aren't otherwise tracked): see _on_state.
        entities.extend(self.config.fast_reporting_sensors)
        return tuple(sorted({e for e in entities if e}))

    @callback
    def _reporting_unconfirmed(self, entity_id: str) -> None:
        """The sensor may have lost Faster updates: show it as not confirmed and send again."""
        status = self._reporting_status.get(entity_id)
        if status is None or not status.get("ok") or entity_id not in self.config.fast_reporting_sensors:
            return
        self._reporting_status[entity_id] = {
            **status, "ok": False, "applied": False, "pending": False,
            "error": "the sensor rejoined (re-paired or reconfigured) — sending Faster updates again",
        }

    @callback
    def _retry_reporting_while_awake(self, entity_id: str) -> None:
        """A sleepy Zigbee sensor only listens just after it sends a reading. If its
        Faster updates request hasn't got through, send it now — to it alone.

        23 Oct 2026: the bathroom and ensuite SNZB-02Ms (reading every ~15 min)
        missed every half-hourly retry, which landed while they slept.
        """
        status = self._reporting_status.get(entity_id)
        if status is None or not status.get("supported") or status.get("ok"):
            return
        if entity_id not in self.config.fast_reporting_sensors:
            return
        task = self._reporting_task
        if task is not None and not task.done():
            return  # busy with another sensor; this one's next reading tries again
        if not self._zigbee_settled():
            return
        self._reporting_task = self.hass.async_create_background_task(
            self._async_apply_reporting({entity_id: True}), f"{DOMAIN}_sensor_reporting_awake"
        )

    @callback
    def _subscribe_state_changes(self) -> None:
        entities = self._tracked_entities()
        if self._state_unsub is not None and entities == self._watched:
            return
        if self._state_unsub is not None:
            self._state_unsub()

        @callback
        def _on_state(event: Any) -> None:
            new = event.data.get("new_state")
            if (
                new is not None
                and event.data.get("entity_id") == self.config.heater
                and new.state not in ("unknown", "unavailable")
            ):
                self._relay_since(self._is_on(self.config.heater), new.last_changed)
            if new is not None and new.state not in ("unknown", "unavailable"):
                old = event.data.get("old_state")
                entity_id = event.data.get("entity_id")
                if old is not None and old.state == "unavailable":
                    # Back from unavailable = ZHA reconfigure/re-pair, which puts reporting back to
                    # ZHA's defaults (23 Oct: it overwrote Faster updates set seconds earlier).
                    # ZHA is still configuring it right now: send at its NEXT reading instead.
                    self._reporting_unconfirmed(entity_id)
                else:
                    self._retry_reporting_while_awake(entity_id)
            self.hass.async_create_task(self.async_request_refresh())

        self._watched = entities
        self._state_unsub = (
            async_track_state_change_event(self.hass, list(entities), _on_state)
            if entities
            else (lambda: None)
        )

    # ---- Fully Kiosk wall panels ----
    @property
    def _kiosk_pin(self) -> str:
        """Fully's menu PIN follows the wall PIN; blank leaves Fully's own PIN alone."""
        return str(self.config.wall_pin or "").strip()

    def kiosk_status(self) -> dict[str, Any]:
        return {
            "devices": kiosk.fully_devices(self.hass),
            "defaults": self.config.kiosk_defaults,
            "auto_sync": self.config.kiosk_auto_sync,
            "panels": {
                p.id: kiosk.panel_status(self.hass, p, self.config.kiosk_defaults, pin=self._kiosk_pin) for p in self.config.wall_panels
            },
        }

    async def async_kiosk_apply(self, panel_id: str | None = None, *, force: bool = True) -> dict[str, list[str]]:
        """Push settings to one panel (or all linked panels)."""
        out: dict[str, list[str]] = {}
        for panel in self.config.wall_panels:
            if panel_id and panel.id != panel_id:
                continue
            if not panel.linked_kiosk_device:
                continue
            try:
                out[panel.id] = await kiosk.async_apply(
                    self.hass, panel, self.config.kiosk_defaults, force=force, pin=self._kiosk_pin
                )
            except Exception as err:  # noqa: BLE001 - one bad panel mustn't stop the rest
                _LOGGER.warning("Nook: couldn't sync wall panel %s: %s", panel.id, err)
                out[panel.id] = [f"error: {err}"]
        return out

    def _kiosk_subscribe(self) -> None:
        watched: dict[str, str] = {}
        for panel in self.config.wall_panels:
            if panel.linked_kiosk_device:
                for entity_id in kiosk.device_entities(self.hass, panel.linked_kiosk_device).values():
                    watched[entity_id] = panel.id
        if self._kiosk_unsub is not None and watched == self._kiosk_watched:
            return
        if self._kiosk_unsub is not None:
            self._kiosk_unsub()

        @callback
        def _on_state(event: Any) -> None:
            panel_id = self._kiosk_watched.get(event.data.get("entity_id"))
            if not panel_id or not self.config.kiosk_auto_sync:
                return
            old = event.data.get("old_state")
            new = event.data.get("new_state")
            came_back = (old is None or old.state == "unavailable") and new is not None and new.state != "unavailable"
            # Back online: re-apply everything soon (it may have lost settings or rebooted).
            self._kiosk_schedule(panel_id, delay=5 if came_back else 10, force=came_back)
            if came_back:  # and give it a new wall app version it slept through
                self.hass.async_create_task(self.async_kiosk_version_refresh())

        self._kiosk_watched = watched
        self._kiosk_unsub = (
            async_track_state_change_event(self.hass, list(watched), _on_state) if watched else (lambda: None)
        )

    @callback
    def _kiosk_schedule(self, panel_id: str, *, delay: float, force: bool = False) -> None:
        """Debounced sync of one panel; backs off while a panel keeps refusing a setting."""
        if panel_id in self._kiosk_timers:
            return
        attempts = self._kiosk_attempts.get(panel_id, 0)
        wait = delay if attempts == 0 else min(1800, 60 * 2 ** (attempts - 1))

        async def _run(_now: Any) -> None:
            self._kiosk_timers.pop(panel_id, None)
            panel = self.get_wall_panel(panel_id)
            if panel is None or not panel.linked_kiosk_device or not self.config.kiosk_auto_sync:
                return
            status = kiosk.panel_status(self.hass, panel, self.config.kiosk_defaults, pin=self._kiosk_pin)
            if not status.get("online"):
                return
            if status.get("in_sync") and not force:
                self._kiosk_attempts[panel_id] = 0
                return
            await self.async_kiosk_apply(panel_id, force=force)
            after = kiosk.panel_status(self.hass, panel, self.config.kiosk_defaults, pin=self._kiosk_pin)
            self._kiosk_attempts[panel_id] = 0 if after.get("in_sync") else attempts + 1

        self._kiosk_timers[panel_id] = async_call_later(self.hass, wait, _run)

    async def async_kiosk_version_refresh(self) -> list[str]:
        """Once per new wall app version: clear each linked panel's cache and reload it.

        The app reloads itself on a new version, but only Fully's own button can clear the
        browser cache (stale files caused glitches). The version is saved per panel, so this
        runs once per update, not on every restart — and a panel that was asleep or offline
        at the time gets it when it's back (called again then, and every 10 min)."""
        async with self._version_refresh_lock:
            return await self._async_kiosk_version_refresh()

    async def _async_kiosk_version_refresh(self) -> list[str]:
        from .panel import WWW_DIR

        version = await self.hass.async_add_executor_job(kiosk.bundled_wall_version, WWW_DIR)
        if not version:
            return []
        stored = await self._kiosk_store.async_load() or {}
        done = stored.get("wall_versions")
        if done is None:  # before 0.6.41 one version was kept for all panels
            done = {p.id: stored.get("wall_version") for p in self.config.wall_panels}
        done = dict(done)
        refreshed: list[str] = []
        for panel in self.config.wall_panels:
            if not panel.linked_kiosk_device or done.get(panel.id) == version:
                continue
            status = kiosk.panel_status(self.hass, panel, self.config.kiosk_defaults, pin=self._kiosk_pin)
            if not status.get("online") or not status.get("expected_url"):
                continue  # asleep/offline: retried when it's back
            try:
                await kiosk.async_fresh_load(self.hass, panel.linked_kiosk_device, status["expected_url"])
                refreshed.append(panel.id)
                done[panel.id] = version
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Nook: couldn't refresh wall panel %s: %s", panel.id, err)
        if done != stored.get("wall_versions"):
            stored = await self._kiosk_store.async_load() or {}  # screens may have changed meanwhile
            stored.pop("wall_version", None)
            await self._kiosk_store.async_save({**stored, "wall_versions": done})
        if refreshed:
            _LOGGER.info("Nook: wall app %s — cleared cache and reloaded %s", version, ", ".join(refreshed))
        return refreshed

    async def async_setup_listeners(self) -> None:
        self._subscribe_state_changes()
        self._kiosk_subscribe()

        @callback
        def _version_check(_now: Any) -> None:
            self.hass.async_create_task(self.async_kiosk_version_refresh())

        # Give the Fully Kiosk entities time to come up after a restart.
        self._unsubs.append(async_call_later(self.hass, 30, _version_check))

        @callback
        def _kiosk_check(_now: Any) -> None:
            # Safety net: catch drift on settings HA can only read occasionally.
            for panel in self.config.wall_panels:
                if panel.linked_kiosk_device:
                    self._kiosk_schedule(panel.id, delay=1)
            self.hass.async_create_task(self.async_kiosk_version_refresh())

        self._unsubs.append(async_track_time_interval(self.hass, _kiosk_check, timedelta(minutes=10)))

        @callback
        def _helper_check(_now: Any) -> None:
            # Cheap when nothing is paired: it only reads the stored keys.
            self.hass.async_create_task(self.async_helper_poll())

        self._unsubs.append(async_track_time_interval(self.hass, _helper_check, timedelta(minutes=1)))

        # @callback keeps it on the event loop; without it HA runs it in a worker thread, where
        # async_create_task is refused and the refresh coroutine is dropped (never awaited).
        @callback
        def _tick(_now: Any) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        self._unsubs.append(
            async_track_time_interval(self.hass, _tick, UPDATE_INTERVAL)
        )

        @callback
        def _on_registry(event: Any) -> None:
            old = event.data.get("old_entity_id")
            if event.data.get("action") == "update" and old and self._async_follow_rename(old, event.data["entity_id"]):
                self.hass.async_create_task(self.async_request_refresh())

        self._unsubs.append(self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _on_registry))

    async def async_unload(self) -> None:
        if self._reporting_task is not None and not self._reporting_task.done():
            self._reporting_task.cancel()
        for task in self._trv_tasks.values():
            if not task.done():
                task.cancel()
        self._trv_tasks.clear()
        if self._dirty_intel:
            await self.intel.async_save()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        if self._kiosk_unsub is not None:
            self._kiosk_unsub()
            self._kiosk_unsub = None
        for cancel in self._kiosk_timers.values():
            cancel()
        self._kiosk_timers.clear()
