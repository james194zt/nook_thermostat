# Nook

Home Assistant custom integration that replaces Better Thermostat-style heating control with a **Nook** hub:

- **House climate** `climate.nook_home` — schedule, Eco / Boost / Away, window & summer hold
- **Room climates** `climate.nook_<room>` — own sensors/setpoints; each room can call for heat
- **Boiler demand** — heats when the house **or** any room needs heat
- **Nook Intelligence (house only)** — True Radiant, Auto-Schedule, Home/Away, Leaf, Safety Temps, Time-to-Temp, Seasonal Savings, Adaptive Comfort
- **Energy History** — 24h heat timeline with setpoint changes and Leaf days
- **HA sidebar** — Overview, Energy, Rooms, Schedule, Wall panels, Settings
- **Wall panels** — optional per-panel temperature PIN lock; multi-sensor rooms

## Install

### HACS (recommended)

1. HACS → Integrations → Custom repositories → add `https://github.com/james194zt/nook_thermostat` (category: Integration)
2. Install **Nook**
3. Restart Home Assistant
4. Settings → Devices & services → Add integration → **Nook**

### Manual

Copy `custom_components/nook` into your HA `config/custom_components/` folder, restart, then add the integration.

## Setup

1. Pick **heater/boiler** entity (switch, input_boolean, or climate) and **house temperature sensor**
2. Optional: window sensors, person for Away, Eco/Boost/Away temps
3. Open the **Nook** sidebar:
   - **Rooms** — add TRV climates (creates `climate.nook_*`); optional extra temp sensors (averaged)
   - **Schedule** — 7-day comfort blocks
   - **Energy** — heat runtime history + Leaf days
   - **Wall panels** — one entry per physical NSPanel (optional temperature lock)

## Dashboard card

The integration loads its own card — no resource to add. On a dashboard choose **Add card → Nook**.

- Dial: tap **− / +** or drag the knob round the arc to change the setpoint
- Heat / Off, and Eco / Boost / Away (tap an active preset again to clear it)
- Status pills (boiler, Leaf, Away, window, summer) and room tiles in your Rooms order — tap a room for its controls
- **Compact** layout for small spaces; every section can be hidden in the card editor

```yaml
type: custom:nook-card
entity: climate.nook_nook_home  # optional — found automatically
layout: full        # or compact
show_status: true
show_modes: true
show_rooms: true
```

### Radiators card

**Add card → Nook Radiators** lists every room's radiator / TRV with its own controls. Use it
instead of HA's thermostat card on the TRVs themselves: Nook owns the TRV setpoints, so a TRV
changed directly is put back to Nook's target on the next update. This card changes the Nook
room instead, and Nook then sets the TRV.

- Per room: small dial (drag or **− / +**), Heat / Off, Eco / Boost, and what it's doing
  ("Heating to 21°", "Window open — paused", "until 22:00" for a manual change that lasts until
  the next schedule change)
- TRV status: online / offline, battery and valve opening (found on the TRV's device), and
  "TRV at 18°" while Nook is still sending a new setpoint. Tap a pill for that entity's details
- Header: how many rooms are heating, TRVs offline, boiler on

```yaml
type: custom:nook-radiators-card
title: Radiators         # optional
entities:                # optional — all Nook rooms, in your Rooms order, when left out
  - climate.nook_nook_kitchen
show_trv: true
show_modes: true
```

## NSPanel / wall UI

The wall panel app lives in [`nspanel-thermostat/`](nspanel-thermostat/) and **ships with the
integration** — HACS updates it, nothing to copy into `/config/www`. Set each panel's kiosk
browser to:

```
http://<home-assistant>:8123/nook/static/wall/index.html?device=<panel id>
```

Panels reload themselves within a minute of a Nook update.

1. Add the panel in the Nook sidebar → **Wall panels** (the Preview shows exactly what it will look like)
2. Open the URL on the panel; enter the HA URL + token once on the setup page
3. Full config loads from Nook via `nook/get_wall_panel_config`
4. Locked panels prompt for the house **Wall PIN** before setpoint/mode changes; unlock lasts until screensaver/idle

The original v1 app is retired and kept only for reference in [`deprecated/`](deprecated/).
## Nook Intelligence (house only)

Intelligence applies to **`climate.nook_home` / the boiler**, not per-room TRV learning.

| Feature | Nook setting | Behaviour |
|--------------|--------------|-----------|
| **True Radiant / Early-On** | Settings → True Radiant (default On) | Learns °C/h warm-up; preheats so the house hits the scheduled temp *at* block start; stops early by the measured radiator coast to limit overshoot. |
| **Auto-Schedule** | Settings → Auto-Schedule (default Off) | The same change at the same half-hour on the same weekday, on 2+ different days (within 1°C, last 4 weeks), becomes a schedule block or adjusts one. |
| **Home/Away Assist** | Presence entities + Away delay | Away Eco when **all** presence entities are away, after the delay. |
| **Leaf** | Settings → Leaf coaching (default On) | Live Leaf when efficient; earned Leaf hours only accumulate. |
| **Safety Temperatures** | Settings → Safety (default On, 7°C) | Forces heat if the house sensor hits the min floor (even Away/Off/summer). |
| **Time-to-Temp** | Automatic from warm-up model | ETA on Overview dial and NSPanel while heating. |
| **Energy History** | Energy tab | 24h heat segments + setpoint bubbles + Leaf per day. |
| **Seasonal Savings** | Settings → Seasonal Savings | Over 21 days lowers each schedule block 0.1°C every 3 days (max 0.5°C); a block you turn up eases off and is left alone; at the end the result is saved into the schedule. Stop (Energy banner) puts it back. |
| **Cold-weather preheat** | Settings → Cold-weather preheat | Lets preheat start up to 4 h before a block (normally 2 h) when the house warms slowly. |
| **Temperature Lock** | Wall PIN + per-panel lock | NSPanel only; HA sidebar stays unlocked. |

Optional: set an **outdoor temp sensor** so preheat learns (from your own heating runs) how much cold weather slows warming up.

## Migrating from Better Thermostat

1. Install Nook and add rooms pointing at the same TRV climates BT used
2. Point wall panels / automations at `climate.nook_home` (and room entities as needed)
3. Disable or remove the Better Thermostat integration once Nook is behaving

NSPanel attributes kept compatible: `hvac_action`, `preset_mode` (`none`/`eco`/`boost`), `window_open`, `summer_mode_state`, plus `safety_active`, `time_to_temp_minutes`, Leaf attrs.

## WebSocket API (for panels / tools)

| Type | Purpose |
|------|---------|
| `nook/get_state` | Full config + live snapshot |
| `nook/update_settings` | Eco/Boost/Away, intelligence, safety, PIN, etc. |
| `nook/update_schedule` | 7-day schedule |
| `nook/update_rooms` | Room list (reloads platforms) |
| `nook/get_energy_history` | Energy History days + seasonal banner |
| `nook/stop_seasonal_savings` | Clear seasonal ramp and disable |
| `nook/verify_wall_pin` | Validate wall PIN (NSPanel unlock) |
| `nook/list_wall_panels` | List wall panels |
| `nook/upsert_wall_panel` | Create/update wall panel |
| `nook/delete_wall_panel` | Remove wall panel |
| `nook/get_wall_panel_config` | Full config payload for a wall screen |

## License

MIT
