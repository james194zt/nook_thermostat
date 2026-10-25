"""Wall panel screen shape and Fully Kiosk switch are stored per panel (needs HA test venv)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook.const import DEFAULT_WALL_PANEL_MODEL  # noqa: E402
from custom_components.nook.models import WallPanelConfig  # noqa: E402


def test_panel_saved_before_models_gets_default():
    panel = WallPanelConfig.from_dict({"id": "hallway", "label": "Hallway panel"})
    assert panel.model == DEFAULT_WALL_PANEL_MODEL == "square"


def test_old_hardware_model_becomes_nspanel_pro():
    # Before 0.6.40 the only choice was the 480×480 NSPanel Pro.
    assert WallPanelConfig.from_dict({"id": "hallway", "model": "nspanel_pro_gen2"}).model == "nspanel_pro"
    assert WallPanelConfig.from_dict({"id": "hallway", "model": "made_up"}).model == "square"


@pytest.mark.parametrize("shape", ["square", "tall", "landscape", "wide", "nspanel_pro"])
def test_shape_round_trips(shape):
    panel = WallPanelConfig.from_dict({"id": "kitchen", "model": shape})
    assert WallPanelConfig.from_dict(panel.to_dict()).model == shape


def test_pairing_code_in_the_address_box_is_ignored():
    assert WallPanelConfig.from_dict({"id": "hallway", "helper_host": "931710"}).helper_host == ""
    assert WallPanelConfig.from_dict({"id": "hallway", "helper_host": " 192.168.1.50 "}).helper_host == "192.168.1.50"
    assert WallPanelConfig.from_dict({"id": "hallway", "helper_host": "panel.local"}).helper_host == "panel.local"


def test_fully_kiosk_is_on_by_default_and_off_keeps_the_device():
    assert WallPanelConfig.from_dict({"id": "hallway", "kiosk_device": "abc"}).linked_kiosk_device == "abc"
    off = WallPanelConfig.from_dict({"id": "hallway", "kiosk_device": "abc", "kiosk_enabled": False})
    assert off.linked_kiosk_device == ""
    again = WallPanelConfig.from_dict({**off.to_dict(), "kiosk_enabled": True})
    assert again.linked_kiosk_device == "abc"  # remembered for when it's switched back on
