"""The dashboard card JS is added to the frontend once, versioned (needs HA test venv)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.nook import panel  # noqa: E402

VERSION = json.loads((Path(panel.__file__).parent / "manifest.json").read_text())["version"]


async def test_card_js_added_once_with_version(hass):
    with (
        patch.object(panel, "_async_ensure_static_paths", AsyncMock(return_value=True)),
        patch.object(panel, "_sync_versioned_panel_js", return_value={"component": "x", "module_url": "/x.js"}),
        patch.object(panel, "_panel_exists", return_value=False),
        patch("homeassistant.components.frontend.async_register_built_in_panel"),
        patch("homeassistant.components.frontend.add_extra_js_url") as add_js,
    ):
        await panel.async_register_panel(hass)
        await panel.async_register_panel(hass)  # e.g. entry reload
    add_js.assert_called_once_with(hass, f"/nook/static/nook-card.js?v={VERSION}")


def test_card_file_ships_in_www():
    assert (panel.WWW_DIR / panel.CARD_JS_FILE).is_file()
