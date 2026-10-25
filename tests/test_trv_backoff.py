"""TRV commands: one at a time per TRV, back-off when it doesn't answer (needs HA test venv).

17 Oct 2026: two TRVs stopped answering and Nook sent set_temperature every
30 s tick; 21 were still queued at ZHA when HA stopped, and ZHA hung on start.
"""

import asyncio
from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import CoreState  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook.coordinator import (  # noqa: E402
    NookCoordinator,
)

START = "2026-10-17 12:00:00+01:00"
TRV = "climate.trv_lounge"


@pytest.fixture
async def setup(hass, monkeypatch, freezer):
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(START)
    monkeypatch.setattr(
        "custom_components.nook.coordinator.boiler_cycle_guard",
        lambda want_on, is_on, seconds, **_kw: (want_on, 0.0),
    )
    trv = {"mode": "ok", "calls": [], "release": asyncio.Event()}

    async def climate(call):
        trv["calls"].append((call.service, {k: v for k, v in call.data.items() if k != "entity_id"}))
        if trv["mode"] == "dead":
            raise HomeAssistantError("Failed to send request: device did not respond")
        if trv["mode"] == "slow":
            await trv["release"].wait()
        if trv["mode"] == "clamp":
            return  # accepted, but the TRV keeps its own setpoint
        old = hass.states.get(call.data["entity_id"])
        attrs = dict(old.attributes)
        state = old.state
        if call.service == "set_temperature":
            attrs["temperature"] = call.data["temperature"]
        else:
            state = call.data["hvac_mode"]
        hass.states.async_set(call.data["entity_id"], state, attrs)

    async def switch(call):
        hass.states.async_set(call.data["entity_id"], "on" if call.service == "turn_on" else "off")

    for service in ("set_temperature", "set_hvac_mode"):
        hass.services.async_register("climate", service, climate)
    for service in ("turn_on", "turn_off"):
        hass.services.async_register("switch", service, switch)
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set("sensor.house", "18.0")
    hass.states.async_set(TRV, "heat", {"temperature": 14, "current_temperature": 18})
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.house"},
        options={
            "true_radiant": False,
            "schedule_enabled": False,
            "target_temp": 20,
            "rooms": [{"id": "lounge", "name": "Lounge", "trv_entity": TRV, "target_temp": 20}],
        },
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    yield coord, trv
    trv["release"].set()
    await coord.async_unload()
    await coord.async_shutdown()


async def _ticks(hass, coord, freezer, count, every=timedelta(seconds=30)):
    for _ in range(count):
        await coord._async_update_data()  # noqa: SLF001
        await hass.async_block_till_done(wait_background_tasks=True)
        freezer.tick(every)


async def test_dead_trv_is_not_sent_a_command_every_tick(hass, setup, freezer):
    coord, trv = setup
    trv["mode"] = "dead"
    await _ticks(hass, coord, freezer, 10)  # 5 minutes of ticks
    # 12:00 first try, 12:01 after 1 min, 12:03 after 2 more; next due 12:07.
    assert [c[0] for c in trv["calls"]] == ["set_temperature"] * 3
    await _ticks(hass, coord, freezer, 1, every=timedelta(minutes=40))
    await _ticks(hass, coord, freezer, 1)
    assert len(trv["calls"]) == 4


async def test_trv_answering_again_gets_its_setpoint(hass, setup, freezer):
    coord, trv = setup
    trv["mode"] = "dead"
    await _ticks(hass, coord, freezer, 1)
    trv["mode"] = "ok"
    await _ticks(hass, coord, freezer, 1, every=timedelta(minutes=1))
    await _ticks(hass, coord, freezer, 1)
    assert hass.states.get(TRV).attributes["temperature"] == 20.0
    assert coord._trv_retry == {}  # noqa: SLF001
    calls = len(trv["calls"])
    await _ticks(hass, coord, freezer, 5)
    assert len(trv["calls"]) == calls  # in step: nothing more to send


async def test_only_one_command_in_flight_per_trv(hass, setup, freezer):
    coord, trv = setup
    trv["mode"] = "slow"
    for _ in range(6):  # 3 minutes while the TRV is still working on the first
        await coord._async_update_data()  # noqa: SLF001
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=30))
    assert len(trv["calls"]) == 1
    trv["mode"] = "ok"
    trv["release"].set()
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_clamping_trv_is_not_resent_every_tick(hass, setup, freezer):
    coord, trv = setup
    trv["mode"] = "clamp"
    await _ticks(hass, coord, freezer, 19)  # 9.5 minutes
    assert len(trv["calls"]) == 1
    await _ticks(hass, coord, freezer, 2)
    assert len(trv["calls"]) == 2  # tried again after 10 min


async def test_trv_turned_by_hand_is_put_back_at_once(hass, setup, freezer):
    coord, trv = setup
    await _ticks(hass, coord, freezer, 1)
    assert hass.states.get(TRV).attributes["temperature"] == 20.0
    hass.states.async_set(TRV, "heat", {"temperature": 25, "current_temperature": 18})
    await _ticks(hass, coord, freezer, 1)
    assert hass.states.get(TRV).attributes["temperature"] == 20.0
    assert trv["calls"] == [("set_temperature", {"temperature": 20.0})] * 2


async def test_nothing_sent_to_trvs_while_ha_stops(hass, setup, freezer):
    coord, trv = setup
    hass.set_state(CoreState.stopping)
    try:
        await _ticks(hass, coord, freezer, 3)
    finally:
        hass.set_state(CoreState.running)
    assert trv["calls"] == []
