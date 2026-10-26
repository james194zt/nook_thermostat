"""TRV calibration: the TRV's own offset follows "room sensor − TRV" (needs HA test venv).

21 Oct 2026: the hall TRV read 21.3 °C beside its hot radiator and shut, while the
room sensor next to it read 19 — the boiler ran on with only upstairs radiators open.
"""

from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook.coordinator import (  # noqa: E402
    NookCoordinator,
)

START = "2026-10-21 06:00:00+01:00"
TRV = "climate.trv_hall"
OFFSET = "number.trv_hall_local_temperature_offset"
ROOM_SENSOR = "sensor.hall"


@pytest.fixture
async def setup(hass, monkeypatch, freezer):
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(START)
    monkeypatch.setattr(
        "custom_components.nook.coordinator.boiler_cycle_guard",
        lambda want_on, is_on, seconds, **_kw: (want_on, 0.0),
    )
    zha = MockConfigEntry(domain="zha")
    zha.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha.entry_id, identifiers={("zha", "trv-hall")}
    )
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("climate", "zha", "trv-hall", suggested_object_id="trv_hall", device_id=device.id)
    ent_reg.async_get_or_create(
        "number", "zha", "trv-hall-offset",
        suggested_object_id="trv_hall_local_temperature_offset",
        device_id=device.id,
        translation_key="local_temperature_offset",
    )
    ent_reg.async_get_or_create(
        "number", "zha", "trv-hall-max", suggested_object_id="trv_hall_max_heat_setpoint_limit", device_id=device.id
    )

    # The TRV's raw reading (beside the radiator); what it reports includes its offset.
    trv = {"raw": 21.3, "writes": [], "setpoints": [], "setpoint": 20.0}

    def report():
        offset = float(hass.states.get(OFFSET).state)
        hass.states.async_set(TRV, "heat", {
            "temperature": trv["setpoint"], "target_temp_step": 0.5,
            "current_temperature": round(trv["raw"] + offset, 1),
        })

    async def set_value(call):
        trv["writes"].append(call.data["value"])
        hass.states.async_set(OFFSET, str(call.data["value"]), {"min": -2.5, "max": 2.5, "step": 0.1})

    async def set_temperature(call):
        trv["setpoint"] = call.data["temperature"]
        trv["setpoints"].append(call.data["temperature"])
        report()

    async def noop(call):
        return

    hass.services.async_register("number", "set_value", set_value)
    hass.services.async_register("climate", "set_temperature", set_temperature)
    hass.services.async_register("climate", "set_hvac_mode", noop)
    for service in ("turn_on", "turn_off"):
        hass.services.async_register("switch", service, noop)
    hass.states.async_set("switch.boiler", "on")
    hass.states.async_set("sensor.house", "19.0")
    hass.states.async_set(ROOM_SENSOR, "19.0")
    hass.states.async_set(OFFSET, "0.0", {"min": -2.5, "max": 2.5, "step": 0.1})
    hass.states.async_set("number.trv_hall_max_heat_setpoint_limit", "30.0")
    report()
    trv["report"] = report

    entries = []

    async def make(calibrate=True, sensor=ROOM_SENSOR):
        entry = MockConfigEntry(
            domain="nook",
            data={"heater": "switch.boiler", "temperature_sensor": "sensor.house"},
            options={
                "true_radiant": False,
                "schedule_enabled": False,
                "target_temp": 20,
                "rooms": [{
                    "id": "hall", "name": "Hall", "trv_entity": TRV, "target_temp": 20,
                    "temperature_sensor": sensor, "calibrate_trv": calibrate,
                }],
            },
        )
        entry.add_to_hass(hass)
        coord = NookCoordinator(hass, entry)
        await coord.async_initialize_intelligence()
        entries.append(coord)
        return coord

    yield make, trv
    for coord in entries:
        await coord.async_unload()
        await coord.async_shutdown()


async def _tick(hass, coord, freezer, every=timedelta(minutes=1)):
    freezer.tick(every)
    await coord._async_update_data()  # noqa: SLF001
    await hass.async_block_till_done(wait_background_tasks=True)


async def _run(hass, coord, freezer, minutes):
    """A tick every minute (the room-sensor settling check needs a 15-min window)."""
    for _ in range(minutes):
        await _tick(hass, coord, freezer)


async def test_finds_the_offset_setting_on_the_trv_device(hass, setup):
    make, _ = setup
    coord = await make()
    assert coord.trv_offset_entity(TRV) == OFFSET


async def test_hall_trv_gets_room_sensor_offset(hass, setup, freezer):
    make, trv = setup
    coord = await make()
    await _run(hass, coord, freezer, 14)  # no 15-min view of the room sensor yet
    assert trv["writes"] == []
    await _run(hass, coord, freezer, 3)  # the setpoint margin goes first, the offset next tick
    assert trv["writes"] == [-2.3]


async def test_off_by_default_and_needs_a_room_sensor(hass, setup, freezer):
    make, trv = setup
    for coord in (await make(calibrate=False), await make(sensor="")):
        await _run(hass, coord, freezer, 20)
    assert trv["writes"] == []


async def test_waits_for_a_trv_reading_with_the_new_offset(hass, setup, freezer):
    make, trv = setup
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["writes"] == [-2.3]
    # The TRV hasn't reported since: its 21.3 was taken with the old offset.
    await _run(hass, coord, freezer, 20)
    assert trv["writes"] == [-2.3]
    trv["report"]()  # now it shows 19.0 = the room
    await _run(hass, coord, freezer, 20)
    assert trv["writes"] == [-2.3]
    # Room past its cut-out (20 + 0.3); radiator cooled: the TRV shows 18.2 with the room at 20.4.
    hass.states.async_set(ROOM_SENSOR, "20.4")
    trv["raw"] = 20.5
    trv["report"]()
    await _run(hass, coord, freezer, 17)
    assert trv["writes"] == [-2.3, -0.1]


async def test_offset_only_moves_down_while_the_room_warms_up(hass, setup, freezer):
    """21 Oct live: with the radiator cool the hall TRV over-read only ~0.5 °C, so
    easing the offset back mid warm-up would shut the valve once the radiator got hot."""
    make, trv = setup
    trv["raw"] = 20.5
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    trv["report"]()
    assert trv["writes"] == [-1.5]
    trv["raw"] = 19.5  # radiator cool: TRV now shows 18.0, room 19.0, target 20
    trv["report"]()
    await _run(hass, coord, freezer, 30)
    assert trv["writes"] == [-1.5]  # not eased back while the room needs heat
    trv["raw"] = 21.5  # radiator hot: shows 20.0 with the room at 19.0 → down again
    trv["report"]()
    await _run(hass, coord, freezer, 1)
    assert trv["writes"] == [-1.5, -2.5]


async def test_downward_corrections_come_quicker_while_warming(hass, setup, freezer):
    make, trv = setup
    trv["raw"] = 20.5
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["writes"] == [-1.5]
    trv["report"]()
    trv["raw"] = 21.5  # radiator heating up: shows 20.0, room 19.0
    trv["report"]()
    await _run(hass, coord, freezer, 3)
    assert trv["writes"] == [-1.5]
    await _run(hass, coord, freezer, 3)
    assert trv["writes"] == [-1.5, -2.5]  # 5 min after the last change, not 15


async def test_small_changes_are_left_alone(hass, setup, freezer):
    make, trv = setup
    trv["raw"] = 19.2  # 0.2 above the room
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 20)
    assert trv["writes"] == []


async def test_offset_stays_inside_the_trv_range(hass, setup, freezer):
    make, trv = setup
    trv["raw"] = 23.0  # 4 °C above the room; the TRV only allows −2.5
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    trv["report"]()
    await _run(hass, coord, freezer, 17)
    assert trv["writes"] == [-2.5]


async def test_silent_room_sensor_stops_calibration(hass, setup, freezer):
    make, trv = setup
    hass.states.async_set(ROOM_SENSOR, "unavailable")
    coord = await make()
    await _run(hass, coord, freezer, 20)
    assert trv["writes"] == []


async def test_offset_never_goes_above_zero(hass, setup, freezer):
    """21 Oct live: with cold radiators the living room TRVs read ~4 °C under the
    room sensor and were set to +2.5 — then shut early at the next warm-up."""
    make, trv = setup
    trv["raw"] = 17.5  # radiator cold: TRV under-reads the 19.0 room
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 20)
    assert trv["writes"] == []


async def test_a_positive_offset_is_brought_back_to_zero(hass, setup, freezer):
    make, trv = setup
    hass.states.async_set(OFFSET, "2.5", {"min": -2.5, "max": 2.5, "step": 0.1})
    trv["raw"] = 17.5
    trv["report"]()  # shows 20.0
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["writes"] == [0.0]


async def test_setpoint_topped_up_beyond_the_offset_limit(hass, setup, freezer):
    """22 Oct live: living room TRVs read 20.0 at −2.5 with the room at 17.8, and shut."""
    make, trv = setup
    hass.states.async_set(OFFSET, "-2.5", {"min": -2.5, "max": 2.5, "step": 0.1})
    hass.states.async_set(ROOM_SENSOR, "18.0")
    trv["raw"] = 23.5  # shows 21.0: 3.0 above the room even at −2.5
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["setpoint"] == 25.0  # 3.0 over the room at −2.5, + the 2.0 margin
    assert trv["writes"] == []  # the offset is already as low as it goes
    trv["raw"] = 22.5  # over-read shrinks: the top-up doesn't (no churn mid warm-up)
    trv["report"]()
    await _run(hass, coord, freezer, 3)
    assert trv["setpoint"] == 25.0
    hass.states.async_set(ROOM_SENSOR, "20.4")  # past the room's cut-out: back to the real setpoint
    await _run(hass, coord, freezer, 1)
    assert trv["setpoint"] == 20.0


async def test_top_up_follows_the_rooms_own_call(hass, setup, freezer):
    """23 Oct live: the living room called on at 20.1 (cut-out 20.3) but its top-up had ended
    at 20.0 — tiles said "Heating", valves shut; the TRVs then reopened at 19.9, no hysteresis."""
    make, trv = setup
    hass.states.async_set(OFFSET, "-2.5", {"min": -2.5, "max": 2.5, "step": 0.1})
    hass.states.async_set(ROOM_SENSOR, "19.0")
    trv["raw"] = 23.5  # shows 21.0
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["setpoint"] == 24.0  # TRV 21.0 vs room 19.0 → +2.0, + margin
    hass.states.async_set(ROOM_SENSOR, "20.1")  # at target, still inside the room's call
    await _run(hass, coord, freezer, 2)
    assert coord._room_states["hall"]["needs_heat"]  # noqa: SLF001
    assert trv["setpoint"] > 20.0  # valve kept open while the room calls
    hass.states.async_set(ROOM_SENSOR, "20.4")  # cut-out
    await _run(hass, coord, freezer, 2)
    assert trv["setpoint"] == 20.0
    hass.states.async_set(ROOM_SENSOR, "19.9")  # cooling, but above the cut-in (19.7)
    await _run(hass, coord, freezer, 2)
    assert trv["setpoint"] == 20.0  # no top-up yet: no reopening at 19.9
    hass.states.async_set(ROOM_SENSOR, "19.6")  # cut-in
    await _run(hass, coord, freezer, 17)
    assert trv["setpoint"] > 20.0


async def test_margin_keeps_the_valve_open_until_the_room_is_there(hass, setup, freezer):
    """26 Oct live: the hall's valve eased off as the room neared target (setpoint only just
    above what matched the room) and the last 0.6 °C took over an hour."""
    make, trv = setup
    trv["raw"] = 19.0  # TRV reads the room exactly: nothing for the offset to correct
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["writes"] == []
    assert trv["setpoint"] == 22.0  # target 20 + 2.0 margin while the room warms
    hass.states.async_set(ROOM_SENSOR, "20.4")  # cut-out: back to the real setpoint
    await _run(hass, coord, freezer, 1)
    assert trv["setpoint"] == 20.0


async def test_top_up_is_capped(hass, setup, freezer):
    make, trv = setup
    hass.states.async_set(OFFSET, "-2.5", {"min": -2.5, "max": 2.5, "step": 0.1})
    hass.states.async_set(ROOM_SENSOR, "17.0")
    trv["raw"] = 27.5  # 8.0 above the room at −2.5
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["setpoint"] == 28.0  # +6 at most, + the 2.0 margin


async def test_top_up_covers_a_hot_radiator(hass, setup, freezer):
    """24 Oct live: the living-room front TRV read ~6 °C over the room at −2.5 and shut
    at 19.6 because the top-up stopped at +3."""
    make, trv = setup
    hass.states.async_set(OFFSET, "-2.5", {"min": -2.5, "max": 2.5, "step": 0.1})
    hass.states.async_set(ROOM_SENSOR, "17.0")
    trv["raw"] = 25.0  # 5.5 above the room at −2.5
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["setpoint"] == 27.5  # the whole 5.5 (was capped at +3), + the margin


async def test_no_top_up_while_the_offset_can_still_correct(hass, setup, freezer):
    make, trv = setup
    coord = await make()
    await _run(hass, coord, freezer, 30)
    assert trv["writes"] == [-2.3]
    assert all(s <= 22.0 for s in trv["setpoints"])  # only the 2.0 margin


async def test_no_top_up_without_calibration(hass, setup, freezer):
    make, trv = setup
    hass.states.async_set(OFFSET, "-2.5", {"min": -2.5, "max": 2.5, "step": 0.1})
    hass.states.async_set(ROOM_SENSOR, "18.0")
    trv["raw"] = 23.5
    trv["report"]()
    coord = await make(calibrate=False)
    await _run(hass, coord, freezer, 20)
    assert all(s <= 20.0 for s in trv["setpoints"])


async def test_last_step_onto_the_limit_is_taken(hass, setup, freezer):
    """23 Oct live: kitchen + living-room front TRVs sat at −2.2 wanting −2.5; the 0.3 step
    came out as 0.29999… < 0.3, so the limit (and the top-up after it) was never reached."""
    make, trv = setup
    hass.states.async_set(OFFSET, "-2.2", {"min": -2.5, "max": 2.5, "step": 0.1})
    trv["raw"] = 23.2  # shows 21.0 with the room at 19.0
    trv["report"]()
    coord = await make()
    await _run(hass, coord, freezer, 17)
    assert trv["writes"] == [-2.5]
    trv["report"]()
    await _run(hass, coord, freezer, 2)
    assert trv["setpoint"] == 24.0  # then the top-up covers the rest (20.7 vs 19.0 → +2.0) + margin


async def test_a_quick_warm_up_still_calibrates(hass, setup, freezer):
    """23 Oct live: the living room sensor (Faster updates on) rose 3.6 °C/h in the warm-up."""
    make, trv = setup
    coord = await make()
    for minute in range(20):  # 4.2 °C/h, the TRV 2.3 above the room throughout
        room = 18.0 + 0.07 * minute
        hass.states.async_set(ROOM_SENSOR, f"{room:.2f}")
        trv["raw"] = room + 2.3
        trv["report"]()
        await _tick(hass, coord, freezer)
    assert trv["writes"] == [-2.3]


async def test_house_sensor_room_keeps_its_top_up_while_the_house_calls(hass, setup, freezer):
    """23 Oct live: the hall (house sensor) top-up ended at 20.0 and the TRV shut, but the
    house calls on to target + 0.3 − coast, so the boiler ran for a hall that couldn't warm."""
    make, trv = setup
    hass.states.async_set(OFFSET, "-2.5", {"min": -2.5, "max": 2.5, "step": 0.1})
    trv["raw"] = 23.5  # shows 21.0
    trv["report"]()
    coord = await make(sensor="sensor.house")  # the hall: its room sensor IS the house sensor
    await _run(hass, coord, freezer, 17)
    assert trv["setpoint"] == 24.0  # 2.0 over the room at −2.5, + the 2.0 margin
    hass.states.async_set("sensor.house", "20.0")  # at target, short of the house cut-off
    await _run(hass, coord, freezer, 3)
    assert coord._house_calling  # noqa: SLF001
    assert trv["setpoint"] == 24.0  # stays open while the house still wants heat
    hass.states.async_set("sensor.house", "20.4")  # past the cut-off: house stops
    await _run(hass, coord, freezer, 2)
    assert not coord._house_calling  # noqa: SLF001
    assert trv["setpoint"] == 20.0


async def test_settling_room_sensor_is_ignored(hass, setup, freezer):
    """21 Oct live: a new living room sensor came on at 25.0 °C (warm from handling)
    and fell 3.7 °C in 25 min; Nook calibrated to it within 3 minutes."""
    make, trv = setup
    trv["raw"] = 17.0
    trv["report"]()
    hass.states.async_set(ROOM_SENSOR, "25.0")
    coord = await make()
    for minute in range(40):  # cooling 0.15 °C/min = 9 °C/h towards 19.0
        hass.states.async_set(ROOM_SENSOR, f"{max(19.0, 25.0 - 0.15 * minute):.2f}")
        await _tick(hass, coord, freezer)
    assert trv["writes"] == []  # the sensor was never steady long enough
    hass.states.async_set(ROOM_SENSOR, "19.0")
    trv["raw"] = 21.3  # warm-up starts with the sensor now steady at 19.0
    trv["report"]()
    await _run(hass, coord, freezer, 17)
    assert trv["writes"] == [-2.3]
