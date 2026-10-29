"""House intelligence: True Radiant, Auto-Schedule, Home/Away."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.helpers.storage import Store

from .const import (
    DAYS,
    DEFAULT_ECO_TEMP,
    DOMAIN,
    ENERGY_HISTORY_KEEP_DAYS,
    SEASONAL_MAX_C,
    SEASONAL_SAVINGS_DAYS,
    SEASONAL_STEP_C,
    SEASONAL_STEP_DAYS,
)
from .models import ScheduleBlock
from .schedule import _minutes, _parse_hhmm, day_key, running_block
from .sensor_health import SensorHealth

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.intelligence"

# Local wall-clock source; the coordinator swaps in HA's configured time zone
# (the OS clock inside HA is often UTC, an hour out during BST).
clock: Callable[[], datetime] = datetime.now

DEFAULT_WARMUP_C_PER_HOUR = 1.5
MIN_WARMUP_C_PER_HOUR = 0.4
MAX_WARMUP_C_PER_HOUR = 4.0
MAX_PREHEAT_MINUTES = 120
# With Adaptive Comfort on, a slow (cold-weather) warm-up may start this early:
# cheaper than holding the house warmer all night, and just as warm on time.
LONG_PREHEAT_MINUTES = 240
MIN_PREHEAT_MINUTES = 5
WARMUP_MIN_CYCLE_MINUTES = 15
WARMUP_MIN_RISE_C = 0.3
# A room's own warm-up rate times preheat once it has this many runs.
ROOM_WARMUP_MIN_SAMPLES = 2
# Dead time: minutes from the boiler starting until the sensor has risen this
# much (radiators heating up, sensor reporting). Learned per house and room; the
# rate is then measured from that point. 29 Oct 2026: the living room took ~18
# min to move, then rose 3.2 °C/h — one blended rate plus a fixed 5 min started
# it 20–40 min early.
LAG_RISE_C = 0.2
DEFAULT_LAG_MINUTES = 5.0
DEFAULT_AWAY_DELAY_MINUTES = 20
LEARNING_WINDOW_MINUTES = 30

# "Not warming" check: boiler-on minutes that should have warmed the house.
# A run is credited with its rise (plus radiator coast), less one sensor step
# so noise across many runs doesn't add up to fake warming.
WARMING_RISE_C = 0.3
HEAT_CHECK_COAST_MINUTES = 30
HEAT_CHECK_SENSOR_STEP_C = 0.1
HEAT_CHECK_STALE_HOURS = 6
HEAT_CHECK_MAX_TICK_MINUTES = 5
# Auto-Schedule: a change must repeat on this many different dates, agree
# within this spread, and be this recent.
AUTO_SCHEDULE_MIN_DAYS = 2
AUTO_SCHEDULE_MAX_SPREAD_C = 1.0
AUTO_SCHEDULE_KEEP_DAYS = 28
# Preheat: fit warm-up rate against outdoor temperature from this many runs
# spanning at least this much outdoor range; otherwise use the plain rate.
OUTDOOR_FIT_MIN_RUNS = 6
OUTDOOR_FIT_MIN_SPREAD_C = 4.0

# True Radiant coast: how far the house keeps warming after the boiler stops.
# Measured after each house run instead of guessed. Starts at one sensor step,
# so until it has learned Nook behaves almost like a plain thermostat (a
# little overshoot is safer than stopping short of the target).
DEFAULT_COAST_C = 0.1
MAX_COAST_C = 1.0
# Runs shorter than this never got the radiators properly hot.
COAST_MIN_RUN_MINUTES = 15
# The peak is passed once the house has cooled this far below it.
COAST_PEAK_PASSED_C = 0.2
# A peak later than this after the boiler stopped isn't radiator coast
# (sun, cooking); give up watching after COAST_MAX_WATCH_MINUTES.
COAST_MAX_PEAK_MINUTES = 60
COAST_MAX_WATCH_MINUTES = 120

# Leaf (heating hard floor ≈ 62°F)
LEAF_HARD_FLOOR_C = 16.5
LEAF_CHALLENGE_OFFSET_C = 0.5
LEAF_DEFAULT_EARLY_THRESHOLD_C = 19.5
LEAF_BASELINE_SAMPLES_NEEDED = 6
LEAF_DAY_MEANINGFUL_MINUTES = 30
TTT_MIN_SAMPLES = 3


@dataclass
class WarmupModel:
    """House warm-up rate estimate (C per hour while heating)."""

    c_per_hour: float = DEFAULT_WARMUP_C_PER_HOUR
    samples: int = 0
    last_outdoor: float | None = None
    # Learned True Radiant coast (°C the house rises after the boiler stops).
    coast_c: float = DEFAULT_COAST_C
    coast_samples: int = 0
    # Learned dead time (LAG_RISE_C); until then c_per_hour includes it.
    lag_minutes: float = DEFAULT_LAG_MINUTES
    lag_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WarmupModel:
        if not data:
            return cls()
        return cls(
            lag_minutes=float(data.get("lag_minutes", DEFAULT_LAG_MINUTES)),
            lag_samples=int(data.get("lag_samples", 0)),
            c_per_hour=float(data.get("c_per_hour", DEFAULT_WARMUP_C_PER_HOUR)),
            samples=int(data.get("samples", 0)),
            last_outdoor=(
                float(data["last_outdoor"])
                if data.get("last_outdoor") is not None
                else None
            ),
            coast_c=float(data.get("coast_c", DEFAULT_COAST_C)),
            coast_samples=int(data.get("coast_samples", 0)),
        )


@dataclass
class ManualAdjustment:
    """User setpoint change for Auto-Schedule learning."""

    at: str
    day: str
    minute_of_day: int
    temperature: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManualAdjustment:
        return cls(
            at=str(data.get("at") or ""),
            day=str(data.get("day") or "mon"),
            minute_of_day=int(data.get("minute_of_day", 0)),
            temperature=float(data.get("temperature", DEFAULT_ECO_TEMP)),
        )


@dataclass
class LeafState:
    """Accumulate-only Leaf coaching state (never decrements totals)."""

    comfort_samples: list[float] = field(default_factory=list)
    baseline: float | None = None
    minutes_total: float = 0.0
    minutes_by_day: dict[str, float] = field(default_factory=dict)
    coaching_started_at: str | None = None
    last_sample_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "comfort_samples": self.comfort_samples[-80:],
            "baseline": self.baseline,
            "minutes_total": self.minutes_total,
            "minutes_by_day": dict(list(self.minutes_by_day.items())[-60:]),
            "coaching_started_at": self.coaching_started_at,
            "last_sample_at": self.last_sample_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LeafState:
        if not data:
            return cls()
        return cls(
            comfort_samples=[float(x) for x in (data.get("comfort_samples") or [])][-80:],
            baseline=(
                float(data["baseline"]) if data.get("baseline") is not None else None
            ),
            minutes_total=float(data.get("minutes_total") or 0.0),
            minutes_by_day={
                str(k): float(v) for k, v in (data.get("minutes_by_day") or {}).items()
            },
            coaching_started_at=data.get("coaching_started_at"),
            last_sample_at=data.get("last_sample_at"),
        )


@dataclass
class EnergyHistoryState:
    """Daily heat intervals + setpoint events for Energy History UI."""

    heat_intervals_by_day: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    setpoint_events_by_day: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    open_heat_start: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "heat_intervals_by_day": {
                k: v
                for k, v in sorted(self.heat_intervals_by_day.items())[
                    -ENERGY_HISTORY_KEEP_DAYS:
                ]
            },
            "setpoint_events_by_day": {
                k: v
                for k, v in sorted(self.setpoint_events_by_day.items())[
                    -ENERGY_HISTORY_KEEP_DAYS:
                ]
            },
            "open_heat_start": self.open_heat_start,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EnergyHistoryState:
        if not data:
            return cls()
        return cls(
            heat_intervals_by_day={
                str(k): list(v or [])
                for k, v in (data.get("heat_intervals_by_day") or {}).items()
            },
            setpoint_events_by_day={
                str(k): list(v or [])
                for k, v in (data.get("setpoint_events_by_day") or {}).items()
            },
            open_heat_start=data.get("open_heat_start"),
        )


@dataclass
class SeasonalSavingsState:
    """Seasonal Savings run: per-block reductions and the blocks the user kept."""

    started_at: str | None = None
    last_step_at: str | None = None
    # "mon|06:30" -> °C taken off that schedule block (negative).
    offsets: dict[str, float] = field(default_factory=dict)
    # Blocks the user turned back up: never lowered further this run.
    kept: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SeasonalSavingsState:
        if not data:
            return cls()
        try:
            return cls(
                started_at=data.get("started_at"),
                last_step_at=data.get("last_step_at"),
                offsets={str(k): float(v) for k, v in (data.get("offsets") or {}).items()},
                kept=[str(k) for k in (data.get("kept") or [])],
            )
        except (TypeError, ValueError, AttributeError):
            return cls()


@dataclass
class HeatCheck:
    """Is the boiler actually warming the house? (persisted across restarts)"""

    # Boiler-on minutes (house calling) since the house last warmed properly.
    on_minutes: float = 0.0
    # Warming credited to finished runs over the same period.
    rise_c: float = 0.0
    # The current/last run: temperature when it started, highest seen since.
    run_start_temp: float | None = None
    run_max_temp: float | None = None
    run_ended_at: str | None = None
    last_tick: str | None = None
    last_heat_at: str | None = None
    # Set while the house is flagged as not warming.
    fault_since: str | None = None
    # What the fault was raised on: boiler minutes and warming seen, and why
    # (room names whose TRV was offline / had closed its valve). Kept after
    # an idle reset so the alert never reads "0 min, 0.0 °C".
    fault_on_minutes: float = 0.0
    fault_rise_c: float = 0.0
    # The temperature the house was heating to; reaching it clears the fault.
    fault_target: float | None = None
    fault_offline: list[str] = field(default_factory=list)
    fault_closed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HeatCheck:
        if not data:
            return cls()
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        try:
            return cls(**known)
        except TypeError:
            return cls()

    def total_rise(self) -> float:
        rise = self.rise_c
        if self.run_start_temp is not None and self.run_max_temp is not None:
            rise += _credited_rise(self.run_start_temp, self.run_max_temp)
        return rise


def _credited_rise(start: float, peak: float) -> float:
    return max(0.0, peak - start - HEAT_CHECK_SENSOR_STEP_C)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def update_heat_check(
    check: HeatCheck,
    *,
    heating: bool,
    current_temp: float | None,
    alert_minutes: float,
    target: float | None = None,
    now: datetime | None = None,
) -> str | None:
    """Advance the not-warming check by one tick.

    ``heating`` = the boiler is on because the house (or safety floor) wants
    heat — rooms alone don't count, the house sensor may not see them.
    Returns "fault" when the house is newly flagged, "recovered" when a
    flagged house warms again or is back at ``target``, else None.
    """
    now = now or clock()
    last = _parse_ts(check.last_tick)
    check.last_tick = now.isoformat()
    if current_temp is None:
        return None
    elapsed = 0.0
    if last is not None:
        elapsed = max(0.0, min(HEAT_CHECK_MAX_TICK_MINUTES, (now - last).total_seconds() / 60.0))

    if heating:
        if check.run_start_temp is None or check.run_ended_at is not None:
            # New run: bank what the previous one achieved.
            if check.run_start_temp is not None and check.run_max_temp is not None:
                check.rise_c += _credited_rise(check.run_start_temp, check.run_max_temp)
            check.run_start_temp = current_temp
            check.run_max_temp = current_temp
            check.run_ended_at = None
        check.on_minutes += elapsed
        check.last_heat_at = now.isoformat()
    elif check.run_start_temp is not None and check.run_ended_at is None:
        check.run_ended_at = now.isoformat()

    # Radiators keep warming the room for a while after the boiler stops.
    if check.run_start_temp is not None:
        ended = _parse_ts(check.run_ended_at)
        if ended is None or now - ended <= timedelta(minutes=HEAT_CHECK_COAST_MINUTES):
            check.run_max_temp = max(check.run_max_temp or current_temp, current_temp)

    if check.total_rise() >= WARMING_RISE_C:
        recovered = check.fault_since is not None
        _restart_heat_check(check, current_temp if heating else None, now)
        return "recovered" if recovered else None

    if check.fault_since is not None and check.fault_target is None:
        # Fault saved before the target was kept (≤0.6.71): use today's.
        check.fault_target = target
    if (
        check.fault_since is not None
        and check.fault_target is not None
        and current_temp >= check.fault_target
    ):
        # Up to the temperature it couldn't reach (the TRVs came back, or the
        # sun did it): the alert mustn't sit there until the next run. Not a
        # lower target later on — an Eco night isn't the heating working.
        _restart_heat_check(check, current_temp if heating else None, now)
        return "recovered"

    if check.fault_since is not None and check.on_minutes > check.fault_on_minutes:
        # Still not warming: the alert shows the whole run so far.
        check.fault_on_minutes = check.on_minutes
        check.fault_rise_c = check.total_rise()

    last_heat = _parse_ts(check.last_heat_at)
    if not heating and (
        last_heat is None or now - last_heat > timedelta(hours=HEAT_CHECK_STALE_HOURS)
    ):
        # Nothing to judge for hours: start afresh next time the house calls.
        # A standing fault stays until the house is seen warming again.
        if check.on_minutes or check.run_start_temp is not None:
            _restart_heat_check(check, None, now, keep_fault=True)
            check.last_heat_at = None
        return None

    if check.fault_since is None and alert_minutes > 0 and check.on_minutes >= alert_minutes:
        check.fault_since = now.isoformat()
        check.fault_on_minutes = check.on_minutes
        check.fault_rise_c = check.total_rise()
        check.fault_target = target
        return "fault"
    return None


def _restart_heat_check(
    check: HeatCheck, run_temp: float | None, now: datetime, *, keep_fault: bool = False
) -> None:
    check.on_minutes = 0.0
    check.rise_c = 0.0
    check.run_start_temp = run_temp
    check.run_max_temp = run_temp
    check.run_ended_at = None
    if not keep_fault:
        check.fault_since = None
        check.fault_on_minutes = 0.0
        check.fault_rise_c = 0.0
        check.fault_target = None
        check.fault_offline = []
        check.fault_closed = []
    if run_temp is not None:
        check.last_heat_at = now.isoformat()


@dataclass
class CoastWatch:
    """Measures one run's radiator coast (persisted across restarts)."""

    # The boiler run in progress.
    run_started_at: str | None = None
    house_called: bool = False
    # After the boiler stopped: temperature then, and the highest seen since.
    off_at: str | None = None
    off_temp: float | None = None
    peak_temp: float | None = None
    peak_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CoastWatch:
        if not data:
            return cls()
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        try:
            return cls(**known)
        except TypeError:
            return cls()

    def clear(self) -> None:
        for name, f in self.__dataclass_fields__.items():
            setattr(self, name, f.default)


def update_coast_watch(
    watch: CoastWatch,
    warmup: WarmupModel,
    *,
    boiler_on: bool,
    house_calling: bool,
    current_temp: float | None,
    disturbed: bool = False,
    learn: bool = True,
    now: datetime | None = None,
) -> WarmupModel | None:
    """Advance the coast measurement by one tick.

    Coast = highest house temperature after the boiler stops, less the
    temperature when it stopped. Only runs the house itself called for (rooms
    alone may not reach the house sensor) and that lasted long enough to get
    the radiators hot are measured. A window opening, the boiler starting
    again or a late peak throws the measurement away. Returns the updated
    model when a measurement completes and ``learn`` is set, else None.
    """
    now = now or clock()
    if disturbed:
        watch.clear()
        return None

    if boiler_on:
        if watch.off_at is not None:
            # Back on before the peak passed: this coast can't be measured.
            watch.clear()
        if watch.run_started_at is None:
            watch.run_started_at = now.isoformat()
        if house_calling:
            watch.house_called = True
        return None

    if watch.off_at is None:
        started = _parse_ts(watch.run_started_at)
        if started is None:
            return None
        long_enough = now - started >= timedelta(minutes=COAST_MIN_RUN_MINUTES)
        house_called = watch.house_called
        watch.clear()
        if long_enough and house_called and current_temp is not None:
            watch.off_at = now.isoformat()
            watch.off_temp = watch.peak_temp = current_temp
            watch.peak_at = watch.off_at
        return None

    off_at = _parse_ts(watch.off_at)
    if off_at is None or watch.off_temp is None or watch.peak_temp is None:
        watch.clear()
        return None
    elapsed = now - off_at
    if current_temp is not None and current_temp > watch.peak_temp:
        watch.peak_temp = current_temp
        watch.peak_at = now.isoformat()
    peak_passed = current_temp is not None and current_temp <= watch.peak_temp - COAST_PEAK_PASSED_C
    if not peak_passed and elapsed < timedelta(minutes=COAST_MAX_WATCH_MINUTES):
        return None

    peak_at = _parse_ts(watch.peak_at) or off_at
    coast = watch.peak_temp - watch.off_temp
    watch.clear()
    if peak_at - off_at > timedelta(minutes=COAST_MAX_PEAK_MINUTES) or not learn:
        return None
    return learn_coast(warmup, coast)


def learn_coast(warmup: WarmupModel, observed: float) -> WarmupModel:
    """Blend one measured coast into the model, like the warm-up rate."""
    observed = max(0.0, min(MAX_COAST_C, observed))
    n = warmup.coast_samples
    weight = min(0.35, 1.0 / (n + 1) + 0.15)
    return replace(
        warmup,
        coast_c=round(warmup.coast_c * (1 - weight) + observed * weight, 3),
        coast_samples=n + 1,
    )


@dataclass
class IntelligenceState:
    """Persisted intelligence state."""

    warmup: WarmupModel = field(default_factory=WarmupModel)
    heat_check: HeatCheck = field(default_factory=HeatCheck)
    coast_watch: CoastWatch = field(default_factory=CoastWatch)
    # The boiler run in progress, for warm-up learning: {"start", "start_temp", "house_called"}.
    heat_cycle: dict[str, Any] = field(default_factory=dict)
    # Each room's own warm-up rate (rooms with their own sensor), by room id,
    # and the runs in progress: {room_id: {"start", "start_temp"}}.
    room_warmup: dict[str, WarmupModel] = field(default_factory=dict)
    room_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Which house sensor is in use, and the learned backup offset.
    sensor_health: SensorHealth = field(default_factory=SensorHealth)
    # Sensors Nook set to fast reporting (so turning it off can put them back).
    fast_reporting: list[str] = field(default_factory=list)
    recent_cycles: list[dict[str, Any]] = field(default_factory=list)
    adjustments: list[dict[str, Any]] = field(default_factory=list)
    learning_started_at: str | None = None
    away_since: str | None = None
    leaf: LeafState = field(default_factory=LeafState)
    energy: EnergyHistoryState = field(default_factory=EnergyHistoryState)
    seasonal: SeasonalSavingsState = field(default_factory=SeasonalSavingsState)
    # Last user-chosen mode/preset/setpoints (restored across restarts).
    control: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "warmup": self.warmup.to_dict(),
            "heat_check": self.heat_check.to_dict(),
            "coast_watch": self.coast_watch.to_dict(),
            "heat_cycle": self.heat_cycle,
            "room_warmup": {k: v.to_dict() for k, v in self.room_warmup.items()},
            "room_runs": self.room_runs,
            "sensor_health": self.sensor_health.to_dict(),
            "fast_reporting": self.fast_reporting,
            "recent_cycles": self.recent_cycles[-40:],
            "adjustments": self.adjustments[-200:],
            "learning_started_at": self.learning_started_at,
            "away_since": self.away_since,
            "leaf": self.leaf.to_dict(),
            "energy": self.energy.to_dict(),
            "seasonal": self.seasonal.to_dict(),
            "control": self.control,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IntelligenceState:
        if not data:
            return cls()
        return cls(
            warmup=WarmupModel.from_dict(data.get("warmup")),
            heat_check=HeatCheck.from_dict(data.get("heat_check")),
            coast_watch=CoastWatch.from_dict(data.get("coast_watch")),
            heat_cycle=dict(data.get("heat_cycle") or {}),
            room_warmup={
                str(k): WarmupModel.from_dict(v)
                for k, v in (data.get("room_warmup") or {}).items()
            },
            room_runs={str(k): dict(v) for k, v in (data.get("room_runs") or {}).items()},
            sensor_health=SensorHealth.from_dict(data.get("sensor_health")),
            fast_reporting=[str(e) for e in (data.get("fast_reporting") or [])],
            recent_cycles=list(data.get("recent_cycles") or []),
            adjustments=list(data.get("adjustments") or []),
            learning_started_at=data.get("learning_started_at"),
            away_since=data.get("away_since"),
            leaf=LeafState.from_dict(data.get("leaf")),
            energy=EnergyHistoryState.from_dict(data.get("energy")),
            seasonal=SeasonalSavingsState.from_dict(data.get("seasonal")),
            control=dict(data.get("control") or {}),
        )


def next_upcoming_block(
    schedule: dict[str, list[dict[str, Any]]],
    now: datetime | None = None,
    *,
    look_ahead_hours: int = 18,
) -> tuple[ScheduleBlock, datetime] | None:
    """Return next enabled comfort block and its absolute start datetime."""
    now = now or clock()
    best: tuple[ScheduleBlock, datetime] | None = None
    horizon = now + timedelta(hours=look_ahead_hours)

    for day_offset in range(3):
        day_dt = now + timedelta(days=day_offset)
        key = DAYS[day_dt.weekday()]
        for raw in schedule.get(key) or []:
            block = ScheduleBlock.from_dict(raw)
            if not block.enabled:
                continue
            start_t = _parse_hhmm(block.start)
            start_dt = datetime.combine(day_dt.date(), start_t)
            if start_dt <= now or start_dt > horizon:
                continue
            if best is None or start_dt < best[1]:
                best = (block, start_dt)
    return best


def _cycle_rate(cycle: dict[str, Any]) -> tuple[float, float] | None:
    """(outdoor °C, warm-up °C/h) of a recorded run that says something about the house."""
    try:
        outdoor = float(cycle["outdoor_temp"])
        rise = float(cycle["end_temp"]) - float(cycle["start_temp"])
        minutes = float(cycle["duration_minutes"])
    except (KeyError, TypeError, ValueError):
        return None
    if minutes < WARMUP_MIN_CYCLE_MINUTES or rise < WARMUP_MIN_RISE_C:
        return None
    rate = rise / (minutes / 60.0)
    if rate < MIN_WARMUP_C_PER_HOUR:
        return None
    return outdoor, min(MAX_WARMUP_C_PER_HOUR, rate)


def outdoor_rate_factor(cycles: list[dict[str, Any]], outdoor_temp: float | None) -> float:
    """How much faster/slower the house warms at this outdoor temperature.

    A straight-line fit of measured warm-up rate against outdoor temperature
    over the recorded runs, as a ratio to the fit at their average outdoor
    temperature (the learned rate is roughly that average). 1.0 until there
    are enough runs over a wide enough range of weather; never extrapolated
    past the weather seen; a fit saying colder weather warms faster is noise.
    """
    if outdoor_temp is None:
        return 1.0
    points = [p for p in (_cycle_rate(c) for c in cycles) if p is not None]
    if len(points) < OUTDOOR_FIT_MIN_RUNS:
        return 1.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if max(xs) - min(xs) < OUTDOOR_FIT_MIN_SPREAD_C:
        return 1.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sum(
        (x - mean_x) ** 2 for x in xs
    )
    if slope <= 0:
        return 1.0
    x = max(min(xs), min(max(xs), outdoor_temp))
    predicted = mean_y + slope * (x - mean_x)
    return max(0.25, predicted / mean_y)


def estimate_preheat_minutes(
    *,
    current_temp: float | None,
    target_temp: float,
    warmup: WarmupModel,
    outdoor_temp: float | None = None,
    cycles: list[dict[str, Any]] | None = None,
    max_minutes: int = MAX_PREHEAT_MINUTES,
) -> int:
    """Minutes of preheat needed to reach target from current."""
    if current_temp is None:
        return MIN_PREHEAT_MINUTES
    delta = target_temp - current_temp
    if delta <= 0.2:
        return 0

    rate = warmup.c_per_hour * outdoor_rate_factor(cycles or [], outdoor_temp)
    if outdoor_temp is not None:
        warmup.last_outdoor = outdoor_temp

    rate = max(MIN_WARMUP_C_PER_HOUR, min(MAX_WARMUP_C_PER_HOUR, rate))
    if warmup.lag_samples:
        minutes = int(warmup.lag_minutes + (max(0.0, delta - LAG_RISE_C) / rate) * 60)
    else:
        minutes = int((delta / rate) * 60) + int(DEFAULT_LAG_MINUTES)
    return max(0, min(max_minutes, minutes))


@dataclass
class PreheatRoom:
    """A room with its own sensor that will call for heat when the block starts."""

    name: str
    current_temp: float
    # Learned for this room; the house rate until it has ROOM_WARMUP_MIN_SAMPLES.
    warmup: WarmupModel | None = None
    # Follows the house: block temperature + this. None: its own target_temp.
    house_offset: float | None = 0.0
    target_temp: float = 0.0


def preheat_status(
    schedule: dict[str, list[dict[str, Any]]],
    *,
    schedule_enabled: bool,
    true_radiant: bool,
    current_temp: float | None,
    warmup: WarmupModel,
    outdoor_temp: float | None,
    away_eco_active: bool,
    cycles: list[dict[str, Any]] | None = None,
    max_minutes: int = MAX_PREHEAT_MINUTES,
    offsets: dict[str, float] | None = None,
    now: datetime | None = None,
    started_block: str | None = None,
    rooms: list[PreheatRoom] | None = None,
) -> dict[str, Any] | None:
    """Return preheat status dict when approaching an upcoming block.

    ``offsets`` are Seasonal Savings reductions by block key; the block's
    temperature is aimed for with its reduction applied.

    ``started_block``: the block whose preheat has already begun. It keeps
    going until the block starts — re-estimating from the warmer house made it
    "too early" again (22 Oct 2026: five boiler starts in one morning).

    ``rooms``: the preheat starts for whichever needs longest, the house sensor
    or one of these. 27 Oct 2026: the hall was 0.4 °C short, so a 19-minute
    preheat; the living room was 1.4 °C short and reached 20 half an hour late.
    """
    if not true_radiant or not schedule_enabled or away_eco_active:
        return None
    now = now or clock()
    upcoming = next_upcoming_block(schedule, now)
    if upcoming is None:
        return None
    block, start_dt = upcoming
    key = schedule_block_key(DAYS[start_dt.weekday()], block.start)
    target = round(block.temperature + (offsets or {}).get(key, 0.0), 1)
    needed = estimate_preheat_minutes(
        current_temp=current_temp,
        target_temp=target,
        warmup=warmup,
        outdoor_temp=outdoor_temp,
        cycles=cycles,
        max_minutes=max_minutes,
    )
    led_by = None
    for room in rooms or []:
        room_target = (
            round(target + room.house_offset, 1)
            if room.house_offset is not None
            else float(room.target_temp)
        )
        learned = room.warmup if room.warmup and room.warmup.samples >= ROOM_WARMUP_MIN_SAMPLES else None
        room_needed = estimate_preheat_minutes(
            current_temp=room.current_temp,
            target_temp=room_target,
            warmup=replace(learned or warmup),
            outdoor_temp=outdoor_temp,
            cycles=cycles,
            max_minutes=max_minutes,
        )
        if room_needed > needed:
            needed, led_by = room_needed, room.name
    # Same block key next week mustn't count: only within the longest preheat.
    started = (
        started_block is not None
        and key == started_block
        and now >= start_dt - timedelta(minutes=max_minutes)
    )
    if needed <= 0 and not started:
        return None
    preheat_start = start_dt - timedelta(minutes=needed)
    if now >= start_dt:
        return None
    return {
        "preheating": started or now >= preheat_start,
        "temperature": target,
        "block_key": key,
        "block_start": start_dt.strftime("%H:%M"),
        "preheat_start": preheat_start.strftime("%H:%M"),
        "preheat_minutes": needed,
        # The room the timing is for (None: the house sensor).
        "preheat_room": led_by,
    }


def update_warmup_from_cycle(
    warmup: WarmupModel,
    *,
    start_temp: float,
    end_temp: float,
    duration_minutes: float,
    outdoor_temp: float | None = None,
    lag_minutes: float | None = None,
) -> WarmupModel:
    """Blend a completed heat cycle into the warm-up model.

    Short runs and rises within sensor resolution say nothing about the house,
    and a rate below the floor means the boiler didn't really heat (a fault,
    not a slow house), so all of those are skipped rather than clamped in.

    ``lag_minutes``: when the sensor had risen LAG_RISE_C; the dead time is
    learned and the rate is measured from then on. None (never rose that much,
    or not tracked): the rate over the whole run, as before.
    """
    if duration_minutes < WARMUP_MIN_CYCLE_MINUTES:
        return warmup
    rise = end_temp - start_temp
    if rise < WARMUP_MIN_RISE_C:
        return warmup
    timed = lag_minutes is not None and 0 <= lag_minutes <= duration_minutes - MIN_PREHEAT_MINUTES
    if timed:
        observed = (rise - LAG_RISE_C) / ((duration_minutes - lag_minutes) / 60.0)
    else:
        observed = rise / (duration_minutes / 60.0)
    if observed < MIN_WARMUP_C_PER_HOUR:
        return warmup
    observed = min(MAX_WARMUP_C_PER_HOUR, observed)
    # Always blend (the first cycle too), so one odd run can't set the rate.
    n = warmup.samples
    weight = min(0.35, 1.0 / (n + 1) + 0.15)
    new_rate = warmup.c_per_hour * (1 - weight) + observed * weight
    lag, lag_n = warmup.lag_minutes, warmup.lag_samples
    if timed:
        lag_weight = min(0.35, 1.0 / (lag_n + 1) + 0.15)
        lag, lag_n = round(lag * (1 - lag_weight) + lag_minutes * lag_weight, 1), lag_n + 1
    return replace(
        warmup,
        c_per_hour=round(new_rate, 3),
        samples=n + 1,
        last_outdoor=outdoor_temp if outdoor_temp is not None else warmup.last_outdoor,
        lag_minutes=lag,
        lag_samples=lag_n,
    )


def record_manual_adjustment(
    state: IntelligenceState,
    temperature: float,
    now: datetime | None = None,
) -> IntelligenceState:
    now = now or clock()
    if state.learning_started_at is None:
        state.learning_started_at = now.isoformat()
    adj = ManualAdjustment(
        at=now.isoformat(),
        day=day_key(now),
        minute_of_day=_minutes(now.time()),
        temperature=temperature,
    )
    state.adjustments.append(adj.to_dict())
    state.adjustments = state.adjustments[-200:]
    return state


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _block_span(raw: dict[str, Any]) -> tuple[int, int]:
    """(start, end) minutes of a block; an overnight block ends past 24:00."""
    block = ScheduleBlock.from_dict(raw)
    start = _minutes(_parse_hhmm(block.start))
    end = _minutes(_parse_hhmm(block.end))
    if end <= start:
        end += 24 * 60
    return start, end


def learn_schedule_from_adjustments(
    schedule: dict[str, list[dict[str, Any]]],
    state: IntelligenceState,
    *,
    auto_schedule: bool,
    eco_temp: float = DEFAULT_ECO_TEMP,
    now: datetime | None = None,
    default_block_minutes: int = 120,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """Turn a repeated manual change into a schedule block.

    A pattern is the same half-hour on the same weekday, on at least
    AUTO_SCHEDULE_MIN_DAYS different dates, with the final setting each date
    within AUTO_SCHEDULE_MAX_SPREAD_C
    of each other. Several dial taps on one date count once (the last one
    wins); changes older than AUTO_SCHEDULE_KEEP_DAYS are forgotten; turning
    the heat down to Eco or below never creates a comfort block.

    Near an existing block's start only its temperature changes. Elsewhere a
    new block is added in a gap, ending before the next block; a change in
    the middle of an existing block is left to the manual hold.
    """
    if not auto_schedule:
        return schedule, False
    now = now or clock()
    cutoff = now - timedelta(days=AUTO_SCHEDULE_KEEP_DAYS)
    kept: list[ManualAdjustment] = []
    for adj in (ManualAdjustment.from_dict(a) for a in state.adjustments):
        at = _parse_ts(adj.at)
        if at is not None and at >= cutoff:
            kept.append(adj)
    if len(kept) != len(state.adjustments):
        state.adjustments = [a.to_dict() for a in kept]

    # (weekday, half-hour) -> {date: last setting that date}
    buckets: dict[tuple[str, int], dict[str, ManualAdjustment]] = {}
    for adj in sorted(kept, key=lambda a: a.at):
        key = (adj.day, adj.minute_of_day // LEARNING_WINDOW_MINUTES)
        buckets.setdefault(key, {})[adj.at[:10]] = adj

    changed = False
    new_schedule = {d: list(schedule.get(d) or []) for d in DAYS}
    for (day, bucket), by_date in sorted(buckets.items()):
        latest = sorted(by_date.values(), key=lambda a: a.at, reverse=True)[:5]
        if len(latest) < AUTO_SCHEDULE_MIN_DAYS:
            continue
        temps = [a.temperature for a in latest]
        if max(temps) - min(temps) > AUTO_SCHEDULE_MAX_SPREAD_C:
            continue  # no consistent setting to learn
        avg_temp = round(sum(temps) / len(temps) * 2) / 2.0
        if avg_temp <= eco_temp:
            continue
        center = bucket * LEARNING_WINDOW_MINUTES + LEARNING_WINDOW_MINUTES // 2

        blocks = new_schedule[day]
        spans = [
            (i, *_block_span(raw))
            for i, raw in enumerate(blocks)
            if raw.get("enabled", True)
        ]
        near = [i for i, s, _e in spans if abs(s - center) <= LEARNING_WINDOW_MINUTES]
        if near:
            i = near[0]
            if abs(float(blocks[i].get("temperature", 0)) - avg_temp) >= 0.25:
                blocks[i] = {**blocks[i], "temperature": avg_temp}
                changed = True
            continue
        if any(s <= c < e for _i, s, e in spans for c in (center, center + 24 * 60)):
            continue
        next_start = min(
            [s for _i, s, _e in spans if s > center] + [24 * 60 - 1]
        )
        end = min(center + default_block_minutes, next_start)
        if end - center < LEARNING_WINDOW_MINUTES:
            continue
        blocks.append(
            ScheduleBlock(
                start=_hhmm(center), end=_hhmm(end), temperature=avg_temp, enabled=True
            ).to_dict()
        )
        blocks.sort(key=lambda b: _minutes(_parse_hhmm(b.get("start", "00:00"))))
        changed = True

    return new_schedule, changed


def presence_anyone_home(
    get_state: Callable[[str], Any],
    entity_ids: list[str],
) -> bool | None:
    """True if anyone home, False if all away, None if unconfigured."""
    entities = [e for e in entity_ids if e]
    if not entities:
        return None
    known = False
    for entity_id in entities:
        state = get_state(entity_id)
        if state is None:
            continue
        known = True
        if state.state in ("home", "Home"):
            return True
    if not known:
        return None
    return False


def update_away_tracking(
    state: IntelligenceState,
    *,
    anyone_home: bool | None,
    delay_minutes: int,
    now: datetime | None = None,
) -> tuple[IntelligenceState, bool]:
    """Track absence; return away_eco_active after delay."""
    now = now or clock()
    if anyone_home is None or anyone_home:
        state.away_since = None
        return state, False
    if state.away_since is None:
        state.away_since = now.isoformat()
        return state, False
    try:
        since = datetime.fromisoformat(state.away_since)
    except ValueError:
        state.away_since = now.isoformat()
        return state, False
    elapsed = (now - since).total_seconds() / 60.0
    return state, elapsed >= max(0, delay_minutes)


class IntelligenceStore:
    """Load/save intelligence state via HA Store."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")
        self.state = IntelligenceState()
        self._save_pending = False

    async def async_load(self) -> IntelligenceState:
        data = await self._store.async_load()
        self.state = IntelligenceState.from_dict(data)
        return self.state

    async def async_save(self) -> None:
        # Replaces any pending delayed write.
        self._save_pending = False
        await self._store.async_save(self.state.to_dict())

    def async_delay_save(self, delay: float = 30.0) -> None:
        """Coalesce routine writes (the 30s tick shouldn't hit disk every time).

        HA's Store restarts its timer on every call, so calling it each tick
        could postpone the write indefinitely; arm it once and let it fire.
        """
        if self._save_pending:
            return
        self._save_pending = True
        self._store.async_delay_save(self._data_to_save, delay)

    def _data_to_save(self) -> dict[str, Any]:
        self._save_pending = False
        return self.state.to_dict()


def note_comfort_setpoint(leaf: LeafState, temperature: float) -> LeafState:
    """Record a Home comfort setpoint toward the Leaf baseline (never shrinks totals)."""
    leaf.comfort_samples.append(float(temperature))
    leaf.comfort_samples = leaf.comfort_samples[-80:]
    samples = sorted(leaf.comfort_samples)
    mid = len(samples) // 2
    if len(samples) % 2:
        leaf.baseline = samples[mid]
    else:
        leaf.baseline = (samples[mid - 1] + samples[mid]) / 2.0
    leaf.baseline = round(float(leaf.baseline), 2)
    return leaf


def leaf_threshold(leaf: LeafState, now: datetime | None = None) -> float:
    """Personalised Leaf threshold (°C). Stable ~0.5 below baseline; hard floor separate."""
    now = now or clock()
    if leaf.baseline is not None and len(leaf.comfort_samples) >= LEAF_BASELINE_SAMPLES_NEEDED:
        return max(LEAF_HARD_FLOOR_C, float(leaf.baseline) - LEAF_CHALLENGE_OFFSET_C)

    # Early days: mild default until we know the household
    if leaf.coaching_started_at:
        try:
            started = datetime.fromisoformat(leaf.coaching_started_at)
            if (now - started).days < 3:
                return LEAF_DEFAULT_EARLY_THRESHOLD_C
        except ValueError:
            pass
    if leaf.baseline is not None:
        return max(LEAF_HARD_FLOOR_C, float(leaf.baseline) - LEAF_CHALLENGE_OFFSET_C)
    return LEAF_DEFAULT_EARLY_THRESHOLD_C


def evaluate_leaf(
    *,
    leaf: LeafState,
    effective_target: float,
    eco_or_away: bool,
    leaf_enabled: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return live Leaf awareness status (icon may hide; earned minutes never decrease).

    ``eco_or_away`` is true for Eco/Away presets, presence-away eco, or HVAC off —
    you can't get more efficient than the heat being off.
    """
    now = now or clock()
    if leaf.coaching_started_at is None:
        leaf.coaching_started_at = now.isoformat()

    threshold = leaf_threshold(leaf, now)
    active = False
    if leaf_enabled:
        if eco_or_away:
            active = True
        elif effective_target <= LEAF_HARD_FLOOR_C:
            active = True
        elif effective_target <= threshold:
            active = True

    return {
        "active": active,
        "threshold": round(threshold, 2),
        "baseline": leaf.baseline,
        "hard_floor": LEAF_HARD_FLOOR_C,
        "enabled": leaf_enabled,
    }


def accrue_leaf_minutes(
    leaf: LeafState,
    *,
    leaf_active: bool,
    now: datetime | None = None,
    default_delta_minutes: float = 0.5,
) -> LeafState:
    """While Leaf is active, add minutes. Totals only increase."""
    now = now or clock()
    if not leaf_active:
        leaf.last_sample_at = now.isoformat()
        return leaf

    delta = default_delta_minutes
    if leaf.last_sample_at:
        try:
            prev = datetime.fromisoformat(leaf.last_sample_at)
            delta = max(0.0, min(5.0, (now - prev).total_seconds() / 60.0))
        except ValueError:
            delta = default_delta_minutes

    if delta <= 0:
        leaf.last_sample_at = now.isoformat()
        return leaf

    day_key_str = now.date().isoformat()
    leaf.minutes_by_day[day_key_str] = float(leaf.minutes_by_day.get(day_key_str, 0.0)) + delta
    leaf.minutes_total = float(leaf.minutes_total) + delta
    leaf.last_sample_at = now.isoformat()

    # Cap day map size (keep last 60 days) without reducing total
    if len(leaf.minutes_by_day) > 60:
        for old in sorted(leaf.minutes_by_day.keys())[:-60]:
            del leaf.minutes_by_day[old]
    return leaf


def leaf_week_stats(leaf: LeafState, now: datetime | None = None) -> dict[str, Any]:
    """Rolling week display + streak of days that earned meaningful Leaf time."""
    now = now or clock()
    week_minutes = 0.0
    week_days: list[dict[str, Any]] = []
    for i in range(6, -1, -1):
        day = (now.date() - timedelta(days=i)).isoformat()
        minutes = float(leaf.minutes_by_day.get(day, 0.0))
        week_minutes += minutes
        week_days.append(
            {
                "date": day,
                "minutes": round(minutes, 1),
                "earned": minutes >= LEAF_DAY_MEANINGFUL_MINUTES,
            }
        )

    streak = 0
    for i in range(60):
        day = (now.date() - timedelta(days=i)).isoformat()
        if float(leaf.minutes_by_day.get(day, 0.0)) >= LEAF_DAY_MEANINGFUL_MINUTES:
            streak += 1
        else:
            if i == 0:
                # Today not yet meaningful — still allow streak from yesterday
                continue
            break

    return {
        "minutes_week": round(week_minutes, 1),
        "hours_week": round(week_minutes / 60.0, 2),
        "minutes_total": round(float(leaf.minutes_total), 1),
        "hours_total": round(float(leaf.minutes_total) / 60.0, 2),
        "days_streak": streak,
        # Oldest first, today last — the panel's Leaf week chart.
        "week_days": week_days,
    }


def estimate_time_to_temp_minutes(
    *,
    current_temp: float | None,
    target_temp: float,
    warmup: WarmupModel,
    heating: bool,
    hvac_mode: str = "heat",
) -> int | None:
    """ETA minutes to reach target while heating; None when not applicable."""
    if hvac_mode != "heat" or not heating:
        return None
    if current_temp is None:
        return None
    delta = float(target_temp) - float(current_temp)
    if delta <= 0.05:
        return None
    rate = max(MIN_WARMUP_C_PER_HOUR, float(warmup.c_per_hour or DEFAULT_WARMUP_C_PER_HOUR))
    minutes = int(round((delta / rate) * 60.0))
    if warmup.samples < TTT_MIN_SAMPLES:
        # Still estimate, but UI may show soft wording
        minutes = max(5, minutes)
    return max(1, min(24 * 60, minutes))


def schedule_block_key(day: str, start: str) -> str:
    """Stable name for a schedule block: weekday + start time."""
    return f"{day}|{start}"


def active_block_key(
    schedule: dict[str, list[dict[str, Any]]], now: datetime | None = None
) -> str | None:
    """Key of the schedule block running at ``now`` (schedule.running_block's rules)."""
    found = running_block(schedule, now or clock())
    if found is None:
        return None
    day, block = found
    return schedule_block_key(day, block.start)


def _enabled_block_keys(schedule: dict[str, list[dict[str, Any]]]) -> list[str]:
    return [
        schedule_block_key(day, str(raw.get("start", "06:00")))
        for day in DAYS
        for raw in schedule.get(day) or []
        if raw.get("enabled", True)
    ]


def seasonal_savings_step(
    seasonal: SeasonalSavingsState,
    schedule: dict[str, list[dict[str, Any]]],
    *,
    enabled: bool,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Advance Seasonal Savings; return (status, state_changed).

    Every SEASONAL_STEP_DAYS (starting on day one) each schedule block the
    user hasn't pushed back on loses SEASONAL_STEP_C, down to
    SEASONAL_MAX_C. ``status["finished"]`` is set once SEASONAL_SAVINGS_DAYS
    have passed: the caller then writes the result into the schedule.
    """
    now = now or clock()
    if not enabled:
        return {"active": False, "offset_c": 0.0, "days_remaining": SEASONAL_SAVINGS_DAYS}, False
    changed = False
    started = _parse_ts(seasonal.started_at)
    if started is None:
        seasonal.started_at = now.isoformat()
        started = now
        changed = True
    last_step = _parse_ts(seasonal.last_step_at)
    elapsed = max(0, (now.date() - started.date()).days)
    finished = elapsed >= SEASONAL_SAVINGS_DAYS
    if not finished and (
        last_step is None or now - last_step >= timedelta(days=SEASONAL_STEP_DAYS)
    ):
        for key in _enabled_block_keys(schedule):
            if key in seasonal.kept:
                continue
            seasonal.offsets[key] = round(
                max(-SEASONAL_MAX_C, seasonal.offsets.get(key, 0.0) - SEASONAL_STEP_C), 2
            )
        seasonal.last_step_at = now.isoformat()
        changed = True
    lowered = [v for v in seasonal.offsets.values() if v < 0]
    return {
        "active": True,
        "finished": finished,
        "offset_c": min(lowered) if lowered else 0.0,
        "blocks_lowered": len(lowered),
        "blocks_kept": len(seasonal.kept),
        "days_elapsed": elapsed,
        "days_remaining": max(0, SEASONAL_SAVINGS_DAYS - elapsed),
        "started_at": seasonal.started_at,
    }, changed


def seasonal_offset(seasonal: SeasonalSavingsState, key: str | None) -> float:
    if not key or seasonal.started_at is None:
        return 0.0
    return float(seasonal.offsets.get(key, 0.0))


def seasonal_push_back(seasonal: SeasonalSavingsState, key: str | None) -> bool:
    """The user turned a lowered block up: give one step back and stop lowering it."""
    if not key or seasonal.started_at is None or key in seasonal.kept:
        return False
    seasonal.kept.append(key)
    offset = seasonal.offsets.get(key, 0.0)
    seasonal.offsets[key] = round(min(0.0, offset + SEASONAL_STEP_C), 2)
    return True


def seasonal_bake(
    schedule: dict[str, list[dict[str, Any]]], seasonal: SeasonalSavingsState
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Write the run's reductions into the schedule; returns (schedule, blocks changed)."""
    new_schedule = {d: [dict(b) for b in schedule.get(d) or []] for d in DAYS}
    count = 0
    for day, blocks in new_schedule.items():
        for block in blocks:
            offset = seasonal.offsets.get(schedule_block_key(day, str(block.get("start", "06:00"))), 0.0)
            if offset < 0 and block.get("enabled", True):
                block["temperature"] = round(float(block.get("temperature", 20.0)) + offset, 1)
                count += 1
    return new_schedule, count


def stop_seasonal_savings(seasonal: SeasonalSavingsState) -> SeasonalSavingsState:
    seasonal.started_at = None
    seasonal.last_step_at = None
    seasonal.offsets = {}
    seasonal.kept = []
    return seasonal


def _prune_day_map(day_map: dict[str, Any], keep: int = ENERGY_HISTORY_KEEP_DAYS) -> None:
    if len(day_map) <= keep:
        return
    for old in sorted(day_map.keys())[:-keep]:
        del day_map[old]


def track_heat_interval(
    energy: EnergyHistoryState,
    *,
    want_heat: bool,
    now: datetime | None = None,
) -> bool:
    """Open/close heat intervals for Energy History. Returns True if state changed."""
    now = now or clock()
    changed = False
    day = now.date().isoformat()

    if want_heat and energy.open_heat_start is None:
        energy.open_heat_start = now.isoformat()
        changed = True
    elif not want_heat and energy.open_heat_start is not None:
        try:
            start = datetime.fromisoformat(energy.open_heat_start)
        except ValueError:
            start = now
        # Split across midnight if needed
        cursor = start
        while cursor.date() < now.date():
            day_end = datetime.combine(cursor.date(), datetime.max.time()).replace(microsecond=0)
            dkey = cursor.date().isoformat()
            energy.heat_intervals_by_day.setdefault(dkey, []).append(
                {"start_ts": cursor.isoformat(), "end_ts": day_end.isoformat()}
            )
            cursor = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time())
            changed = True
        energy.heat_intervals_by_day.setdefault(day, []).append(
            {"start_ts": cursor.isoformat(), "end_ts": now.isoformat()}
        )
        energy.open_heat_start = None
        changed = True

    # Keep open interval visible: do not close until off
    _prune_day_map(energy.heat_intervals_by_day)
    _prune_day_map(energy.setpoint_events_by_day)
    return changed


def note_setpoint_event(
    energy: EnergyHistoryState,
    temperature: float,
    *,
    now: datetime | None = None,
) -> bool:
    """Log effective target change once per distinct value."""
    now = now or clock()
    day = now.date().isoformat()
    events = energy.setpoint_events_by_day.setdefault(day, [])
    temp = round(float(temperature), 1)
    if events:
        last = events[-1]
        if abs(float(last.get("temperature", 0)) - temp) < 0.05:
            return False
    events.append({"ts": now.isoformat(), "temperature": temp})
    # Cap per day
    if len(events) > 48:
        energy.setpoint_events_by_day[day] = events[-48:]
    _prune_day_map(energy.setpoint_events_by_day)
    return True


def energy_history_payload(
    energy: EnergyHistoryState,
    leaf: LeafState,
    *,
    now: datetime | None = None,
    days: int = 31,
) -> dict[str, Any]:
    """Slice for Energy History UI (includes open heat interval as ongoing)."""
    now = now or clock()
    out_days: list[dict[str, Any]] = []
    for i in range(days):
        d = (now.date() - timedelta(days=i)).isoformat()
        intervals = list(energy.heat_intervals_by_day.get(d) or [])
        # Attach open interval for today
        if i == 0 and energy.open_heat_start:
            try:
                start = datetime.fromisoformat(energy.open_heat_start)
                if start.date() == now.date():
                    intervals = [
                        *intervals,
                        {"start_ts": energy.open_heat_start, "end_ts": None},
                    ]
                elif start.date() < now.date():
                    intervals = [
                        *intervals,
                        {
                            "start_ts": datetime.combine(now.date(), datetime.min.time()).isoformat(),
                            "end_ts": None,
                        },
                    ]
            except ValueError:
                pass
        leaf_mins = float(leaf.minutes_by_day.get(d, 0.0))
        out_days.append(
            {
                "date": d,
                "leaf": leaf_mins >= LEAF_DAY_MEANINGFUL_MINUTES,
                "leaf_minutes": round(leaf_mins, 1),
                "heat_intervals": intervals,
                "setpoints": list(energy.setpoint_events_by_day.get(d) or []),
            }
        )
    return {"days": out_days}


def _heat_runs(energy: EnergyHistoryState, now: datetime, since: datetime) -> list[tuple[datetime, datetime]]:
    """Boiler runs overlapping [since, now], joined back up where midnight split them."""
    raw: list[tuple[datetime, datetime]] = []
    day = since.date()
    while day <= now.date():
        for item in energy.heat_intervals_by_day.get(day.isoformat()) or []:
            try:
                start = datetime.fromisoformat(item["start_ts"])
                end = datetime.fromisoformat(item["end_ts"]) if item.get("end_ts") else now
            except (KeyError, TypeError, ValueError):
                continue
            raw.append((start, end))
        day += timedelta(days=1)
    if energy.open_heat_start:
        try:
            raw.append((datetime.fromisoformat(energy.open_heat_start), now))
        except ValueError:
            pass
    raw.sort()
    runs: list[tuple[datetime, datetime]] = []
    for start, end in raw:
        if end <= since or start >= now:
            continue
        start, end = max(start, since), min(end, now)
        # Midnight splits end at 23:59:59 and restart at 00:00:00.
        if runs and (start - runs[-1][1]).total_seconds() <= 2:
            runs[-1] = (runs[-1][0], max(end, runs[-1][1]))
        else:
            runs.append((start, end))
    return runs


def wall_usage_payload(
    energy: EnergyHistoryState,
    *,
    now: datetime | None = None,
    hours: int = 24,
) -> dict[str, Any]:
    """The wall panel's usage page: boiler runs and targets over the last day.

    Times are minutes from the start of the window (now − hours), so the panel
    never has to parse dates or know the server's time zone.
    """
    now = now or clock()
    since = now - timedelta(hours=hours)
    window_min = hours * 60.0

    def mins(at: datetime) -> float:
        return round((at - since).total_seconds() / 60.0, 1)

    runs = _heat_runs(energy, now, since)
    prev = _heat_runs(energy, since, since - timedelta(hours=hours))

    events: list[tuple[datetime, float]] = []
    day = (since - timedelta(days=1)).date()
    while day <= now.date():
        for item in energy.setpoint_events_by_day.get(day.isoformat()) or []:
            try:
                events.append((datetime.fromisoformat(item["ts"]), float(item["temperature"])))
            except (KeyError, TypeError, ValueError):
                continue
        day += timedelta(days=1)
    events.sort()
    setpoints: list[dict[str, float]] = []
    before = [temp for at, temp in events if at <= since]
    if before:
        setpoints.append({"m": 0.0, "t": before[-1]})
    for at, temp in events:
        if since < at <= now:
            setpoints.append({"m": mins(at), "t": temp})

    return {
        "window_minutes": window_min,
        "runs": [{"s": mins(s), "e": mins(e)} for s, e in runs],
        "run_count": len(runs),
        "on_minutes": round(sum((e - s).total_seconds() for s, e in runs) / 60.0, 1),
        "prev_on_minutes": round(sum((e - s).total_seconds() for s, e in prev) / 60.0, 1),
        "heating_now": energy.open_heat_start is not None,
        "setpoints": setpoints,
    }
