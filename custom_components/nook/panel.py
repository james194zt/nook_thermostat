"""Register the Nook sidebar panel."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_URL_PATH,
)

_LOGGER = logging.getLogger(__name__)

PANEL_JS_FILE = "nook-panel.js"
CARD_JS_FILE = "nook-card.js"
WWW_DIR = Path(__file__).parent / "www"
_STATIC_DATA_KEY = "_nook_static_registered"
_CARD_DATA_KEY = "_nook_card_registered"


def panel_js_path() -> Path:
    return WWW_DIR / PANEL_JS_FILE


def _panel_js_version() -> str:
    with (Path(__file__).parent / "manifest.json").open(encoding="utf-8") as mf:
        return json.load(mf).get("version", "0")


def _sync_versioned_panel_js() -> dict[str, str]:
    """Copy the panel JS to a versioned, content-hashed name; return the names to register.

    Blocking file I/O — run in the executor, never the event loop.
    """
    ver = _panel_js_version().replace(".", "_")
    names = {"component": f"{PANEL_COMPONENT}-{ver}"}
    src = panel_js_path()
    if not src.is_file():
        names["module_url"] = f"{PANEL_STATIC_URL}/nook-panel.v{ver}.missing.js"
        return names
    data = src.read_bytes()
    dest = WWW_DIR / f"nook-panel.v{ver}.{hashlib.sha256(data).hexdigest()[:12]}.js"
    if not dest.is_file() or dest.read_bytes() != data:
        dest.write_bytes(data)
    for old in WWW_DIR.glob("nook-panel.v*.js"):
        if old.name != dest.name:
            try:
                old.unlink()
            except OSError:
                pass
    names["module_url"] = f"{PANEL_STATIC_URL}/{dest.name}"
    return names


def _panel_exists(hass: HomeAssistant) -> bool:
    from homeassistant.components import frontend

    if hasattr(frontend, "async_panel_exists"):
        return frontend.async_panel_exists(hass, PANEL_URL_PATH)
    panels = hass.data.get("frontend_panels", {})
    return PANEL_URL_PATH in panels


def build_panel_config(hass: HomeAssistant, names: dict[str, str]) -> dict[str, Any]:
    entries = []
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if not isinstance(data, dict) or "coordinator" not in data:
            continue
        coordinator = data["coordinator"]
        entries.append(
            {
                "entry_id": entry_id,
                "title": coordinator.entry.title,
            }
        )
    return {
        "entries": entries,
        "brand_domain": DOMAIN,
        "panel_element": names["component"],
        "panel_js_module_url": names["module_url"],
    }


async def _async_ensure_static_paths(hass: HomeAssistant) -> bool:
    if hass.data.get(_STATIC_DATA_KEY):
        return True
    if not WWW_DIR.is_dir() or not panel_js_path().is_file():
        _LOGGER.error("Nook panel JS missing at %s", panel_js_path())
        return False
    from homeassistant.components.http import StaticPathConfig

    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_STATIC_URL, str(WWW_DIR), False)]
    )
    hass.data[_STATIC_DATA_KEY] = True
    return True


async def async_register_panel(hass: HomeAssistant) -> None:
    from homeassistant.components import frontend

    if not await _async_ensure_static_paths(hass):
        return

    names = await hass.async_add_executor_job(_sync_versioned_panel_js)

    # Dashboard card: loaded on every frontend page, so "Nook" shows in the
    # card picker without adding a resource by hand. Version in the URL busts caches.
    if not hass.data.get(_CARD_DATA_KEY) and (WWW_DIR / CARD_JS_FILE).is_file():
        version = await hass.async_add_executor_job(_panel_js_version)
        frontend.add_extra_js_url(hass, f"{PANEL_STATIC_URL}/{CARD_JS_FILE}?v={version}")
        hass.data[_CARD_DATA_KEY] = True

    config = {
        **build_panel_config(hass, names),
        "_panel_custom": {
            "name": names["component"],
            "embed_iframe": False,
            "trust_external": False,
            "module_url": names["module_url"],
        },
    }

    if _panel_exists(hass):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)

    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL_PATH,
        config=config,
        require_admin=False,
        update=False,
        config_panel_domain=DOMAIN,
    )
    _LOGGER.info(
        "Nook panel registered at /%s (%s)",
        PANEL_URL_PATH,
        names["module_url"],
    )
