"""Room demand on the boiler (needs HA test venv). Both seen live on 21 Oct 2026:

- the hall room uses the house sensor, but called on to target + 0.3 after the
  house (True Radiant) had stopped, so coast took the hall past 20.5;
- the kitchen's sensor read 19.4 while its TRV read 21 and had shut its valve,
  so the boiler ran on for the kitchen and the heat went to the upstairs radiators.
"""

from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook.coordinator import (  # noqa: E402
    NookCoordinator,
)

START = "2026-10-21 15:00:00+01:00"
TRV = "climate.trv_room"


@pytest.fixture
async def setup(hass, monkeypatch, freezer):
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(START)
    monkeypatch.setattr(
        "custom_components.nook.coordinator.boiler_cycle_guard",
        lambda want_on, is_on, seconds, **_kw: (want_on, 0.0),
    )

    async def climate(call):
        old = hass.states.get(call.data["entity_id"])
        attrs = dict(old.attributes)
        if call.service == "set_temperature":
            attrs["temperature"] = call.data["temperature"]
        hass.states.async_set(call.data["entity_id"], old.state, attrs)

    async def switch(call):
        hass.states.async_set(call.data["entity_id"], "on" if call.service == "turn_on" else "off")

    for service in ("set_temperature", "set_hvac_mode"):
        hass.services.async_register("climate", service, climate)
    for service in ("turn_on", "turn_off"):
        hass.services.async_register("switch", service, switch)
    hass.states.async_set("switch.boiler", "off")

    coords = []

    async def make(room_sensor):
        entry = MockConfigEntry(
            domain="nook",
            data={"heater": "switch.boiler", "temperature_sensor": "sensor.house"},
            options={
                "true_radiant": True,
                "schedule_enabled": False,
                "target_temp": 20,
                "rooms": [{
                    "id": "room", "name": "Room", "trv_entity": TRV, "target_temp": 20,
                    "temperature_sensor": room_sensor,
                }],
            },
        )
        entry.add_to_hass(hass)
        coord = NookCoordinator(hass, entry)
        await coord.async_initialize_intelligence()
        coords.append(coord)
        return coord

    yield make
    for coord in coords:
        await coord.async_unload()
        await coord.async_shutdown()


async def _tick(hass, coord, freezer):
    await coord._async_update_data()  # noqa: SLF001
    await hass.async_block_till_done(wait_background_tasks=True)
    freezer.tick(timedelta(seconds=30))


def _trv(hass, action):
    hass.states.async_set(TRV, "heat", {"temperature": 20.0, "current_temperature": 19.0, "hvac_action": action})


async def test_room_with_the_house_sensor_stops_with_the_house(hass, setup, freezer):
    coord = await setup("sensor.house")
    coast = coord.intel.state.warmup.coast_c
    _trv(hass, "heating")
    hass.states.async_set("sensor.house", "19.5")
    await _tick(hass, coord, freezer)
    assert hass.states.get("switch.boiler").state == "on"
    # Past the house's True Radiant cut-off, short of target + 0.3.
    hass.states.async_set("sensor.house", f"{20.3 - coast / 2:.2f}")
    await _tick(hass, coord, freezer)
    assert hass.states.get("switch.boiler").state == "off"


async def test_room_with_its_own_sensor_keeps_its_band(hass, setup, freezer):
    coord = await setup("sensor.room")
    _trv(hass, "heating")
    hass.states.async_set("sensor.house", "21.0")
    hass.states.async_set("sensor.room", "19.5")
    await _tick(hass, coord, freezer)
    assert hass.states.get("switch.boiler").state == "on"
    hass.states.async_set("sensor.room", "20.2")  # still under 20 + 0.3
    await _tick(hass, coord, freezer)
    assert hass.states.get("switch.boiler").state == "on"


async def test_room_with_a_shut_valve_does_not_run_the_boiler(hass, setup, freezer):
    coord = await setup("sensor.room")
    hass.states.async_set("sensor.house", "21.0")  # house satisfied
    hass.states.async_set("sensor.room", "19.4")  # room sensor says cold…
    _trv(hass, "idle")  # …but its TRV has shut
    await _tick(hass, coord, freezer)
    assert coord._room_states["room"]["needs_heat"]  # noqa: SLF001 — still wants heat
    assert hass.states.get("switch.boiler").state == "off"
    _trv(hass, "heating")  # valve opens (e.g. calibrated): now the boiler serves it
    await _tick(hass, coord, freezer)
    assert hass.states.get("switch.boiler").state == "on"


async def test_trv_without_valve_state_still_counts(hass, setup, freezer):
    coord = await setup("sensor.room")
    hass.states.async_set("sensor.house", "21.0")
    hass.states.async_set("sensor.room", "19.4")
    hass.states.async_set(TRV, "heat", {"temperature": 20.0, "current_temperature": 19.0})
    await _tick(hass, coord, freezer)
    assert hass.states.get("switch.boiler").state == "on"
