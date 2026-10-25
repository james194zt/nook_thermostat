"""Preheat keeps going once it has started (22 Oct 2026 live: five boiler starts in
one morning — each time the warmer house made the re-estimate say "too early")."""

from datetime import datetime, timedelta

import pytest

from custom_components.nook.intelligence import WarmupModel, preheat_status
from custom_components.nook.models import default_schedule

THU_0447 = datetime(2026, 10, 22, 4, 47)  # local time; block thu 06:30 at 20 °C


def _status(now, current, started=None):
    return preheat_status(
        default_schedule(),
        schedule_enabled=True,
        true_radiant=True,
        current_temp=current,
        warmup=WarmupModel(c_per_hour=1.337),
        outdoor_temp=None,
        away_eco_active=False,
        now=now,
        started_block=started,
    )


def test_warmer_house_says_too_early_without_the_latch():
    # 17.9 °C needs ~99 min: start 04:51, so at 04:47 the old answer was "not yet".
    assert _status(THU_0447, 17.9)["preheating"] is False


def test_started_preheat_carries_on():
    status = _status(THU_0447, 17.9, started="thu|06:30")
    assert status["preheating"] is True
    assert status["temperature"] == 20.0


def test_started_preheat_carries_on_close_to_target():
    # Within 0.2 °C the estimate is 0 minutes (no preheat at all before).
    assert _status(THU_0447, 19.9) is None
    assert _status(THU_0447, 19.9, started="thu|06:30")["preheating"] is True


def test_last_weeks_marker_does_not_start_a_preheat():
    # Same block key, but a whole day early: far outside the longest preheat.
    wed_0447 = THU_0447 - timedelta(days=1) + timedelta(hours=2)  # wed 06:47 → next is thu 06:30
    assert _status(wed_0447, 17.9, started="thu|06:30") is None or not _status(
        wed_0447, 17.9, started="thu|06:30"
    )["preheating"]


pytest.importorskip("pytest_homeassistant_custom_component")

from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook.coordinator import NookCoordinator  # noqa: E402


async def test_boiler_runs_on_through_the_preheat(hass, monkeypatch, freezer):
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to("2026-10-22 04:45:00+01:00")
    monkeypatch.setattr(
        "custom_components.nook.coordinator.boiler_cycle_guard",
        lambda want_on, is_on, seconds, **_kw: (want_on, 0.0),
    )

    async def switch(call):
        hass.states.async_set(call.data["entity_id"], "on" if call.service == "turn_on" else "off")

    for service in ("turn_on", "turn_off"):
        hass.services.async_register("switch", service, switch)
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set("sensor.house", "17.4")
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.house"},
        options={"true_radiant": True, "schedule_enabled": True, "eco_temp": 16},
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    try:
        coord.intel.state.warmup.c_per_hour = 1.337
        await coord._async_update_data()  # noqa: SLF001
        await hass.async_block_till_done()
        assert hass.states.get("switch.boiler").state == "on"
        assert coord.intel.state.control["preheat_started"] == "thu|06:30"
        freezer.tick(timedelta(minutes=2))
        hass.states.async_set("sensor.house", "17.9")  # "too early" by the old sum
        await coord._async_update_data()  # noqa: SLF001
        await hass.async_block_till_done()
        assert coord.effective_main_target()[0] == 20.0
        assert hass.states.get("switch.boiler").state == "on"
    finally:
        await coord.async_unload()
        await coord.async_shutdown()
