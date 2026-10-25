"""Nook Panel Helper: pairing, status polling, settings and self-update (needs HA test venv)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook import panel_helper  # noqa: E402
from tests.test_schedule_ha import setup  # noqa: E402,F401

HOST = "192.168.1.50"
BASE = f"http://{HOST}:2424"
SHIPPED = {"version": "0.2.0", "version_code": 3, "sha256": "ab" * 32}


def _status(version_code=2, blocked=True, showing=False):
    sonoff = "com.eWeLinkControlPanel/com.coolkit.nspanelpro.service.accessibility.BackButtonService"
    return {
        "version": "0.1.1" if version_code == 2 else "0.2.0",
        "version_code": version_code,
        "device_owner": True,
        "update": {"state": "", "target": 0},
        "device": {"model": "PX30_Android11", "android": "11"},
        "uptime_s": 600,
        "screen_on": False,
        "wifi": {"rssi": -47},
        "stay_awake": {"cpu_lock_enabled": False, "wifi_lock_enabled": False},
        "guard": {
            "can_write": True,
            "automatic": True,
            "blocked": [sonoff] if blocked else [],
            "times_turned_off": 1,
            "services": [{"id": sonoff, "label": "Return to main program with accessibility service", "enabled": showing}],
        },
        "fully": {"foreground_app": "de.ozerov.fully"},
        "sensors": {"light_lux": 800},
        "permissions": [],
    }


async def _panel(coord, hass, monkeypatch):
    hass.config.internal_url = "http://192.168.1.10:8123"
    monkeypatch.setattr(panel_helper, "bundled_helper", lambda _dir: SHIPPED)
    await coord.async_save_config(
        {"wall_panels": [{"id": "hallway", "label": "Hallway", "model": "nspanel_pro", "helper_host": HOST}]}
    )


def _calls(aioclient_mock, path):
    return [c for c in aioclient_mock.mock_calls if str(c[1]).endswith(path)]


async def test_pair_poll_and_update(hass, setup, aioclient_mock, monkeypatch):
    coord, _calls_ = setup
    await _panel(coord, hass, monkeypatch)
    aioclient_mock.post(f"{BASE}/pair", json={"key": "k1"})
    aioclient_mock.get(f"{BASE}/status", json=_status(version_code=2))
    aioclient_mock.post(f"{BASE}/update", json={"started": True})

    state = await coord.async_helper_pair("hallway", "123 456")
    assert _calls(aioclient_mock, "/pair")[0][2] == {"code": "123456"}
    assert state["paired"] and state["summary"]["version"] == "0.1.1"
    assert state["summary"]["return_button_found"] and not state["summary"]["return_button_showing"]
    stored = await coord._kiosk_store.async_load()
    assert stored["helper_keys"] == {"hallway": "k1"}
    # Behind the shipped version: told to fetch it from Nook's static path, with its checksum.
    update = _calls(aioclient_mock, "/update")
    assert len(update) == 1
    assert update[0][2] == {
        "url": "http://192.168.1.10:8123/nook/static/panel-helper/neat-panel-helper.apk",
        "sha256": SHIPPED["sha256"],
        "version_code": 3,
    }
    assert update[0][3]["X-Neat-Key"] == "k1"
    # Polled again within the hour: not asked twice.
    await coord.async_helper_poll()
    assert len(_calls(aioclient_mock, "/update")) == 1


async def test_up_to_date_helper_is_left_alone(hass, setup, aioclient_mock, monkeypatch):
    coord, _calls_ = setup
    await _panel(coord, hass, monkeypatch)
    aioclient_mock.post(f"{BASE}/pair", json={"key": "k1"})
    aioclient_mock.get(f"{BASE}/status", json=_status(version_code=3))
    await coord.async_helper_pair("hallway", "123456")
    assert not _calls(aioclient_mock, "/update")


async def test_helper_settings_and_unreachable(hass, setup, aioclient_mock, monkeypatch):
    coord, _calls_ = setup
    await _panel(coord, hass, monkeypatch)
    aioclient_mock.post(f"{BASE}/pair", json={"key": "k1"})
    aioclient_mock.get(f"{BASE}/status", json=_status(version_code=3))
    aioclient_mock.post(f"{BASE}/config", json={})
    await coord.async_helper_pair("hallway", "123456")

    await coord.async_helper_config("hallway", {"hide_return_button": False, "cpu_lock": True})
    assert _calls(aioclient_mock, "/config")[0][2] == {"blocked_services": [], "cpu_lock": True}
    await coord.async_helper_config("hallway", {"hide_return_button": True})
    assert _calls(aioclient_mock, "/config")[1][2] == {"blocked_services": None}

    # Helper gone: the last status stays, with the error.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/status", status=500, json={"error": "boom"})
    await coord.async_helper_poll()
    state = (await coord.async_helpers_state())["hallway"]
    assert state["error"] == "boom" and state["summary"]["version"] == "0.2.0"


async def test_wrong_code_is_reported(hass, setup, aioclient_mock, monkeypatch):
    coord, _calls_ = setup
    await _panel(coord, hass, monkeypatch)
    aioclient_mock.post(f"{BASE}/pair", status=403, json={"error": "wrong code"})
    with pytest.raises(panel_helper.HelperError, match="wrong code"):
        await coord.async_helper_pair("hallway", "000000")
    assert not (await coord.async_helpers_state())["hallway"]["paired"]


async def test_pairing_before_saving_the_screen_type(hass, setup, aioclient_mock, monkeypatch):
    """The NSPanel section shows as soon as the type is picked, so pairing can come before
    Save: the panel is still saved as square (seen live 14 Oct: KeyError → 'Unknown error')."""
    coord, _calls_ = setup
    hass.config.internal_url = "http://192.168.1.10:8123"
    monkeypatch.setattr(panel_helper, "bundled_helper", lambda _dir: SHIPPED)
    await coord.async_save_config(
        {"wall_panels": [{"id": "hallway", "label": "Hallway", "model": "square", "helper_host": HOST}]}
    )
    aioclient_mock.post(f"{BASE}/pair", json={"key": "k1"})
    aioclient_mock.get(f"{BASE}/status", json=_status(version_code=3))
    state = await coord.async_helper_pair("hallway", "123456")
    assert state["paired"] and state["summary"]["version"] == "0.2.0"
    assert "hallway" in await coord.async_helpers_state()
    # Pairing records the type: only an NSPanel Pro has a helper.
    assert coord.get_wall_panel("hallway").model == "nspanel_pro"
    assert coord.get_wall_panel("hallway").helper_host == HOST


def test_summary_spots_a_showing_button():
    s = panel_helper.summary(_status(showing=True))
    assert s["return_button_showing"] and s["hide_return_button"]
    assert panel_helper.summary(_status(blocked=False))["return_button_found"] is False
