"""Central management of wall panels running Fully Kiosk Browser.

Nook keeps house-wide kiosk defaults plus per-panel overrides, and pushes them to each
panel through Home Assistant's Fully Kiosk integration (entities + fully_kiosk services).
Only settings that differ are written, and the start URL always points the panel at the
wall app the integration ships, with its own ?device=.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

FULLY_DOMAIN = "fully_kiosk"
WALL_APP_PATH = "/nook/static/wall/index.html"

# Managed settings: key -> (entity domain, range or None for on/off).
# Keys match the Fully Kiosk integration's entity translation keys.
KIOSK_SETTINGS: dict[str, tuple[str, tuple[float, float] | None]] = {
    "screen_brightness": ("number", (0, 255)),
    "screensaver_timer": ("number", (0, 86400)),
    "screensaver_brightness": ("number", (0, 255)),
    "screen_off_timer": ("number", (0, 86400)),
    "kiosk_lock": ("switch", None),
    "motion_detection": ("switch", None),
    "proximity_motion": ("config", None),
    "proximity_threshold": ("config", (0, 100)),
    "js_interface": ("config", None),
    "stay_awake": ("config", None),
    # How Fully's menu (and the PIN dialog) opens; see EXIT_GESTURES.
    "exit_gesture": ("config", (0, 3)),
}
# Settings with no HA entity: written with fully_kiosk.set_config and read back from the
# settings HA's Fully integration fetches with every update. If they can't be read they're
# only sent on an explicit sync/save or when the panel comes back online.
FULLY_CONFIG_KEYS = {
    "proximity_motion": "motionDetectionProximity",  # "Enable Proximity Motion Detection"
    "proximity_threshold": "motionThresholdProximity",  # 0–100 %
    # "Enable JavaScript Interface": the wall app binds Fully's onMotion/screenOn
    # through it; without it a wave never clears the clock (seen 13 Oct).
    "js_interface": "websiteIntegration",
    # "Prevent from Sleep while Screen Off": a CPU wake lock, so the panel (and its
    # Wi-Fi) stays up with the screen off and wakes straight to live data. The screen
    # still turns off, so the backlight isn't on all day.
    "stay_awake": "preventSleepWhileScreenOff",
    # "Kiosk Exit Gesture". 0 = swipe from the left edge (Fully's default; on the
    # NSPanel it fights the wall app's page swipes), 1 = double-tap top-left then
    # bottom-right, 2 = fast 5 taps, 3 = fast 7 taps (newer Fully; number unconfirmed).
    "exit_gesture": "kioskExitGesture",
}
EXIT_GESTURES = (0, 1, 2, 3)
# Fully's "Kiosk Mode PIN"; Nook sends the wall panel PIN (one PIN for everything).
FULLY_PIN_KEY = "kioskPin"
# "Enable Kiosk Mode" can only be switched on the panel itself (Fully refuses it
# from Remote Admin); once on, the kiosk_lock switch locks/unlocks it remotely.
FULLY_KIOSK_MODE_KEY = "kioskMode"
# Other entities we need from the same device.
_CURRENT_PAGE = ("sensor", "current_page")
_CLEAR_CACHE = ("button", "clear_browser_cache")
# Brightness can read back a step off what was written.
_TOLERANCE = 2


def clean_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Keep known keys with valid values. A missing key means "not managed"."""
    out: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        spec = KIOSK_SETTINGS.get(key)
        if spec is None or value is None or value == "":
            continue
        _domain, bounds = spec
        if bounds is None:
            out[key] = bool(value)
            continue
        try:
            number = round(float(value))
        except (TypeError, ValueError):
            continue
        out[key] = int(min(bounds[1], max(bounds[0], number)))
    return out


def effective_settings(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """House defaults with the panel's overrides on top."""
    return {**clean_settings(defaults), **clean_settings(overrides)}


def fully_settings(hass: HomeAssistant, device_id: str) -> dict[str, Any] | None:
    """All of Fully's settings for a device, as HA's Fully integration last fetched them.

    Its coordinator calls Fully's getSettings with every update and keeps the result
    under data["settings"]. None if the device or its data isn't there.
    """
    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != FULLY_DOMAIN:
            continue
        coordinator = getattr(entry, "runtime_data", None)
        data = getattr(coordinator, "data", None)
        settings = data.get("settings") if isinstance(data, dict) else None
        if isinstance(settings, dict):
            return settings
    return None


def _config_value(settings: dict[str, Any] | None, key: str) -> Any:
    """One of our FULLY_CONFIG_KEYS settings as Fully reports it, in our terms."""
    if not settings:
        return None
    raw = settings.get(FULLY_CONFIG_KEYS[key])
    if raw is None or raw == "":
        return None
    _domain, bounds = KIOSK_SETTINGS[key]
    if bounds is None:
        return raw if isinstance(raw, bool) else str(raw).lower() == "true"
    try:
        return round(float(raw))
    except (TypeError, ValueError):
        return None


def kiosk_mode(settings: dict[str, Any] | None) -> bool | None:
    """Fully's "Enable Kiosk Mode", or None if unknown."""
    if not settings or settings.get(FULLY_KIOSK_MODE_KEY) is None:
        return None
    raw = settings[FULLY_KIOSK_MODE_KEY]
    return raw if isinstance(raw, bool) else str(raw).lower() == "true"


def device_entities(hass: HomeAssistant, device_id: str) -> dict[str, str]:
    """Map our setting keys (plus current_page) to this Fully device's entity ids."""
    reg = er.async_get(hass)
    wanted = {
        **{k: d for k, (d, _b) in KIOSK_SETTINGS.items()},
        _CURRENT_PAGE[1]: _CURRENT_PAGE[0],
        _CLEAR_CACHE[1]: _CLEAR_CACHE[0],
    }
    found: dict[str, str] = {}
    for entry in er.async_entries_for_device(reg, device_id):
        if entry.platform != FULLY_DOMAIN:
            continue
        for key, domain in wanted.items():
            if entry.domain != domain or key in found:
                continue
            if entry.translation_key == key or entry.entity_id.endswith(f"_{key}"):
                found[key] = entry.entity_id
    return found


def fully_devices(hass: HomeAssistant) -> list[dict[str, str]]:
    """Fully Kiosk devices HA knows about, for the panel's device picker."""
    from homeassistant.helpers import device_registry as dr

    reg = er.async_get(hass)
    device_ids = {e.device_id for e in reg.entities.values() if e.platform == FULLY_DOMAIN and e.device_id}
    devices = dr.async_get(hass)
    out = []
    for device_id in device_ids:
        device = devices.async_get(device_id)
        if device is not None:
            out.append({"id": device_id, "name": device.name_by_user or device.name or device_id})
    return sorted(out, key=lambda d: d["name"].lower())


def _origin(url: str) -> str:
    parsed = urlparse(url or "")
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def panel_url(hass: HomeAssistant, panel_id: str, current_page: str = "") -> str:
    """Where the panel should be: the shipped wall app, with its own ?device=.

    Uses HA's internal URL; if none is configured, the server the panel is already
    talking to (it can reach that one)."""
    base = ""
    try:
        from homeassistant.helpers.network import get_url

        base = get_url(hass, allow_external=False, allow_cloud=False, prefer_external=False)
    except Exception:  # noqa: BLE001 - NoURLAvailableError and friends
        base = ""
    base = base or _origin(current_page)
    return f"{base.rstrip('/')}{WALL_APP_PATH}?device={panel_id}" if base else ""


def page_ok(current_page: str, panel_id: str) -> bool:
    """On the shipped wall app with the right device (the app may add its own ?_v=)."""
    parsed = urlparse(current_page or "")
    if parsed.path != WALL_APP_PATH:
        return False
    return parse_qs(parsed.query).get("device", [""])[0] == panel_id


def _read(hass: HomeAssistant, entity_id: str | None, domain: str) -> Any:
    state = hass.states.get(entity_id) if entity_id else None
    if state is None or state.state in ("unknown", "unavailable", ""):
        return None
    if domain == "switch":
        return state.state == "on"
    try:
        return round(float(state.state))
    except (TypeError, ValueError):
        return None


def read_current(hass: HomeAssistant, device_id: str) -> dict[str, Any]:
    """The device's current values for every setting HA can read (for "Import from panel")."""
    entities = device_entities(hass, device_id)
    settings = fully_settings(hass, device_id)
    out = {}
    for key, (domain, _bounds) in KIOSK_SETTINGS.items():
        if key in FULLY_CONFIG_KEYS:
            value = _config_value(settings, key)
        else:
            value = _read(hass, entities.get(key), domain)
        if value is not None:
            out[key] = value
    return out


def panel_status(
    hass: HomeAssistant, panel: Any, defaults: dict[str, Any], *, pin: str = ""
) -> dict[str, Any]:
    """Target vs actual for one wall panel. pin: the wall PIN to keep Fully's menu PIN at."""
    device_id = getattr(panel, "linked_kiosk_device", None)
    if device_id is None:
        device_id = getattr(panel, "kiosk_device", "") or ""
    if not device_id:
        return {"linked": False}
    entities = device_entities(hass, device_id)
    page_entity = entities.get(_CURRENT_PAGE[1])
    page_state = hass.states.get(page_entity) if page_entity else None
    online = page_state is not None and page_state.state != "unavailable"
    current_page = page_state.state if online else ""
    target = effective_settings(defaults, getattr(panel, "kiosk_overrides", {}) or {})
    fully = fully_settings(hass, device_id) if online else None
    settings = {}
    for key, value in target.items():
        domain, bounds = KIOSK_SETTINGS[key]
        if key in FULLY_CONFIG_KEYS:
            actual = _config_value(fully, key)
        else:
            actual = _read(hass, entities.get(key), domain)
        if actual is None:
            ok = None  # can't read it (e.g. brightness while the screen is off)
        elif bounds is None:
            ok = actual == value
        else:
            ok = abs(actual - value) <= (_TOLERANCE if "brightness" in key else 0)
        settings[key] = {"target": value, "actual": actual, "ok": ok, "entity_id": entities.get(key)}
    if pin:
        # Never echoed back: only whether the panel's PIN matches.
        reported = (fully or {}).get(FULLY_PIN_KEY)
        settings["menu_pin"] = {
            "target": None,
            "actual": None,
            "ok": None if reported is None else str(reported) == pin,
            "entity_id": None,
        }
    url = panel_url(hass, panel.id, current_page)
    on_app = page_ok(current_page, panel.id) if online else None
    in_sync = bool(online and on_app and all(s["ok"] is not False for s in settings.values()))
    return {
        "linked": True,
        "device_id": device_id,
        "online": online,
        "current_page": current_page,
        "expected_url": url,
        "page_ok": on_app,
        "settings": settings,
        "in_sync": in_sync,
        "kiosk_mode": kiosk_mode(fully),
    }


async def async_apply(
    hass: HomeAssistant, panel: Any, defaults: dict[str, Any], *, force: bool = False, pin: str = ""
) -> list[str]:
    """Write whatever differs to the panel. Returns what changed (human readable).

    force (an explicit sync / save) also rewrites Fully's start URL, which HA can't read
    back: the panel may show the right page while still booting into an old one."""
    status = panel_status(hass, panel, defaults, pin=pin)
    if not status.get("linked") or not status.get("online"):
        return []
    device_id = status["device_id"]
    changes: list[str] = []
    for key, info in status["settings"].items():
        if key == "menu_pin":
            if info["ok"] is False or (info["ok"] is None and force):
                await hass.services.async_call(
                    FULLY_DOMAIN, "set_config", {"device_id": device_id, "key": FULLY_PIN_KEY, "value": pin}, blocking=True
                )
                changes.append("menu PIN")
            continue
        if key in FULLY_CONFIG_KEYS:
            # Readable: write only when it differs. Unreadable: only on an explicit sync.
            if info["ok"] is False or (info["ok"] is None and force):
                await hass.services.async_call(
                    FULLY_DOMAIN,
                    "set_config",
                    {"device_id": device_id, "key": FULLY_CONFIG_KEYS[key], "value": info["target"]},
                    blocking=True,
                )
                changes.append(f"{key} → {info['target']}")
            continue
        entity_id = info["entity_id"]
        # Unreadable values (ok is None) are written too: we can't tell they're right.
        if info["ok"] is True or not entity_id:
            continue
        domain, _bounds = KIOSK_SETTINGS[key]
        if domain == "switch":
            await hass.services.async_call(
                "switch", "turn_on" if info["target"] else "turn_off", {"entity_id": entity_id}, blocking=True
            )
        else:
            await hass.services.async_call(
                "number", "set_value", {"entity_id": entity_id, "value": info["target"]}, blocking=True
            )
        changes.append(f"{key} → {info['target']}")
    url = status["expected_url"]
    if url and (force or not status["page_ok"]):
        await hass.services.async_call(
            FULLY_DOMAIN, "set_config", {"device_id": device_id, "key": "startURL", "value": url}, blocking=True
        )
        if not status["page_ok"]:
            await async_fresh_load(hass, device_id, url)
            changes.append(f"page → {url}")
    if changes:
        _LOGGER.info("Nook: synced wall panel %s (%s)", panel.id, "; ".join(changes))
    return changes


async def async_fresh_load(hass: HomeAssistant, device_id: str, url: str) -> None:
    """Clear Fully's browser cache, then load the page.

    Switching between copies of the app (or to a new version) with stale cached files gave
    odd glitches; clearing first avoids them. Without the button we still load the page."""
    button = device_entities(hass, device_id).get(_CLEAR_CACHE[1])
    if button:
        await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.services.async_call(FULLY_DOMAIN, "load_url", {"device_id": device_id, "url": url}, blocking=True)


def bundled_wall_version(www_dir: Any) -> str:
    """Version of the wall app this Nook install ships (blocking file read)."""
    import json

    try:
        return str(json.loads((www_dir / "wall" / "version.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""
