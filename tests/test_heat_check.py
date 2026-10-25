"""House-not-warming alert and warm-up learning (needs HA test venv).

Run: <venv>/bin/python -m pytest tests/test_heat_check.py
"""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.intelligence import (  # noqa: E402
    DEFAULT_WARMUP_C_PER_HOUR,
    HeatCheck,
    IntelligenceState,
    WarmupModel,
    update_heat_check,
    update_warmup_from_cycle,
)
from tests.test_schedule_ha import MONDAY, _tick, setup  # noqa: E402,F401

T0 = datetime(2026, 10, 12, 17, 0)


def _run(check, start, minutes, temps, *, heating=True, alert=60, step=1):
    """Tick once a minute; temps(i) gives the reading at minute i. Returns events."""
    events = []
    for i in range(0, minutes + 1, step):
        ev = update_heat_check(
            check,
            heating=heating,
            current_temp=temps(i),
            alert_minutes=alert,
            now=start + timedelta(minutes=i),
        )
        if ev:
            events.append((i, ev))
    return events


def test_boiler_not_firing_raises_one_alert():
    """12 Oct: runs of 31 + 31 + 17 min, house drifting 17.8→18.2 (sensor noise)."""
    check = HeatCheck()
    events = _run(check, T0, 31, lambda i: 17.8 if i < 20 else 17.9)
    events += _run(check, T0 + timedelta(minutes=32), 40, lambda i: 18.0, heating=False)
    assert events == []
    events = _run(check, T0 + timedelta(hours=3), 31, lambda i: 18.1 if i % 2 else 18.2)
    assert [e for _, e in events] == ["fault"]
    assert check.fault_since is not None
    # Still not warming: no repeat alert.
    events = _run(check, T0 + timedelta(hours=4), 30, lambda i: 18.2)
    assert events == []


def test_healthy_heating_never_alerts():
    check = HeatCheck()
    # 2 h of boiler at a slow 0.5 °C/h still clears the check every ~40 min.
    events = _run(check, T0, 120, lambda i: 17.0 + i / 120)
    assert events == []
    assert check.on_minutes < 60


def test_warming_after_a_fault_reports_recovered():
    check = HeatCheck()
    events = _run(check, T0, 61, lambda i: 18.0)
    assert [e for _, e in events] == ["fault"]
    events = _run(check, T0 + timedelta(minutes=62), 20, lambda i: 18.0 + i * 0.05)
    assert [e for _, e in events] == ["recovered"]
    assert check.fault_since is None
    assert check.on_minutes < 20


def test_passive_warming_long_after_a_run_is_not_credited():
    check = HeatCheck()
    _run(check, T0, 30, lambda i: 17.8)
    # Sun warms the house an hour after the boiler stopped.
    _run(check, T0 + timedelta(minutes=31), 90, lambda i: 17.8 + (0.5 if i > 45 else 0), heating=False)
    assert check.total_rise() == 0.0
    events = _run(check, T0 + timedelta(hours=2), 30, lambda i: 18.3)
    assert [e for _, e in events] == ["fault"]


def test_radiator_coast_is_credited():
    check = HeatCheck()
    _run(check, T0, 15, lambda i: 18.0)
    # Boiler off; radiators keep warming the room for the next 20 minutes.
    events = _run(check, T0 + timedelta(minutes=16), 20, lambda i: 18.0 + i * 0.03, heating=False)
    assert events == []
    assert check.on_minutes == 0.0  # cleared: the run did warm the house


def test_idle_hours_reset_the_tally_but_keep_a_fault():
    check = HeatCheck()
    _run(check, T0, 40, lambda i: 18.0)
    _run(check, T0 + timedelta(minutes=41), 7 * 60, lambda i: 18.0, heating=False, step=5)
    assert check.on_minutes == 0.0
    assert check.fault_since is None

    check = HeatCheck()
    _run(check, T0, 61, lambda i: 18.0)
    _run(check, T0 + timedelta(minutes=62), 7 * 60, lambda i: 18.0, heating=False, step=5)
    assert check.on_minutes == 0.0
    assert check.fault_since is not None  # no warming seen yet → still flagged
    # 18 Oct: the banner then read "called for 0 min … warmed 0.0°C".
    assert check.fault_on_minutes >= 60


def test_fault_shows_the_whole_failed_run():
    check = HeatCheck()
    _run(check, T0, 200, lambda i: 17.5 + (0.1 if i > 100 else 0), step=5)
    assert check.fault_since is not None
    assert check.fault_on_minutes == 200
    assert check.fault_rise_c == pytest.approx(0.0)  # one sensor step isn't warming


def test_reaching_the_target_clears_a_standing_fault():
    """18 Oct: preheat to 20 failed (TRVs shut); the house later reached 21 with
    no heat call, and the alert stayed up all day."""
    check = HeatCheck()

    def run(start, minutes, temp, *, heating, target):
        return [
            ev
            for i in range(0, minutes + 1, 5)
            if (ev := update_heat_check(
                check, heating=heating, current_temp=temp, alert_minutes=60,
                target=target, now=start + timedelta(minutes=i),
            ))
        ]

    assert run(T0, 65, 17.8, heating=True, target=20.0) == ["fault"]
    # Eco evening at 16: 18 °C beats that, but the heating still never made 20.
    assert run(T0 + timedelta(minutes=70), 7 * 60, 18.0, heating=False, target=16.0) == []
    assert check.fault_since is not None
    # Next day the house gets to 20 by itself.
    assert run(T0 + timedelta(hours=9), 10, 20.0, heating=False, target=16.0) == ["recovered"]
    assert check.fault_since is None and check.fault_on_minutes == 0.0


def test_old_saved_fault_uses_the_current_target():
    check = HeatCheck(fault_since=T0.isoformat(), last_tick=T0.isoformat())
    events = [update_heat_check(
        check, heating=False, current_temp=21.0, alert_minutes=60, target=16.0,
        now=T0 + timedelta(minutes=1),
    )]
    assert events == ["recovered"]


def test_alert_disabled_and_missing_sensor():
    check = HeatCheck()
    assert _run(check, T0, 120, lambda i: 18.0, alert=0) == []
    check = HeatCheck()
    assert _run(check, T0, 120, lambda i: None) == []
    assert check.on_minutes == 0.0


def test_big_gap_between_ticks_is_capped():
    check = HeatCheck()
    update_heat_check(check, heating=True, current_temp=18.0, alert_minutes=60, now=T0)
    # HA was down for two hours mid-run: that isn't two hours of boiler time.
    update_heat_check(check, heating=True, current_temp=18.0, alert_minutes=60, now=T0 + timedelta(hours=2))
    assert check.on_minutes == 5.0


def test_heat_check_persists():
    state = IntelligenceState()
    _run(state.heat_check, T0, 61, lambda i: 18.0)
    restored = IntelligenceState.from_dict(state.to_dict())
    assert restored.heat_check == state.heat_check
    assert IntelligenceState.from_dict({"heat_check": {"bogus": 1}}).heat_check == HeatCheck()


def test_warmup_ignores_cycles_that_say_nothing():
    model = WarmupModel()
    # Too short, too small a rise, or slower than any working house: skipped.
    for start, end, minutes in ((18.0, 18.5, 10), (18.0, 18.2, 60), (17.8, 18.1, 120)):
        assert update_warmup_from_cycle(model, start_temp=start, end_temp=end, duration_minutes=minutes) == model


def test_warmup_first_cycle_blends_with_default():
    model = update_warmup_from_cycle(WarmupModel(), start_temp=18.0, end_temp=20.0, duration_minutes=30)
    # Observed 4 °C/h; one cycle moves the estimate, it doesn't replace it.
    assert DEFAULT_WARMUP_C_PER_HOUR < model.c_per_hour < 4.0
    assert model.samples == 1


# --- the real coordinator ---------------------------------------------------


async def _minutes(hass, coord, freezer, start, minutes, temp):
    for i in range(0, minutes + 1, 5):
        freezer.move_to(start + timedelta(minutes=i))
        hass.states.async_set("sensor.house", str(temp(i) if callable(temp) else temp))
        data = await _tick(hass, coord)
    return data


@pytest.fixture
def phone(hass):
    sent = []

    async def record(call):
        sent.append(dict(call.data))

    hass.services.async_register("notify", "mobile_app_test", record)
    return sent


async def test_coordinator_alerts_and_recovers(hass, setup, phone, freezer):
    coord, _ = setup
    await coord.async_save_config({"alert_notify": ["notify.mobile_app_test"]})
    assert coord.config.alert_notify == ["mobile_app_test"]
    start = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")

    data = await _minutes(hass, coord, freezer, start, 55, 18.0)
    assert data["boiler_on"] is True
    assert data["heating_fault"] is None
    data = await _minutes(hass, coord, freezer, start + timedelta(minutes=60), 5, 18.0)
    assert data["heating_fault"]["on_minutes"] >= 60
    assert len(phone) == 1 and "isn't warming" in phone[0]["title"]
    notes = hass.data["persistent_notification"]
    assert any("not_warming" in key for key in notes)
    # Learning nothing from the broken run.
    hass.states.async_set("sensor.house", "21.0")
    await _tick(hass, coord)
    assert coord.intel.state.warmup.samples == 0

    # Boiler fixed: the house warms on the next run.
    hass.states.async_set("sensor.house", "18.0")
    data = await _minutes(
        hass, coord, freezer, start + timedelta(minutes=70), 20, lambda i: 18.0 + i * 0.03
    )
    assert data["heating_fault"] is None
    assert len(phone) == 2 and "working again" in phone[1]["title"]
    assert not any("not_warming" in key for key in hass.data["persistent_notification"])


async def test_alert_names_offline_and_closed_trvs(hass, setup, phone, freezer):
    coord, _ = setup
    await coord.async_save_config({"alert_notify": ["notify.mobile_app_test"]})
    start = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")

    # The lounge TRV is offline: that's the cause, not the boiler.
    hass.states.async_set("climate.trv_lounge", "unavailable")
    data = await _minutes(hass, coord, freezer, start, 65, 18.0)
    fault = data["heating_fault"]
    assert fault["trvs_offline"] == ["Lounge"] and fault["trvs_closed"] == []
    assert "Lounge TRV is offline" in phone[0]["message"]
    assert "boiler is firing" not in phone[0]["message"]

    # Back online but its own sensor reads the set point: valve shut.
    hass.states.async_set(
        "climate.trv_lounge", "heat",
        {"temperature": 20, "current_temperature": 20.5, "hvac_action": "idle"},
    )
    data = await _minutes(hass, coord, freezer, start + timedelta(minutes=70), 5, 18.0)
    assert data["heating_fault"]["trvs_offline"] == []
    assert data["heating_fault"]["trvs_closed"] == ["Lounge"]

    # An open valve means the TRVs aren't the problem.
    hass.states.async_set(
        "climate.trv_lounge", "heat",
        {"temperature": 20, "current_temperature": 18.0, "hvac_action": "heating"},
    )
    data = await _minutes(hass, coord, freezer, start + timedelta(minutes=80), 5, 18.0)
    assert data["heating_fault"]["trvs_closed"] == []
    assert "boiler is firing" in coord._not_warming_cause(coord.intel.state.heat_check)  # noqa: SLF001


async def test_rooms_alone_do_not_count(hass, setup, freezer):
    coord, _ = setup
    start = datetime.fromisoformat(f"{MONDAY}T16:10:00+01:00")
    # House is warm; only the lounge TRV (18 < 20) wants heat.
    data = await _minutes(hass, coord, freezer, start, 90, 21.0)
    assert data["boiler_on"] is True
    assert coord.intel.state.heat_check.on_minutes == 0.0
    assert data["heating_fault"] is None


async def test_reset_warmup(hass, setup):
    coord, _ = setup
    coord.intel.state.warmup = WarmupModel(c_per_hour=0.4, samples=1)
    await coord.async_reset_warmup()
    assert coord.intel.state.warmup == WarmupModel()
