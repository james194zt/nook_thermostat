"""Settings → Temperature Sensors: Faster updates per sensor (22 Oct 2026: the new
living room sensor reported every 15 min / 0.5 °C, so TRV calibration lagged)."""

import pytest

from custom_components.nook.models import NookConfig

BASE = {"heater": "switch.boiler", "temperature_sensor": "sensor.hall", "backup_temperature_sensor": "sensor.gw"}


def test_old_house_switch_becomes_house_and_backup():
    cfg = NookConfig.from_entry_data({**BASE, "fast_sensor_reporting": True})
    assert cfg.fast_reporting_sensors == ["sensor.hall", "sensor.gw"]


def test_old_switch_off_means_none():
    assert NookConfig.from_entry_data(BASE).fast_reporting_sensors == []


def test_saved_list_wins_over_the_old_switch():
    cfg = NookConfig.from_entry_data(
        {**BASE, "fast_sensor_reporting": True, "fast_reporting_sensors": ["sensor.lounge"]}
    )
    assert cfg.fast_reporting_sensors == ["sensor.lounge"]
    cfg = NookConfig.from_entry_data({**BASE, "fast_sensor_reporting": True, "fast_reporting_sensors": []})
    assert cfg.fast_reporting_sensors == []
    assert cfg.to_dict()["fast_reporting_sensors"] == []


pytest.importorskip("pytest_homeassistant_custom_component")

from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook.coordinator import NookCoordinator  # noqa: E402


async def test_sensor_list_shows_every_sensor_and_its_uses(hass):
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.hall"},
        options={
            "backup_temperature_sensor": "sensor.gw",
            "fast_reporting_sensors": ["sensor.lounge"],
            "rooms": [
                {"id": "lr1", "name": "Living Room 1", "trv_entity": "climate.a", "temperature_sensor": "sensor.lounge"},
                {"id": "lr2", "name": "Living Room 2", "trv_entity": "climate.b", "temperature_sensor": "sensor.lounge"},
                {"id": "hall", "name": "Hallway", "trv_entity": "climate.c", "temperature_sensor": "sensor.hall"},
                {"id": "kitchen", "name": "Kitchen", "trv_entity": "climate.d", "temperature_sensor": "sensor.gw"},
            ],
        },
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    try:
        info = {s["entity_id"]: s for s in coord.temperature_sensors_info()}
        assert list(info) == ["sensor.hall", "sensor.gw", "sensor.lounge"]
        assert info["sensor.hall"]["uses"] == ["house", "room:Hallway"]
        assert info["sensor.gw"]["uses"] == ["backup", "room:Kitchen"]
        assert info["sensor.lounge"]["uses"] == ["room:Living Room 1", "room:Living Room 2"]
        assert info["sensor.lounge"]["fast"] is True
        assert info["sensor.hall"]["fast"] is False
        assert info["sensor.hall"]["zigbee"] is False  # not a ZHA entity here
        assert "temperature_sensors" in coord._snapshot()  # noqa: SLF001
    finally:
        await coord.async_unload()
        await coord.async_shutdown()


async def test_missed_recheck_of_an_applied_sensor_is_not_an_error(hass, monkeypatch):
    """23 Oct live: the living room SNZB-02P had Faster updates (0.1 °C every ~5 min), but
    slept through the post-restart re-check and the card showed it as not set."""
    from custom_components.nook import zigbee_reporting

    async def asleep(_hass, _entity_id, *, fast):
        raise zigbee_reporting.ReportingError("the sensor didn't answer (it may be asleep) — will retry")

    monkeypatch.setattr(zigbee_reporting, "zha_ieee", lambda _hass, _e: "00:11:22:33:44:55:66:77")
    monkeypatch.setattr(zigbee_reporting, "async_configure", asleep)
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.hall"},
        options={"fast_reporting_sensors": ["sensor.hall", "sensor.lounge"]},
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    try:
        coord.intel.state.fast_reporting = ["sensor.lounge"]  # set on the sensor before the restart
        await coord._async_apply_reporting({"sensor.hall": True, "sensor.lounge": True})  # noqa: SLF001
        status = coord._reporting_status  # noqa: SLF001
        assert status["sensor.lounge"]["ok"] is False and status["sensor.lounge"]["applied"] is True
        assert status["sensor.hall"]["applied"] is False  # never got through: a real "not set"
        assert coord.intel.state.fast_reporting == ["sensor.lounge"]  # a miss doesn't forget it
    finally:
        await coord.async_unload()
        await coord.async_shutdown()


async def test_sleepy_sensor_gets_the_request_when_it_reports(hass, monkeypatch):
    """23 Oct live: bathroom/ensuite SNZB-02Ms missed every half-hourly retry (asleep).
    A sensor is awake just after it sends a reading: retry then, to that sensor alone."""
    from custom_components.nook import zigbee_reporting

    awake = {"sensor.bath": False}
    sent: list[str] = []

    async def configure(_hass, entity_id, *, fast):
        sent.append(entity_id)
        if not awake.get(entity_id, True):
            raise zigbee_reporting.ReportingError("the sensor didn't answer (it may be asleep) — will retry")

    monkeypatch.setattr(zigbee_reporting, "zha_ieee", lambda _hass, _e: "00:11:22:33:44:55:66:77")
    monkeypatch.setattr(zigbee_reporting, "async_configure", configure)
    hass.states.async_set("sensor.bath", "19.6")
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.hall"},
        options={"fast_reporting_sensors": ["sensor.bath"], "watch_temperature_sensors": ["sensor.bath"]},
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    monkeypatch.setattr(coord, "_zigbee_settled", lambda: True)
    monkeypatch.setattr(coord, "async_request_refresh", lambda: hass.async_add_executor_job(lambda: None))
    try:
        assert "sensor.bath" in coord._tracked_entities()  # noqa: SLF001 — watched-only, still tracked
        coord._subscribe_state_changes()  # noqa: SLF001
        await coord._async_apply_reporting({"sensor.bath": True})  # noqa: SLF001 — the half-hourly try: asleep
        assert coord._reporting_status["sensor.bath"]["ok"] is False  # noqa: SLF001
        awake["sensor.bath"] = True
        hass.states.async_set("sensor.bath", "19.7")  # it just reported: awake
        await hass.async_block_till_done(wait_background_tasks=True)
        assert sent == ["sensor.bath", "sensor.bath"]
        assert coord._reporting_status["sensor.bath"]["ok"] is True  # noqa: SLF001
        hass.states.async_set("sensor.bath", "19.8")  # already set: no more requests
        await hass.async_block_till_done(wait_background_tasks=True)
        assert sent == ["sensor.bath", "sensor.bath"]
    finally:
        await coord.async_unload()
        await coord.async_shutdown()


async def test_rejoined_sensor_gets_faster_updates_again(hass, monkeypatch):
    """23 Oct live: a ZHA Reconfigure (unavailable → back) reset the bedroom 1 sensor to
    ZHA's 0.5 °C reporting seconds after Nook had set Faster updates, and Nook kept
    showing it as set."""
    from custom_components.nook import zigbee_reporting

    sent: list[str] = []

    async def configure(_hass, entity_id, *, fast):
        sent.append(entity_id)

    monkeypatch.setattr(zigbee_reporting, "zha_ieee", lambda _hass, _e: "00:11:22:33:44:55:66:77")
    monkeypatch.setattr(zigbee_reporting, "async_configure", configure)
    hass.states.async_set("sensor.bed1", "23.9")
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.hall"},
        options={"fast_reporting_sensors": ["sensor.bed1"], "watch_temperature_sensors": ["sensor.bed1"]},
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    monkeypatch.setattr(coord, "_zigbee_settled", lambda: True)
    monkeypatch.setattr(coord, "async_request_refresh", lambda: hass.async_add_executor_job(lambda: None))
    try:
        coord._subscribe_state_changes()  # noqa: SLF001
        await coord._async_apply_reporting({"sensor.bed1": True})  # noqa: SLF001
        assert coord._reporting_status["sensor.bed1"]["ok"] is True  # noqa: SLF001
        hass.states.async_set("sensor.bed1", "unavailable")  # ZHA Reconfigure
        hass.states.async_set("sensor.bed1", "23.8")  # back — ZHA still configuring it
        await hass.async_block_till_done(wait_background_tasks=True)
        assert coord._reporting_status["sensor.bed1"]["ok"] is False  # noqa: SLF001
        assert sent == ["sensor.bed1"]  # not sent mid-reconfigure
        hass.states.async_set("sensor.bed1", "23.4")  # its next reading
        await hass.async_block_till_done(wait_background_tasks=True)
        assert sent == ["sensor.bed1", "sensor.bed1"]
        assert coord._reporting_status["sensor.bed1"]["ok"] is True  # noqa: SLF001
    finally:
        await coord.async_unload()
        await coord.async_shutdown()


async def test_nook_follows_entity_id_renames(hass):
    """23 Oct live: renaming the bedroom 1 sensor in HA left Nook on an id that no longer existed."""
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    reg.async_get_or_create("sensor", "zha", "bed", suggested_object_id="ensuite_bed1_temperature")
    reg.async_get_or_create("sensor", "zha", "hall", suggested_object_id="hall")
    reg.async_get_or_create("climate", "zha", "trv", suggested_object_id="old_trv")
    calls = []
    hass.services.async_register("switch", "turn_off", lambda call: calls.append(call))
    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.hall"},
        options={
            "watch_temperature_sensors": ["sensor.ensuite_bed1_temperature"],
            "fast_reporting_sensors": ["sensor.hall", "sensor.ensuite_bed1_temperature"],
            "rooms": [{"id": "bed1", "name": "Bedroom 1", "trv_entity": "climate.old_trv",
                       "temperature_sensor": "sensor.ensuite_bed1_temperature"}],
        },
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    await coord.async_setup_listeners()
    try:
        reg.async_update_entity("sensor.ensuite_bed1_temperature", new_entity_id="sensor.bedroom_1_temperature")
        reg.async_update_entity("sensor.hall", new_entity_id="sensor.hall_temperature")
        reg.async_update_entity("climate.old_trv", new_entity_id="climate.bedroom_1_trv")
        await hass.async_block_till_done()
        cfg = coord.config
        assert cfg.watch_temperature_sensors == ["sensor.bedroom_1_temperature"]
        assert cfg.fast_reporting_sensors == ["sensor.hall_temperature", "sensor.bedroom_1_temperature"]
        assert cfg.temperature_sensor == "sensor.hall_temperature"
        assert entry.data["temperature_sensor"] == "sensor.hall_temperature"  # saved, survives restart
        assert cfg.rooms[0].trv_entity == "climate.bedroom_1_trv"
        assert cfg.rooms[0].temperature_sensor == "sensor.bedroom_1_temperature"
        assert "sensor.bedroom_1_temperature" in coord._tracked_entities()  # noqa: SLF001
        assert calls == []  # nothing switched off
    finally:
        await coord.async_unload()
        await coord.async_shutdown()


async def test_floors_from_ha_areas_and_watched_sensors(hass):
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import floor_registry as fr

    ground = fr.async_get(hass).async_create("Ground Floor", level=0)
    first = fr.async_get(hass).async_create("First Floor", level=1)
    hall = ar.async_get(hass).async_create("Hallway", floor_id=ground.floor_id)
    bath = ar.async_get(hass).async_create("Bathroom", floor_id=first.floor_id)
    zha = MockConfigEntry(domain="zha")
    zha.add_to_hass(hass)
    trv_dev = dr.async_get(hass).async_get_or_create(config_entry_id=zha.entry_id, identifiers={("zha", "trv")})
    dr.async_get(hass).async_update_device(trv_dev.id, area_id=hall.id)  # TRV: area via its device
    reg = er.async_get(hass)
    reg.async_get_or_create("climate", "zha", "trv", suggested_object_id="hall_trv", device_id=trv_dev.id)
    sensor = reg.async_get_or_create("sensor", "zha", "bath-t", suggested_object_id="bath")
    reg.async_update_entity(sensor.entity_id, area_id=bath.id)  # sensor: its own area

    entry = MockConfigEntry(
        domain="nook",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.hall"},
        options={
            "watch_temperature_sensors": ["sensor.bath"],
            "rooms": [{"id": "hall", "name": "Hallway", "trv_entity": "climate.hall_trv"}],
        },
    )
    entry.add_to_hass(hass)
    coord = NookCoordinator(hass, entry)
    await coord.async_initialize_intelligence()
    try:
        assert coord.room_floors()["hall"]["name"] == "Ground Floor"
        info = coord.temperature_sensors_info()
        # First Floor sorts before "no floor": sensor.hall has no area.
        assert [s["entity_id"] for s in info] == ["sensor.bath", "sensor.hall"]
        assert info[0]["uses"] == ["watch"]
        assert info[0]["floor"] == {"id": first.floor_id, "name": "First Floor", "level": 1, "area": "Bathroom"}
        assert info[1]["floor"] is None
        # Watched sensors never drive the heating.
        assert coord.room_current_temp(coord.config.rooms[0]) is None
    finally:
        await coord.async_unload()
        await coord.async_shutdown()
