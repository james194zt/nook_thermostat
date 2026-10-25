"""Nook Panel Helper: the small Android app on Sonoff NSPanel Pro wall panels.

It does what Fully Kiosk can't (keeps Sonoff's floating "Return to main program" button
off, reports the panel's health and sensors) and answers on port 2424. Nook pairs with it
using the 6-digit code shown on its screen, polls its status, and keeps it up to date:
Nook ships the APK in www/panel-helper/, and the helper installs it over itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import kiosk

_LOGGER = logging.getLogger(__name__)

HELPER_PORT = 2424
HELPER_MODEL = "nspanel_pro"  # the Screen type that has a helper
APK_SUBDIR = "panel-helper"
APK_NAME = "neat-panel-helper.apk"
_TIMEOUT = aiohttp.ClientTimeout(total=8)


class HelperError(Exception):
    """The helper couldn't be reached or refused the request."""


def bundled_helper(www_dir: Path) -> dict[str, Any] | None:
    """The helper version Nook ships ({version, version_code, sha256}), or None."""
    try:
        data = json.loads((www_dir / APK_SUBDIR / "version.json").read_text())
    except (OSError, ValueError):
        return None
    if not (www_dir / APK_SUBDIR / APK_NAME).is_file():
        return None
    return data


def helper_host(hass: HomeAssistant, panel: Any) -> str:
    """Where the helper is: the panel's own setting, else the linked Fully device's address."""
    if getattr(panel, "helper_host", ""):
        return str(panel.helper_host).strip()
    device_id = getattr(panel, "kiosk_device", "")
    if not device_id:
        return ""
    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get(device_id)
    url = getattr(device, "configuration_url", None) if device else None
    return urlparse(str(url or "")).hostname or ""


def apk_url(hass: HomeAssistant, panel: Any) -> str:
    """URL the helper downloads its update from: the HA address the panel already uses."""
    status = kiosk.panel_status(hass, panel, {}) if getattr(panel, "linked_kiosk_device", "") else {}
    page = status.get("expected_url") or kiosk.panel_url(hass, panel.id)
    parsed = urlparse(page)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/nook/static/{APK_SUBDIR}/{APK_NAME}"


async def async_request(
    hass: HomeAssistant,
    host: str,
    method: str,
    path: str,
    *,
    key: str = "",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not host:
        raise HelperError("no address for the panel (link its Fully Kiosk device, or enter one)")
    session = async_get_clientsession(hass)
    headers = {"X-Neat-Key": key} if key else {}
    try:
        async with session.request(
            method, f"http://{host}:{HELPER_PORT}{path}", json=body, headers=headers, timeout=_TIMEOUT
        ) as resp:
            try:
                data = await resp.json(content_type=None)
            except ValueError:
                data = {}
            if resp.status != 200:
                raise HelperError(str((data or {}).get("error") or f"HTTP {resp.status}"))
            return data or {}
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise HelperError(f"can't reach the helper at {host}:{HELPER_PORT}") from err


async def async_pair(hass: HomeAssistant, host: str, code: str) -> str:
    """Trade the code shown on the helper's screen for its key."""
    data = await async_request(hass, host, "POST", "/pair", body={"code": str(code).strip().replace(" ", "")})
    key = str(data.get("key") or "")
    if not key:
        raise HelperError("the helper didn't send a key")
    return key


def summary(status: dict[str, Any] | None) -> dict[str, Any]:
    """The bits Nook shows, from a helper /status reply."""
    if not status:
        return {}
    guard = status.get("guard") or {}
    blocked = set(guard.get("blocked") or [])
    showing = [s.get("label") for s in guard.get("services") or [] if s.get("enabled") and s.get("id") in blocked]
    return {
        "version": status.get("version"),
        "version_code": status.get("version_code"),
        "device_owner": bool(status.get("device_owner")),
        "update_state": (status.get("update") or {}).get("state") or "",
        "android": (status.get("device") or {}).get("android"),
        "model": (status.get("device") or {}).get("model"),
        "uptime_s": status.get("uptime_s"),
        "screen_on": status.get("screen_on"),
        "wifi_rssi": (status.get("wifi") or {}).get("rssi"),
        "cpu_lock": (status.get("stay_awake") or {}).get("cpu_lock_enabled", False),
        "wifi_lock": (status.get("stay_awake") or {}).get("wifi_lock_enabled", False),
        "hide_return_button": bool(guard.get("automatic", True)) or bool(blocked),
        "return_button_found": bool(blocked),
        "return_button_showing": bool(showing),
        "can_hide": bool(guard.get("can_write")),
        "times_hidden": guard.get("times_turned_off", 0),
        "foreground_app": (status.get("fully") or {}).get("foreground_app"),
        "light_lux": (status.get("sensors") or {}).get("light_lux"),
        "missing_permissions": status.get("permissions") or [],
    }
