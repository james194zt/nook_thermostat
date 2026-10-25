"""Central Fully Kiosk management (needs HA test venv).

The fake device mirrors a typical panel being migrated: on an old /local copy,
screensaver/screen-off 0, lock and motion off, brightness unreadable (screen off).
"""

from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.nook import kiosk  # noqa: E402
from custom_components.nook.models import WallPanelConfig  # noqa: E402
from tests.test_schedule_ha import setup  # noqa: E402,F401

OLD_PAGE = "http://192.168.1.10:8123/local/nspanel-thermostat-v2/index.html"
GOOD_PAGE = "http://192.168.1.10:8123/nook/static/wall/index.html?device=hallway&_v=2.0.45-dev"
P = "hallway_wall_panel"
ENTITIES = {
    # key: (domain, state)
    "screen_brightness": ("number", "unknown"),
    "screensaver_timer": ("number", "0"),
    "screensaver_brightness": ("number", "unknown"),
    "screen_off_timer": ("number", "0"),
    "kiosk_lock": ("switch", "off"),
    "motion_detection": ("switch", "off"),
    "current_page": ("sensor", OLD_PAGE),
    "clear_browser_cache": ("button", "unknown"),
}


def _make_device(hass):
    entry = MockConfigEntry(domain="fully_kiosk", title="Wall Panel")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("fully_kiosk", "abc123")}, name="Wall Panel"
    )
    reg = er.async_get(hass)
    for key, (domain, state) in ENTITIES.items():
        entity = reg.async_get_or_create(
            domain, "fully_kiosk", f"abc123-{key}", config_entry=entry, device_id=device.id,
            suggested_object_id=f"{P}_{key}", translation_key=key,
        )
        hass.states.async_set(entity.entity_id, state)
    return device.id


def _panel(device_id, overrides=None):
    return WallPanelConfig.from_dict({"id": "hallway", "label": "Test", "kiosk_device": device_id, "kiosk_overrides": overrides or {}})


def _mocks(hass):
    order = []
    hass.bus.async_listen("call_service", lambda ev: order.append(f"{ev.data['domain']}.{ev.data['service']}"))
    return {
        "order": order,
        "press": async_mock_service(hass, "button", "press"),
        "set_value": async_mock_service(hass, "number", "set_value"),
        "turn_on": async_mock_service(hass, "switch", "turn_on"),
        "turn_off": async_mock_service(hass, "switch", "turn_off"),
        "set_config": async_mock_service(hass, "fully_kiosk", "set_config"),
        "load_url": async_mock_service(hass, "fully_kiosk", "load_url"),
    }


def test_clean_settings_bounds_and_unknown_keys():
    assert kiosk.clean_settings(
        {"screen_brightness": 999, "screensaver_timer": "300", "kiosk_lock": 1, "bogus": 5, "screen_off_timer": None}
    ) == {"screen_brightness": 255, "screensaver_timer": 300, "kiosk_lock": True}


async def test_import_reads_only_what_the_panel_reports(hass):
    device_id = _make_device(hass)
    assert kiosk.read_current(hass, device_id) == {
        "screensaver_timer": 0, "screen_off_timer": 0, "kiosk_lock": False, "motion_detection": False,
    }


async def test_status_flags_old_page_and_drift(hass):
    device_id = _make_device(hass)
    status = kiosk.panel_status(hass, _panel(device_id), {"kiosk_lock": True, "screen_brightness": 180})
    assert status["online"] and status["page_ok"] is False and not status["in_sync"]
    # No internal URL configured: the server the panel already uses.
    assert status["expected_url"] == "http://192.168.1.10:8123/nook/static/wall/index.html?device=hallway"
    assert status["settings"]["kiosk_lock"]["ok"] is False
    assert status["settings"]["screen_brightness"]["ok"] is None  # unreadable, not "wrong"


async def test_apply_writes_only_managed_differences_and_moves_the_page(hass):
    device_id = _make_device(hass)
    calls = _mocks(hass)
    defaults = {"screensaver_timer": 0, "kiosk_lock": True, "screen_brightness": 180}  # motion not managed
    changes = await kiosk.async_apply(hass, _panel(device_id), defaults)
    assert [c.data["value"] for c in calls["set_value"]] == [180]  # timer already 0 → untouched
    assert [c.data["entity_id"] for c in calls["turn_on"]] == [f"switch.{P}_kiosk_lock"]
    assert not calls["turn_off"]  # motion detection isn't managed
    assert calls["set_config"][0].data == {
        "device_id": device_id, "key": "startURL",
        "value": "http://192.168.1.10:8123/nook/static/wall/index.html?device=hallway",
    }
    assert calls["load_url"][0].data["url"].endswith("?device=hallway")
    # Moving page: clear Fully's cache first (stale files caused glitches), then load.
    assert calls["press"][0].data == {"entity_id": f"button.{P}_clear_browser_cache"}
    assert calls["order"].index("button.press") < calls["order"].index("fully_kiosk.load_url")
    assert len(changes) == 3


async def test_in_sync_panel_is_left_alone_unless_forced(hass):
    device_id = _make_device(hass)
    hass.states.async_set(f"switch.{P}_kiosk_lock", "on")
    hass.states.async_set(f"sensor.{P}_current_page", GOOD_PAGE)  # app adds its own ?_v=
    calls = _mocks(hass)
    panel = _panel(device_id)
    assert kiosk.panel_status(hass, panel, {"kiosk_lock": True})["in_sync"]
    assert await kiosk.async_apply(hass, panel, {"kiosk_lock": True}) == []
    assert not any(v for k, v in calls.items() if k != "order")
    await kiosk.async_apply(hass, panel, {"kiosk_lock": True}, force=True)
    assert len(calls["set_config"]) == 1 and not calls["load_url"]  # start URL refreshed, no reload
    assert not calls["press"]  # same page: no cache clear


async def test_proximity_settings_are_write_only_and_sent_when_forced(hass):
    device_id = _make_device(hass)
    hass.states.async_set(f"switch.{P}_motion_detection", "on")
    hass.states.async_set(f"sensor.{P}_current_page", GOOD_PAGE)
    calls = _mocks(hass)
    panel = _panel(device_id)
    defaults = {"motion_detection": True, "proximity_motion": True, "proximity_threshold": 150, "js_interface": True}
    status = kiosk.panel_status(hass, panel, defaults)
    assert status["in_sync"]  # can't read them back, so they never count as drift
    assert status["settings"]["proximity_motion"]["ok"] is None
    assert status["settings"]["proximity_threshold"]["target"] == 100  # clamped to 0–100
    assert "proximity_motion" not in kiosk.read_current(hass, device_id)
    assert await kiosk.async_apply(hass, panel, defaults) == []
    assert not calls["set_config"]
    await kiosk.async_apply(hass, panel, defaults, force=True)
    sent = {c.data["key"]: c.data["value"] for c in calls["set_config"]}
    assert sent["motionDetectionProximity"] is True
    assert sent["motionThresholdProximity"] == 100
    assert sent["websiteIntegration"] is True  # JS interface: the wall app hears Fully's motion
    assert "startURL" in sent


async def test_panel_override_beats_house_default(hass):
    device_id = _make_device(hass)
    status = kiosk.panel_status(hass, _panel(device_id, {"screensaver_timer": 120}), {"screensaver_timer": 0})
    assert status["settings"]["screensaver_timer"]["target"] == 120


async def test_offline_panel_is_not_touched(hass):
    device_id = _make_device(hass)
    hass.states.async_set(f"sensor.{P}_current_page", "unavailable")
    calls = _mocks(hass)
    assert await kiosk.async_apply(hass, _panel(device_id), {"kiosk_lock": True}) == []
    assert not any(v for k, v in calls.items() if k != "order")


async def test_auto_sync_reapplies_when_the_panel_comes_back(hass, setup):
    coord, _calls = setup
    device_id = _make_device(hass)
    calls = _mocks(hass)
    await coord.async_save_config(
        {"kiosk_defaults": {"kiosk_lock": True}, "wall_panels": [_panel(device_id).to_dict()]}
    )
    await coord.async_setup_listeners()
    hass.states.async_set(f"sensor.{P}_current_page", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(f"sensor.{P}_current_page", OLD_PAGE)  # back online, wrong page
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert calls["turn_on"] and calls["load_url"]
    await coord.async_unload()


async def test_new_wall_app_version_clears_cache_once(hass, setup, monkeypatch):
    coord, _calls = setup
    device_id = _make_device(hass)
    hass.states.async_set(f"sensor.{P}_current_page", GOOD_PAGE)
    calls = _mocks(hass)
    await coord.async_save_config({"wall_panels": [_panel(device_id).to_dict()]})
    monkeypatch.setattr(kiosk, "bundled_wall_version", lambda _dir: "2.0.46-dev")

    assert await coord.async_kiosk_version_refresh() == ["hallway"]
    assert len(calls["press"]) == 1 and len(calls["load_url"]) == 1
    # Saved: a restart on the same version does nothing.
    assert await coord.async_kiosk_version_refresh() == []
    assert len(calls["press"]) == 1

    monkeypatch.setattr(kiosk, "bundled_wall_version", lambda _dir: "2.0.47-dev")
    assert await coord.async_kiosk_version_refresh() == ["hallway"]
    assert len(calls["press"]) == 2


async def test_panel_without_fully_is_left_alone(hass, setup, monkeypatch):
    coord, _calls = setup
    device_id = _make_device(hass)
    calls = _mocks(hass)
    panel = {**_panel(device_id).to_dict(), "kiosk_enabled": False}
    await coord.async_save_config({"kiosk_defaults": {"kiosk_lock": True}, "wall_panels": [panel]})
    assert coord.kiosk_status()["panels"]["hallway"] == {"linked": False}
    assert await coord.async_kiosk_apply() == {}
    monkeypatch.setattr(kiosk, "bundled_wall_version", lambda _dir: "2.0.59")
    assert await coord.async_kiosk_version_refresh() == []
    # Only the panel's own Fully entities count: the heating loop may switch the test
    # boiler (switch.boiler) on meanwhile, which once made this test flaky.
    touched = [
        c for k, v in calls.items() if k != "order" for c in v
        if P in str(c.data.get("entity_id", "")) or c.data.get("device_id") == device_id
    ]
    assert not touched


async def test_wall_screen_report_is_kept_per_panel(hass, setup, monkeypatch):
    coord, _calls = setup
    await coord.async_save_config({"wall_panels": [_panel("").to_dict()]})
    await coord.async_report_wall_screen("hallway", {"width": 480, "height": 480, "scale": 1.5})
    await coord.async_report_wall_screen("nope", {"width": 1, "height": 1})  # unknown panel
    await coord.async_report_wall_screen("hallway", {"width": "x"})  # junk
    screens = await coord.async_wall_screens()
    assert set(screens) == {"hallway"}
    assert {k: screens["hallway"][k] for k in ("width", "height", "scale")} == {"width": 480, "height": 480, "scale": 1.5}
    # Saved alongside the wall versions, and a version refresh doesn't wipe it.
    device_id = _make_device(hass)
    hass.states.async_set(f"sensor.{P}_current_page", GOOD_PAGE)
    _mocks(hass)
    await coord.async_save_config({"wall_panels": [_panel(device_id).to_dict()]})
    monkeypatch.setattr(kiosk, "bundled_wall_version", lambda _dir: "2.0.59")
    assert await coord.async_kiosk_version_refresh() == ["hallway"]
    stored = await coord._kiosk_store.async_load()
    assert stored["wall_versions"] == {"hallway": "2.0.59"} and stored["screens"]["hallway"]["width"] == 480


async def test_panel_asleep_at_a_new_version_gets_it_when_back(hass, setup, monkeypatch):
    coord, _calls = setup
    device_id = _make_device(hass)
    hass.states.async_set(f"sensor.{P}_current_page", "unavailable")  # screen off, Fully asleep
    calls = _mocks(hass)
    await coord.async_save_config({"wall_panels": [_panel(device_id).to_dict()]})
    monkeypatch.setattr(kiosk, "bundled_wall_version", lambda _dir: "2.0.60")
    assert await coord.async_kiosk_version_refresh() == []
    assert not calls["press"]
    hass.states.async_set(f"sensor.{P}_current_page", GOOD_PAGE)  # woke up
    assert await coord.async_kiosk_version_refresh() == ["hallway"]
    assert len(calls["press"]) == 1 and len(calls["load_url"]) == 1
    assert await coord.async_kiosk_version_refresh() == []  # once only


async def test_stay_awake_is_sent_to_fully(hass):
    device_id = _make_device(hass)
    hass.states.async_set(f"sensor.{P}_current_page", GOOD_PAGE)
    calls = _mocks(hass)
    await kiosk.async_apply(hass, _panel(device_id), {"stay_awake": True}, force=True)
    sent = {c.data["key"]: c.data["value"] for c in calls["set_config"]}
    assert sent["preventSleepWhileScreenOff"] is True


def _with_fully_settings(hass, device_id, settings):
    """What HA's Fully integration keeps: coordinator.data["settings"] from getSettings."""
    from types import SimpleNamespace

    device = dr.async_get(hass).async_get(device_id)
    entry = hass.config_entries.async_get_entry(next(iter(device.config_entries)))
    entry.runtime_data = SimpleNamespace(data={"deviceID": "abc123", "settings": settings})


async def test_fully_settings_are_read_back_and_only_differences_written(hass):
    device_id = _make_device(hass)
    hass.states.async_set(f"sensor.{P}_current_page", GOOD_PAGE)
    _with_fully_settings(hass, device_id, {
        # As Fully reports them: bools, and numbers as strings.
        "motionDetectionProximity": True, "websiteIntegration": False,
        "motionThresholdProximity": "60", "kioskExitGesture": "0", "kioskMode": True, "kioskPin": "1234",
    })
    calls = _mocks(hass)
    panel = _panel(device_id)
    defaults = {"proximity_motion": True, "js_interface": True, "proximity_threshold": 60, "exit_gesture": 1}
    status = kiosk.panel_status(hass, panel, defaults)
    assert status["settings"]["proximity_motion"]["ok"] is True
    assert status["settings"]["proximity_threshold"]["ok"] is True
    assert status["settings"]["js_interface"] == {**status["settings"]["js_interface"], "actual": False, "ok": False}
    assert status["settings"]["exit_gesture"]["actual"] == 0 and status["settings"]["exit_gesture"]["ok"] is False
    assert status["kiosk_mode"] is True and not status["in_sync"]
    assert kiosk.read_current(hass, device_id)["exit_gesture"] == 0
    # Not forced: only what differs goes out.
    await kiosk.async_apply(hass, panel, defaults)
    sent = {c.data["key"]: c.data["value"] for c in calls["set_config"]}
    assert sent == {"websiteIntegration": True, "kioskExitGesture": 1}


async def test_menu_pin_follows_the_wall_pin_and_is_never_echoed(hass):
    device_id = _make_device(hass)
    hass.states.async_set(f"sensor.{P}_current_page", GOOD_PAGE)
    _with_fully_settings(hass, device_id, {"kioskPin": "1234", "kioskMode": False})
    calls = _mocks(hass)
    panel = _panel(device_id)
    # No wall PIN: Fully keeps its own.
    status = kiosk.panel_status(hass, panel, {})
    assert "menu_pin" not in status["settings"] and status["kiosk_mode"] is False
    # Wall PIN set and different: it's sent; the status says only that it differs.
    status = kiosk.panel_status(hass, panel, {}, pin="4321")
    assert status["settings"]["menu_pin"] == {"target": None, "actual": None, "ok": False, "entity_id": None}
    assert "1234" not in str(status) and "4321" not in str(status)
    await kiosk.async_apply(hass, panel, {}, pin="4321")
    assert [(c.data["key"], c.data["value"]) for c in calls["set_config"]] == [("kioskPin", "4321")]
    # Same PIN: nothing to do.
    _with_fully_settings(hass, device_id, {"kioskPin": "4321"})
    assert kiosk.panel_status(hass, panel, {}, pin="4321")["settings"]["menu_pin"]["ok"] is True


def test_exit_gesture_is_one_of_fullys_choices():
    assert kiosk.clean_settings({"exit_gesture": 9}) == {"exit_gesture": 3}
    assert kiosk.clean_settings({"exit_gesture": "1"}) == {"exit_gesture": 1}


def test_bundled_wall_version_reads_the_shipped_app():
    from custom_components.nook.panel import WWW_DIR

    import json
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "nspanel-thermostat" / "version.json"
    assert kiosk.bundled_wall_version(WWW_DIR) == json.loads(source.read_text())["version"]
