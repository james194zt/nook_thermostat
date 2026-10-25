# ⚠️ Deprecated — NSPanel wall UI v1

**Retired on 2026-10-11. Kept for reference only — don't deploy or change it.**

This was the first wall-panel app, adapted from the old HADashboard thermostat. It has been
replaced by the app in [`../../nspanel-thermostat/`](../../nspanel-thermostat/) (formerly
`nspanel-thermostat-v2`), which the integration now ships and keeps up to date through HACS.

What changed since this version:

- The current app is served by the integration at `/nook/static/wall/` — no copying
  files into `/config/www`, and panels reload themselves after each Nook update.
- Embedded mode works in the Nook panel's Wall panels preview.
- The Android APK / Capacitor wrapper in `apk/` was abandoned; panels run in a kiosk browser.

If a panel still opens `/local/nspanel-thermostat/`, point its kiosk browser at:

```
http://<home-assistant>:8123/nook/static/wall/index.html?device=<panel id>
```
