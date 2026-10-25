"""Moving from the old name (neat_thermostat) to Nook, end to end (needs HA test venv).

Import offered by the config flow → Nook renames the old entities to its own ids
and waits (never two controllers on one boiler) → the old integration is removed →
Nook copies its learned data and takes over under the same entity ids.
"""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.helpers.storage import Store  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.nook import migrate  # noqa: E402


@pytest.fixture(autouse=True)
def no_frontend(hass, monkeypatch):
    """The test venv has no HA frontend build: mark Nook's web dependencies as loaded and
    skip the sidebar panel (the move itself doesn't touch them)."""
    hass.config.components.update({"http", "frontend", "panel_custom"})

    async def no_panel(_hass):
        return None

    monkeypatch.setattr("custom_components.nook.panel.async_register_panel", no_panel)


@pytest.fixture
async def old_install(hass, enable_custom_integrations):
    calls: list[str] = []

    async def switch(call):
        calls.append(call.service)
        hass.states.async_set(call.data["entity_id"], "on" if call.service == "turn_on" else "off")

    for service in ("turn_on", "turn_off"):
        hass.services.async_register("switch", service, switch)
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set("sensor.hall", "19.0")
    hass.states.async_set("climate.trv_hall", "heat", {"temperature": 16, "current_temperature": 18})

    old = MockConfigEntry(
        domain=migrate.OLD_DOMAIN,
        title="Neat Thermostat",
        data={"heater": "switch.boiler", "temperature_sensor": "sensor.hall"},
        options={
            "rooms": [{"id": "hallway", "name": "Hallway", "trv_entity": "climate.trv_hall"}],
            "wall_panels": [{"id": "hallway", "label": "Hallway", "primary_entity": "climate.neat_thermostat_neat_home"}],
            "eco_temp": 16,
        },
    )
    old.add_to_hass(hass)
    reg = er.async_get(hass)
    reg.async_get_or_create("climate", migrate.OLD_DOMAIN, "neat_home",
                            suggested_object_id="neat_thermostat_neat_home", config_entry=old)
    reg.async_get_or_create("climate", migrate.OLD_DOMAIN, "neat_hallway",
                            suggested_object_id="hallway_neat_thermostat_neat_hallway", config_entry=old)
    await Store(hass, 1, f"{migrate.OLD_DOMAIN}.intelligence.{old.entry_id}").async_save(
        {"warmup": {"c_per_hour": 1.489, "samples": 12, "coast_c": 0.229, "coast_samples": 3}}
    )
    await Store(hass, 1, f"{migrate.OLD_DOMAIN}.kiosk_{old.entry_id}").async_save({"wall_versions": {"hallway": "2.0.72"}})
    return old, calls


async def test_import_waits_then_takes_over_with_history_ids_and_learning(hass, old_install):
    old, calls = old_install
    reg = er.async_get(hass)

    result = await hass.config_entries.flow.async_init("nook", context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form" and result["step_id"] == "import_old"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry" and result["title"] == "Nook"
    await hass.async_block_till_done()
    nook = hass.config_entries.async_entries("nook")[0]

    # Old entities now carry Nook's ids (HA moves their history with a rename) …
    assert reg.async_get("climate.nook_home").platform == migrate.OLD_DOMAIN
    assert reg.async_get("climate.nook_hallway").platform == migrate.OLD_DOMAIN
    assert reg.async_get("climate.neat_thermostat_neat_home") is None
    # … settings copied with the ids swapped, and Nook is waiting, not controlling.
    assert nook.options["wall_panels"][0]["primary_entity"] == "climate.nook_home"
    assert nook.options["rooms"][0]["trv_entity"] == "climate.trv_hall"
    assert nook.data["heater"] == "switch.boiler"
    assert nook.state is config_entries.ConfigEntryState.SETUP_RETRY
    assert calls == []  # the boiler relay was never touched while waiting

    # The old integration is removed → Nook takes over.
    assert await hass.config_entries.async_remove(old.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(nook.entry_id)
    await hass.async_block_till_done()
    assert nook.state is config_entries.ConfigEntryState.LOADED

    home = reg.async_get("climate.nook_home")
    assert home is not None and home.platform == "nook" and home.unique_id == "nook_home"
    assert reg.async_get("climate.nook_hallway").platform == "nook"
    assert hass.states.get("climate.nook_home") is not None
    coord = hass.data["nook"][nook.entry_id]["coordinator"]
    assert coord.intel.state.warmup.c_per_hour == pytest.approx(1.489)
    assert coord.intel.state.warmup.samples == 12
    assert nook.data[migrate.STORES_IMPORTED] is True
    assert (await Store(hass, 1, f"nook.kiosk_{nook.entry_id}").async_load())["wall_versions"]["hallway"] == "2.0.72"

    await hass.config_entries.async_unload(nook.entry_id)


async def test_fresh_install_still_gets_the_normal_setup_form(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init("nook", context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form" and result["step_id"] == "user"
