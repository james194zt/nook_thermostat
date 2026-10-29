"""Preheat is timed for the room that needs longest, not just the house sensor.

27 Oct 2026 live: the hall (house sensor) was 19.6 at 07:10, so a 19-minute
preheat for 07:30; the living room was 18.6 and only reached 20 at 08:00.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.nook.intelligence import PreheatRoom, WarmupModel, preheat_status
from custom_components.nook.models import default_schedule

THU_0600 = datetime(2026, 10, 22, 6, 0)  # local time; block thu 06:30 at 20 °C
HOUSE = WarmupModel(c_per_hour=1.558, samples=14)


def _status(now=THU_0600, house=19.6, rooms=None):
    return preheat_status(
        default_schedule(),
        schedule_enabled=True,
        true_radiant=True,
        current_temp=house,
        warmup=HOUSE,
        outdoor_temp=None,
        away_eco_active=False,
        max_minutes=240,
        now=now,
        rooms=rooms,
    )


def test_house_alone_gives_a_short_preheat():
    status = _status()
    assert status["preheat_minutes"] == 20  # 0.4 °C at 1.558 °C/h + 5
    assert status["preheat_room"] is None


def test_colder_room_starts_it_earlier():
    status = _status(rooms=[PreheatRoom(name="Living Room", current_temp=18.6)])
    # 1.4 °C at the house rate (no room rate learned yet): 53 + 5 minutes.
    assert status["preheat_minutes"] == 58
    assert status["preheat_start"] == "05:32"
    assert status["preheat_room"] == "Living Room"
    assert status["preheating"] is True


def test_room_already_warm_leaves_the_house_timing():
    status = _status(rooms=[PreheatRoom(name="Kitchen", current_temp=20.0)])
    assert status["preheat_minutes"] == 20
    assert status["preheat_room"] is None


def test_room_learned_rate_used_once_it_has_runs():
    slow = PreheatRoom(name="Living Room", current_temp=18.6, warmup=WarmupModel(c_per_hour=1.0, samples=2))
    assert _status(rooms=[slow])["preheat_minutes"] == 88  # 1.4 °C (1.3999…) at 1.0 °C/h + 5
    one_run = PreheatRoom(name="Living Room", current_temp=18.6, warmup=WarmupModel(c_per_hour=1.0, samples=1))
    assert _status(rooms=[one_run])["preheat_minutes"] == 58  # still the house rate


def test_room_targets_follow_the_house_offset_or_their_own():
    cooler = PreheatRoom(name="Bedroom", current_temp=18.6, house_offset=-1.0)
    assert _status(rooms=[cooler])["preheat_room"] is None  # 19.0 is 0.4 away: house timing
    own = PreheatRoom(name="Study", current_temp=18.6, house_offset=None, target_temp=21.0)
    assert _status(rooms=[own])["preheat_minutes"] == 97  # 2.4 °C at 1.558 + 5


def test_rooms_dont_start_a_preheat_when_nothing_is_short():
    assert _status(house=20.0, rooms=[PreheatRoom(name="Kitchen", current_temp=19.9)]) is None


def test_room_model_is_not_changed_by_the_estimate():
    model = WarmupModel(c_per_hour=1.2, samples=3)
    _status(rooms=[PreheatRoom(name="Living Room", current_temp=18.6, warmup=model)])
    assert model.last_outdoor is None and model.c_per_hour == 1.2


pytest.importorskip("pytest_homeassistant_custom_component")

from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook.coordinator import NookCoordinator  # noqa: E402

TRV = "climate.trv_lr"


@pytest.fixture
async def coord(hass, monkeypatch, freezer):
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to("2026-10-22 05:20:00+01:00")  # thu, block 06:30
    monkeypatch.setattr(
        "custom_components.nook.coordinator.boiler_cycle_guard",
        lambda want_on, is_on, seconds, **_kw: (want_on, 0.0),
    )

    async def switch(call):
        hass.states.async_set(call.data["entity_id"], "on" if call.service == "turn_on" else "off")

    async def climate(call):
        old = hass.states.get(call.data["entity_id"])
        attrs = dict(old.attributes)
        if call.service == "set_temperature":
            attrs["temperature"] = call.data["temperature"]
        hass.states.async_set(call.data["entity_id"], old.state, attrs)

    for service in ("turn_on", "turn_off"):
        hass.services.async_register("switch", service, switch)
    for service in ("set_temperature", "set_hvac_mode"):
        hass.services.async_register("climate", service, climate)
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set("sensor.house", "19.6")
    hass.states.async_set("sensor.lr", "18.6")
    hass.states.async_set("binary_sensor.lr_window", "off")
    hass.states.async_set(TRV, "heat", {"temperature": 16.0, "current_temperature": 18.0, "hvac_action": "heating"})
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.house"},
        options={
            "true_radiant": True,
            "schedule_enabled": True,
            "eco_temp": 16,
            "rooms": [
                {"id": "living_room", "name": "Living Room", "trv_entity": TRV,
                 "temperature_sensor": "sensor.lr", "window_sensors": ["binary_sensor.lr_window"]},
                {"id": "hall", "name": "Hall", "trv_entity": "climate.trv_hall",
                 "temperature_sensor": "sensor.house"},
            ],
        },
    )
    entry.add_to_hass(hass)
    c = NookCoordinator(hass, entry)
    await c.async_initialize_intelligence()
    c.intel.state.warmup.c_per_hour = 1.558
    yield c
    await c.async_unload()
    await c.async_shutdown()


async def _tick(hass, coord):
    await coord._async_update_data()  # noqa: SLF001
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_living_room_starts_the_preheat(hass, coord):
    # 05:20: the hall alone would wait until 06:10; the living room needs 58 min → 05:32.
    await _tick(hass, coord)
    assert coord._preheat["preheating"] is False  # noqa: SLF001
    assert coord._preheat["preheat_room"] == "Living Room"  # noqa: SLF001
    assert [r.name for r in coord._preheat_rooms()] == ["Living Room"]  # noqa: SLF001


async def test_settling_limit_follows_a_fast_room(hass, coord):
    assert coord._settling_limit("living_room") == 6.0  # noqa: SLF001  nothing learned
    coord.intel.state.room_warmup["living_room"] = WarmupModel(c_per_hour=3.2, samples=1)
    assert coord._settling_limit("living_room") == 6.0  # noqa: SLF001  one run isn't enough
    coord.intel.state.room_warmup["living_room"] = WarmupModel(c_per_hour=3.2, samples=2)
    assert coord._settling_limit("living_room") == pytest.approx(8.0)  # noqa: SLF001
    coord.intel.state.room_warmup["living_room"] = WarmupModel(c_per_hour=1.2, samples=5)
    assert coord._settling_limit("living_room") == 6.0  # noqa: SLF001  never below the floor


async def test_open_window_room_is_left_out(hass, coord, freezer):
    hass.states.async_set("binary_sensor.lr_window", "on")
    freezer.tick(timedelta(minutes=coord.config.window_open_delay_minutes + 1))
    assert coord._preheat_rooms() == []  # noqa: SLF001


async def test_room_learns_its_warm_up_rate(hass, coord, freezer):
    freezer.move_to("2026-10-22 05:40:00+01:00")
    await _tick(hass, coord)
    assert hass.states.get("switch.boiler").state == "on"
    assert coord.intel.state.room_runs["living_room"]["start_temp"] == 18.6
    assert "hall" not in coord.intel.state.room_runs  # the house sensor's room: house rate
    for minute, temp in ((20, "19.2"), (40, "19.8"), (50, "20.4")):
        freezer.move_to(f"2026-10-22 06:{minute:02d}:00+01:00")
        hass.states.async_set("sensor.lr", temp)
        hass.states.async_set("sensor.house", "20.4")
        await _tick(hass, coord)
    assert "living_room" not in coord.intel.state.room_runs
    learned = coord.intel.state.room_warmup["living_room"]
    assert learned.samples == 1
    # Rose 0.2 by the 06:20 reading (40 min in), then 1.6 °C in the last 30 min
    # = 3.2 °C/h, blended into the 1.5 default at the first weight.
    assert learned.c_per_hour == pytest.approx(1.5 * 0.65 + 3.2 * 0.35, abs=0.002)
    assert learned.lag_samples == 1
    assert learned.lag_minutes == pytest.approx(5 * 0.65 + 40 * 0.35, abs=0.06)
    # The house run learned its dead time the same way.
    assert coord.intel.state.warmup.lag_samples == 1
    assert coord.room_warmup_info()["living_room"]["samples"] == 1
    # It is kept across restarts.
    data = coord.intel.state.to_dict()
    assert data["room_warmup"]["living_room"]["samples"] == 1
