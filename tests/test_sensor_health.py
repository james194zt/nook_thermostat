"""House sensor health: dead-sensor detection, backup sensor, timed heating; fast reporting.

Run: <venv>/bin/python -m pytest tests/test_sensor_health.py
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook import coordinator as coordinator_module  # noqa: E402
from custom_components.nook import zigbee_reporting  # noqa: E402
from custom_components.nook.sensor_health import (  # noqa: E402
    SOURCE_BACKUP,
    SOURCE_MAIN,
    SOURCE_NONE,
    SensorHealth,
    choose,
    fallback_heat,
    frost_risk,
    learn_offset,
    reading,
)
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _state(value, minutes_ago=0):
    return SimpleNamespace(state=str(value), last_reported=NOW - timedelta(minutes=minutes_ago))


# --- pure logic -------------------------------------------------------------------


def test_reading_spots_dead_sensors():
    assert reading(_state(20.5, 5), now_utc=NOW, stale_minutes=60) == 20.5
    # A frozen value is still "20.5" in HA — only the silence gives it away.
    assert reading(_state(20.5, 61), now_utc=NOW, stale_minutes=60) is None
    assert reading(_state("unavailable"), now_utc=NOW, stale_minutes=60) is None
    assert reading(_state("abc"), now_utc=NOW, stale_minutes=60) is None
    assert reading(None, now_utc=NOW, stale_minutes=60) is None


def test_choose_main_then_backup_then_nothing():
    health = SensorHealth(offset_c=-1.2)
    assert choose(19.0, 20.5, health) == (19.0, SOURCE_MAIN)
    assert choose(None, 20.5, health) == (19.3, SOURCE_BACKUP)
    assert choose(None, None, health) == (None, SOURCE_NONE)


def test_offset_learns_slowly_and_not_too_often():
    health = SensorHealth()
    t = datetime(2026, 10, 13, 12, 0)
    assert learn_offset(health, 19.0, 20.5, t)
    assert health.offset_c == -1.5
    assert not learn_offset(health, 19.0, 21.5, t + timedelta(minutes=5))  # too soon
    for i in range(1, 200):
        learn_offset(health, 19.0, 20.0, t + timedelta(minutes=10 * i))
    assert health.offset_c == pytest.approx(-1.0, abs=0.01)
    assert not learn_offset(health, None, 20.0, t + timedelta(days=9))


def test_timed_heating_pattern():
    at = lambda h, m: datetime(2026, 10, 13, h, m)  # noqa: E731
    assert fallback_heat(at(7, 10), comfort=True, frost=False)
    assert not fallback_heat(at(7, 30), comfort=True, frost=False)
    assert fallback_heat(at(4, 5), comfort=False, frost=True)  # every 4 h
    assert not fallback_heat(at(5, 5), comfort=False, frost=True)
    assert not fallback_heat(at(4, 5), comfort=False, frost=False)
    assert frost_risk(2.0, summer_mode=False) and not frost_risk(12.0, summer_mode=False)
    assert frost_risk(None, summer_mode=False) and not frost_risk(None, summer_mode=True)


def test_health_persists():
    health = SensorHealth(source=SOURCE_BACKUP, since="x", offset_c=-0.8, offset_samples=4)
    assert SensorHealth.from_dict(health.to_dict()) == health
    assert SensorHealth.from_dict({"source": "bogus"}).source == SOURCE_MAIN


# --- the real coordinator ---------------------------------------------------------

START = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")
# ZHA's per-device "last seen" (what a Zigbee heartbeat updates), by entity.
SEEN: dict = {}


async def _at(hass, coord, freezer, minute, *, house=None, backup=None, heartbeat=()):
    now = START + timedelta(minutes=minute)
    freezer.move_to(now)
    if house is not None:
        hass.states.async_set("sensor.house", str(house))
        SEEN["sensor.house"] = now
    if backup is not None:
        hass.states.async_set("sensor.backup", str(backup))
        SEEN["sensor.backup"] = now
    for entity_id in heartbeat:  # a report with an unchanged value: HA hears nothing
        SEEN[entity_id] = now
    return await _tick(hass, coord)


@pytest.fixture
async def backed_up(hass, setup, freezer, monkeypatch):
    coord, calls = setup
    SEEN.clear()
    monkeypatch.setattr(zigbee_reporting, "zha_last_seen", lambda hass, e: SEEN.get(e))
    # Only the house calls: the lounge is warm.
    hass.states.async_set("climate.trv_lounge", "heat", {"temperature": 16, "current_temperature": 22})
    freezer.move_to(START)
    hass.states.async_set("sensor.house", "18.0")
    hass.states.async_set("sensor.backup", "19.5")
    await coord.async_save_config({"backup_temperature_sensor": "sensor.backup"})
    return coord, calls


async def test_dead_main_sensor_falls_back_then_recovers(hass, backed_up, freezer):
    coord = backed_up[0]
    data = await _at(hass, coord, freezer, 0, house=18.0, backup=19.5)
    assert data["boiler_on"] is True
    assert coord.intel.state.sensor_health.offset_c == -1.5

    # The hall sensor's battery dies at 18.0; the backup keeps reporting.
    for m in (20, 40, 60):
        await _at(hass, coord, freezer, m, backup=20.0)
    data = await _at(hass, coord, freezer, 61, backup=20.0)
    assert data["house_sensor"]["source"] == SOURCE_MAIN  # not confirmed yet
    data = await _at(hass, coord, freezer, 65, backup=20.0)
    assert data["house_sensor"]["source"] == SOURCE_BACKUP
    assert coord._house_temp() == 18.5  # noqa: SLF001 — 20.0 backup − 1.5
    assert any("sensor" in key for key in hass.data["persistent_notification"])

    # Back again: switched straight back, warning cleared.
    data = await _at(hass, coord, freezer, 70, house=18.6, backup=20.0)
    assert data["house_sensor"]["source"] == SOURCE_MAIN
    assert not any("sensor" in key for key in hass.data["persistent_notification"])


async def test_no_sensor_heats_on_a_timer(hass, backed_up, freezer):
    coord = backed_up[0]
    await _at(hass, coord, freezer, 0, house=18.0, backup=19.5)
    # Both go silent (17:10+ local); confirmed after 3 minutes.
    await _at(hass, coord, freezer, 61)
    data = await _at(hass, coord, freezer, 65)
    assert data["house_sensor"]["source"] == SOURCE_NONE
    assert any("sensor" in key for key in hass.data["persistent_notification"])
    # 17:15 in the 16:00–22:00 block: heat for the first 20 min of each hour.
    assert data["boiler_on"] is True
    assert (await _at(hass, coord, freezer, 75))["boiler_on"] is False  # 17:25
    assert (await _at(hass, coord, freezer, 115))["boiler_on"] is True  # 18:05


async def test_a_blip_changes_nothing(hass, backed_up, freezer):
    coord = backed_up[0]
    assert (await _at(hass, coord, freezer, 0, house=18.0, backup=19.5))["boiler_on"] is True
    # HA starting: the sensor is "unavailable" for a moment.
    hass.states.async_set("sensor.house", "unavailable")
    hass.states.async_set("sensor.backup", "unavailable")
    data = await _at(hass, coord, freezer, 1)
    assert data["boiler_on"] is True  # kept going, no timer kicked in
    data = await _at(hass, coord, freezer, 2, house=18.1, backup=19.6)
    assert data["house_sensor"]["source"] == SOURCE_MAIN
    assert not any("sensor" in key for key in hass.data.get("persistent_notification", {}))


async def test_steady_zigbee_sensor_is_not_dead(hass, backed_up, freezer):
    """ZHA only tells HA about changes: a steady 18.0 for hours is fine if the device checks in."""
    coord = backed_up[0]
    await _at(hass, coord, freezer, 0, house=18.0, backup=19.5)
    for m in range(15, 240, 15):
        data = await _at(hass, coord, freezer, m, heartbeat=("sensor.house", "sensor.backup"))
    assert data["house_sensor"]["source"] == SOURCE_MAIN
    assert not any("sensor" in key for key in hass.data.get("persistent_notification", {}))


async def test_sensor_without_heartbeat_gets_three_hours(hass, backed_up, freezer):
    coord = backed_up[0]
    await _at(hass, coord, freezer, 0, house=18.0, backup=19.5)
    SEEN.clear()  # neither is a ZHA device now: only HA's last_reported to go on
    for m in (61, 65, 120):
        assert (await _at(hass, coord, freezer, m))["house_sensor"]["source"] == SOURCE_MAIN
    await _at(hass, coord, freezer, 181)
    data = await _at(hass, coord, freezer, 185)
    assert data["house_sensor"]["source"] == SOURCE_NONE


async def test_learning_pauses_on_the_backup(hass, backed_up, freezer):
    coord = backed_up[0]
    await _at(hass, coord, freezer, 0, house=18.0, backup=19.5)
    for m in (20, 40, 61, 65):
        await _at(hass, coord, freezer, m, backup=19.5 + m / 100)
    assert coord._heat_cycle_start is None  # noqa: SLF001
    assert coord.intel.state.recent_cycles == []


# --- fast reporting -----------------------------------------------------------------


@pytest.fixture
def zha_up(monkeypatch):
    """ZHA loaded long ago: no start-up wait."""
    monkeypatch.setattr(zigbee_reporting, "zha_loaded", lambda hass: True)
    monkeypatch.setattr(coordinator_module, "ZIGBEE_SETTLE", timedelta(0))


@pytest.fixture
def zha(monkeypatch, zha_up):
    calls = []
    fail = {"on": False}

    async def configure(hass, entity_id, *, fast):
        calls.append((entity_id, fast))
        if fail["on"]:
            raise zigbee_reporting.ReportingError("the sensor didn't answer (it may be asleep) — will retry")

    monkeypatch.setattr(zigbee_reporting, "zha_ieee", lambda hass, e: "aa:bb" if e == "sensor.house" else None)
    monkeypatch.setattr(zigbee_reporting, "async_configure", configure)
    return calls, fail


async def test_fast_reporting_on_off_and_retry(hass, backed_up, freezer, zha):
    coord = backed_up[0]
    calls, fail = zha
    await coord.async_save_config({"fast_sensor_reporting": True})
    await _at(hass, coord, freezer, 0, house=18.0, backup=19.5)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == [("sensor.house", True)]
    rep = coord._sensor_info()["reporting"]  # noqa: SLF001
    assert rep["sensor.house"] == {"supported": True, "fast": True, "ok": True, "at": rep["sensor.house"]["at"]}
    assert rep["sensor.backup"]["supported"] is False
    assert coord.intel.state.fast_reporting == ["sensor.house"]

    # Not re-sent every tick; re-sent after a day.
    await _at(hass, coord, freezer, 1, house=18.0, backup=19.5)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 1
    await _at(hass, coord, freezer, 24 * 60 + 5, house=18.0, backup=19.5)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 2

    # Turning it off puts the sensor back to ZHA's normal reporting — even if it's asleep at first.
    fail["on"] = True
    await coord.async_save_config({"fast_sensor_reporting": False})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls[-1] == ("sensor.house", False)
    assert coord._sensor_info()["reporting"]["sensor.house"]["ok"] is False  # noqa: SLF001
    assert coord.intel.state.fast_reporting == ["sensor.house"]  # still to undo
    fail["on"] = False
    await _at(hass, coord, freezer, 24 * 60 + 40, house=18.0, backup=19.5)  # retry after 30 min
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls[-1] == ("sensor.house", False)
    assert coord.intel.state.fast_reporting == []


async def test_nothing_sent_while_zha_or_ha_starts_or_stops(hass, backed_up, freezer, monkeypatch):
    """A request during ZHA's start-up (or HA's shutdown) can leave ZHA stuck until a reboot."""
    from homeassistant.core import CoreState

    coord = backed_up[0]
    calls = []
    loaded = {"on": False}

    async def configure(hass, entity_id, *, fast):
        calls.append(entity_id)

    monkeypatch.setattr(zigbee_reporting, "zha_loaded", lambda hass: loaded["on"])
    monkeypatch.setattr(zigbee_reporting, "zha_ieee", lambda hass, e: "aa:bb" if e == "sensor.house" else None)
    monkeypatch.setattr(zigbee_reporting, "async_configure", configure)
    await coord.async_save_config({"fast_sensor_reporting": True})

    async def tick(minute):
        await _at(hass, coord, freezer, minute, house=18.0, backup=19.5)
        await hass.async_block_till_done(wait_background_tasks=True)

    await tick(0)
    assert calls == []  # ZHA's entry not loaded yet
    loaded["on"] = True
    await tick(1)
    await tick(3)
    assert calls == []  # loaded, but still polling its devices
    await tick(4)
    assert calls == ["sensor.house"]  # 3 min after ZHA loaded

    # HA stopping: nothing new goes out, and the wait starts again afterwards.
    calls.clear()
    coord._reporting_next_try.clear()  # noqa: SLF001 — due again
    hass.set_state(CoreState.stopping)
    try:
        await coord._async_sync_sensor_reporting()  # noqa: SLF001
        await coord._async_apply_reporting({"sensor.house": True})  # noqa: SLF001 — already queued
        assert calls == []
        assert coord._zigbee_ok_after is None  # noqa: SLF001
    finally:
        hass.set_state(CoreState.running)


def test_zha_loaded_means_its_entry_finished_setting_up(hass, monkeypatch):
    from homeassistant.config_entries import ConfigEntryState

    # (A real "zha" entry would make HA try to load ZHA, which this venv doesn't have.)
    entry = SimpleNamespace(state=ConfigEntryState.SETUP_IN_PROGRESS)
    monkeypatch.setattr(
        hass.config_entries, "async_entries", lambda domain=None, **kw: [entry] if domain == "zha" else []
    )
    hass.config.components.add("zha")  # HA adds this before ZHA's entry has even started
    assert not zigbee_reporting.zha_loaded(hass)
    entry.state = ConfigEntryState.LOADED
    assert zigbee_reporting.zha_loaded(hass)
    hass.config.components.remove("zha")


async def test_zha_still_starting_retries_soon_and_quietly(hass, backed_up, freezer, monkeypatch, caplog, zha_up):
    coord = backed_up[0]
    calls = []
    ready = {"on": False}

    async def configure(hass, entity_id, *, fast):
        calls.append(entity_id)
        if not ready["on"]:
            raise zigbee_reporting.ReportingError("waiting for ZHA to start", not_ready=True)

    monkeypatch.setattr(zigbee_reporting, "zha_ieee", lambda hass, e: "aa:bb" if e == "sensor.house" else None)
    monkeypatch.setattr(zigbee_reporting, "async_configure", configure)
    await coord.async_save_config({"fast_sensor_reporting": True})
    await _at(hass, coord, freezer, 0, house=18.0, backup=19.5)
    await hass.async_block_till_done(wait_background_tasks=True)
    rep = coord._sensor_info()["reporting"]["sensor.house"]  # noqa: SLF001
    assert rep["pending"] is True and rep["ok"] is False
    assert "couldn't set" not in caplog.text  # no warning in the log for a normal start-up
    ready["on"] = True
    await _at(hass, coord, freezer, 3, house=18.0, backup=19.5)  # 2 min later is enough
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coord._sensor_info()["reporting"]["sensor.house"]["ok"] is True  # noqa: SLF001


async def test_zha_not_imported_before_ha_loads_it(hass, monkeypatch):
    """Nook must not import ZHA itself during start-up (HA flags it as blocking)."""
    import sys

    monkeypatch.setattr(zigbee_reporting, "zha_ieee", lambda hass, e: "aa:bb")
    sys.modules.pop("homeassistant.components.zha.helpers", None)
    assert "zha" not in hass.config.components
    assert zigbee_reporting.zha_last_seen(hass, "sensor.house") is None
    with pytest.raises(zigbee_reporting.ReportingError) as err:
        await zigbee_reporting.async_configure(hass, "sensor.house", fast=True)
    assert err.value.not_ready
    assert "homeassistant.components.zha.helpers" not in sys.modules


def test_zigpy_result_parsing():
    ok = SimpleNamespace(status=0)
    bad = SimpleNamespace(status=134)
    assert zigbee_reporting._succeeded([[ok]])  # noqa: SLF001
    assert not zigbee_reporting._succeeded([[bad]])  # noqa: SLF001
    assert zigbee_reporting._succeeded([ok])  # noqa: SLF001
    # zigpy 2.x (HA 2026.10): {attribute: Status}
    assert zigbee_reporting._succeeded({"measured_value": 0})  # noqa: SLF001
    assert not zigbee_reporting._succeeded({"measured_value": 134})  # noqa: SLF001
    assert not zigbee_reporting._succeeded({})  # noqa: SLF001
