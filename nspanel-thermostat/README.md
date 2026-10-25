# Nook wall panel app (NSPanel)

The touch-screen thermostat that runs on each wall panel (e.g. Sonoff NSPanel Pro Gen2) in a
kiosk browser. It replaced the original v1 app, now in
[`../deprecated/nspanel-thermostat-v1/`](../deprecated/nspanel-thermostat-v1/).

## How panels get it

The integration ships a copy of this app and serves it at:

```
http://<home-assistant>:8123/nook/static/wall/index.html?device=<panel id>
```

Set that as the kiosk browser's start URL. The app checks `version.json` every minute and
reloads itself when it changes, so each HACS update of Nook reaches the panels automatically.
`?device=` picks which wall panel (from the Nook sidebar → Wall panels) this screen is.

## Changing the app

1. Edit the files here.
2. **Bump `version.json`** — panels only reload when the version changes.
3. Run `python3 scripts/sync_wall_app.py` to refresh the integration's copy
   (`custom_components/nook/www/wall/`). `tests/test_wall_app_bundle.py` fails if
   you forget.
4. Bump the integration version in `manifest.json` and release as usual.

## Modes

- **Standalone** (on a panel): connects with the HA URL + long-lived token entered once on
  the setup page; everything else comes from Nook (`nook/get_wall_panel_config`).
- **Embedded** (`?embedded=1`, used by the Nook panel's Wall panels preview): borrows the
  logged-in Home Assistant session from the page around it. `?preview=1` also turns off the
  screensaver and display sleep.

## Leftovers

`apk/`, `capacitor.config.json`, `package.json` and `js/native-shell.js` are from an Android
wrapper that was abandoned in favour of a kiosk browser.
