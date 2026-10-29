/**
 * Nook — HA sidebar panel.
 * Fox Plant–style shell + dial overview / schedule.
 * @version 0.7.5
 */
const PANEL_VERSION = "0.7.5";

/* —— Labels ——
   Every word the panel shows comes from a language file (www/i18n/<lang>.json, keys like
   "settings.windows.pause_after"), loaded before anything renders. It follows HA's language:
   English is loaded first, then the file for HA's language on top (e.g. de.json), so a
   missing file — or a label a translation hasn't got yet — shows in English. Adding a
   language is just adding a file. {name} placeholders are filled from the values given;
   callers escape anything that comes from the user or HA. tests/test_panel_i18n.py checks
   keys and leftovers. */
async function loadLabels(lang) {
  try {
    const res = await fetch(new URL(`i18n/${lang}.json?v=${PANEL_VERSION}`, import.meta.url));
    if (res.ok) return await res.json();
    if (lang === "en") console.error(`Nook: couldn't load labels (HTTP ${res.status})`);
  } catch (err) {
    if (lang === "en") console.error("Nook: couldn't load labels", err);
  }
  return null;
}

/** HA's language: it sets <html lang>; else the language picked in HA, else the browser's. */
function haLanguage() {
  let picked = "";
  try {
    picked = JSON.parse(localStorage.getItem("selectedLanguage") || "null") || "";
  } catch {
    // Not set, or not JSON.
  }
  return String(document.documentElement.lang || picked || navigator.language || "en").toLowerCase();
}

const LANG = haLanguage();
const STRINGS = await (async () => {
  const labels = { ...((await loadLabels("en")) || {}) };
  // "de-de" → de-de.json, else de.json. English (any en-…) is already the base.
  for (const lang of [...new Set([LANG, LANG.split("-")[0]])]) {
    if (lang === "en" || lang.startsWith("en-")) break;
    const local = await loadLabels(lang);
    if (local) return { ...labels, ...local };
  }
  return labels;
})();

/** A label, with {placeholders} filled in. A missing key shows as the key itself. */
function t(key, vars) {
  let text = STRINGS[key];
  if (text == null) {
    console.warn(`Nook: no label for "${key}"`);
    return key;
  }
  if (vars) text = text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
  return text;
}

/** Singular/plural label: "<key>.one" or "<key>.other", with {count}. */
function tn(key, count, vars = {}) {
  return t(`${key}.${Number(count) === 1 ? "one" : "other"}`, { count, ...vars });
}

const NAV = ["overview", "energy", "schedule", "wall_panels", "settings"].map((id) => ({ id, label: t(`nav.${id}`) }));

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_LABELS = Object.fromEntries(DAYS.map((d) => [d, t(`day.${d}`)]));
const DAY_SHORT = Object.fromEntries(DAYS.map((d) => [d, t(`day_short.${d}`)]));
const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].map((m) => t(`month.${m}`));
// New-room defaults (match RoomConfig / DEFAULT_TARGET_TEMP / DEFAULT_ECO_TEMP).
const ROOM_TEMP_DEFAULTS = { follow_house: true, house_offset: 0, hold_ends: "house_change", target_temp: 20, eco_temp: 16 };
// TRV Configuration: the HA domains a device setting can be, with the service + field
// that sets it (switch and button have their own services).
const TRV_CONFIG_DOMAINS = {
  number: ["set_value", "value"],
  select: ["select_option", "option"],
  switch: null,
  text: ["set_value", "value"],
  time: ["set_value", "time"],
  button: null,
};
const HEAT_ORANGE = "#F57C00";
const HEAT_ORANGE_SOFT = "#FF9800";
// The integration ships a copy of the wall app (scripts/sync_wall_app.py);
// the preview runs it embedded, so it always matches the installed version.
const WALL_APP_URL = "/nook/static/wall/index.html";
// Wall screen shapes (stored as the panel's "model"): the preview renders the app at this
// size. The wall app itself lays out from its real screen, so this never changes the panel.
// The first entry is the default (matches DEFAULT_WALL_PANEL_MODEL); old hardware ids fall back to it.
const WALL_MODELS = [
  { id: "square", ratio: "1:1", width: 480, height: 480 },
  { id: "tall", ratio: "9:16", width: 405, height: 720 },
  { id: "landscape", ratio: "16:10", width: 960, height: 600 },
  { id: "wide", ratio: "2:1", width: 720, height: 360 },
  // A square panel with extras: the Nook Panel Helper app (hides Sonoff's floating button, health).
  { id: "nspanel_pro", ratio: "1:1", width: 480, height: 480, shape: "square" },
].map((m) => ({ ...m, label: t(`wall.shape.${m.id}`), hint: t(`wall.shape.${m.id}.hint`) }));

function wallModel(id) {
  return WALL_MODELS.find((m) => m.id === id) || WALL_MODELS[0];
}

/** The plain shape a screen type lays out as (NSPanel Pro → square). */
function wallShapeId(id) {
  const m = wallModel(id);
  return m.shape || m.id;
}

/** The shape a reported screen is (same thresholds as the wall app's layouts). */
function wallShapeFor(width, height) {
  const r = width / height;
  if (r >= 1.75) return wallModel("wide");
  if (r >= 1.25) return wallModel("landscape");
  if (r <= 0.8) return wallModel("tall");
  return wallModel("square");
}

const STYLES = `
:host {
  display: block;
  height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  font-family: var(--ha-font-family, Roboto, Noto Sans, sans-serif);
  background: var(--primary-background-color);
  color: var(--primary-text-color);
  --nt-radius: 14px;
  --nt-accent: #08979C;
  --nt-accent-hi: #19D4DE;
  --nt-green: #52C41A;
  --nt-amber: #FA8C16;
  --nt-red: #e53935;
  --nt-heat: ${HEAT_ORANGE};
  --nt-heat-soft: ${HEAT_ORANGE_SOFT};
  --nt-nest-blue: #5BA3D9;
  --nt-nest-tab: #4285F4;
}
.shell { position: relative; display: block; min-height: 100%; background: var(--primary-background-color); }
.page-header {
  position: sticky; top: 0; z-index: 10;
  border-bottom: 1px solid var(--divider-color);
  background: var(--app-header-background-color, var(--primary-background-color));
}
.panel-header-top { display: flex; align-items: flex-start; }
.panel-ha-menu-btn {
  display: none; flex-shrink: 0; align-items: center; justify-content: center;
  width: 48px; height: 48px; margin: 8px 0 0 4px; padding: 0; border: none;
  border-radius: 50%; background: transparent; color: var(--primary-text-color); cursor: pointer;
}
.panel-ha-menu-btn:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
:host(.narrow) .panel-ha-menu-btn, .shell.narrow .panel-ha-menu-btn { display: inline-flex; }
@media (max-width: 870px) {
  .panel-ha-menu-btn { display: inline-flex; }
  .panel-brand-row { padding: 12px 12px 4px 0; }
}
.panel-brand-row {
  display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; padding: 12px 16px 4px;
}
.panel-brand-mark {
  width: 40px; height: 40px; flex-shrink: 0; border-radius: 12px; overflow: hidden;
  box-shadow: 0 4px 12px rgba(8,151,156,0.35), inset 0 0 0 1px rgba(255,255,255,0.08);
}
.panel-brand-mark svg { display: block; width: 100%; height: 100%; }
.panel-brand-title { font-size: 18px; font-weight: 600; line-height: 1.2; }
.panel-brand-sub { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; }
.tab-bar {
  display: flex; align-items: stretch; gap: 0; padding: 0 8px;
  overflow-x: auto; scrollbar-width: none;
}
.tab-bar::-webkit-scrollbar { display: none; }
.tab {
  flex-shrink: 0; padding: 14px 20px 12px; border: none; border-bottom: 2px solid transparent;
  background: transparent; color: var(--secondary-text-color); font-size: 14px; font-weight: 500;
  font-family: inherit; cursor: pointer; white-space: nowrap;
}
.tab:hover { color: var(--primary-text-color); }
.tab.active { color: var(--primary-text-color); font-weight: 600; border-bottom-color: var(--primary-text-color); }
.shell.narrow .tab { padding: 12px 14px 10px; font-size: 13px; }
.main { display: block; width: 100%; }
.main-inner {
  max-width: 1100px; width: 100%; margin: 0 auto; padding: 20px 24px 48px; box-sizing: border-box;
}
.shell.narrow .main-inner { padding: 16px; }
.header { margin-bottom: 18px; }
.header h1 { margin: 0; font-size: 26px; font-weight: 600; letter-spacing: -0.02em; }
.header p { margin: 6px 0 0; color: var(--secondary-text-color); font-size: 14px; }
.card {
  background: var(--card-background-color); border-radius: var(--nt-radius);
  padding: 18px 20px; margin-bottom: 14px;
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,0.08));
  border: 1px solid var(--divider-color, transparent);
}
.card-title {
  font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--secondary-text-color); margin: 0 0 14px;
}
.stats-row {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 14px;
}
.stat {
  --tone: var(--secondary-text-color);
  display: flex; align-items: center; gap: 12px;
  background: var(--card-background-color); border-radius: var(--nt-radius);
  padding: 14px 16px; border: 1px solid var(--divider-color, transparent);
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,0.06));
}
.stat.heat { --tone: var(--nt-heat-soft); }
.stat.warn { --tone: var(--nt-amber); }
.stat.good { --tone: var(--nt-accent-hi); }
.stat-icon {
  flex-shrink: 0; width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center;
  color: var(--tone); background: color-mix(in srgb, var(--tone) 14%, transparent);
}
.stat-icon svg { width: 22px; height: 22px; }
.stat .label { font-size: 12px; color: var(--secondary-text-color); font-weight: 500; }
.stat .value { font-size: 18px; font-weight: 600; letter-spacing: -0.01em; margin-top: 1px; }
.stat.heat .value, .stat.warn .value { color: var(--tone); }

/* —— Overview detail cards —— */
.ov-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-bottom: 14px; }
.ov-grid > .card { margin-bottom: 0; display: flex; flex-direction: column; }
.leaf-week { flex: 1; display: flex; flex-direction: column; margin-top: 18px; min-height: 120px; }
.leaf-week-title { display: flex; justify-content: space-between; font-size: 12px; color: var(--secondary-text-color); margin-bottom: 10px; }
.leaf-week-bars { flex: 1; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 8px; align-items: end; }
.leaf-day { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 6px; }
.leaf-day-track {
  flex: 1; width: 100%; max-width: 34px; min-height: 60px; position: relative; border-radius: 8px;
  background: color-mix(in srgb, var(--primary-text-color) 5%, transparent);
}
.leaf-day-bar {
  position: absolute; left: 0; right: 0; bottom: 0; border-radius: 8px; min-height: 4px;
  background: color-mix(in srgb, var(--primary-text-color) 22%, transparent);
}
.leaf-day.earned .leaf-day-bar { background: linear-gradient(180deg, #7BE05A, var(--nt-green)); }
.leaf-day-label { font-size: 11px; color: var(--secondary-text-color); font-weight: 500; }
.leaf-day.today .leaf-day-label { color: var(--primary-text-color); font-weight: 700; }
.leaf-day.today .leaf-day-track { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary-text-color) 25%, transparent); }
.card-head { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
.card-head .card-title { margin: 0; }
.card-head-text { flex: 1; min-width: 0; }
.card-sub { margin: 3px 0 0; font-size: 13px; color: var(--secondary-text-color); line-height: 1.4; }
.card-icon {
  flex-shrink: 0; width: 36px; height: 36px; border-radius: 11px; display: grid; place-items: center;
  color: var(--secondary-text-color); background: color-mix(in srgb, var(--primary-text-color) 7%, transparent);
}
.card-icon svg { width: 20px; height: 20px; }
.card-icon.leaf { color: var(--nt-green); background: color-mix(in srgb, var(--nt-green) 14%, transparent); }
.card-icon.intel { color: var(--nt-accent-hi); background: color-mix(in srgb, var(--nt-accent) 16%, transparent); }
.card-icon.heat { color: var(--nt-heat-soft); background: color-mix(in srgb, var(--nt-heat) 14%, transparent); }
.card-icon.warn { color: var(--nt-amber); background: color-mix(in srgb, var(--nt-amber) 14%, transparent); }
/* A card that opens and closes from its header (closed: header only). */
.collapse-head { cursor: pointer; user-select: none; border-radius: 12px; }
.collapse-head:focus-visible { outline: 2px solid var(--nt-accent); outline-offset: 4px; }
.card.collapsed .collapse-head { margin-bottom: 0; }
.collapse-chev { flex-shrink: 0; display: grid; place-items: center; color: var(--secondary-text-color); }
.collapse-chev svg { width: 24px; height: 24px; transition: transform 0.2s ease; }
.collapse-head[aria-expanded="true"] .collapse-chev svg { transform: rotate(180deg); }
.collapse-body > .set-row:first-child { border-top: 0; padding-top: 0; }
.dlg-collapse-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.dlg-collapse-head .collapse-chev svg { width: 20px; height: 20px; }
.dlg-section .dlg-collapse-desc { margin-top: -8px; }
.dlg-collapse-body:not([hidden]) { display: flex; flex-direction: column; gap: 14px; }

/* —— Settings —— */
.set-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
.set-field { min-width: 0; }
.set-field-label { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.set-group-title { font-size: 12px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); padding: 14px 0 2px; }
.card-head + .set-group-title { padding-top: 0; }
.set-group-title + .set-row { border-top: 0; }
#sensorsCard .room-card { cursor: default; background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); box-shadow: none; gap: 8px; }
#sensorsCard .room-card:hover { border-color: var(--divider-color, transparent); }
#sensorsCard .room-grid + .set-group-title { padding-top: 18px; }
.sensor-card-entity { font-size: 12px; color: var(--secondary-text-color); margin-top: -6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sensor-card-badges { display: inline-flex; flex-wrap: wrap; gap: 4px; }
.sensor-card .room-card-top .set-remove { margin: -6px -8px -6px 0; }
.sensor-watch-add { margin-top: 18px; }
.set-field .set-row-desc { margin-top: 6px; }
.set-row {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 0; border-top: 1px solid var(--divider-color);
}
.card-head + .set-row { border-top: 0; padding-top: 0; }
.set-row-text { min-width: 0; }
.set-row-name { font-size: 14px; font-weight: 500; }
.set-row-desc { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; line-height: 1.4; }
.set-row-control { flex-shrink: 0; }
.num-input {
  display: inline-flex; align-items: center; border-radius: 10px; overflow: hidden;
  border: 1px solid var(--divider-color); background: var(--card-background-color);
}
.num-input input { width: 76px; border: 0; border-radius: 0; text-align: right; padding: 8px 10px; background: transparent; }
.num-input input:focus { outline: none; }
.num-input:focus-within { border-color: var(--nt-accent-hi); }
.num-input span { padding: 0 10px 0 0; font-size: 13px; color: var(--secondary-text-color); }
.num-input.stepper input { width: 44px; text-align: center; padding: 8px 2px; -moz-appearance: textfield; }
.num-input.stepper input::-webkit-inner-spin-button, .num-input.stepper input::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.num-input.stepper button {
  border: 0; background: transparent; color: var(--primary-text-color); width: 36px; height: 36px;
  font-size: 18px; line-height: 1; cursor: pointer; padding: 0;
}
.num-input.stepper button:hover:not(:disabled) { background: var(--secondary-background-color); }
.num-input.stepper button:disabled { opacity: 0.35; cursor: default; }
.switch { position: relative; display: inline-block; width: 44px; height: 26px; cursor: pointer; }
.switch input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
.switch span {
  position: absolute; inset: 0; border-radius: 999px; pointer-events: none;
  background: color-mix(in srgb, var(--primary-text-color) 22%, transparent); transition: background 0.15s ease;
}
.switch span::after {
  content: ""; position: absolute; top: 3px; left: 3px; width: 20px; height: 20px; border-radius: 50%;
  background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.15s ease;
}
.switch input:checked + span { background: var(--nt-accent); }
.switch input:checked + span::after { transform: translateX(18px); }
.switch input:focus-visible + span { outline: 2px solid var(--nt-accent-hi); outline-offset: 2px; }
.set-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
.set-list-empty { margin: 0 0 10px; font-size: 13px; color: var(--secondary-text-color); }
.set-list-item {
  display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 12px;
  background: color-mix(in srgb, var(--primary-text-color) 4%, transparent);
}
.set-avatar {
  flex-shrink: 0; width: 34px; height: 34px; border-radius: 50%; object-fit: cover;
  display: grid; place-items: center; font-size: 14px; font-weight: 700; color: #fff;
  background: linear-gradient(145deg, var(--nt-accent-hi), var(--nt-accent));
}
.set-avatar.icon { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); color: var(--secondary-text-color); border-radius: 10px; }
.set-avatar.icon svg { width: 18px; height: 18px; }
.set-list-text { flex: 1; min-width: 0; }
.set-list-name { font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.set-list-text code {
  display: block; padding: 0; background: none; font-size: 11px; color: var(--secondary-text-color);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.set-state {
  flex-shrink: 0; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
  background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--secondary-text-color);
}
.set-state.good { background: color-mix(in srgb, var(--nt-green) 16%, transparent); color: var(--nt-green); }
.set-state.away { background: color-mix(in srgb, var(--nt-accent) 16%, transparent); color: var(--nt-accent-hi); }
.set-state.warn { background: color-mix(in srgb, var(--nt-amber) 16%, transparent); color: var(--nt-amber); }
.set-state.bad { background: color-mix(in srgb, var(--nt-red) 16%, transparent); color: var(--nt-red); }
.set-remove {
  flex-shrink: 0; width: 32px; height: 32px; border: 0; border-radius: 50%; display: grid; place-items: center;
  background: transparent; color: var(--secondary-text-color); cursor: pointer;
}
.set-remove:hover { background: color-mix(in srgb, var(--nt-red) 14%, transparent); color: var(--nt-red); }
.set-add { margin-bottom: 4px; }
/* —— Page header with an action button —— */
/* The row owns the gap below it, so it's the same whether the button sits beside the title or wraps under it. */
.page-head-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px 16px; flex-wrap: wrap; margin-bottom: 18px; }
.page-head-row > .header { margin-bottom: 0; }
.page-head-row > button { margin-top: 4px; }
button.primary svg, button.secondary svg { vertical-align: -4px; margin: 0 6px 0 -4px; }
.empty-state { display: flex; flex-direction: column; align-items: flex-start; gap: 14px; }

/* —— Wall panel list —— */
.wp-list { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
.wp-card {
  display: flex; align-items: center; gap: 14px; padding: 14px 16px; cursor: pointer;
  background: var(--card-background-color); border-radius: var(--nt-radius);
  border: 1px solid var(--divider-color, transparent);
}
.wp-card:hover { border-color: color-mix(in srgb, var(--primary-text-color) 22%, transparent); }
.wp-card.selected { border-color: var(--nt-accent-hi); }
.wp-card-text { flex: 1; min-width: 0; }
.wp-card-name { font-size: 15px; font-weight: 600; }
.wp-card-meta { font-size: 12px; color: var(--secondary-text-color); margin-top: 3px; }
.wp-card-meta strong { color: var(--primary-text-color); font-weight: 500; }
.wp-card-meta .set-state { padding: 1px 8px; font-size: 11px; }
.warn-note { color: var(--nt-amber) !important; }
.kiosk-line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.kiosk-act { padding: 2px 6px; font-size: 11px; letter-spacing: 0.04em; }
.kiosk-act:hover { color: var(--nt-accent-hi); }
.kiosk-select { width: auto; min-width: 150px; }
.kiosk-num input { width: 128px; }

/* —— Dialog (add / edit) —— */
.dlg-backdrop {
  position: fixed; inset: 0; z-index: 50; display: flex; align-items: center; justify-content: center;
  padding: 24px; background: rgba(0,0,0,0.55); backdrop-filter: blur(2px);
  animation: dlg-fade 0.15s ease;
}
.dlg {
  width: 100%; max-width: 640px; max-height: calc(100vh - 48px); display: flex; flex-direction: column;
  background: var(--card-background-color); border-radius: 20px; border: 1px solid var(--divider-color);
  box-shadow: 0 24px 60px rgba(0,0,0,0.5); animation: dlg-rise 0.18s ease;
}
.dlg-head { display: flex; align-items: center; gap: 12px; padding: 18px 20px; border-bottom: 1px solid var(--divider-color); }
.dlg-title { margin: 0; font-size: 17px; font-weight: 600; }
.dlg-x {
  margin-left: auto; flex-shrink: 0; width: 36px; height: 36px; border: 0; border-radius: 50%;
  display: grid; place-items: center; background: transparent; color: var(--secondary-text-color); cursor: pointer;
}
.dlg-x:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); color: var(--primary-text-color); }
.dlg-body {
  padding: 4px 20px 8px; overflow-y: auto;
  scrollbar-width: thin; scrollbar-color: color-mix(in srgb, var(--primary-text-color) 25%, transparent) transparent;
}
.dlg-section { display: flex; flex-direction: column; gap: 14px; padding: 16px 0; border-top: 1px solid var(--divider-color); }
.dlg-section:first-child { border-top: 0; }
.dlg-section-title { font-size: 12px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
.dlg-section .set-row { padding: 0; border-top: 0; }
.dlg-section .set-row + .set-row { padding-top: 14px; border-top: 1px solid var(--divider-color); }
.dlg-section .set-list { margin-bottom: 8px; }
.set-field-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; }
.set-field-pair > .set-row-desc { grid-column: 1 / -1; }
.dlg-section [hidden] { display: none; }
.trv-cfg > .set-row-desc:first-child:not(:last-child) { margin: 0 0 4px; }
/* Same space above and below every divider (the dialog default leaves none under a row). */
.dlg-section .trv-cfg .set-row { padding: 10px 0; }
.dlg-section .trv-cfg .set-row:last-child { padding-bottom: 0; }
.trv-cfg select, .trv-cfg input[type="text"], .trv-cfg input[type="password"] { max-width: 180px; }
.dlg-foot { display: flex; align-items: center; gap: 10px; padding: 14px 20px; border-top: 1px solid var(--divider-color); }
input[readonly] { opacity: 0.7; cursor: default; }
@keyframes dlg-fade { from { opacity: 0; } }
@keyframes dlg-rise { from { opacity: 0; transform: translateY(12px); } }
@media (max-width: 720px) {
  .dlg-backdrop { align-items: flex-end; padding: 0; }
  .dlg { max-width: none; max-height: 92vh; border-radius: 20px 20px 0 0; }
}

/* —— Rooms —— */
.room-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.room-card {
  display: flex; flex-direction: column; gap: 10px; padding: 16px 18px; cursor: pointer;
  background: var(--card-background-color); border-radius: var(--nt-radius);
  border: 1px solid var(--divider-color, transparent);
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,0.06));
  transition: border-color 0.15s ease, background 0.15s ease;
}
#roomsCard .room-card { background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); box-shadow: none; }
#roomsCard .card-head > button { flex-shrink: 0; }
.room-card:hover { border-color: color-mix(in srgb, var(--primary-text-color) 22%, transparent); }
.room-card:focus-visible { outline: 2px solid var(--nt-nest-tab); outline-offset: 2px; }
.room-card.selected { border-color: var(--nt-accent-hi); }
.room-card.heat { background: color-mix(in srgb, var(--nt-heat) 7%, var(--card-background-color)); }
.room-grid.reorderable .room-card { -webkit-user-select: none; user-select: none; -webkit-touch-callout: none; }
.room-card.dragging {
  cursor: grabbing; position: relative; z-index: 2; transform: scale(1.03); opacity: 0.94;
  border-color: var(--nt-accent-hi); box-shadow: 0 12px 28px rgba(0,0,0,0.35);
}
.room-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 24px; }
.room-card-name { font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.heat-badge { display: inline-flex; align-items: center; gap: 4px; background: color-mix(in srgb, var(--nt-heat) 16%, transparent); color: var(--nt-heat-soft); }
.heat-badge svg { width: 12px; height: 12px; }
.room-card-temps { display: flex; align-items: baseline; gap: 10px; }
.room-card-now { font-size: 34px; font-weight: 400; letter-spacing: -0.03em; line-height: 1; font-variant-numeric: tabular-nums; }
.room-card-now.unknown { color: var(--secondary-text-color); }
.room-card-target { font-size: 13px; color: var(--secondary-text-color); }
.room-card-meta { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 4px 8px; }
.room-card-sensors { font-size: 12px; color: var(--secondary-text-color); }
.room-card-calls {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding-top: 10px; border-top: 1px solid var(--divider-color); font-size: 13px; font-weight: 500;
}
.form-actions { display: flex; align-items: center; gap: 10px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--divider-color); flex-wrap: wrap; }
.save-bar {
  position: sticky; bottom: 12px; z-index: 5; margin-top: 14px;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px 16px; border-radius: var(--nt-radius);
  background: color-mix(in srgb, var(--card-background-color) 92%, transparent);
  border: 1px solid var(--divider-color); box-shadow: 0 8px 24px rgba(0,0,0,0.3);
  backdrop-filter: blur(8px);
}
.badge {
  flex-shrink: 0; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
  background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--secondary-text-color);
}
.badge.on { background: color-mix(in srgb, var(--nt-green) 16%, transparent); color: var(--nt-green); }
.badge.warn { background: color-mix(in srgb, var(--nt-amber) 18%, transparent); color: var(--nt-amber); }
.metric-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.metric {
  padding: 12px 14px; border-radius: 12px;
  background: color-mix(in srgb, var(--primary-text-color) 4%, transparent);
}
.metric-value { font-size: 26px; font-weight: 500; letter-spacing: -0.03em; line-height: 1.1; font-variant-numeric: tabular-nums; }
.metric-value small { font-size: 14px; font-weight: 500; color: var(--secondary-text-color); margin-left: 3px; letter-spacing: 0; }
.metric-label { font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
.card-foot { margin: 14px 0 0; font-size: 12px; color: var(--secondary-text-color); line-height: 1.45; }
.feature-list { display: flex; flex-direction: column; }
.feature {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 0; border-top: 1px solid var(--divider-color);
}
.feature:first-child { border-top: 0; padding-top: 0; }
.feature-name { font-size: 14px; font-weight: 500; }
.feature-desc { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; line-height: 1.35; }
.feature-value { font-size: 14px; font-weight: 600; white-space: nowrap; text-align: right; }
.feature-value small { display: block; font-size: 11px; font-weight: 500; color: var(--secondary-text-color); }
.room-rates > div + div { margin-top: 6px; }
.link-btn {
  border: 0; background: none; padding: 0; font: inherit; color: var(--primary-color);
  cursor: pointer; text-decoration: underline;
}
.notify-list { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
.notify-list .set-row { padding-top: 6px; padding-bottom: 6px; }
details.card > summary {
  list-style: none; cursor: pointer; display: flex; align-items: center; gap: 12px;
}
details.card > summary::-webkit-details-marker { display: none; }
details.card > summary .card-title { margin: 0; }
details.card > summary .chev { margin-left: auto; transition: transform 0.15s ease; color: var(--secondary-text-color); }
details.card[open] > summary .chev { transform: rotate(180deg); }
details.card[open] > summary { margin-bottom: 14px; }
.entity-rows { display: flex; flex-direction: column; gap: 10px; }
.entity-row { display: grid; grid-template-columns: 110px 1fr; gap: 12px; align-items: start; }
.entity-row-label { font-size: 12px; font-weight: 600; color: var(--secondary-text-color); padding-top: 8px; }
.entity-chips { display: flex; flex-wrap: wrap; gap: 8px; min-width: 0; }
.entity-chip {
  display: flex; flex-direction: column; gap: 1px; min-width: 0; max-width: 100%;
  padding: 7px 12px; border-radius: 10px;
  background: color-mix(in srgb, var(--primary-text-color) 5%, transparent);
}
.entity-chip-name { font-size: 13px; font-weight: 500; display: flex; gap: 8px; justify-content: space-between; }
.entity-chip-state { color: var(--secondary-text-color); font-weight: 500; }
.entity-chip-state.bad { color: var(--nt-red); }
.entity-chip code { padding: 0; background: none; font-size: 11px; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 720px) {
  .stats-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ov-grid { grid-template-columns: minmax(0, 1fr); }
  .metric-value { font-size: 22px; }
  .entity-row { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .entity-row-label { padding-top: 0; }
}
.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; margin-bottom: 12px; }
label.field {
  display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 500;
  color: var(--secondary-text-color); min-width: 140px; flex: 1;
}
input, select, textarea {
  font-family: inherit; font-size: 14px; padding: 10px 12px; border-radius: 10px;
  border: 1px solid var(--divider-color); background: var(--card-background-color);
  color: var(--primary-text-color); box-sizing: border-box; width: 100%;
}
input:disabled { opacity: 0.65; }
button.primary, button.secondary, button.danger, button.linkish {
  border: 0; border-radius: 10px; padding: 10px 16px; cursor: pointer;
  font-size: 13px; font-weight: 600; font-family: inherit;
}
button.primary {
  background: linear-gradient(90deg, var(--nt-accent-hi), var(--nt-accent)); color: #041018;
}
button.secondary {
  background: var(--secondary-background-color, color-mix(in srgb, var(--primary-text-color) 8%, transparent));
  color: var(--primary-text-color);
}
button.danger {
  background: color-mix(in srgb, var(--nt-red) 18%, transparent); color: var(--nt-red);
}
button.primary:disabled, button.secondary:disabled, button.danger:disabled { opacity: 0.45; cursor: default; }
button.linkish {
  background: transparent; color: var(--secondary-text-color); padding: 8px 10px;
  letter-spacing: 0.06em; text-transform: uppercase; font-size: 12px;
}
button.linkish:hover { color: var(--primary-text-color); }
button.linkish.active { color: var(--nt-nest-tab); }
button.compact { padding: 6px 10px; font-size: 12px; }
table.data { width: 100%; border-collapse: collapse; font-size: 13px; }
table.data th, table.data td {
  text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--divider-color);
}
table.data th {
  color: var(--secondary-text-color); font-weight: 600; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.banner { padding: 10px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 13px; }
.banner.err { background: color-mix(in srgb, var(--nt-red) 14%, transparent); color: var(--nt-red); }
.banner.ok { background: color-mix(in srgb, var(--nt-accent) 14%, transparent); color: var(--nt-accent); }
.banner.warn { background: color-mix(in srgb, var(--nt-amber) 16%, transparent); color: var(--nt-amber); }
.warn-text { color: var(--nt-amber); }
.muted { color: var(--secondary-text-color); font-size: 12px; }
code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.92em;
  padding: 1px 5px; border-radius: 4px;
  background: color-mix(in srgb, var(--primary-text-color) 6%, transparent);
}
.panel-list { display: grid; gap: 10px; }
.panel-item {
  display: flex; justify-content: space-between; gap: 12px; align-items: center;
  padding: 14px 16px; border-radius: 12px; border: 1px solid var(--divider-color);
  background: var(--secondary-background-color, transparent);
  cursor: pointer;
}
table.data tbody tr.room-row {
  cursor: pointer;
}
table.data tbody tr.room-row:hover {
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
}
table.data tbody tr.room-row.selected {
  background: color-mix(in srgb, var(--primary-color) 18%, transparent);
}
.field-toggle {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 220px;
}
.field-toggle .toggle-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--secondary-text-color);
}
.field-toggle select {
  width: 100%;
  max-width: 280px;
}
.call-heat-btn {
  border: 1px solid var(--divider-color);
  background: var(--secondary-background-color, transparent);
  color: var(--primary-text-color);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.call-heat-btn.on {
  border-color: color-mix(in srgb, var(--success-color, #4caf50) 55%, var(--divider-color));
  color: var(--success-color, #4caf50);
}
.call-heat-btn.off {
  opacity: 0.75;
}
.panel-build-footer {
  position: absolute; right: 12px; bottom: 8px; font-size: 9px;
  color: var(--secondary-text-color); opacity: 0.42; pointer-events: none;
}

/* —— Overview hero —— */
.hero {
  /* Idle: a faint teal, like the dashboard card and wall panel. Orange only while the
     boiler is actually heating (.heating), grey when off — amber here read as "heating". */
  --hero-tint: var(--nt-accent-hi);
  position: relative;
  display: grid;
  grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
  gap: 28px;
  align-items: center;
  padding: 24px 28px;
  border-radius: 20px;
  background:
    radial-gradient(70% 120% at 0% 0%, color-mix(in srgb, var(--hero-tint) 14%, transparent), transparent 65%),
    var(--card-background-color);
  border: 1px solid var(--divider-color, transparent);
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,0.08));
  overflow: hidden;
}
.hero.heating { --hero-tint: var(--nt-heat-soft); }
.hero.off { --hero-tint: #9aa0a6; }
.hero-dial {
  position: relative; width: 100%; max-width: 260px; aspect-ratio: 1; margin: 0 auto;
  background: transparent; border: 0; padding: 0; color: inherit; font-family: inherit;
  border-radius: 50%;
}
.dial-steps {
  position: absolute; left: 50%; bottom: 3%; transform: translateX(-50%);
  display: flex; gap: 44px; z-index: 1;
}
.dial-step {
  width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center; cursor: pointer;
  border: 1px solid color-mix(in srgb, var(--primary-text-color) 14%, transparent);
  background: color-mix(in srgb, var(--primary-text-color) 6%, var(--card-background-color));
  color: var(--primary-text-color); transition: background 0.15s ease, transform 0.1s ease;
}
.dial-step svg { width: 22px; height: 22px; }
.dial-step:hover { background: color-mix(in srgb, var(--primary-text-color) 12%, var(--card-background-color)); }
.dial-step:active { transform: scale(0.92); }
.dial-step:focus-visible { outline: 2px solid var(--nt-accent-hi); outline-offset: 2px; }
.dial-step:disabled { opacity: 0.35; cursor: default; }
.hero.heating .dial-step { border-color: color-mix(in srgb, var(--nt-heat) 40%, transparent); }
.hero-dial > svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.hero-dial .track { stroke: color-mix(in srgb, var(--primary-text-color) 9%, transparent); }
.hero-dial .fill { transition: stroke-dasharray 0.6s ease; }
.hero-dial .now-dot { fill: var(--primary-text-color); opacity: 0.75; }
.hero-left { display: flex; flex-direction: column; align-items: center; gap: 16px; min-width: 0; }
.hm-modes { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.hm-seg { display: inline-flex; padding: 3px; border-radius: 999px; background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); }
.hm-mode {
  border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer;
  padding: 7px 13px; border-radius: 999px; font: inherit; font-size: 13px; font-weight: 600;
  display: inline-flex; align-items: center; gap: 6px;
}
.hm-mode svg { width: 15px; height: 15px; }
.hm-mode:hover { color: var(--primary-text-color); }
.hm-mode:focus-visible { outline: 2px solid var(--nt-accent-hi); outline-offset: 2px; }
.hm-mode.active { background: var(--card-background-color); color: var(--primary-text-color); box-shadow: 0 1px 3px rgba(0,0,0,0.25); }
.hm-mode.active.heat, .hm-mode.active.boost { color: var(--nt-heat-soft); }
.hm-mode.active.eco { color: var(--nt-green); }
.hm-mode.active.away { color: var(--nt-accent-hi); }
.hero-dial-core {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; text-align: center;
}
.hero-dial-caption {
  font-size: 12px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--secondary-text-color);
}
.hero.heating .hero-dial-caption { color: var(--nt-heat-soft); }
.hero-dial-temp {
  font-size: 68px; font-weight: 300; line-height: 1; letter-spacing: -0.04em; margin: 6px 0 4px;
  font-variant-numeric: tabular-nums;
}
.hero-dial-temp sup { font-size: 0.38em; font-weight: 400; vertical-align: top; position: relative; top: 0.35em; margin-left: 2px; }
.hero-dial-sub { font-size: 13px; color: var(--secondary-text-color); font-weight: 500; }
.hero-dial-eta { margin-top: 2px; font-size: 12px; font-weight: 600; color: var(--nt-heat-soft); }
.hero-side { min-width: 0; display: flex; flex-direction: column; gap: 18px; }
.hero-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.hero-title { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin: 0; }
.hero-headline { font-size: 14px; color: var(--secondary-text-color); margin: 4px 0 0; }
.hero-pills { display: flex; flex-wrap: wrap; gap: 8px; }
.hero-pill {
  display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px;
  font-size: 12px; font-weight: 600; white-space: nowrap;
  background: color-mix(in srgb, var(--primary-text-color) 7%, transparent);
  color: var(--secondary-text-color);
}
.hero-pill svg { width: 14px; height: 14px; }
.hero-pill.heat { background: color-mix(in srgb, var(--nt-heat) 16%, transparent); color: var(--nt-heat-soft); }
.hero-pill.leaf { background: color-mix(in srgb, var(--nt-green) 16%, transparent); color: var(--nt-green); }
.hero-pill.info { background: color-mix(in srgb, var(--nt-accent) 16%, transparent); color: var(--nt-accent-hi); }
.hero-pill.warn { background: color-mix(in srgb, var(--nt-amber) 16%, transparent); color: var(--nt-amber); }
.hero-rooms { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.hero-room {
  display: flex; flex-direction: column; gap: 2px; text-align: left;
  padding: 14px 16px; border-radius: 14px; cursor: pointer; font-family: inherit; color: inherit;
  background: color-mix(in srgb, var(--primary-text-color) 4%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary-text-color) 8%, transparent);
  transition: background 0.15s ease, border-color 0.15s ease;
}
.hero-room:hover { background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); }
.hero-room:focus-visible { outline: 2px solid var(--nt-nest-tab); outline-offset: 2px; }
.hero-room.selected {
  border-color: var(--nt-accent-hi);
  box-shadow: inset 0 0 0 1px var(--nt-accent-hi);
}
.hero-back {
  display: inline-flex; align-items: center; gap: 2px; margin: 0 0 4px -6px; padding: 4px 10px 4px 4px;
  border: 0; border-radius: 999px; background: transparent; cursor: pointer;
  font: inherit; font-size: 13px; font-weight: 600; color: var(--nt-accent-hi);
}
.hero-back svg { width: 18px; height: 18px; }
.hero-back:hover { background: color-mix(in srgb, var(--nt-accent) 14%, transparent); }
.hero-back:focus-visible { outline: 2px solid var(--nt-accent-hi); outline-offset: 2px; }
.hero-room.heat {
  background: color-mix(in srgb, var(--nt-heat) 10%, transparent);
  border-color: color-mix(in srgb, var(--nt-heat) 35%, transparent);
}
.hero-rooms.reorderable .hero-room { cursor: grab; -webkit-user-select: none; user-select: none; -webkit-touch-callout: none; }
.hero-room.dragging {
  cursor: grabbing; position: relative; z-index: 2;
  transform: scale(1.04); opacity: 0.92;
  border-color: var(--nt-accent-hi);
  box-shadow: 0 12px 28px rgba(0,0,0,0.35);
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.hero-rooms.is-dragging .hero-room:not(.dragging) { transition: transform 0.18s ease; }
.hero-rooms-hint { margin: -10px 0 0; font-size: 11px; color: var(--secondary-text-color); opacity: 0.7; }
.hero-room-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.hero-room-name {
  font-size: 13px; font-weight: 600; color: var(--secondary-text-color);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.hero-room-off {
  flex-shrink: 0; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;
  background: color-mix(in srgb, var(--nt-red) 16%, transparent); color: var(--nt-red);
}
.hero-room-target .hero-room-off { display: inline-block; margin-top: 2px; }
.hero-room-flame { width: 16px; height: 16px; color: var(--nt-heat-soft); flex-shrink: 0; }
.hero-room-temp { font-size: 30px; font-weight: 400; letter-spacing: -0.03em; line-height: 1.15; font-variant-numeric: tabular-nums; }
.hero-room-temp.unknown { color: var(--secondary-text-color); }
.hero-room-target { font-size: 12px; color: var(--secondary-text-color); }
/* Setpoint on the left, the TRV's battery right-aligned on the same line. */
.hero-room-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 18px; }
.hero-room-battery {
  display: inline-flex; align-items: center; gap: 2px; flex-shrink: 0;
  font-size: 12px; font-variant-numeric: tabular-nums; color: var(--secondary-text-color);
}
.hero-room-battery svg { width: 14px; height: 14px; }
.hero-room-battery.warn { color: var(--nt-amber, #ffc107); }
.hero-room-battery.bad { color: var(--nt-red); }
.hero-room.heat .hero-room-target { color: var(--nt-heat-soft); }
.hero-empty { font-size: 13px; color: var(--secondary-text-color); margin: 0; }
@media (max-width: 720px) {
  .hero { grid-template-columns: minmax(0, 1fr); gap: 16px; padding: 20px 16px; }
  .hero-dial { max-width: 220px; }
  .hero-dial-temp { font-size: 56px; }
  .hero-head { flex-direction: column; align-items: center; text-align: center; }
  .hero-pill { white-space: normal; }
  .hero-pills { justify-content: center; }
  .hero-rooms { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

/* —— Wall panel preview —— */
.wp-preview-bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
.wp-preview-bar select { width: auto; min-width: 180px; }
.wp-preview-taps { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; }
.wp-preview-taps input { width: auto; margin: 0; }
.wp-preview-taps.live { color: var(--nt-heat-soft); font-weight: 600; }
.wp-preview-stage { display: flex; justify-content: center; }
.wp-preview-device {
  width: 100%; box-sizing: border-box;
  padding: 14px; border-radius: 26px; background: #0d0f12;
  box-shadow: 0 18px 40px rgba(0,0,0,0.35), inset 0 0 0 1px rgba(255,255,255,0.06);
}
.wp-preview-screen {
  position: relative; width: 100%; overflow: hidden;
  border-radius: 6px; background: #000;
}
.wp-preview-screen iframe {
  position: absolute; top: 0; left: 0; border: 0;
  transform-origin: 0 0; transform: scale(var(--wp-scale, 1));
}
.wp-preview-shield { position: absolute; inset: 0; cursor: not-allowed; }
.wp-preview-missing { text-align: center; padding: 32px 16px; }

/* —— Schedule grid —— */
.nest-schedule-sheet {
  background: var(--card-background-color);
  border-radius: 20px;
  border: 1px solid var(--divider-color, transparent);
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,0.08));
  padding: 8px 8px 12px;
  margin: 14px 0;
}
.nest-schedule-toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 12px 6px; flex-wrap: wrap;
}
.nest-schedule-toolbar .pill {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--nt-nest-tab); color: #fff; border-radius: 999px;
  padding: 8px 16px; font-size: 12px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase;
}
.nest-schedule-grid {
  position: relative;
  display: grid;
  grid-template-columns: 108px 1fr;
  gap: 0;
  padding: 8px 12px 4px;
}
.nest-day-label {
  display: flex; align-items: center;
  font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--secondary-text-color); padding: 0 8px 0 4px; height: 44px;
}
.nest-day-track {
  position: relative; height: 44px;
  border-bottom: 1px solid color-mix(in srgb, var(--divider-color) 80%, transparent);
}
.nest-day-track.selected { background: color-mix(in srgb, var(--nt-nest-tab) 6%, transparent); }
.nest-point {
  position: absolute; top: 50%; transform: translate(-50%, -50%);
  width: 34px; height: 34px; border-radius: 50%;
  background: var(--nt-heat); color: #fff;
  border: 0; cursor: pointer;
  font-size: 12px; font-weight: 700; font-family: inherit;
  box-shadow: 0 2px 6px rgba(0,0,0,0.2);
  z-index: 2;
}
.nest-point:hover { filter: brightness(1.08); }
.nest-point.selected {
  outline: 2px solid var(--nt-nest-tab);
  outline-offset: 2px;
  z-index: 3;
}
.nest-time-axis {
  grid-column: 2;
  position: relative; height: 14px; margin: 10px 0 4px;
  font-size: 11px; color: var(--secondary-text-color);
  font-weight: 500;
}
.nest-time-axis span { position: absolute; top: 0; transform: translateX(-50%); white-space: nowrap; }
/* Noon sits between 11a and 1p: too tight on a phone. */
@media (max-width: 600px) { .nest-time-axis span:nth-child(7) { display: none; } }
.nest-schedule-actions {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px 4px; gap: 8px; flex-wrap: wrap;
}
.nest-schedule-actions .group { display: flex; gap: 4px; }
.nest-add-row {
  display: flex; gap: 10px; flex-wrap: wrap; align-items: end;
  padding: 8px 12px 12px;
}
.nest-overlaps { margin: 0 12px 8px; padding: 8px 12px; border-radius: 10px; font-size: 13px; color: var(--primary-text-color); background: color-mix(in srgb, var(--nt-amber) 14%, transparent); border: 1px solid color-mix(in srgb, var(--nt-amber) 35%, transparent); }
.nest-overlaps p { margin: 2px 0; }
.nest-edit-note { margin: 0; padding: 10px 12px 0; border-top: 1px solid var(--divider-color); font-size: 13px; color: var(--secondary-text-color); }
.nest-edit-note.editing { color: var(--primary-text-color); font-weight: 600; }
.intel-chip {
  display: inline-flex; align-items: center; gap: 8px;
  margin: 0 0 14px; padding: 8px 14px; border-radius: 999px;
  background: color-mix(in srgb, var(--nt-heat) 16%, transparent);
  color: var(--nt-heat); font-size: 13px; font-weight: 600;
}
.intel-chip.home {
  background: color-mix(in srgb, var(--nt-accent) 14%, transparent);
  color: var(--nt-accent);
}
.intel-chip.leaf {
  background: color-mix(in srgb, var(--nt-green) 16%, transparent);
  color: var(--nt-green);
}
.eh-banner {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  margin: 0 0 16px; padding: 14px 16px; border-radius: var(--nt-radius);
  background: color-mix(in srgb, var(--nt-heat) 12%, var(--card-background-color, #fff));
  border: 1px solid color-mix(in srgb, var(--nt-heat) 25%, transparent);
}
.eh-banner .eh-copy { flex: 1; min-width: 160px; }
.eh-banner strong { display: block; font-size: 15px; margin-bottom: 2px; }
.eh-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }
.eh-total-label { font-size: 12px; color: var(--secondary-text-color); }
.eh-total-value { font-size: 22px; font-weight: 500; letter-spacing: -0.02em; }
.eh-legend { display: flex; gap: 16px; font-size: 12px; color: var(--secondary-text-color); align-items: center; }
.eh-legend i { display: inline-block; width: 14px; height: 8px; border-radius: 4px; background: var(--nt-heat); margin-right: 6px; vertical-align: middle; }
.eh-legend b { display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: var(--nt-heat); margin-right: 6px; vertical-align: middle; }
.eh-legend svg { width: 14px; height: 14px; color: var(--nt-green); margin-right: 4px; vertical-align: middle; }
.eh-grid-row { display: grid; grid-template-columns: 84px minmax(0, 1fr) 64px; gap: 14px; align-items: center; }
.eh-axis-row { padding: 10px 0 6px; border-bottom: 1px solid var(--divider-color); }
.eh-axis { position: relative; height: 14px; font-size: 11px; color: var(--secondary-text-color); }
.eh-axis span { position: absolute; top: 0; transform: translateX(-50%); white-space: nowrap; }
.eh-axis span:first-child { transform: none; }
.eh-axis span:last-child { transform: translateX(-100%); }
.eh-month {
  margin: 18px 0 2px; font-size: 12px; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--secondary-text-color);
}
.eh-day { padding: 8px 0; border-bottom: 1px solid color-mix(in srgb, var(--divider-color) 70%, transparent); }
.eh-day:last-child { border-bottom: 0; }
.eh-day-label { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; white-space: nowrap; }
.eh-day-label svg { width: 14px; height: 14px; color: var(--nt-green); flex-shrink: 0; }
.eh-timeline { position: relative; height: 50px; }
/* Setpoint bubbles, in their own lane above the track (never over the row above). */
.eh-sp {
  position: absolute; top: 0; z-index: 1;
  width: 26px; height: 26px; margin-left: -13px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--nt-heat); color: #fff;
  font-size: 10px; font-weight: 700; font-variant-numeric: tabular-nums;
  box-shadow: 0 0 0 2px var(--card-background-color), 0 2px 6px rgba(0,0,0,0.25);
  cursor: default;
}
.eh-sp:hover { z-index: 2; transform: scale(1.12); }
.eh-track {
  position: absolute; left: 0; right: 0; top: 34px; height: 12px; border-radius: 6px; overflow: hidden;
  background:
    linear-gradient(90deg, transparent calc(25% - 0.5px), var(--divider-color) calc(25% - 0.5px), var(--divider-color) calc(25% + 0.5px), transparent calc(25% + 0.5px),
      transparent calc(50% - 0.5px), var(--divider-color) calc(50% - 0.5px), var(--divider-color) calc(50% + 0.5px), transparent calc(50% + 0.5px),
      transparent calc(75% - 0.5px), var(--divider-color) calc(75% - 0.5px), var(--divider-color) calc(75% + 0.5px), transparent calc(75% + 0.5px)),
    color-mix(in srgb, var(--primary-text-color) 6%, transparent);
}
.eh-seg { position: absolute; top: 0; bottom: 0; min-width: 3px; background: var(--nt-heat); border-radius: 3px; }
.eh-day-total { text-align: right; font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
.eh-day-total.none { color: var(--secondary-text-color); font-weight: 500; }
.eh-day-gas { margin-top: 2px; font-size: 12px; font-weight: 600; color: #1E88E5; white-space: nowrap; }
/* Gas per hour: a thin blue lane under the boiler runs. */
.eh-gas { position: absolute; left: 0; right: 0; top: 50px; height: 16px; display: flex; align-items: flex-end; gap: 1px; }
.eh-gas span { flex: 1; min-width: 0; border-radius: 2px 2px 0 0; background: linear-gradient(180deg, #6FD0FF, #1E6FE0); }
.eh-has-meter .eh-timeline { height: 68px; }
.eh-legend em { display: inline-block; width: 12px; height: 12px; border-radius: 3px; background: linear-gradient(180deg, #6FD0FF, #1E6FE0); margin-right: 6px; vertical-align: middle; }
/* Cards across the top, like the wall panel's usage page. */
.eh-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
.eh-tiles-note { margin: 6px 2px 14px; font-size: 12px; color: var(--secondary-text-color); }
.eh-tile {
  position: relative; overflow: hidden; display: flex; align-items: center; gap: 14px;
  padding: 16px; border-radius: var(--nt-radius); color: #fff;
  box-shadow: 0 4px 14px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.25);
}
.eh-tile::after {
  content: ""; position: absolute; right: -30%; top: -45%; width: 75%; height: 100%;
  border-radius: 50%; background: rgba(255,255,255,0.12); pointer-events: none;
}
.eh-tile.heat { background: linear-gradient(145deg, #ffb238 0%, #ff7a1a 45%, #e8461e 100%); }
.eh-tile.gas { background: linear-gradient(145deg, #4fc3ff 0%, #2a8cf0 50%, #1a4fc4 100%); }
.eh-tile.leaf { background: linear-gradient(145deg, #8fdc5a 0%, #43b649 50%, #1f8a3b 100%); }
.eh-badge {
  flex-shrink: 0; width: 48px; height: 48px; border-radius: 50%; display: grid; place-items: center;
  background: #fff; box-shadow: 0 3px 8px rgba(0,0,0,0.2);
}
.eh-badge svg { width: 32px; height: 32px; }
.eh-tile-text { min-width: 0; }
.eh-tile-value { font-size: 28px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.05; white-space: nowrap; }
.eh-tile-value small { margin-left: 4px; font-size: 15px; font-weight: 600; opacity: 0.9; letter-spacing: 0; }
.eh-tile-label { margin-top: 2px; font-size: 14px; font-weight: 600; }
.eh-tile-sub { font-size: 12px; opacity: 0.9; }
@media (max-width: 600px) {
  .eh-tiles { gap: 8px; }
  .eh-tile { padding: 10px 14px; gap: 12px; }
  .eh-badge { width: 38px; height: 38px; }
  .eh-badge svg { width: 26px; height: 26px; }
  .eh-tile-value { font-size: 22px; }
  .eh-tile-value small { font-size: 13px; }
  .eh-tile-label { font-size: 13px; }
}
@media (max-width: 720px) {
  .eh-grid-row { grid-template-columns: 58px minmax(0, 1fr) 48px; gap: 8px; }
  .eh-day-label { font-size: 12px; }
  .eh-sp { width: 22px; height: 22px; margin-left: -11px; font-size: 9px; }
  .eh-axis span.half { display: none; }
}
.toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  padding: 12px 20px; border-radius: 10px; font-size: 14px; font-weight: 500;
  z-index: 100; box-shadow: 0 4px 16px rgba(0,0,0,0.25); max-width: 90%;
  pointer-events: none;
}
.toast.ok { background: var(--nt-green); color: #fff; }
.toast.err { background: var(--nt-red); color: #fff; }
.entity-picker-host {
  display: block; min-height: 56px; width: 100%;
}
.entity-picker-host ha-entity-picker,
.entity-picker-host ha-entities-picker {
  display: block; width: 100%;
}
.entity-picker-loading, .entity-picker-error {
  margin: 0; font-size: 13px; color: var(--secondary-text-color);
}
.entity-picker-error { color: var(--error-color, #db4437); }
label.field .entity-picker-host { margin-top: 0; }

@media (max-width: 720px) {
  .nest-schedule-grid { grid-template-columns: 72px 1fr; }
  .nest-day-label { font-size: 10px; padding-right: 4px; }
  .nest-point { width: 28px; height: 28px; font-size: 11px; }
}
`;

function parseHHMM(value) {
  const parts = String(value || "00:00").split(":");
  const h = Number(parts[0]) || 0;
  const m = Number(parts[1]) || 0;
  return h * 60 + m;
}

function minutesToHHMM(mins) {
  const m = ((mins % (24 * 60)) + 24 * 60) % (24 * 60);
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

function formatTemp(value) {
  if (value == null || Number.isNaN(Number(value))) return null;
  const n = Number(value);
  return Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, "");
}

// Fully Kiosk settings Nook manages (keys match the backend's kiosk.KIOSK_SETTINGS).
const KIOSK_FIELDS = [
  { key: "screen_brightness", kind: "pct" },
  { key: "screensaver_timer", kind: "sec" },
  { key: "screensaver_brightness", kind: "pct" },
  { key: "screen_off_timer", kind: "sec" },
  { key: "kiosk_lock", kind: "bool" },
  { key: "motion_detection", kind: "bool" },
  { key: "proximity_motion", kind: "bool" },
  { key: "js_interface", kind: "bool" },
  { key: "proximity_threshold", kind: "pct100" },
  { key: "stay_awake", kind: "bool" },
  // Fully's "Kiosk Exit Gesture" (kiosk.py EXIT_GESTURES); double-tap corners first: the
  // default swipe from the left fights the wall app's page swipe.
  { key: "exit_gesture", kind: "choice", options: [1, 0, 2, 3] },
].map((f) => ({ ...f, label: t(`kiosk.field.${f.key}`), desc: t(`kiosk.field.${f.key}.desc`) }));

/** Fully stores brightness 0–255; people think in %. */
function kioskDisplay(field, raw) {
  if (raw == null) return "";
  if (field.kind === "bool") return raw ? t("common.on") : t("common.off");
  if (field.kind === "choice") return field.options.includes(Number(raw)) ? t(`kiosk.${field.key}.${raw}`) : String(raw);
  if (field.kind === "pct") return `${Math.round(Number(raw) / 2.55)}%`;
  if (field.kind === "pct100") return `${Math.round(Number(raw))}%`;
  return Number(raw) === 0 ? t("common.never") : t("common.seconds_short", { value: raw });
}

/** Lower-case id from a name: "Hallway Panel" → "hallway-panel". */
function slugId(value) {
  return String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function flameSvg() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true">
    <path fill="currentColor" d="M12 2c.5 3.2-1.6 5-3.2 6.9C7.4 10.6 6 12.4 6 15a6 6 0 0 0 12 0c0-2.6-1.3-4.6-2.6-6.1-.3 1.6-1.1 2.7-2.3 3.2.6-3.7-.3-7.6-1.1-10.1z"/>
  </svg>`;
}

/** Brand mark: the hero's 270° dial ring, cool-to-warm, around a leaf, on a deep teal tile. */
function logoSvg() {
  return `<svg viewBox="0 0 40 40">
    <defs>
      <linearGradient id="ntLogoBg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#0E6F74"/>
        <stop offset="1" stop-color="#062B33"/>
      </linearGradient>
      <linearGradient id="ntLogoRing" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#19D4DE"/>
        <stop offset="0.5" stop-color="#FFB74D"/>
        <stop offset="1" stop-color="#FF6A3D"/>
      </linearGradient>
    </defs>
    <rect width="40" height="40" fill="url(#ntLogoBg)"/>
    <path d="M12.22 27.78 A11 11 0 1 1 27.78 27.78" fill="none" stroke="url(#ntLogoRing)" stroke-width="3.2" stroke-linecap="round"/>
    <path d="M24.6 13.2c-3.6.2-6.8 1.9-8.3 4.6-1.2 2.1-1.2 4.6-.4 6.6 2.7-.3 5.1-1.6 6.6-3.8 1.4-2.1 2-4.6 2.1-7.4z" fill="#EFFFFB"/>
    <path d="M16.6 24.6c1.4-2.5 3.4-4.5 5.8-5.9" fill="none" stroke="#0E6F74" stroke-width="1.2" stroke-linecap="round"/>
  </svg>`;
}

const ICONS = {
  chevron_down: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>`,
  tune: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 17v2h6v-2H3zM3 5v2h10V5H3zm10 16v-2h8v-2h-8v-2h-2v6h2zM7 9v2H3v2h4v2h2V9H7zm14 4v-2H11v2h10zm-6-4h2V7h4V5h-4V3h-2v6z"/></svg>`,
  window: `<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M12 3v18M4 12h16"/></g></svg>`,
  sun: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="currentColor"/><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`,
  home: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>`,
  sparkle: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M10 2l1.9 5.6L17.5 9.5l-5.6 1.9L10 17l-1.9-5.6L2.5 9.5l5.6-1.9zM18 13l1 2.9 3 1.1-3 1-1 3-1-3-3-1 3-1.1z"/></svg>`,
  people: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16 11c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 3-1.34 3-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5C15 14.17 10.33 13 8 13zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>`,
  shield: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-1 15-4-4 1.41-1.41L11 13.17l5.59-5.59L18 9l-7 7z"/></svg>`,
  bell: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 22a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4a1.5 1.5 0 0 0-3 0v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>`,
  gauge: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M5.6 18.4a9 9 0 1 1 12.8 0M12 13l4-4"/><circle cx="12" cy="13" r="1.6" fill="currentColor"/></svg>`,
  thermo: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M15 13V5a3 3 0 0 0-6 0v8a5 5 0 1 0 6 0zm-3 7a3 3 0 0 1-1.5-5.6l.5-.29V5a1 1 0 0 1 2 0v9.11l.5.29A3 3 0 0 1 12 20z"/></svg>`,
  plus: `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>`,
  panel: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="3" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="11" r="3.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 17h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`,
  link: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>`,
};

/** SVG arc gauge: 270° sweep, `fill` and `now` are 0–1 positions along it. */
function dialSvg({ fill, now, color }) {
  const r = 84;
  const arc = "M40.6 159.4 A84 84 0 1 1 159.4 159.4";
  const pct = Math.max(0, Math.min(1, fill)) * 100;
  let nowDot = "";
  if (now != null) {
    const a = ((135 + 270 * Math.max(0, Math.min(1, now))) * Math.PI) / 180;
    nowDot = `<circle class="now-dot" cx="${(100 + r * Math.cos(a)).toFixed(1)}" cy="${(100 + r * Math.sin(a)).toFixed(1)}" r="3.5"/>`;
  }
  return `<svg viewBox="0 0 200 200" aria-hidden="true">
    <defs>
      <linearGradient id="heroArc" x1="0" y1="1" x2="1" y2="0">
        <stop offset="0" stop-color="${color[0]}"/>
        <stop offset="1" stop-color="${color[1]}"/>
      </linearGradient>
    </defs>
    <path class="track" d="${arc}" fill="none" stroke-width="12" stroke-linecap="round"/>
    ${pct > 0 ? `<path class="fill" d="${arc}" pathLength="100" fill="none" stroke="url(#heroArc)" stroke-width="12"
      stroke-linecap="round" stroke-dasharray="${pct.toFixed(1)} 100"/>` : ""}
    ${nowDot}
  </svg>`;
}

// Two-tone badges for the Energy cards, the same set as the wall panel's usage page.
const TILE_ICONS = {
  heat: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#FF7A1A" d="M12 1.8c.6 3.4-1.7 5.3-3.4 7.3C7.1 10.9 5.6 12.8 5.6 15.6a6.4 6.4 0 0 0 12.8 0c0-2.8-1.4-4.9-2.8-6.5-.3 1.7-1.2 2.9-2.5 3.4.7-4-.3-8.1-1.1-10.7z"/><path fill="#FFC53D" d="M12 11.2c.3 1.8-.9 2.8-1.8 3.8-.7.8-1.3 1.6-1.3 2.8a3.1 3.1 0 0 0 6.2 0c0-1.5-.8-2.6-1.6-3.4-.2.8-.6 1.3-1.2 1.6.3-1.8-.1-3.6-.3-4.8z"/></svg>`,
  gas: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#7FD3FF" d="M12 1.6c2.6 3.3 6.2 7.4 6.2 12.2a6.2 6.2 0 0 1-12.4 0c0-2.6 1.1-4.7 2.5-6.6.3 1.6 1.1 2.7 2.2 3.2-.6-3.3.4-6.3 1.5-8.8z"/><path fill="#1E6FE0" d="M12 9.4c1.4 1.9 3.1 3.9 3.1 6.3a3.1 3.1 0 0 1-6.2 0c0-1.4.6-2.5 1.4-3.5.2.8.6 1.4 1.1 1.7-.2-1.7.1-3.1.6-4.5z"/></svg>`,
  leaf: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#6CC24A" d="M6.6 17.4C4.6 9.9 10.6 4.3 20 4z"/><path fill="#3E9B34" d="M20 4c.3 9.4-5.4 15.4-13.4 13.4z"/><path fill="none" stroke="#2F7D2A" stroke-width="1.7" stroke-linecap="round" d="M3.6 20.4 7.4 16.6"/></svg>`,
};

/** A meter amount: kWh to 1 dp; gas volume (m³, ft³…) to 2 dp while small. */
function formatMeter(value, unit = "kWh") {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  if (n >= 100) return n.toFixed(0);
  if (unit !== "kWh" && n < 10) return n.toFixed(2);
  return n.toFixed(1);
}

// The Leaf (same drawing on the card and wall panel): a folded leaf, one half a shade darker.
function leafSvg() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6.6 17.4C4.6 9.9 10.6 4.3 20 4z"/><path fill="currentColor" opacity=".68" d="M20 4c.3 9.4-5.4 15.4-13.4 13.4z"/><path fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" d="M3.6 20.4 7.4 16.6"/></svg>`;
}

let _haEntityPickerLoadPromise = null;

async function ensureHaEntityPickerLoaded() {
  if (customElements.get("ha-entity-picker") && customElements.get("ha-entities-picker")) {
    return;
  }
  if (typeof window.loadCardHelpers !== "function") {
    throw new Error(t("error.entity_picker"));
  }
  if (!_haEntityPickerLoadPromise) {
    _haEntityPickerLoadPromise = (async () => {
      const helpers = await window.loadCardHelpers();
      const card = await helpers.createCardElement({ type: "entities", entities: [] });
      const configEl = card.constructor.getConfigElement?.();
      if (configEl && typeof configEl.then === "function") await configEl;
      await customElements.whenDefined("ha-entity-picker");
      // Multi-picker may load with the same helpers path; don't hang if missing
      if (!customElements.get("ha-entities-picker")) {
        await Promise.race([
          customElements.whenDefined("ha-entities-picker"),
          new Promise((resolve) => setTimeout(resolve, 1500)),
        ]);
      }
    })();
  }
  await _haEntityPickerLoadPromise;
}

function temperatureSensorFilter(stateObj) {
  if (!stateObj) return false;
  if (stateObj.attributes?.device_class === "temperature") return true;
  const uom = stateObj.attributes?.unit_of_measurement;
  return uom === "°C" || uom === "°F" || uom === "K" || uom === "celsius" || uom === "fahrenheit";
}

/** Meters with statistics: kWh (a boiler's own counter, a smart meter's gas import) or gas volume (m³, ft³, CCF). */
function energySensorFilter(stateObj) {
  if (!stateObj) return false;
  const dc = stateObj.attributes?.device_class;
  if (dc === "energy" || dc === "gas") return true;
  const uom = stateObj.attributes?.unit_of_measurement;
  return ["kWh", "Wh", "MWh", "m³", "ft³", "CCF", "MCF"].includes(uom);
}

function humiditySensorFilter(stateObj) {
  if (!stateObj) return false;
  if (stateObj.attributes?.device_class === "humidity") return true;
  return stateObj.attributes?.unit_of_measurement === "%";
}

class NookPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._narrow = false;
    this._view = "overview";
    this._state = null;
    this._focusZone = "home";
    this._selectedDay = "mon";
    this._selectedPoint = null; // { day, index }
    this._clipboard = null;
    this._error = "";
    this._flash = "";
    this._energy = null;
    this._liveTimer = null;
    this._refreshingLive = false;
    this._toastTimer = null;
    this._roomDraft = { trv: "", sensor: "", extras: [], calls_for_heat: true };
    this._editingRoomId = null;
    this._roomPickerMountGen = 0;
    this._kiosk = null;
    this._kioskTimer = null;
    this._dialogKind = null;
    this._wallEditingId = null;
    this._wallIdTouched = false;
    this._wallDraft = {
      primary: "",
      insideTemp: "",
      outsideTemp: "",
      humidity: "",
      weather: "weather.home",
    };
    this._wallPickerMountGen = 0;
    this._previewPanel = "";
    this._previewTaps = false;
    this._entitiesOpen = false;
    this._previewResize = null;
    this._settingsDraft = null;
    this._settingsPickerMountGen = 0;
    this.attachShadow({ mode: "open" });
    this.shadowRoot.addEventListener("click", (ev) => {
      const sync = ev.target.closest?.("[data-kiosk-sync]");
      const reload = ev.target.closest?.("[data-kiosk-reload]");
      if (sync) {
        ev.stopPropagation();
        this._kioskSync(sync.dataset.kioskSync || null);
      } else if (reload) {
        ev.stopPropagation();
        this._kioskReload(reload.dataset.kioskReload);
      }
    });
    // Dialog closing: ×, Cancel, backdrop click (not clicks inside the dialog), Esc.
    this.shadowRoot.addEventListener("click", (ev) => {
      const closer = ev.target.closest?.("[data-close-dialog]");
      if (!closer || !this._dialogKind) return;
      if (closer.classList.contains("dlg-backdrop") && ev.target !== closer) return;
      this._closeDialog();
    });
    this.shadowRoot.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && this._dialogKind) this._closeDialog();
    });
    // Settings lists (presence, windows) redraw in place, so remove buttons are delegated.
    this.shadowRoot.addEventListener("click", (ev) => {
      const btn = ev.target.closest?.("[data-remove-key]");
      if (!btn) return;
      const key = btn.dataset.removeKey;
      if (key === "room_extras") {
        this._roomDraft.extras = (this._roomDraft.extras || []).filter((id) => id !== btn.dataset.removeId);
        this._refreshRoomExtras();
        return;
      }
      if (!this._settingsDraft) return;
      this._settingsDraft[key] = (this._settingsDraft[key] || []).filter((id) => id !== btn.dataset.removeId);
      this._refreshSettingsList(key);
    });
  }

  set hass(hass) {
    this._hass = hass;
    // Do not full-render on every HA hass update — that wipes Settings/Rooms form edits.
    if (!this._state) this._loadState();
  }

  set narrow(n) {
    this._narrow = Boolean(n);
    this.classList.toggle("narrow", this._narrow);
    const shell = this.shadowRoot?.querySelector(".shell");
    if (shell) {
      shell.classList.toggle("narrow", this._narrow);
    } else {
      this._render();
    }
  }

  connectedCallback() {
    // The class is defined only after the labels have loaded, so HA may already have set
    // hass/narrow on the plain element; those own properties would hide our setters.
    for (const prop of ["hass", "narrow", "route", "panel"]) {
      if (Object.prototype.hasOwnProperty.call(this, prop)) {
        const value = this[prop];
        delete this[prop];
        this[prop] = value;
      }
    }
    this._render();
    this._loadState();
    this._liveTimer = window.setInterval(() => this._softRefreshLive(), 5000);
  }

  disconnectedCallback() {
    clearInterval(this._kioskTimer);
    this._previewResize?.disconnect();
    this._previewResize = null;
    this._ehResize?.disconnect();
    this._ehResize = null;
    if (this._liveTimer) {
      window.clearInterval(this._liveTimer);
      this._liveTimer = null;
    }
    if (this._toastTimer) {
      window.clearTimeout(this._toastTimer);
      this._toastTimer = null;
    }
  }

  _showToast(msg, type = "ok") {
    const root = this.shadowRoot;
    if (!root) return;
    const old = root.querySelector(".toast");
    if (old) old.remove();
    if (this._toastTimer) window.clearTimeout(this._toastTimer);
    const el = document.createElement("div");
    el.className = `toast ${type === "err" ? "err" : "ok"}`;
    el.textContent = msg;
    root.appendChild(el);
    this._toastTimer = window.setTimeout(() => el.remove(), 3500);
  }

  _formViews() {
    return new Set(["settings", "rooms", "wall_panels", "schedule"]);
  }

  async _softRefreshLive() {
    if (!this._hass || !this._state || this._refreshingLive) return;
    // Never rebuild form pages while the user may be editing — except the sensor tiles on Settings.
    if (this._formViews().has(this._view)) {
      if (this._view === "settings") await this._refreshSettingsLive();
      return;
    }
    // Re-rendering mid-drag would drop the tile out from under the pointer.
    if (this._dragging) return;
    this._refreshingLive = true;
    const startedAt = Date.now();
    try {
      const next = await this._ws("nook/get_state");
      // A drag or room-order save during the fetch makes this snapshot stale.
      if (this._dragging || (this._orderSavedAt || 0) >= startedAt) return;
      this._state = next;
      if (this._view === "energy") await this._loadEnergy();
      if ((this._view === "overview" || this._view === "energy") && !this._dragging) this._render();
    } catch {
      // Ignore background refresh errors
    } finally {
      this._refreshingLive = false;
    }
  }

  async _refreshSettingsLive() {
    if (this._refreshingLive) return;
    this._refreshingLive = true;
    try {
      const next = await this._ws("nook/get_state");
      if (this._view !== "settings" || !this._state) return;
      // Only the live part: the form keeps editing its own draft of the config.
      this._state = { ...this._state, live: next.live };
      this._refreshSensorTiles();
    } catch {
      // Ignore background refresh errors
    } finally {
      this._refreshingLive = false;
    }
  }

  _ws(type, payload = {}) {
    return new Promise((resolve, reject) => {
      if (!this._hass) {
        reject(new Error(t("error.ha_not_ready")));
        return;
      }
      this._hass.connection
        .sendMessagePromise({ type, ...payload })
        .then(resolve)
        .catch(reject);
    });
  }

  async _loadState() {
    try {
      if (this._view === "wall_panels" && !this._kiosk) this._loadKiosk();
      this._state = await this._ws("nook/get_state");
      this._error = "";
      if (this._view === "energy") await this._loadEnergy();
      this._render();
    } catch (err) {
      this._error = String(err?.message || err);
      this._render();
    }
  }

  async _loadEnergy() {
    try {
      this._energy = await this._ws("nook/get_energy_history", { days: 31 });
    } catch (err) {
      this._energy = null;
      this._error = String(err?.message || err);
    }
  }

  _formatEta(minutes) {
    if (minutes == null || !Number.isFinite(Number(minutes))) return null;
    const m = Math.round(Number(minutes));
    if (m < 60) return t("time.approx_min", { m });
    const h = Math.floor(m / 60);
    const rem = m % 60;
    return rem ? t("time.approx_hm", { h, m: rem }) : t("time.approx_h", { h });
  }

  _cfg() {
    return this._state?.config || {};
  }

  _live() {
    return this._state?.live || {};
  }

  _setView(id) {
    if (id === "rooms") id = "settings"; // Rooms now lives on Settings
    this._view = id;
    this._flash = "";
    this._settingsDraft = null;
    clearInterval(this._kioskTimer);
    if (id === "wall_panels") {
      this._loadKiosk();
      // Panel status (online / in sync) changes on its own; refresh just the pills.
      this._kioskTimer = setInterval(() => this._loadKiosk(true), 15000);
    }
    if (id === "energy") {
      this._loadEnergy().then(() => this._render());
      return;
    }
    this._render();
  }

  /** "A", "A and B", "A, B and C" — in HA's language. */
  _listNames(names) {
    try {
      return new Intl.ListFormat(LANG, { style: "long", type: "conjunction" }).format(names);
    } catch (_err) {
      return names.join(", ");
    }
  }

  _escape(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  _entityState(entityId) {
    if (!entityId || !this._hass?.states) return null;
    return this._hass.states[entityId] || null;
  }

  /** Real Nook climate entity ids (HA may have prefixed them, e.g. climate.nook_nook_home). */
  _nookClimateEntities() {
    const registry = this._hass?.entities || {};
    const ids = Object.keys(registry).filter(
      (id) => id.startsWith("climate.") && registry[id]?.platform === "nook"
    );
    // Only the house entity carries boiler attributes.
    const home = ids.find((id) => this._entityState(id)?.attributes?.boiler_demand !== undefined) || "";
    return { home, rooms: ids.filter((id) => id !== home).sort() };
  }

  _mainTarget() {
    const live = this._live().main || {};
    const cfg = this._cfg();
    const home = this._nookClimateEntities().home;
    const reported = this._entityState(home)?.attributes?.temperature ?? live.target ?? cfg.target_temp ?? null;
    return this._withPending(home, reported);
  }

  /** A − / + change shows at once; HA's value wins once it catches up (or after 15 s). */
  _withPending(entityId, reported) {
    if (this._pendingTarget != null && this._pendingEntity === entityId) {
      const settled = reported != null && Number(reported) === this._pendingTarget && !this._sendTimer;
      if (settled || Date.now() - this._pendingAt > 15000) this._pendingTarget = null;
      else return this._pendingTarget;
    }
    return reported;
  }

  /** Nook's climate entity for a room (found by its room_id attribute, never by a guessed id). */
  _roomEntity(room) {
    if (!room) return "";
    return this._nookClimateEntities().rooms.find((id) => this._entityState(id)?.attributes?.room_id === room.id) || "";
  }

  /** The room the Overview dial is controlling, or null for the whole house. */
  _focusRoom() {
    if (!this._focusZone || this._focusZone === "home") return null;
    return (this._cfg().rooms || []).find((r) => r.id === this._focusZone && r.enabled !== false) || null;
  }

  /** The room's setpoint as Nook applies it (schedule/Eco/Boost included). */
  _roomTarget(room) {
    return this._withPending(this._roomEntity(room), this._roomDisplayTemp(room));
  }

  /** − / + on the dial: update at once, send to HA when the taps stop. */
  _stepTarget(direction) {
    const room = this._focusRoom();
    const entity = room ? this._roomEntity(room) : this._nookClimateEntities().home;
    if (!entity) {
      this._showToast(room ? t("dial.room_unavailable", { name: room.name }) : t("dial.house_unavailable"), "err");
      return;
    }
    const attrs = this._entityState(entity)?.attributes || {};
    const step = Number(attrs.target_temp_step) || 0.5;
    const lo = Number(attrs.min_temp ?? 7);
    const hi = Number(attrs.max_temp ?? 30);
    if (this._pendingEntity !== entity) {
      // Taps on another dial still waiting to go out: send them now, not to this one.
      if (this._sendTimer && this._pendingTarget != null && this._pendingEntity) {
        void this._hass.callService("climate", "set_temperature", { entity_id: this._pendingEntity, temperature: this._pendingTarget });
      }
      clearTimeout(this._sendTimer);
      this._sendTimer = null;
      this._pendingTarget = null;
    }
    const base = Number((room ? this._roomTarget(room) : this._mainTarget()) ?? 20);
    const next = Math.min(hi, Math.max(lo, Math.round((base + step * direction) / step) * step));
    this._pendingTarget = next;
    this._pendingEntity = entity;
    this._pendingAt = Date.now();
    this._render();
    clearTimeout(this._sendTimer);
    this._sendTimer = setTimeout(async () => {
      this._sendTimer = null;
      const value = this._pendingTarget;
      if (value == null) return;
      try {
        await this._hass.callService("climate", "set_temperature", { entity_id: entity, temperature: value });
        this._pendingAt = Date.now();
      } catch (e) {
        this._pendingTarget = null;
        this._showToast(t("dial.change_failed", { error: e?.message || e }), "err");
        this._render();
      }
    }, 700);
  }

  _mainCurrent() {
    const sensor = this._cfg().temperature_sensor;
    const st = this._entityState(sensor);
    if (!st) return null;
    const n = Number(st.state);
    return Number.isFinite(n) ? n : null;
  }

  /** The room's setpoint as Nook applies it. live.rooms[].target is only the last manual
   *  setpoint (it ignores the schedule, Eco and Boost), so the entity comes first. */
  _roomDisplayTemp(room) {
    const temp = this._entityState(this._roomEntity(room))?.attributes?.temperature;
    if (temp != null) return temp;
    const live = (this._live().rooms || {})[room.id] || {};
    return live.target ?? room.target_temp ?? null;
  }

  _roomHeating(room) {
    const live = (this._live().rooms || {})[room.id] || {};
    return Boolean(live.needs_heat);
  }

  _pageHeader(title, lead) {
    return `<div class="header"><h1>${title}</h1><p>${lead}</p></div>`;
  }

  /** Same sources as the coordinator's room_current_temp: sensors averaged, else the TRV. */
  _roomCurrent(room) {
    const readings = [room.temperature_sensor, ...(room.extra_temperature_sensors || [])]
      .filter(Boolean)
      .map((id) => Number(this._entityState(id)?.state))
      .filter((n) => Number.isFinite(n));
    if (readings.length) return readings.reduce((a, b) => a + b, 0) / readings.length;
    const trvTemp = Number(this._entityState(room.trv_entity)?.attributes?.current_temperature);
    return Number.isFinite(trvTemp) ? trvTemp : null;
  }

  /** Status pills for the hero: heating state first, then whatever Nook is doing. */
  _heroPills() {
    const live = this._live();
    const intel = live.intelligence || {};
    const preheat = live.preheat || {};
    const preset = (live.main || {}).preset;
    const pills = [];
    const pill = (cls, text, icon = "") =>
      pills.push(`<span class="hero-pill ${cls}">${icon}${this._escape(text)}</span>`);
    if (live.safety_active) pill("heat", t("hero.pill.safety"), flameSvg());
    else if (live.boiler_on) pill("heat", t("hero.pill.boiler_on"), flameSvg());
    if (preheat.preheating) {
      pill("heat", preheat.preheat_room
        ? t("hero.pill.preheating_room", { time: preheat.block_start ?? "", room: preheat.preheat_room })
        : t("hero.pill.preheating", { time: preheat.block_start ?? "" }).trim());
    }
    if (live.leaf?.active) pill("leaf", t("hero.pill.leaf"), leafSvg());
    if (live.away) pill("warn", t("hero.pill.away"));
    if (live.window_open) pill("warn", t("hero.pill.window_open"));
    if (live.summer_mode) pill("warn", t("hero.pill.summer"));
    if (preset && preset !== "none" && !live.away) pill("info", t(`preset.${preset}`));
    if (intel.true_radiant && intel.warmup_c_per_hour != null) {
      pill("info", t("hero.pill.true_radiant", { rate: intel.warmup_c_per_hour }));
    }
    return pills.join("");
  }

  /** Status pills while a room is on the dial. */
  _roomPills(room) {
    const live = this._live();
    const attrs = this._entityState(this._roomEntity(room))?.attributes || {};
    const trv = this._entityState(room.trv_entity);
    const pills = [];
    const pill = (cls, text, icon = "") =>
      pills.push(`<span class="hero-pill ${cls}">${icon}${this._escape(text)}</span>`);
    if (this._roomHeating(room)) pill("heat", t("room.pill.calling"), flameSvg());
    if (!room.trv_entity) pill("warn", t("room.pill.no_trv"));
    else if (!trv || trv.state === "unavailable" || trv.state === "unknown") pill("warn", t("room.pill.trv_offline"));
    else pill("info", t(`room.pill.trv_${trv.attributes?.hvac_action === "heating" ? "open" : trv.state === "off" ? "off" : "idle"}`));
    if (attrs.window_open) pill("warn", t("hero.pill.window_open"));
    if (live.summer_mode) pill("warn", t("hero.pill.summer"));
    if (attrs.preset_mode && attrs.preset_mode !== "none") pill("info", t(`preset.${attrs.preset_mode}`));
    else if (attrs.hold_until) pill("info", t("room.pill.until", { time: new Date(attrs.hold_until).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }));
    else if (attrs.held) pill("info", attrs.hold_ends === "manual" ? t("room.pill.held") : t("room.pill.until_house"));
    if (room.calls_for_heat === false) pill("", t("room.pill.no_boiler"));
    return pills.join("");
  }

  _renderHero() {
    const live = this._live();
    const rooms = (this._cfg().rooms || []).filter((r) => r.enabled !== false);
    const focus = this._focusRoom();
    const entityId = focus ? this._roomEntity(focus) : this._nookClimateEntities().home;
    const state = this._entityState(entityId);
    const targetNum = focus ? this._roomTarget(focus) : this._mainTarget();
    const currentNum = focus ? this._roomCurrent(focus) : this._mainCurrent();
    const target = formatTemp(targetNum) ?? "—";
    const current = currentNum != null ? formatTemp(Math.round(currentNum * 10) / 10) : null;
    const heating = focus ? this._roomHeating(focus) : Boolean(live.boiler_on);
    const off = state ? state.state === "off" : focus ? false : (live.main || {}).hvac_mode === "off";
    const preset = state?.attributes?.preset_mode ?? (focus ? "none" : (live.main || {}).preset ?? "none");
    const presets = focus ? ["eco", "boost"] : ["eco", "boost", "away"];
    const preheat = focus ? {} : live.preheat || {};
    // Minimum on/off time: the boiler is held against what Nook wants until then.
    const holdUntil = focus || off || !live.boiler_hold_until ? "" : this._ehClock(live.boiler_hold_until);
    const finishing = Boolean(holdUntil) && heating && !live.boiler_demand;
    let caption = off ? t("hero.caption.off") : heating && !finishing ? t("hero.caption.heating_to") : t("hero.caption.set_to");
    if (preheat.preheating) caption = t("hero.caption.preheating_to");
    let headline = t("hero.headline.holding");
    const trv = focus ? this._entityState(focus.trv_entity) : null;
    if (focus && focus.trv_entity && (!trv || trv.state === "unavailable" || trv.state === "unknown")) {
      headline = t("hero.headline.trv_offline");
    } else if (off) headline = focus ? t("hero.headline.radiator_off") : t("hero.headline.heating_off");
    else if (holdUntil) headline = t(heating ? "hero.headline.boiler_off_at" : "hero.headline.boiler_on_at", { time: holdUntil });
    else if (heating) headline = focus ? t("hero.headline.warming_room") : t("hero.headline.warming_house");
    else if (currentNum != null && targetNum != null && currentNum >= Number(targetNum)) headline = t("hero.headline.up_to_temp");

    const lo = Number(state?.attributes?.min_temp ?? 7);
    const hi = Number(state?.attributes?.max_temp ?? 30);
    const pos = (v) => (v == null || !Number.isFinite(Number(v)) ? null : (Number(v) - lo) / (hi - lo));
    // Warm, Nest-like: amber in Heat, deep orange while heating, grey when off (same as the card).
    const color = off
      ? ["#5f656b", "#8a9096"]
      : heating
        ? ["#FFB74D", "#F4511E"]
        : ["#FFD180", "#FF9800"];
    const eta = heating && !focus ? this._formatEta(live.time_to_temp_minutes) : null;

    const heroClass = `hero${heating ? " heating" : ""}${off ? " off" : ""}`;
    const roomTiles = rooms
      .map((room) => {
        const now = this._roomCurrent(room);
        const set = formatTemp(this._roomTarget(room));
        const heat = this._roomHeating(room);
        const selected = this._focusZone === room.id;
        const trv = this._entityState(room.trv_entity);
        const offline = Boolean(room.trv_entity) && (!trv || trv.state === "unavailable" || trv.state === "unknown");
        const roomOff = this._entityState(this._roomEntity(room))?.state === "off";
        const tip = selected ? t("hero.tile.tip_back") : offline ? t("hero.tile.tip_offline", { name: room.name }) : t("hero.tile.tip_control", { name: room.name });
        return `
          <button type="button" class="hero-room${heat ? " heat" : ""}${selected ? " selected" : ""}${offline ? " offline" : ""}" data-zone="${this._escape(room.id)}" aria-pressed="${selected}" title="${this._escape(tip)}">
            <span class="hero-room-top">
              <span class="hero-room-name">${this._escape(room.name)}</span>
              ${!offline && heat ? `<span class="hero-room-flame" title="${this._escape(t("room.pill.calling"))}">${flameSvg()}</span>` : ""}
            </span>
            <span class="hero-room-temp${now == null ? " unknown" : ""}">${now == null ? "—" : `${this._escape(formatTemp(Math.round(now * 10) / 10))}°`}</span>
            <span class="hero-room-foot">
              ${offline
                ? `<span class="hero-room-target"><span class="hero-room-off">${t("hero.tile.offline")}</span></span>`
                : roomOff
                  ? `<span class="hero-room-target">${t("common.off")}</span>`
                  : `<span class="hero-room-target">${t(heat ? "hero.tile.heating_to" : "hero.tile.set", { temp: this._escape(set ?? "—") })}</span>`}
              ${offline ? "" : this._trvBatteryHtml(room.trv_entity)}
            </span>
          </button>`;
      })
      .join("");

    return `
      <section class="${heroClass}">
        <div class="hero-left">
        <div class="hero-dial">
          ${dialSvg({ fill: off ? 0 : pos(targetNum) ?? 0, now: pos(currentNum), color })}
          <span class="hero-dial-core">
            <span class="hero-dial-caption">${this._escape(caption)}</span>
            <span class="hero-dial-temp">${this._escape(target)}${target !== "—" ? "<sup>°C</sup>" : ""}</span>
            ${current != null ? `<span class="hero-dial-sub">${t("hero.indoor", { temp: this._escape(current) })}</span>` : ""}
            ${eta ? `<span class="hero-dial-eta">${t("hero.eta", { eta: this._escape(eta) })}</span>` : ""}
          </span>
          <span class="dial-steps">
            <button type="button" class="dial-step" data-step="-1" aria-label="${this._escape(t("hero.lower"))}" ${targetNum != null && targetNum <= lo ? "disabled" : ""}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 13H5v-2h14z"/></svg>
            </button>
            <button type="button" class="dial-step" data-step="1" aria-label="${this._escape(t("hero.raise"))}" ${targetNum != null && targetNum >= hi ? "disabled" : ""}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
            </button>
          </span>
        </div>
        <div class="hm-modes">
          <div class="hm-seg" role="group" aria-label="${this._escape(t("hero.mode_group"))}">
            <button type="button" class="hm-mode heat${!off ? " active" : ""}" data-hero-hvac="heat">${flameSvg()}${t("mode.heat")}</button>
            <button type="button" class="hm-mode${off ? " active" : ""}" data-hero-hvac="off">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" d="M12 3v8M6.4 6.6a8 8 0 1 0 11.2 0"/></svg>${t("mode.off")}</button>
          </div>
          <div class="hm-seg" role="group" aria-label="${this._escape(t("hero.preset_group"))}">
            ${presets
              .map((p) => `<button type="button" class="hm-mode ${p}${preset === p ? " active" : ""}" data-hero-preset="${p}">${t(`preset.${p}`)}</button>`)
              .join("")}
          </div>
        </div>
        </div>
        <div class="hero-side">
          <div class="hero-head">
            <div>
              ${focus
                ? `<button type="button" class="hero-back" data-zone="home">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M15.4 7.4 14 6l-6 6 6 6 1.4-1.4-4.6-4.6z"/></svg>${t("hero.home")}</button>`
                : ""}
              <h2 class="hero-title">${this._escape(focus ? focus.name : t("hero.home"))}</h2>
              <p class="hero-headline">${this._escape(headline)}</p>
            </div>
            <div class="hero-pills">${focus ? this._roomPills(focus) : this._heroPills()}</div>
          </div>
          ${roomTiles
            ? `<div class="hero-rooms${rooms.length > 1 ? " reorderable" : ""}">${roomTiles}</div>
              <p class="hero-rooms-hint">${focus ? t("hero.hint.controlling", { name: this._escape(focus.name) }) : t("hero.hint.tap_room")}${rooms.length > 1 ? t("ontouchstart" in window ? "hero.hint.reorder_touch" : "hero.hint.reorder") : ""}</p>`
            : `<p class="hero-empty">${t("hero.no_rooms")}</p>`}
        </div>
      </section>`;
  }

  _renderOverview() {
    const live = this._live();
    const intel = live.intelligence || {};
    const leaf = live.leaf || {};
    const hours = (h, m) => {
      const v = h != null ? Number(h) : m != null ? Number(m) / 60 : null;
      if (v == null || !Number.isFinite(v)) return "—";
      return v < 10 ? v.toFixed(1).replace(/\.0$/, "") : Math.round(v).toLocaleString();
    };
    const streak = Number(leaf.days_streak ?? 0);
    const heater = this._cfg().heater || "";
    const heaterWarning =
      live.heater_available === false
        ? `<div class="banner err">${t("overview.banner.relay_unavailable", { relay: `<code>${this._escape(heater || t("overview.not_set"))}</code>` })}</div>`
        : "";
    const releasedWarning = live.control_released_until
      ? `<div class="banner warn">${t("overview.banner.released", { time: this._escape(this._ehClock(live.control_released_until)) })}</div>`
      : "";
    const fault = live.heating_fault;
    let faultWarning = "";
    if (fault) {
      const names = (list) => this._escape(this._listNames(list));
      const offline = fault.trvs_offline || [];
      const closed = fault.trvs_closed || [];
      const causes = [];
      if (offline.length) causes.push(tn("overview.banner.not_warming.offline", offline.length, { rooms: names(offline) }));
      if (closed.length) causes.push(t("overview.banner.not_warming.closed", { rooms: names(closed) }));
      if (!causes.length) causes.push(t("overview.banner.not_warming.boiler"));
      faultWarning = `<div class="banner err">${t("overview.banner.not_warming", { minutes: this._escape(fault.on_minutes), rise: this._escape(Number(fault.rise_c).toFixed(1)), cause: causes.join(" ") })}</div>`;
    }
    const preset = (live.main || {}).preset;
    const presetLabel = t(`preset.${!preset || preset === "none" ? "none" : preset}`);

    const stat = (tone, icon, label, value) => `
      <div class="stat ${tone}">
        <span class="stat-icon">${icon}</span>
        <div><div class="label">${label}</div><div class="value">${this._escape(value)}</div></div>
      </div>`;

    const onOff = (on) => `<span class="badge${on ? " on" : ""}">${on ? t("common.on") : t("common.off")}</span>`;
    const feature = (name, desc, valueHtml) => `
      <div class="feature">
        <div><div class="feature-name">${name}</div><div class="feature-desc">${desc}</div></div>
        <div class="feature-value">${valueHtml}</div>
      </div>`;
    const samples = Number(intel.warmup_samples ?? 0);
    const rate = intel.warmup_c_per_hour;
    const coast = intel.coast_c;
    const coastSamples = Number(intel.coast_samples ?? 0);
    const roomWarmup = live.room_warmup || {};
    const roomRates = (this._cfg().rooms || [])
      .filter((r) => roomWarmup[r.id]?.samples)
      .map((r) => {
        const w = roomWarmup[r.id];
        const lag = w.lag_minutes != null ? ` · ${t("intel.lag", { value: this._escape(Math.round(w.lag_minutes)) })}` : "";
        return `<div>${this._escape(r.name)} · ${t("unit.c_per_hour", { value: this._escape(w.c_per_hour) })}<small>${tn("intel.samples", w.samples)}${lag}</small></div>`;
      })
      .join("");

    return `
      ${heaterWarning}
      ${releasedWarning}
      ${this._sensorStatusBanner()}
      ${faultWarning}
      ${this._renderHero()}
      <div style="height:14px"></div>
      <div class="stats-row">
        ${stat(live.boiler_on ? "heat" : "", flameSvg(), t("overview.stat.boiler"), live.boiler_on ? t("common.on") : t("common.off"))}
        ${stat(preset && preset !== "none" ? "good" : "", ICONS.tune, t("overview.stat.preset"), presetLabel)}
        ${stat(live.window_open ? "warn" : "", ICONS.window, t("overview.stat.windows"), live.window_open ? t("overview.stat.open") : t("overview.stat.closed"))}
        ${stat(live.summer_mode ? "warn" : "", ICONS.sun, t("overview.stat.summer"), live.summer_mode ? t("common.on") : t("common.off"))}
        ${stat(live.away ? "warn" : "", ICONS.home, t("overview.stat.presence"), live.away ? t("overview.stat.away") : t("overview.stat.home"))}
      </div>
      <div class="ov-grid">
        <div class="card">
          <div class="card-head">
            <span class="card-icon leaf">${leafSvg()}</span>
            <div class="card-head-text">
              <p class="card-title">${t("leaf.title")}</p>
              <p class="card-sub">${leaf.active ? t("leaf.sub_active") : t("leaf.sub_inactive")}</p>
            </div>
            ${leaf.active ? `<span class="badge on">${t("leaf.earning")}</span>` : ""}
          </div>
          <div class="metric-row">
            <div class="metric"><div class="metric-value">${this._escape(hours(leaf.hours_week, leaf.minutes_week))}<small>${t("unit.hours_short")}</small></div><div class="metric-label">${t("leaf.this_week")}</div></div>
            <div class="metric"><div class="metric-value">${this._escape(hours(leaf.hours_total, leaf.minutes_total))}<small>${t("unit.hours_short")}</small></div><div class="metric-label">${t("leaf.all_time")}</div></div>
            <div class="metric"><div class="metric-value">${this._escape(streak)}<small>${tn("unit.days", streak)}</small></div><div class="metric-label">${t("leaf.streak")}</div></div>
          </div>
          ${this._renderLeafWeek(leaf.week_days)}
          <p class="card-foot">${t("leaf.foot")}</p>
        </div>
        <div class="card">
          <div class="card-head">
            <span class="card-icon intel">${ICONS.sparkle}</span>
            <div class="card-head-text">
              <p class="card-title">${t("intel.title")}</p>
              <p class="card-sub">${t("intel.sub")}</p>
            </div>
          </div>
          <div class="feature-list">
            ${feature(t("intel.true_radiant"), t("intel.true_radiant.desc"), onOff(intel.true_radiant))}
            ${feature(t("intel.auto_schedule"), t("intel.auto_schedule.desc"), onOff(intel.auto_schedule))}
            ${feature(t("intel.leaf"), t("intel.leaf.desc"), onOff(intel.leaf_enabled !== false))}
            ${feature(t("intel.away_delay"), t("intel.away_delay.desc"), t("unit.minutes", { value: this._escape(intel.away_delay_minutes ?? 20) }))}
            ${feature(t("intel.warmup"), t("intel.warmup.desc"),
              `${rate != null ? t("unit.c_per_hour", { value: this._escape(rate) }) : "—"}<small>${samples ? tn("intel.samples", samples) : t("intel.still_learning")}${intel.warmup_lag_minutes != null ? ` · ${t("intel.lag", { value: this._escape(Math.round(intel.warmup_lag_minutes)) })}` : ""}</small>`)}
            ${roomRates ? feature(t("intel.room_warmup"), t("intel.room_warmup.desc"), `<div class="room-rates">${roomRates}</div>`) : ""}
            ${feature(t("intel.coast"), t("intel.coast.desc"),
              `${coast != null ? t("unit.celsius", { value: this._escape(Number(coast).toFixed(2)) }) : "—"}<small>${coastSamples ? tn("intel.runs", coastSamples) : t("intel.still_learning")}</small>`)}
          </div>
        </div>
      </div>
      ${this._renderEntitiesCard(heater)}
    `;
  }

  /** Last 7 days of Leaf time as bars; green = a Leaf day. Older backends send no week_days. */
  _renderLeafWeek(days) {
    if (!Array.isArray(days) || !days.length) return "";
    // Scale to the best day, but never below 2 h so a few minutes don't look like a full bar.
    const max = Math.max(120, ...days.map((d) => Number(d.minutes) || 0));
    const earnedCount = days.filter((d) => d.earned).length;
    const bars = days
      .map((d, i) => {
        const mins = Number(d.minutes) || 0;
        const date = new Date(`${d.date}T12:00:00`);
        const name = date.toLocaleDateString([], { weekday: "short" });
        const today = i === days.length - 1;
        const tip = `${name} ${date.getDate()} · ${mins ? t("leaf.day.time", { duration: this._ehDuration(mins) }) : t("leaf.day.none")}${d.earned ? t("leaf.day.earned") : ""}`;
        return `
          <div class="leaf-day${d.earned ? " earned" : ""}${today ? " today" : ""}" title="${this._escape(tip)}">
            <div class="leaf-day-track"><div class="leaf-day-bar" style="height:${mins ? Math.max(4, (mins / max) * 100) : 0}%"></div></div>
            <span class="leaf-day-label">${today ? t("leaf.today") : this._escape(name.slice(0, 3))}</span>
          </div>`;
      })
      .join("");
    return `
      <div class="leaf-week">
        <div class="leaf-week-title"><span>${t("leaf.last_7_days")}</span><span>${t("leaf.days_of_7", { count: earnedCount })}</span></div>
        <div class="leaf-week-bars">${bars}</div>
      </div>`;
  }

  _renderEntitiesCard(heater) {
    const nook = this._nookClimateEntities();
    const chip = (entityId) => {
      if (!entityId) return `<span class="muted">—</span>`;
      const st = this._entityState(entityId);
      const name = this._entityName(entityId);
      const state = st ? st.state : t("entities.missing");
      const bad = !st || state === "unavailable" || state === "unknown";
      return `
        <div class="entity-chip" title="${this._escape(entityId)}">
          <span class="entity-chip-name">${this._escape(name)}<span class="entity-chip-state${bad ? " bad" : ""}">${this._escape(state)}</span></span>
          <code>${this._escape(entityId)}</code>
        </div>`;
    };
    const row = (label, ids) => `
      <div class="entity-row">
        <div class="entity-row-label">${label}</div>
        <div class="entity-chips">${ids.length ? ids.map(chip).join("") : chip("")}</div>
      </div>`;
    const total = (nook.home ? 1 : 0) + nook.rooms.length + (heater ? 1 : 0);
    return `
      <details class="card" id="ovEntities" ${this._entitiesOpen ? "open" : ""}>
        <summary>
          <span class="card-icon">${ICONS.link}</span>
          <div class="card-head-text">
            <p class="card-title">${t("entities.title")}</p>
            <p class="card-sub">${t("entities.sub", { count: total })}</p>
          </div>
          <svg class="chev" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="currentColor" d="M7.4 8.6 12 13.2l4.6-4.6L18 10l-6 6-6-6z"/></svg>
        </summary>
        <div class="entity-rows">
          ${row(t("entities.house"), nook.home ? [nook.home] : [])}
          ${row(t("entities.rooms"), nook.rooms)}
          ${row(t("entities.relay"), heater ? [heater] : [])}
        </div>
      </details>`;
  }

  _ehDayParts(isoDate) {
    const d = new Date(`${isoDate}T12:00:00`);
    const weekday = DAY_SHORT[["sun", "mon", "tue", "wed", "thu", "fri", "sat"][d.getDay()]];
    return {
      label: `${weekday} ${d.getDate()}`,
      monthKey: `${d.getFullYear()}-${d.getMonth()}`,
      monthName: MONTHS[d.getMonth()],
    };
  }

  _ehPct(ts, dayIso) {
    if (!ts) return 100;
    const when = new Date(ts);
    const start = new Date(`${dayIso}T00:00:00`);
    const mins = (when - start) / 60000;
    return Math.max(0, Math.min(100, (mins / (24 * 60)) * 100));
  }

  /** Minutes of boiler time in a day, clipped to that day. */
  _ehHeatMinutes(day) {
    return (day.heat_intervals || []).reduce((sum, iv) => {
      const left = this._ehPct(iv.start_ts, day.date);
      const right = this._ehPct(iv.end_ts || new Date().toISOString(), day.date);
      return sum + Math.max(0, right - left) * 14.4;
    }, 0);
  }

  _ehDuration(mins) {
    const m = Math.round(mins);
    if (m <= 0) return "—";
    if (m < 60) return t("time.m", { m });
    const h = Math.floor(m / 60);
    return m % 60 ? t("time.hm", { h, m: m % 60 }) : t("time.h", { h });
  }

  _renderEnergyDay(day) {
    const parts = this._ehDayParts(day.date);
    const segs = (day.heat_intervals || [])
      .map((iv) => {
        const left = this._ehPct(iv.start_ts, day.date);
        const right = this._ehPct(iv.end_ts || new Date().toISOString(), day.date);
        const span = `${this._ehClock(iv.start_ts)}–${iv.end_ts ? this._ehClock(iv.end_ts) : t("energy.now")}`;
        return `<div class="eh-seg" style="left:${left}%;width:${Math.max(0, right - left)}%" title="${this._escape(t("energy.heating_span", { span }))}"></div>`;
      })
      .join("");
    // Setpoint bubbles; clamped so ones near midnight stay inside the timeline.
    const points = [...(day.setpoints || [])]
      .sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
      .map((sp) => {
        const left = this._ehPct(sp.ts, day.date);
        const temp = formatTemp(sp.temperature) ?? "—";
        return `<div class="eh-sp" data-pct="${left}" style="left:clamp(13px, ${left}%, calc(100% - 13px))" title="${this._escape(t("energy.set_at", { temp, time: this._ehClock(sp.ts) }))}">${this._escape(temp)}</div>`;
      })
      .join("");
    const mins = this._ehHeatMinutes(day);
    // Gas (or energy) per hour under the boiler runs, on one scale for the whole page.
    const meter = this._energy?.meter;
    const used = meter?.days?.[day.date];
    let lane = "";
    let usedTotal = "";
    if (meter) {
      const unit = meter.unit || "kWh";
      const max = this._ehMeterMax || 1;
      const bars = (used?.hours || new Array(24).fill(0))
        .map((v, h) => {
          // Square-root scale: one big hour mustn't flatten the rest of the day.
          const pct = v > 0 ? Math.max(10, Math.sqrt(v / max) * 100) : 0;
          const tip = t("energy.meter_hour", { time: `${String(h).padStart(2, "0")}:00`, amount: formatMeter(v, unit), unit });
          return `<span style="height:${pct.toFixed(1)}%" title="${this._escape(tip)}"></span>`;
        })
        .join("");
      lane = `<div class="eh-gas">${bars}</div>`;
      usedTotal = used && used.total > 0
        ? `<div class="eh-day-gas" title="${this._escape(t("energy.meter_day"))}">${formatMeter(used.total, unit)} ${this._escape(unit)}</div>`
        : "";
    }
    return `
      <div class="eh-day eh-grid-row">
        <div class="eh-day-label">${this._escape(parts.label)}${day.leaf ? `<span title="${this._escape(t("energy.leaf_earned"))}">${leafSvg()}</span>` : ""}</div>
        <div class="eh-timeline">
          ${points}
          <div class="eh-track">${segs}</div>
          ${lane}
        </div>
        <div class="eh-day-total${mins > 0 ? "" : " none"}">
          <div title="${this._escape(t("energy.running_time"))}">${this._ehDuration(mins)}</div>
          ${usedTotal}
        </div>
      </div>`;
  }

  /**
   * Nudge setpoint bubbles apart so close changes sit side by side instead of on top of
   * each other (time is exact in each bubble's tooltip). Re-runs when the card resizes.
   */
  _layoutEnergyBubbles() {
    this._ehResize?.disconnect();
    this._ehResize = null;
    const card = this.shadowRoot.querySelector(".eh-timeline")?.closest(".card");
    if (!card) return;
    const pack = () => {
      card.querySelectorAll(".eh-timeline").forEach((line) => {
        const width = line.clientWidth;
        const bubbles = [...line.querySelectorAll(".eh-sp")];
        if (!width || !bubbles.length) return;
        const size = bubbles[0].offsetWidth || 26;
        const gap = size + 2;
        const half = size / 2;
        const xs = bubbles.map((b) => Math.min(width - half, Math.max(half, (Number(b.dataset.pct) / 100) * width)));
        for (let i = 1; i < xs.length; i++) xs[i] = Math.max(xs[i], xs[i - 1] + gap);
        // Pushed past the end: pull the tail back, keeping the spacing.
        if (xs[xs.length - 1] > width - half) {
          xs[xs.length - 1] = width - half;
          for (let i = xs.length - 2; i >= 0; i--) xs[i] = Math.min(xs[i], xs[i + 1] - gap);
        }
        bubbles.forEach((b, i) => (b.style.left = `${xs[i]}px`));
      });
    };
    pack();
    this._ehResize = new ResizeObserver(pack);
    this._ehResize.observe(card);
  }

  /** "14:05" today, else "Wed 14:05". */
  _sinceText(ts) {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return "";
    if (d.toDateString() === new Date().toDateString()) return this._ehClock(ts);
    return d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
  }

  _ehClock(ts) {
    const d = new Date(ts);
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  _renderEnergy() {
    const hist = this._energy?.history?.days || [];
    const seasonal = this._energy?.seasonal_savings || this._live().seasonal_savings || {};
    const seasonalSummary = (s) => {
      const days = Number(s.days_remaining ?? 0);
      const lowered = Number(s.blocks_lowered ?? 0);
      const kept = Number(s.blocks_kept ?? 0);
      const parts = [tn("seasonal.days_to_go", days)];
      parts.push(lowered ? tn("seasonal.blocks_cooler", lowered, { offset: Math.abs(Number(s.offset_c ?? 0)).toFixed(1) }) : t("seasonal.starting"));
      if (kept) parts.push(tn("seasonal.kept", kept));
      return parts.join(" · ");
    };
    const banner = seasonal.active
      ? `<div class="eh-banner">
          <div class="eh-copy">
            <strong>${t("seasonal.title")}</strong>
            <span class="muted">${this._escape(seasonalSummary(seasonal))}</span>
          </div>
          <button type="button" class="secondary" id="stopSeasonal" title="${this._escape(t("seasonal.stop.tip"))}">${t("seasonal.stop")}</button>
        </div>`
      : "";
    const meter = this._energy?.meter || null;
    const meterUnit = meter?.unit || "kWh";
    const meterDays = Object.values(meter?.days || {});
    this._ehMeterMax = Math.max(0, ...meterDays.flatMap((d) => d.hours || []));
    let lastMonth = null;
    const rows = hist
      .map((day) => {
        const parts = this._ehDayParts(day.date);
        let month = "";
        if (parts.monthKey !== lastMonth) {
          lastMonth = parts.monthKey;
          month = `<div class="eh-month">${this._escape(parts.monthName)}</div>`;
        }
        return `${month}${this._renderEnergyDay(day)}`;
      })
      .join("");
    const totalMins = hist.reduce((sum, day) => sum + this._ehHeatMinutes(day), 0);
    const leafDays = hist.filter((d) => d.leaf).length;
    const axis = [
      ["energy.axis.midnight", 0, ""], ["energy.axis.6am", 25, "half"], ["energy.axis.noon", 50, ""], ["energy.axis.6pm", 75, "half"], ["energy.axis.midnight", 100, ""],
    ].map(([key, at, cls]) => `<span class="${cls}" style="left:${at}%">${t(key)}</span>`).join("");
    // Cards across the top, like the wall panel's usage page.
    const days = hist.length || 1;
    const gasTotal = meterDays.reduce((sum, d) => sum + (Number(d.total) || 0), 0);
    const isGas = meter && (meter.kind === "volume" || /gas/i.test(`${meter.entity_id} ${meter.name}`));
    const streak = Number(this._live().leaf?.days_streak) || 0;
    const tile = (cls, icon, value, label, sub) => `
      <div class="eh-tile ${cls}">
        <span class="eh-badge">${icon}</span>
        <div class="eh-tile-text">
          <div class="eh-tile-value">${value}</div>
          <div class="eh-tile-label">${label}</div>
          <div class="eh-tile-sub">${sub}</div>
        </div>
      </div>`;
    const tiles = hist.length
      ? `<div class="eh-tiles">
          ${tile("heat", TILE_ICONS.heat, this._ehDuration(totalMins), t("energy.card.boiler"), t("energy.card.avg_day", { value: this._ehDuration(totalMins / days) }))}
          ${meter
            ? tile(
                "gas",
                TILE_ICONS.gas,
                `${formatMeter(gasTotal, meterUnit)}<small>${this._escape(meterUnit)}</small>`,
                isGas ? t("energy.card.gas") : t("energy.card.energy"),
                t("energy.card.avg_day", { value: `${formatMeter(gasTotal / days, meterUnit)} ${this._escape(meterUnit)}` })
              )
            : ""}
          ${tile("leaf", TILE_ICONS.leaf, `${leafDays}<small>/ ${days}</small>`, t("energy.card.leaf"), streak ? t("energy.card.streak", { count: streak }) : t("energy.card.no_streak"))}
        </div>
        <p class="eh-tiles-note">${t("energy.card.period", { days })}</p>`
      : "";
    const meterLegend = meter
      ? `<span><em></em>${t("energy.legend.meter", { unit: this._escape(meterUnit) })}</span>`
      : "";
    return `
      ${this._pageHeader(t("energy.title"), t("energy.lead"))}
      ${banner}
      ${tiles}
      <div class="card${meter ? " eh-has-meter" : ""}">
        ${rows
          ? `<div class="eh-head">
              <div class="eh-legend"><span><i></i>${t("energy.legend.heating")}</span>${meterLegend}<span><b></b>${t("energy.legend.setpoint")}</span><span>${leafSvg()}${t("energy.legend.leaf_day")}</span></div>
            </div>
            <div class="eh-axis-row eh-grid-row"><span></span><div class="eh-axis">${axis}</div><span></span></div>
            ${rows}`
          : `<p class="muted" style="margin:0">${t("energy.empty")}</p>`}
      </div>
    `;
  }

  _pointLeftPercent(start) {
    // Map 0–24h across the full width.
    const mins = parseHHMM(start);
    return Math.max(1, Math.min(99, (mins / (24 * 60)) * 100));
  }

  /**
   * Blocks that overlap, per day, in words. The backend's rule: the block that started
   * last is in charge while both run; one that ends before it starts runs past midnight.
   */
  _scheduleOverlaps(schedule) {
    const span = (b, shift = 0) => {
      const s = parseHHMM(b.start);
      let e = parseHHMM(b.end);
      if (e <= s) e += 24 * 60;
      return { s: s + shift, e: e + shift, b };
    };
    const lines = [];
    DAYS.forEach((day, i) => {
      const prev = DAYS[(i + 6) % 7];
      const own = (schedule[day] || []).filter((b) => b.enabled !== false && b.start !== b.end).map((b) => span(b));
      // Last night's overnight block, still running this morning.
      const carried = (schedule[prev] || [])
        .filter((b) => b.enabled !== false && parseHHMM(b.end) < parseHHMM(b.start))
        .map((b) => span(b, -24 * 60));
      const all = [...carried, ...own].sort((a, b) => a.s - b.s);
      for (let x = 0; x < all.length; x++) {
        for (let y = x + 1; y < all.length; y++) {
          const [a, b] = [all[x], all[y]];
          if (b.s >= a.e || !own.includes(b)) continue;
          lines.push(t("schedule.overlap", {
            day: DAY_SHORT[day],
            later: `${this._escape(b.b.start)}–${this._escape(b.b.end)}`,
            earlier: `${carried.includes(a) ? `${DAY_SHORT[prev]} ` : ""}${this._escape(a.b.start)}–${this._escape(a.b.end)}`,
          }));
        }
      }
    });
    return lines;
  }

  _timeAxisLabels() {
    // Each label at its real time, on the same 0–24 h scale as the dots.
    const hours = [["1a", 1], ["3a", 3], ["5a", 5], ["7a", 7], ["9a", 9], ["11a", 11], ["noon", 12], ["1p", 13], ["3p", 15], ["5p", 17], ["7p", 19], ["9p", 21], ["11p", 23]];
    return hours.map(([key, h]) => `<span style="left:${((h / 24) * 100).toFixed(2)}%">${t(`schedule.axis.${key}`)}</span>`).join("");
  }

  _renderSchedule() {
    const schedule = this._cfg().schedule || {};
    const enabled = this._cfg().schedule_enabled !== false;
    const eco = this._cfg().eco_temp ?? 16;
    const sel = this._selectedPoint;
    // The form below shows the selected block (and edits it), or a new block.
    const selBlock = sel ? (schedule[sel.day] || [])[sel.index] || null : null;
    const form = selBlock
      ? { day: sel.day, start: selBlock.start, end: selBlock.end, temp: selBlock.temperature }
      : { day: this._selectedDay, start: "06:30", end: "08:30", temp: this._mainTarget() ?? 20 };
    const overlaps = this._scheduleOverlaps(schedule);

    const rows = DAYS.map((day) => {
      const blocks = schedule[day] || [];
      const selectedDay = this._selectedDay === day;
      const points = blocks
        .map((b, index) => {
          const left = this._pointLeftPercent(b.start);
          const temp = formatTemp(b.temperature) ?? "—";
          const isSel = sel && sel.day === day && sel.index === index;
          return `<button type="button" class="nest-point${isSel ? " selected" : ""}"
            style="left:${left}%"
            data-day="${day}" data-index="${index}"
            title="${this._escape(b.start)} → ${this._escape(b.end)} · ${this._escape(temp)}°">${this._escape(temp)}</button>`;
        })
        .join("");
      return `
        <div class="nest-day-label">${DAY_LABELS[day]}</div>
        <div class="nest-day-track${selectedDay ? " selected" : ""}" data-day-track="${day}">${points}</div>`;
    }).join("");

    return `
      ${this._renderHero()}
      <div class="nest-schedule-sheet">
        <div class="nest-schedule-toolbar">
          <span class="pill">${t("schedule.title")}</span>
          <label class="field" style="flex:0;min-width:120px;margin:0">
            ${t("schedule.enabled")}
            <select id="schedEnabled">
              <option value="true" ${enabled ? "selected" : ""}>${t("common.on")}</option>
              <option value="false" ${!enabled ? "selected" : ""}>${t("common.off")}</option>
            </select>
          </label>
        </div>
        <div class="nest-schedule-grid">
          ${rows}
          <div></div>
          <div class="nest-time-axis">${this._timeAxisLabels()}</div>
        </div>
        <div class="nest-schedule-actions">
          <div class="group">
            <button type="button" class="linkish" id="schedCopy">${t("schedule.copy")}</button>
            <button type="button" class="linkish" id="schedPaste">${t("schedule.paste")}</button>
          </div>
          <div class="group">
            <button type="button" class="linkish" id="schedRemove">${t("schedule.remove")}</button>
            <button type="button" class="linkish" id="schedAdd">${t("schedule.add")}</button>
          </div>
        </div>
        ${overlaps.length ? `<div class="nest-overlaps">${overlaps.map((l) => `<p>${l}</p>`).join("")}</div>` : ""}
        <p class="nest-edit-note${selBlock ? " editing" : ""}">${selBlock
          ? t("schedule.editing", {
            day: DAY_SHORT[sel.day],
            start: this._escape(selBlock.start),
            end: this._escape(selBlock.end),
            overnight: parseHHMM(selBlock.end) < parseHHMM(selBlock.start)
              ? ` ${t("schedule.overnight", { day: DAY_SHORT[DAYS[(DAYS.indexOf(sel.day) + 1) % 7]] })}`
              : "",
          })
          : t("schedule.new_block")}</p>
        <div class="nest-add-row">
          <label class="field">${t("schedule.day")}
            <select id="addDay">${DAYS.map((d) => `<option value="${d}" ${form.day === d ? "selected" : ""}>${DAY_SHORT[d]}</option>`).join("")}</select>
          </label>
          <label class="field">${t("schedule.start")}<input id="addStart" type="time" value="${this._escape(form.start)}" /></label>
          <label class="field">${t("schedule.end")}<input id="addEnd" type="time" value="${this._escape(form.end)}" /></label>
          <label class="field">${t("schedule.temp")}<input id="addTemp" type="number" step="0.5" value="${this._escape(form.temp)}" /></label>
          <button type="button" class="primary" id="saveSchedule">${t("schedule.save")}</button>
        </div>
        <p class="muted" style="margin:0 12px 8px">${t("schedule.help", { eco: this._escape(eco) })}</p>
      </div>
    `;
  }

  /** Rooms, as a card on the Settings page (the Overview handles day-to-day use). */
  _renderRoomsCard() {
    const rooms = this._cfg().rooms || [];
    const editing = this._editingRoomId;
    const editingRoom = editing ? rooms.find((r) => r.id === editing) : null;
    const cards = rooms
      .map((r) => {
        const live = (this._live().rooms || {})[r.id] || {};
        const calls = r.calls_for_heat !== false;
        const now = this._roomCurrent(r);
        const target = formatTemp(live.target ?? r.target_temp);
        const trv = this._entityState(r.trv_entity);
        const trvBad = !trv || trv.state === "unavailable" || trv.state === "unknown";
        const sensors = [r.temperature_sensor, ...(r.extra_temperature_sensors || [])].filter(Boolean).length;
        const floor = (this._live().room_floors || {})[r.id]?.name;
        return `
          <div class="room-card${editing === r.id ? " selected" : ""}${live.needs_heat ? " heat" : ""}" data-room-id="${this._escape(r.id)}" role="button" tabindex="0" title="${this._escape(t("rooms.card.tip"))}">
            <div class="room-card-top">
              <span class="room-card-name">${this._escape(r.name)}</span>
              ${live.needs_heat ? `<span class="set-state heat-badge">${flameSvg()}${t("rooms.card.heating")}</span>` : ""}
            </div>
            <div class="room-card-temps">
              <span class="room-card-now${now == null ? " unknown" : ""}">${now == null ? "—" : `${this._escape(formatTemp(Math.round(now * 10) / 10))}°`}</span>
              <span class="room-card-target">${t("hero.tile.set", { temp: this._escape(target ?? "—") })}</span>
            </div>
            <div class="room-card-meta">
              <span class="set-state ${trvBad ? "bad" : "good"}" title="${this._escape(r.trv_entity)}">${trvBad ? t("rooms.card.trv_state", { state: this._escape(trv ? trv.state : t("entities.missing")) }) : t("rooms.card.trv_online")}</span>
              ${floor ? `<span class="room-card-sensors">${this._escape(floor)}</span>` : ""}
              <span class="room-card-sensors">${sensors ? tn("rooms.card.sensors", sensors) : t("rooms.card.trv_temperature")}</span>
              <span class="room-card-sensors">${r.follow_house !== false
                ? (Number(r.house_offset)
                  ? t("rooms.card.follows_offset", { offset: `${Number(r.house_offset) > 0 ? "+" : "−"}${formatTemp(Math.abs(Number(r.house_offset)))}` })
                  : t("rooms.card.follows"))
                : t("rooms.card.own_temps")}</span>
            </div>
            <div class="room-card-calls">
              <span>${t("rooms.card.calls_boiler")}</span>
              <label class="switch" title="${this._escape(t("rooms.card.calls_boiler.tip"))}"><input type="checkbox" data-toggle-calls="${this._escape(r.id)}" ${calls ? "checked" : ""} /><span></span></label>
            </div>
          </div>`;
      })
      .join("");
    return `
      <div class="card" id="roomsCard">
        <div class="card-head">
          <span class="card-icon">${ICONS.home}</span>
          <div class="card-head-text">
            <p class="card-title">${t("rooms.title")}</p>
            <p class="card-sub">${t("rooms.sub")}${rooms.length ? t("rooms.sub_edit") : ""}</p>
          </div>
          <button class="secondary compact" id="addRoom" type="button">${ICONS.plus}${t("rooms.add")}</button>
        </div>
        ${rooms.length
          ? `<div class="room-grid${rooms.length > 1 ? " reorderable" : ""}">${cards}</div>`
          : `<p class="muted" style="margin:0">${t("rooms.empty")}</p>`}
      </div>
    `;
  }

  _renderRoomDialog() {
    const editing = this._editingRoomId;
    const room = editing ? (this._cfg().rooms || []).find((r) => r.id === editing) : null;
    const d = { ...ROOM_TEMP_DEFAULTS, ...this._roomDraft };
    return this._dialog({
      icon: editing ? ICONS.tune : ICONS.home,
      title: editing ? t("room_dlg.title_edit", { name: this._escape(room?.name || t("room_dlg.room")) }) : t("room_dlg.title_add"),
      sub: editing ? t("room_dlg.sub_edit") : t("room_dlg.sub_add"),
      body: `
        <div class="dlg-section">
          <div class="set-field">
            <div class="set-field-label">${t("room_dlg.name")}</div>
            <input id="roomName" placeholder="${this._escape(t("room_dlg.name.placeholder"))}" value="${this._escape(this._roomDraft.name || "")}" />
          </div>
          <div class="set-field">
            <div class="set-field-label">${t("room_dlg.trv")}</div>
            <div class="entity-picker-host" data-room-picker="trv"></div>
            <div class="set-row-desc">${t("room_dlg.trv.desc")}</div>
          </div>
        </div>
        <div class="dlg-section">
          <div class="dlg-section-title">${t("room_dlg.section.temperature")}</div>
          <div class="set-field">
            <div class="set-field-label">${t("room_dlg.sensor")}</div>
            <div class="entity-picker-host" data-room-picker="sensor"></div>
            <div class="set-row-desc">${t("room_dlg.sensor.desc")}</div>
          </div>
          <div class="set-field">
            <div class="set-field-label">${t("room_dlg.extras")}</div>
            <div class="set-row-desc" style="margin:0 0 8px">${t("room_dlg.extras.desc")}</div>
            <div class="set-list" data-room-extras-list>${this._renderRoomExtras()}</div>
            <div class="entity-picker-host set-add" data-room-picker="extras"></div>
          </div>
        </div>
        <div class="dlg-section">
          <div class="dlg-section-title">${t("room_dlg.section.room_temperature")}</div>
          <div class="set-row">
            <div class="set-row-text">
              <div class="set-row-name">${t("room_dlg.follow")}</div>
              <div class="set-row-desc">${t("room_dlg.follow.desc")}</div>
            </div>
            <div class="set-row-control"><label class="switch"><input type="checkbox" id="roomFollowHouse" ${d.follow_house ? "checked" : ""} /><span></span></label></div>
          </div>
          <div class="set-field" data-follow="on" ${d.follow_house ? "" : "hidden"}>
            <div class="set-field-label">${t("room_dlg.offset")}</div>
            <div class="num-input"><input id="roomOffset" type="number" step="0.5" min="-5" max="5" value="${this._escape(d.house_offset)}" /><span>°C</span></div>
            <div class="set-row-desc">${t("room_dlg.offset.desc")}</div>
          </div>
          <div class="set-field-pair" data-follow="off" ${d.follow_house ? "hidden" : ""}>
            <div class="set-field">
              <div class="set-field-label">${t("room_dlg.comfort")}</div>
              <div class="num-input"><input id="roomComfort" type="number" step="0.5" min="5" max="30" value="${this._escape(d.target_temp)}" /><span>°C</span></div>
            </div>
            <div class="set-field">
              <div class="set-field-label">${t("room_dlg.eco")}</div>
              <div class="num-input"><input id="roomEco" type="number" step="0.5" min="5" max="30" value="${this._escape(d.eco_temp)}" /><span>°C</span></div>
            </div>
            <div class="set-row-desc">${t("room_dlg.own_temps.desc")}</div>
          </div>
          <div class="set-field">
            <div class="set-field-label">${t("room_dlg.hold_ends")}</div>
            <select id="roomHoldEnds">
              ${["house_change", "block_change", "manual"]
                .map((v) => `<option value="${v}" ${d.hold_ends === v ? "selected" : ""}>${t(`room_dlg.hold_ends.${v}`)}</option>`)
                .join("")}
            </select>
            <div class="set-row-desc">${t("room_dlg.hold_ends.desc")}</div>
          </div>
        </div>
        <div class="dlg-section">
          <div class="set-row">
            <div class="set-row-text">
              <div class="set-row-name">${t("room_dlg.calls")}</div>
              <div class="set-row-desc">${t("room_dlg.calls.desc")}</div>
            </div>
            <div class="set-row-control"><label class="switch"><input type="checkbox" id="roomCallsForHeat" ${this._roomDraft.calls_for_heat !== false ? "checked" : ""} /><span></span></label></div>
          </div>
          <div class="set-row">
            <div class="set-row-text">
              <div class="set-row-name">${t("room_dlg.calibrate")}</div>
              <div class="set-row-desc">${t("room_dlg.calibrate.desc")}</div>
            </div>
            <div class="set-row-control"><label class="switch"><input type="checkbox" id="roomCalibrateTrv" ${this._roomDraft.calibrate_trv ? "checked" : ""} /><span></span></label></div>
          </div>
        </div>
        <div class="dlg-section">
          <div class="dlg-section-title">${t("room_dlg.section.trv_config")}</div>
          <div class="trv-cfg" data-trv-config>${this._renderTrvConfig()}</div>
        </div>`,
      foot: `
        ${editing ? `<button class="danger" id="deleteRoom" type="button">${t("common.delete")}</button>` : ""}
        <span style="flex:1"></span>
        <button class="secondary" data-close-dialog type="button">${t("common.cancel")}</button>
        <button class="primary" id="saveRoom" type="button">${editing ? t("common.save_changes") : t("rooms.add")}</button>`,
    });
  }

  /** The room dialog's temperature fields, as RoomConfig values (bad numbers fall back). */
  _readRoomTempFields() {
    const el = (id) => this.shadowRoot.getElementById(id);
    const d = { ...ROOM_TEMP_DEFAULTS, ...this._roomDraft };
    const numOr = (id, fallback, lo, hi) => {
      const n = Number(el(id)?.value);
      return el(id) && el(id).value !== "" && Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : fallback;
    };
    return {
      follow_house: el("roomFollowHouse") ? el("roomFollowHouse").checked : d.follow_house,
      house_offset: numOr("roomOffset", d.house_offset, -5, 5),
      target_temp: numOr("roomComfort", d.target_temp, 5, 30),
      eco_temp: numOr("roomEco", d.eco_temp, 5, 30),
      hold_ends: el("roomHoldEnds")?.value || d.hold_ends,
    };
  }

  _renderRoomExtras() {
    const ids = this._roomDraft.extras || [];
    if (!ids.length) return "";
    return this._renderEntityRows(ids, "sensor", "room_extras");
  }

  _refreshRoomExtras() {
    const box = this.shadowRoot.querySelector("[data-room-extras-list]");
    if (box) box.innerHTML = this._renderRoomExtras();
  }

  _clearRoomForm() {
    this._closeDialog();
  }

  /** Open the room dialog: a room to edit, or nothing to add one. */
  _loadRoomIntoForm(room) {
    this._editingRoomId = room?.id || null;
    this._roomDraft = {
      name: room?.name || "",
      trv: room?.trv_entity || "",
      sensor: room?.temperature_sensor || "",
      extras: [...(room?.extra_temperature_sensors || [])],
      calls_for_heat: room ? room.calls_for_heat !== false : true,
      calibrate_trv: room?.calibrate_trv === true,
      follow_house: room ? room.follow_house !== false : true,
      house_offset: room?.house_offset ?? ROOM_TEMP_DEFAULTS.house_offset,
      hold_ends: room?.hold_ends || ROOM_TEMP_DEFAULTS.hold_ends,
      target_temp: room?.target_temp ?? ROOM_TEMP_DEFAULTS.target_temp,
      eco_temp: room?.eco_temp ?? ROOM_TEMP_DEFAULTS.eco_temp,
    };
    this._openDialog("room");
  }

  async _mountRoomPickers() {
    if (this._view !== "settings" || !this._hass) return;
    const gen = ++this._roomPickerMountGen;
    const hosts = [...(this.shadowRoot?.querySelectorAll("[data-room-picker]") || [])];
    if (!hosts.length) return;
    for (const host of hosts) {
      if (!host.querySelector("ha-entity-picker")) {
        host.innerHTML = `<p class="entity-picker-loading">${t("picker.loading")}</p>`;
      }
    }
    try {
      await ensureHaEntityPickerLoaded();
    } catch (err) {
      if (gen !== this._roomPickerMountGen) return;
      for (const host of hosts) {
        host.innerHTML = `<p class="entity-picker-error">${this._escape(err?.message || t("picker.unavailable"))}</p>`;
      }
      return;
    }
    if (gen !== this._roomPickerMountGen || this._view !== "settings") return;

    const make = (key, { domains, filter, placeholder }) => {
      const host = this.shadowRoot.querySelector(`[data-room-picker="${key}"]`);
      if (!host) return null;
      host.replaceChildren();
      const picker = document.createElement("ha-entity-picker");
      picker.setAttribute("allow-custom-entity", "");
      if (this._hass.userData?.showEntityIdPicker) picker.setAttribute("show-entity-id", "");
      picker.includeDomains = domains;
      if (filter) picker.entityFilter = filter;
      if (placeholder) picker.placeholder = placeholder;
      picker.hass = this._hass;
      host.appendChild(picker);
      return picker;
    };

    for (const [key, opts] of [
      ["trv", { domains: ["climate"] }],
      ["sensor", { domains: ["sensor"], filter: temperatureSensorFilter }],
    ]) {
      const picker = make(key, opts);
      if (!picker) continue;
      picker.value = this._roomDraft[key] || undefined;
      picker.addEventListener("value-changed", (ev) => {
        const changed = (this._roomDraft[key] || "") !== (ev.detail?.value || "");
        this._roomDraft[key] = ev.detail?.value || "";
        if (key === "trv" && changed) this._refreshTrvConfig();
      });
    }

    const extras = make("extras", { domains: ["sensor"], filter: temperatureSensorFilter, placeholder: t("room_dlg.extras.add") });
    extras?.addEventListener("value-changed", (ev) => {
      const id = ev.detail?.value;
      if (!id) return;
      if (!this._roomDraft.extras.includes(id)) this._roomDraft.extras = [...this._roomDraft.extras, id];
      this._refreshRoomExtras();
      setTimeout(() => (extras.value = undefined), 0);
    });
  }

  _readRoomPickerValues() {
    // Pickers write into the draft as they change.
    return this._roomDraft;
  }

  /**
   * The TRV's own settings: every entity on the TRV's device that HA files under
   * "Configuration" (what ZHA, Zigbee2MQTT, Z-Wave JS… show on the device page).
   * Nothing is model-specific — the control follows the entity's domain and attributes.
   */
  _trvConfigEntities(trvId) {
    const entities = this._hass?.entities;
    const dev = trvId && entities?.[trvId]?.device_id;
    if (!dev) return [];
    const order = Object.keys(TRV_CONFIG_DOMAINS);
    return Object.entries(entities)
      .filter(([id, ent]) => ent.device_id === dev && id !== trvId && !ent.hidden
        && ent.entity_category === "config" && order.includes(id.split(".")[0]) && this._hass.states[id])
      .map(([id]) => ({ id, domain: id.split(".")[0], name: this._trvConfigName(id, dev) }))
      .sort((a, b) => (a.domain === "button") - (b.domain === "button") || a.name.localeCompare(b.name));
  }

  /** "Kitchen Radiator Child lock" → "Child lock" (HA puts the device name in front). */
  _trvConfigName(id, deviceId) {
    const dev = this._hass?.devices?.[deviceId];
    const devName = dev?.name_by_user || dev?.name || "";
    let name = this._entityState(id)?.attributes?.friendly_name || id;
    if (devName && name.startsWith(`${devName} `)) name = name.slice(devName.length + 1);
    return name.charAt(0).toUpperCase() + name.slice(1);
  }

  _renderTrvConfig() {
    const trvId = this._roomDraft.trv;
    if (!trvId) return `<div class="set-row-desc">${t("room_dlg.trv_config.pick")}</div>`;
    const items = this._trvConfigEntities(trvId);
    if (!items.length) return `<div class="set-row-desc">${t("room_dlg.trv_config.none")}</div>`;
    const rows = items.map(({ id, domain, name }) => {
      const st = this._entityState(id);
      const a = st.attributes || {};
      const off = st.state === "unavailable" ? "disabled" : "";
      const known = st.state !== "unknown" && st.state !== "unavailable";
      const value = known ? st.state : "";
      const key = `data-trv-cfg="${this._escape(id)}"`;
      let control;
      if (domain === "number") {
        const attr = (n) => (a[n] != null ? `${n}="${this._escape(a[n])}"` : "");
        control = `<div class="num-input"><input type="number" ${key} ${attr("min")} ${attr("max")} ${attr("step")} value="${this._escape(value)}" ${off} />${a.unit_of_measurement ? `<span>${this._escape(a.unit_of_measurement)}</span>` : ""}</div>`;
      } else if (domain === "select") {
        const opts = [...(a.options || [])];
        if (!known) opts.unshift("");
        control = `<select ${key} ${off}>${opts.map((o) => `<option value="${this._escape(o)}" ${o === value ? "selected" : ""}>${this._escape(o || "—")}</option>`).join("")}</select>`;
      } else if (domain === "switch") {
        control = `<label class="switch"><input type="checkbox" ${key} ${value === "on" ? "checked" : ""} ${off} /><span></span></label>`;
      } else if (domain === "text") {
        const attr = (n, as) => (a[n] != null ? `${as}="${this._escape(a[n])}"` : "");
        control = `<input type="${a.mode === "password" ? "password" : "text"}" ${key} ${attr("min", "minlength")} ${attr("max", "maxlength")} value="${this._escape(value)}" ${off} />`;
      } else if (domain === "time") {
        control = `<input type="time" step="1" ${key} value="${this._escape(value)}" ${off} />`;
      } else {
        control = `<button class="secondary compact" type="button" data-trv-press="${this._escape(id)}" ${off}>${t("room_dlg.trv_config.press")}</button>`;
      }
      const note = st.state === "unavailable" ? `<div class="set-row-desc">${t("room_dlg.trv_config.unavailable")}</div>` : "";
      return `
        <div class="set-row">
          <div class="set-row-text"><div class="set-row-name" title="${this._escape(id)}">${this._escape(name)}</div>${note}</div>
          <div class="set-row-control">${control}</div>
        </div>`;
    });
    return `<div class="set-row-desc">${t("room_dlg.trv_config.desc")}</div>${rows.join("")}`;
  }

  /** The TRV picker changed: show the new TRV's settings. */
  _refreshTrvConfig() {
    const box = this.shadowRoot.querySelector("[data-trv-config]");
    if (!box) return;
    box.innerHTML = this._renderTrvConfig();
    this._bindTrvConfig();
  }

  /**
   * Each change goes straight to the TRV's integration (like its HA device page) —
   * Nook stores none of it; the values are read from HA whenever the dialog opens.
   */
  _bindTrvConfig() {
    const box = this.shadowRoot.querySelector("[data-trv-config]");
    if (!box) return;
    const nameOf = (el, id) => el.closest(".set-row")?.querySelector(".set-row-name")?.textContent || id;
    const send = async (el, domain, service, data) => {
      const id = el.dataset.trvCfg || el.dataset.trvPress;
      const name = nameOf(el, id);
      try {
        await this._hass.callService(domain, service, data, { entity_id: id });
        this._showToast(t(domain === "button" ? "room_dlg.trv_config.pressed" : "room_dlg.trv_config.sent", { name }));
      } catch (e) {
        this._showToast(t("room_dlg.trv_config.failed", { name, error: e?.message || e }), "err");
        // Put the control back to what the TRV reports.
        const st = this._entityState(id);
        if (st && el.type === "checkbox") el.checked = st.state === "on";
        else if (st && st.state !== "unknown" && st.state !== "unavailable") el.value = st.state;
      }
    };
    box.querySelectorAll("[data-trv-cfg]").forEach((el) =>
      el.addEventListener("change", () => {
        const domain = el.dataset.trvCfg.split(".")[0];
        if (domain === "switch") return send(el, domain, el.checked ? "turn_on" : "turn_off", {});
        if (el.value === "") return;
        const [service, field] = TRV_CONFIG_DOMAINS[domain];
        if (domain === "number") {
          // Spinner clicks each fire "change": send once they stop, not one radio message per click.
          clearTimeout(el._trvSendTimer);
          el._trvSendTimer = setTimeout(() => {
            const n = Number(el.value);
            if (el.value !== "" && Number.isFinite(n)) send(el, domain, service, { [field]: n });
          }, 800);
          return;
        }
        send(el, domain, service, { [field]: el.value });
      })
    );
    box.querySelectorAll("[data-trv-press]").forEach((btn) =>
      btn.addEventListener("click", () => send(btn, "button", "press", {}))
    );
  }

  _renderWallPanels() {
    const panels = this._cfg().wall_panels || [];
    const nook = this._nookClimateEntities();
    // The outline marks which panel the preview shows — meaningless with only one.
    const several = panels.length > 1;
    const cards = panels
      .map((p) => {
        const model = wallModel(p.model);
        const primary = this._wallPrimary(p.primary_entity);
        const primaryName = (primary && this._entityName(primary)) || "—";
        const notNook = primary && !this._isNookClimate(primary);
        return `
          <div class="wp-card${several && this._previewPanelId() === p.id ? " selected" : ""}" data-id="${this._escape(p.id)}" role="button" tabindex="0" ${several ? `title="${this._escape(t("wall.card.show_in_preview"))}"` : ""}>
            <span class="card-icon">${ICONS.panel}</span>
            <div class="wp-card-text">
              <div class="wp-card-name">${this._escape(p.label || p.id)}</div>
              <div class="wp-card-meta">${t("wall.card.screen", { shape: this._escape(model.label), ratio: model.ratio, id: `<code>${this._escape(p.id)}</code>` })}</div>
              <div class="wp-card-meta">${t("wall.card.controls", { name: `<strong>${this._escape(primaryName)}</strong>` })}${notNook ? ` <span class="set-state warn">${t("wall.card.not_nook")}</span>` : ""}${p.temperature_lock ? ` <span class="set-state">${t("wall.card.locked")}</span>` : ""}</div>
              <div class="wp-card-meta">${this._reportedScreenHtml(p)}</div>
              ${p.model === "nspanel_pro" || this._helperState(p.id)?.paired ? `<div class="wp-card-meta">${this._helperLineHtml(p.id)}</div>` : ""}
              ${p.kiosk_enabled === false ? "" : `<div class="wp-card-meta kiosk-line">${t("wall.card.kiosk")} <span data-kiosk-pill="${this._escape(p.id)}">${this._kioskPillHtml(p.id)}</span></div>
              <div class="wp-card-meta" data-kiosk-mode="${this._escape(p.id)}">${this._kioskModeHtml(p.id)}</div>`}
            </div>
            <button class="secondary compact edit-panel" type="button" data-id="${this._escape(p.id)}">${t("common.edit")}</button>
          </div>`;
      })
      .join("");
    void nook;
    return `
      <div class="page-head-row">
        ${this._pageHeader(t("wall.title"), t("wall.lead"))}
        <button class="primary" id="addWallPanel" type="button">${ICONS.plus}${t("wall.add")}</button>
      </div>
      ${panels.length
        ? `${this._renderWallPreview(panels)}<div class="wp-list">${cards}</div>${panels.some((p) => p.kiosk_enabled !== false) ? `<div style="height:14px"></div>${this._renderKioskCard()}` : ""}`
        : `<div class="card empty-state"><p class="muted" style="margin:0">${t("wall.empty")}</p><button class="primary" id="addWallPanelEmpty" type="button">${ICONS.plus}${t("wall.add_first")}</button></div>`}
    `;
  }

  /** What the panel itself reported: its screen and the shape that makes it. */
  _reportedScreenHtml(panel) {
    const s = this._state?.wall_screens?.[panel.id];
    if (!s?.width || !s?.height) return `${t("wall.reported")} <span class="muted">${t("wall.reported.waiting")}</span>`;
    const shape = wallShapeFor(s.width, s.height);
    const size = `${s.width} × ${s.height}`;
    if (shape.id === wallShapeId(panel.model)) return `${t("wall.reported")} ${size} <span class="set-state good">${shape.label}</span>`;
    return `${t("wall.reported")} ${size} (${shape.label}) <span class="set-state warn" title="${this._escape(t("wall.reported.mismatch.tip"))}">${t("wall.reported.mismatch", { shape: this._escape(wallModel(panel.model).label) })}</span>`;
  }

  _helperState(panelId) {
    return this._state?.wall_helpers?.[panelId] || null;
  }

  /** One line for the panel's card: is the helper there, and is it doing its job. */
  _helperLineHtml(panelId) {
    const h = this._helperState(panelId);
    if (!h?.paired) return `${t("helper.label")} <span class="set-state">${t("helper.not_paired")}</span>`;
    const s = h.summary || {};
    if (h.error) return `${t("helper.label")} <span class="set-state bad" title="${this._escape(h.error)}">${t("helper.not_answering")}</span>`;
    if (!s.version) return `${t("helper.label")} <span class="muted">${t("helper.checking")}</span>`;
    const bits = [`${t("helper.label")} ${this._escape(s.version)}`];
    if (s.update_state && !/^Updated|^Installed/.test(s.update_state)) bits.push(t("helper.update", { state: this._escape(s.update_state) }));
    else if (h.shipped_version && h.shipped_version !== s.version) bits.push(t("helper.update_coming", { version: this._escape(h.shipped_version) }));
    if (s.wifi_rssi != null) bits.push(t("helper.wifi", { rssi: s.wifi_rssi }));
    const pill = s.return_button_showing
      ? `<span class="set-state warn">${t("helper.button_showing")}</span>`
      : `<span class="set-state good">${t("helper.ok")}</span>`;
    return `${bits.join(" · ")} ${pill}`;
  }

  /** The battery sensor (%) on a TRV's device, like the Radiators card; cached per registry. */
  _trvBatteryEntity(trvId) {
    const entities = this._hass?.entities;
    if (!trvId || !entities) return null;
    if (this._batteryFor !== entities) {
      this._batteryFor = entities;
      this._batteryCache = new Map();
    }
    if (this._batteryCache.has(trvId)) return this._batteryCache.get(trvId);
    let found = null;
    const dev = entities[trvId]?.device_id;
    if (dev) {
      for (const [id, ent] of Object.entries(entities)) {
        if (ent.device_id !== dev || id === trvId || ent.hidden || !id.startsWith("sensor.")) continue;
        const st = this._hass.states[id];
        if (st?.attributes?.device_class === "battery" && st.attributes.unit_of_measurement === "%") {
          found = id;
          break;
        }
      }
    }
    this._batteryCache.set(trvId, found);
    return found;
  }

  /** Right-aligned battery level for a room tile ("" if the TRV has no battery sensor). */
  _trvBatteryHtml(trvId) {
    const id = this._trvBatteryEntity(trvId);
    const pct = id ? Number(this._entityState(id)?.state) : NaN;
    if (!Number.isFinite(pct)) return "";
    const level = Math.max(0, Math.min(100, Math.round(pct)));
    const cls = level <= 20 ? " bad" : level <= 35 ? " warn" : "";
    // Battery outline with a fill that follows the level (body runs y 6..20).
    const fillH = (14 * level) / 100;
    return `<span class="hero-room-battery${cls}" title="${this._escape(t("hero.tile.battery", { level }))}">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16 4h-1.5V2h-5v2H8a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1zm-1 16H9V6h6z"/><rect fill="currentColor" x="10" y="${(19 - fillH).toFixed(1)}" width="4" height="${fillH.toFixed(1)}"/></svg>${level}%</span>`;
  }

  /** "Updated to 0.2.1 at 2026-10-14T14:09:53" → "14 Oct, 14:09"; other states as they are. */
  _helperUpdateText(state) {
    const m = /at (\d{4})-(\d\d)-(\d\d)T(\d\d:\d\d)/.exec(state || "");
    if (!m) return state || "";
    const month = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"][Number(m[2]) - 1];
    return t("helper.updated_at", { day: Number(m[3]), month: t(`month_short.${month}`), time: m[4] });
  }

  _renderHelperSection(d) {
    const editing = this._wallEditingId;
    const show = d.model === "nspanel_pro";
    const h = editing ? this._helperState(editing) : null;
    const s = h?.summary || {};
    const switchRow = (id, name, desc, on) => `
        <div class="set-row">
          <div class="set-row-text"><div class="set-row-name">${name}</div><div class="set-row-desc">${desc}</div></div>
          <div class="set-row-control"><label class="switch"><input type="checkbox" id="${id}" ${on ? "checked" : ""} /><span></span></label></div>
        </div>`;
    let body;
    if (!editing) {
      body = `<div class="set-row-desc">${t("helper.add_first")}</div>`;
    } else if (!h?.paired) {
      body = `
        <div class="set-row-desc">${t("helper.intro")}</div>
        <div class="set-fields">
          <div class="set-field">
            <div class="set-field-label">${t("helper.code")}</div>
            <input id="wpHelperCode" inputmode="numeric" maxlength="7" placeholder="123 456" autocomplete="off" />
          </div>
          <div class="set-field">
            <div class="set-field-label">&nbsp;</div>
            <button class="secondary" id="wpHelperPair" type="button">${t("helper.pair")}</button>
          </div>
        </div>`;
    } else {
      const status = h.error
        ? `${t("helper.status")} <span class="set-state bad">${t("helper.not_answering")}</span> ${this._escape(h.error)}`
        : !s.version
          ? `${t("helper.status")} <span class="muted">${t("helper.checking")}</span>`
          : [
              `${t("helper.status")} <span class="set-state good">${t("helper.connected")}</span>`,
              `${t("helper.label")} ${this._escape(s.version)}`,
              t(s.device_owner ? "helper.updates_auto" : "helper.updates_tap"),
              s.update_state && t("helper.last_update", { when: this._escape(this._helperUpdateText(s.update_state)) }),
            ].filter(Boolean).join(" · ");
      const health = [
        s.model && t("helper.device", { model: this._escape(s.model), android: this._escape(s.android || "—") }),
        s.wifi_rssi != null && t("helper.wifi", { rssi: s.wifi_rssi }),
        s.uptime_s != null && t("helper.uptime", { uptime: this._formatEta(s.uptime_s / 60)?.replace("~", "") || "—" }),
        s.foreground_app && t("helper.in_front", { app: s.foreground_app === "de.ozerov.fully" ? t("helper.fully") : this._escape(s.foreground_app) }),
      ].filter(Boolean).join(" · ");
      body = `
        <div class="set-row-desc">${status}</div>
        ${health ? `<div class="set-row-desc">${health}</div>` : ""}
        ${switchRow("wpHelperHide", t("helper.hide"), s.return_button_found
          ? `${t("helper.hide.desc")}${s.times_hidden ? t("helper.hide.count", { count: s.times_hidden }) : ""}.${s.can_hide ? "" : t("helper.hide.needs_permission")}`
          : t("helper.hide.not_found"), s.hide_return_button !== false)}
        ${switchRow("wpHelperCpu", t("helper.cpu_lock"), t("helper.cpu_lock.desc"), Boolean(s.cpu_lock))}
        ${switchRow("wpHelperWifi", t("helper.wifi_lock"), t("helper.wifi_lock.desc"), Boolean(s.wifi_lock))}
        <div class="form-actions"><span style="flex:1"></span><button class="linkish" id="wpHelperUnpair" type="button">${t("helper.unpair")}</button></div>`;
    }
    return `
      <div class="dlg-section" id="wpHelperSection" ${show ? "" : "hidden"}>
        <div class="dlg-section-title">${t("wall.shape.nspanel_pro")}</div>
        ${body}
        <div class="set-field">
          <div class="set-field-label">${t("helper.host")}</div>
          <input id="wpHelperHost" placeholder="${this._escape(h?.host || t("helper.host.placeholder"))}" value="${this._escape(d.helperHost || "")}" />
          <div class="set-row-desc">${t("helper.host.desc")}</div>
        </div>
      </div>`;
  }

  async _helperAction(type, payload, okText) {
    try {
      const result = await this._ws(type, { panel_id: this._wallEditingId, ...payload });
      if (this._state) this._state.wall_helpers = { ...(this._state.wall_helpers || {}), [this._wallEditingId]: result };
      this._showToast(okText);
      return result;
    } catch (e) {
      this._showToast(t("helper.error", { error: e?.message || e }), "err");
      return null;
    }
  }

  _refreshHelperSection() {
    const el = this.shadowRoot.getElementById("wpHelperSection");
    if (!el) return;
    el.outerHTML = this._renderHelperSection(this._wallDraft);
    this._bindHelperSection();
  }

  _bindHelperSection() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    $("wpHelperPair")?.addEventListener("click", async () => {
      const code = String($("wpHelperCode")?.value || "").replace(/\s+/g, "");
      if (!/^\d{6}$/.test(code)) {
        this._showToast(t("helper.code_invalid"), "err");
        return;
      }
      if (await this._helperAction("nook/helper_pair", { code }, t("helper.toast.paired"))) this._refreshHelperSection();
    });
    $("wpHelperUnpair")?.addEventListener("click", async () => {
      if (!window.confirm(t("helper.unpair.confirm"))) return;
      try {
        await this._ws("nook/helper_unpair", { panel_id: this._wallEditingId });
        if (this._state?.wall_helpers?.[this._wallEditingId]) this._state.wall_helpers[this._wallEditingId].paired = false;
        this._refreshHelperSection();
      } catch (e) {
        this._showToast(t("helper.unpair.failed", { error: e?.message || e }), "err");
      }
    });
    const toggle = (id, key, toast) =>
      $(id)?.addEventListener("change", async (ev) => {
        const on = ev.target.checked;
        if (!(await this._helperAction("nook/helper_config", { [key]: on }, t(`helper.toast.${toast}.${on ? "on" : "off"}`)))) ev.target.checked = !on;
      });
    toggle("wpHelperHide", "hide_return_button", "hide");
    toggle("wpHelperCpu", "cpu_lock", "cpu");
    toggle("wpHelperWifi", "wifi_lock", "wifi");
    $("wpHelperHost")?.addEventListener("input", (ev) => {
      this._wallDraft.helperHost = ev.target.value;
    });
  }

  async _loadKiosk(pillsOnly = false) {
    try {
      this._kiosk = await this._ws("nook/kiosk_status");
    } catch {
      this._kiosk = null;
    }
    if (this._view !== "wall_panels") return;
    if (pillsOnly || this._dialogKind) this._refreshKioskPills();
    else {
      const card = this.shadowRoot.getElementById("kioskCard");
      if (card) {
        card.outerHTML = this._renderKioskCard();
        this._bindKioskCard();
      }
      this._refreshKioskPills();
    }
  }

  _kioskPillHtml(panelId) {
    const s = this._kiosk?.panels?.[panelId];
    if (!s || !s.linked) return `<span class="set-state">${t("kiosk.pill.not_linked")}</span>`;
    if (!s.online) return `<span class="set-state bad">${t("kiosk.pill.offline")}</span>`;
    const pill = s.in_sync
      ? `<span class="set-state good">${t("kiosk.pill.in_sync")}</span>`
      : `<span class="set-state warn" title="${this._escape(this._kioskDriftText(s))}">${s.page_ok === false ? t("kiosk.pill.wrong_page") : t("kiosk.pill.out_of_sync")}</span>`;
    return `${pill}
      ${s.in_sync ? "" : `<button class="linkish kiosk-act" type="button" data-kiosk-sync="${this._escape(panelId)}">${t("kiosk.sync_now")}</button>`}
      <button class="linkish kiosk-act" type="button" data-kiosk-reload="${this._escape(panelId)}">${t("kiosk.reload")}</button>`;
  }

  _kioskDriftText(s) {
    const out = [];
    if (s.page_ok === false) out.push(t("kiosk.drift.page", { page: s.current_page || t("kiosk.drift.another_page") }));
    if (s.settings?.menu_pin?.ok === false) out.push(t("kiosk.drift.pin"));
    for (const f of KIOSK_FIELDS) {
      const it = s.settings?.[f.key];
      if (it && it.ok === false) out.push(t("kiosk.drift.setting", { label: f.label, actual: kioskDisplay(f, it.actual), target: kioskDisplay(f, it.target) }));
    }
    return out.join(" · ");
  }

  _refreshKioskPills() {
    this.shadowRoot.querySelectorAll("[data-kiosk-pill]").forEach((el) => {
      const html = this._kioskPillHtml(el.dataset.kioskPill);
      if (el.innerHTML !== html) el.innerHTML = html;
    });
    this.shadowRoot.querySelectorAll("[data-kiosk-mode]").forEach((el) => {
      const html = this._kioskModeHtml(el.dataset.kioskMode);
      if (el.innerHTML !== html) el.innerHTML = html;
    });
  }

  /** "Kiosk Mode: On/Off", read from the panel. Fully only lets it be switched on at the panel. */
  _kioskModeHtml(panelId) {
    const s = this._kiosk?.panels?.[panelId];
    if (!s?.linked || !s.online || s.kiosk_mode == null) return "";
    return s.kiosk_mode
      ? t("wall.card.kiosk_mode", { state: `<span class="set-state good">${t("common.on")}</span>` })
      : `${t("wall.card.kiosk_mode", { state: `<span class="set-state">${t("common.off")}</span>` })} <span class="muted">${t("wall.card.kiosk_mode.off_hint")}</span>`;
  }

  /** One setting's input. Blank = not managed (house) / use the house default (panel). */
  _kioskControl(field, value, idPrefix, placeholder) {
    const id = `${idPrefix}${field.key}`;
    if (field.kind === "bool") {
      const v = value == null ? "" : value ? "on" : "off";
      return `<select id="${id}" class="kiosk-select">
          <option value="" ${v === "" ? "selected" : ""}>${this._escape(placeholder)}</option>
          <option value="on" ${v === "on" ? "selected" : ""}>${t("common.on")}</option>
          <option value="off" ${v === "off" ? "selected" : ""}>${t("common.off")}</option>
        </select>`;
    }
    if (field.kind === "choice") {
      const v = value == null ? "" : String(value);
      return `<select id="${id}" class="kiosk-select">
          <option value="" ${v === "" ? "selected" : ""}>${this._escape(placeholder)}</option>
          ${field.options.map((o) => `<option value="${o}" ${v === String(o) ? "selected" : ""}>${t(`kiosk.${field.key}.${o}`)}</option>`).join("")}
        </select>`;
    }
    const shown = value == null ? "" : field.kind === "pct" ? Math.round(Number(value) / 2.55) : value;
    const isPct = field.kind === "pct" || field.kind === "pct100";
    const max = isPct ? 100 : 86400;
    return `<div class="num-input kiosk-num"><input id="${id}" type="number" min="0" max="${max}" step="1" placeholder="${this._escape(placeholder)}" value="${this._escape(shown)}" /><span>${isPct ? "%" : t("unit.sec")}</span></div>`;
  }

  /** Read a set of kiosk inputs back into backend values (blank fields left out). */
  _readKioskControls(idPrefix) {
    const out = {};
    for (const f of KIOSK_FIELDS) {
      const el = this.shadowRoot.getElementById(`${idPrefix}${f.key}`);
      if (!el || el.value === "") continue;
      if (f.kind === "bool") out[f.key] = el.value === "on";
      else if (f.kind === "choice") out[f.key] = Number(el.value);
      else if (f.kind === "pct") out[f.key] = Math.round(Math.min(100, Math.max(0, Number(el.value))) * 2.55);
      else if (f.kind === "pct100") out[f.key] = Math.round(Math.min(100, Math.max(0, Number(el.value))));
      else out[f.key] = Math.max(0, Math.round(Number(el.value)));
    }
    return out;
  }

  _renderKioskCard() {
    const k = this._kiosk;
    // Closed until opened (kept while the panel stays open, closed again on a fresh load).
    const open = !!this._kioskOpen;
    const head = `
      <div class="card-head collapse-head" id="kioskToggle" role="button" tabindex="0" aria-controls="kioskBody" aria-expanded="${open}" title="${this._escape(t(open ? "common.collapse" : "common.expand"))}">
        <span class="card-icon intel">${ICONS.tune}</span>
        <div class="card-head-text"><p class="card-title">${t("kiosk.title")}</p><p class="card-sub">${t("kiosk.sub")}</p></div>
        <span class="collapse-chev">${ICONS.chevron_down}</span>
      </div>`;
    const card = (body) =>
      `<div class="card${open ? "" : " collapsed"}" id="kioskCard">${head}<div class="collapse-body" id="kioskBody" ${open ? "" : "hidden"}>${body}</div></div>`;
    if (!k) return card(`<p class="muted" style="margin:0">${t("common.loading")}</p>`);
    if (!k.devices?.length) return card(`<p class="muted" style="margin:0">${t("kiosk.no_integration")}</p>`);
    const d = k.defaults || {};
    const rows = KIOSK_FIELDS.map(
      (f) => `
        <div class="set-row">
          <div class="set-row-text"><div class="set-row-name">${f.label}</div>${f.desc ? `<div class="set-row-desc">${f.desc}</div>` : ""}</div>
          <div class="set-row-control">${this._kioskControl(f, d[f.key], "kd_", t("kiosk.not_managed"))}</div>
        </div>`
    ).join("");
    return card(`
        <div class="set-row">
          <div class="set-row-text"><div class="set-row-name">${t("kiosk.auto_sync")}</div><div class="set-row-desc">${t("kiosk.auto_sync.desc")}</div></div>
          <div class="set-row-control"><label class="switch"><input type="checkbox" id="kioskAutoSync" ${k.auto_sync !== false ? "checked" : ""} /><span></span></label></div>
        </div>
        ${rows}
        <div class="form-actions">
          <select id="kioskImportFrom" class="kiosk-select" aria-label="${this._escape(t("kiosk.import_from"))}">
            ${k.devices.map((dev) => `<option value="${this._escape(dev.id)}">${this._escape(dev.name)}</option>`).join("")}
          </select>
          <button class="secondary" id="kioskImport" type="button">${t("kiosk.import")}</button>
          <span style="flex:1"></span>
          <button class="primary" id="kioskSaveDefaults" type="button">${t("kiosk.save_sync")}</button>
        </div>`);
  }

  /** A header that opens and closes its body (click, Enter or Space). */
  _bindCollapse(headId, bodyId, onChange) {
    const head = this.shadowRoot.getElementById(headId);
    if (!head) return;
    const flip = () => {
      // Shown/hidden in place, not re-rendered: unsaved edits inside stay.
      const open = head.getAttribute("aria-expanded") !== "true";
      head.setAttribute("aria-expanded", String(open));
      head.title = t(open ? "common.collapse" : "common.expand");
      head.parentElement?.classList.toggle("collapsed", !open);
      const body = this.shadowRoot.getElementById(bodyId);
      if (body) body.hidden = !open;
      onChange(open);
    };
    head.addEventListener("click", flip);
    head.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      ev.preventDefault();
      flip();
    });
  }

  _bindKioskCard() {
    this._bindCollapse("kioskToggle", "kioskBody", (open) => {
      this._kioskOpen = open;
    });
    this.shadowRoot.getElementById("kioskImport")?.addEventListener("click", async () => {
      const select = this.shadowRoot.getElementById("kioskImportFrom");
      const name = select?.selectedOptions?.[0]?.textContent || t("kiosk.the_panel");
      try {
        const { settings } = await this._ws("nook/kiosk_read", { device_id: select.value });
        let n = 0;
        for (const f of KIOSK_FIELDS) {
          const el = this.shadowRoot.getElementById(`kd_${f.key}`);
          if (!el || settings[f.key] == null) continue;
          el.value = f.kind === "bool" ? (settings[f.key] ? "on" : "off") : f.kind === "pct" ? Math.round(settings[f.key] / 2.55) : String(settings[f.key]);
          n++;
        }
        const missed = KIOSK_FIELDS.filter((f) => !f.writeOnly && settings[f.key] == null).map((f) => f.label.toLowerCase());
        this._showToast(`${tn("kiosk.imported", n, { name })}${missed.length ? t("kiosk.imported.missed", { list: missed.join(", ") }) : ""}${t("kiosk.imported.save")}`);
      } catch (e) {
        this._showToast(t("kiosk.read_failed", { name, error: e?.message || e }), "err");
      }
    });
    this.shadowRoot.getElementById("kioskSaveDefaults")?.addEventListener("click", async () => {
      try {
        const res = await this._ws("nook/update_settings", {
          kiosk_defaults: this._readKioskControls("kd_"),
          kiosk_auto_sync: Boolean(this.shadowRoot.getElementById("kioskAutoSync")?.checked),
        });
        const changed = Object.values(res.kiosk_synced || {}).reduce((n, list) => n + list.length, 0);
        this._showToast(changed ? tn("kiosk.saved_sent", changed) : t("kiosk.saved_match"));
        await this._loadKiosk();
      } catch (e) {
        this._showToast(t("common.save_failed", { error: e?.message || e }), "err");
      }
    });
  }

  async _kioskSync(panelId) {
    try {
      const res = await this._ws("nook/kiosk_apply", panelId ? { panel_id: panelId } : {});
      this._kiosk = res;
      this._refreshKioskPills();
      const changed = Object.values(res.synced || {}).reduce((n, list) => n + list.length, 0);
      this._showToast(changed ? tn("kiosk.synced", changed) : t("kiosk.already_synced"));
    } catch (e) {
      this._showToast(t("kiosk.sync_failed", { error: e?.message || e }), "err");
    }
  }

  async _kioskReload(panelId) {
    try {
      await this._ws("nook/kiosk_reload", { panel_id: panelId });
      this._showToast(t("kiosk.reloading"));
    } catch (e) {
      this._showToast(t("kiosk.reload_failed", { error: e?.message || e }), "err");
    }
  }

  /** Display name. HA prefixes Nook's entities with the device name ("Nook Nook Home"); drop it. */
  _entityName(entityId) {
    const name = this._entityState(entityId)?.attributes?.friendly_name || entityId || "";
    return this._hass?.entities?.[entityId]?.platform === "nook" ? name.replace(/^Nook\s+/, "") : name;
  }

  _isNookClimate(entityId) {
    return this._hass?.entities?.[entityId]?.platform === "nook";
  }

  /** Same rule as the backend: blank, or the old "climate.nook_home" default that isn't Nook's, means Nook's house climate. */
  _wallPrimary(configured) {
    const home = this._nookClimateEntities().home;
    if (!configured) return home || "";
    if (configured === "climate.nook_home" && home && !this._isNookClimate(configured)) return home;
    return configured;
  }

  _renderWallDialog() {
    const d = this._wallDraft;
    const editing = this._wallEditingId;
    const cfg = this._cfg();
    return this._dialog({
      icon: ICONS.panel,
      title: editing ? t("wall_dlg.title_edit", { name: this._escape(d.label || editing) }) : t("wall_dlg.title_add"),
      sub: editing ? t("wall_dlg.sub_edit") : t("wall_dlg.sub_add"),
      body: `
        <div class="dlg-section">
          <div class="set-fields">
            <div class="set-field">
              <div class="set-field-label">${t("wall_dlg.name")}</div>
              <input id="wpLabel" placeholder="${this._escape(t("wall_dlg.name.placeholder"))}" value="${this._escape(d.label || "")}" />
            </div>
            <div class="set-field">
              <div class="set-field-label">${t("wall_dlg.device_id")}</div>
              <input id="wpId" placeholder="hallway" value="${this._escape(d.id || "")}" ${editing ? "readonly" : ""} />
              <div class="set-row-desc">${editing ? t("wall_dlg.device_id.fixed") : t("wall_dlg.device_id.auto")}</div>
            </div>
          </div>
          <div class="set-field">
            <div class="set-field-label">${t("wall_dlg.shape")}</div>
            <select id="wpModel">
              ${WALL_MODELS.map((m) => `<option value="${m.id}" ${wallModel(d.model).id === m.id ? "selected" : ""}>${m.label} · ${m.ratio} — ${m.hint}</option>`).join("")}
            </select>
            <div class="set-row-desc">${t("wall_dlg.shape.desc")}${editing && this._state?.wall_screens?.[editing] ? ` ${this._reportedScreenHtml({ id: editing, model: d.model })}.` : ""}</div>
          </div>
        </div>
        ${this._renderHelperSection(d)}
        <div class="dlg-section">
          <div class="dlg-section-title">${t("wall_dlg.section.controls")}</div>
          <div class="set-field">
            <div class="set-field-label">${t("wall_dlg.thermostat")}</div>
            <div class="entity-picker-host" data-wall-picker="primary"></div>
            <div class="set-row-desc" id="wpPrimaryNote"></div>
          </div>
        </div>
        <div class="dlg-section">
          <div class="dlg-section-title">${t("wall_dlg.section.shows")}</div>
          <div class="set-fields">
            <div class="set-field">
              <div class="set-field-label">${t("wall_dlg.inside_temp")}</div>
              <div class="entity-picker-host" data-wall-picker="insideTemp"></div>
            </div>
            <div class="set-field">
              <div class="set-field-label">${t("wall_dlg.outside_temp")}</div>
              <div class="entity-picker-host" data-wall-picker="outsideTemp"></div>
            </div>
            <div class="set-field">
              <div class="set-field-label">${t("wall_dlg.humidity")}</div>
              <div class="entity-picker-host" data-wall-picker="humidity"></div>
            </div>
            <div class="set-field">
              <div class="set-field-label">${t("wall_dlg.weather")}</div>
              <div class="entity-picker-host" data-wall-picker="weather"></div>
            </div>
          </div>
          <div class="set-row-desc">${t("wall_dlg.shows.desc")}</div>
        </div>
        <div class="dlg-section">
          <div class="dlg-section-title">${t("wall_dlg.section.screen")}</div>
          <div class="set-row">
            <div class="set-row-text"><div class="set-row-name">${t("wall_dlg.clock_after")}</div><div class="set-row-desc">${t("wall_dlg.clock_after.desc")}</div></div>
            <div class="set-row-control"><div class="num-input"><input id="wpIdle" type="number" min="5" step="5" value="${this._escape(d.idleSec ?? 30)}" /><span>${t("unit.sec")}</span></div></div>
          </div>
          <div class="set-row">
            <div class="set-row-text"><div class="set-row-name">${t("wall_dlg.lock")}</div><div class="set-row-desc">${String(cfg.wall_pin || "").trim() ? t("wall_dlg.lock.on") : t("wall_dlg.lock.no_pin")}</div></div>
            <div class="set-row-control"><label class="switch"><input type="checkbox" id="wpLock" ${d.lock ? "checked" : ""} /><span></span></label></div>
          </div>
        </div>
        ${this._renderKioskDialogSection(d)}`,
      foot: `
        ${editing ? `<button class="danger" id="deleteWallPanel" type="button">${t("common.delete")}</button>` : ""}
        <span style="flex:1"></span>
        <button class="secondary" data-close-dialog type="button">${t("common.cancel")}</button>
        <button class="primary" id="saveWallPanel" type="button">${editing ? t("common.save_changes") : t("wall.add")}</button>`,
    });
  }

  _renderKioskDialogSection(d) {
    const k = this._kiosk;
    const on = d.kioskEnabled !== false;
    // Closed each time the dialog opens; the header opens it (state kept in the draft).
    const open = !!d.kioskOpen;
    const section = (body, hasOverrides = true) => `
      <div class="dlg-section${open ? "" : " collapsed"}">
        <div class="dlg-section-title collapse-head dlg-collapse-head" id="wpKioskToggle" role="button" tabindex="0" aria-controls="wpKioskSection" aria-expanded="${open}" title="${this._escape(t(open ? "common.collapse" : "common.expand"))}">
          <span>${t("kiosk.title")}</span><span class="collapse-chev">${ICONS.chevron_down}</span>
        </div>
        ${hasOverrides ? `<div class="set-row-desc dlg-collapse-desc">${t("wall_dlg.kiosk.overrides")}</div>` : ""}
        <div class="dlg-collapse-body" id="wpKioskSection" ${open ? "" : "hidden"}>${body}</div>
      </div>`;
    const toggle = `
        <div class="set-row">
          <div class="set-row-text"><div class="set-row-name">${t("wall_dlg.kiosk_enabled")}</div><div class="set-row-desc">${t("wall_dlg.kiosk_enabled.desc")}</div></div>
          <div class="set-row-control"><label class="switch"><input type="checkbox" id="wpKioskEnabled" ${on ? "checked" : ""} /><span></span></label></div>
        </div>`;
    if (!k?.devices?.length) {
      return section(`
        ${toggle}
        <div id="wpKioskBody" ${on ? "" : "hidden"}><div class="set-row-desc">${t("wall_dlg.kiosk.no_integration")}</div></div>`, false);
    }
    const defaults = k.defaults || {};
    const rows = KIOSK_FIELDS.map((f) => {
      const house = defaults[f.key];
      const placeholder = house == null ? t("kiosk.not_managed") : t("wall_dlg.kiosk.house_value", { value: kioskDisplay(f, house) });
      return `
        <div class="set-row">
          <div class="set-row-text"><div class="set-row-name">${f.label}</div></div>
          <div class="set-row-control">${this._kioskControl(f, d.kioskOverrides?.[f.key], "ko_", placeholder)}</div>
        </div>`;
    }).join("");
    return section(`
        ${toggle}
        <div id="wpKioskBody" ${on ? "" : "hidden"}>
        <div class="set-field">
          <div class="set-field-label">${t("wall_dlg.kiosk.device")}</div>
          <select id="wpKioskDevice">
            <option value="">${t("wall_dlg.kiosk.not_linked")}</option>
            ${k.devices.map((dev) => `<option value="${this._escape(dev.id)}" ${d.kioskDevice === dev.id ? "selected" : ""}>${this._escape(dev.name)}</option>`).join("")}
          </select>
          <div class="set-row-desc">${t("wall_dlg.kiosk.device.desc")}</div>
        </div>
        ${rows}
        </div>`);
  }

  /** Open the wall panel dialog: a panel to edit, or nothing to add one. */
  _openWallDialog(panel) {
    const cfg = this._cfg();
    const sensors = panel?.sensors || {};
    this._wallEditingId = panel?.id || null;
    this._wallIdTouched = Boolean(panel);
    this._wallDraft = {
      id: panel?.id || "",
      label: panel?.label || "",
      model: panel?.model,
      primary: this._wallPrimary(panel?.primary_entity || ""),
      insideTemp: sensors.insideTemp || cfg.temperature_sensor || "",
      outsideTemp: sensors.outsideTemp || cfg.outdoor_temp_sensor || "",
      humidity: sensors.insideHumidity || "",
      weather: sensors.weather || "weather.home",
      idleSec: Math.round(Number(panel?.display?.idleMs ?? 30000) / 1000) || 30,
      lock: Boolean(panel?.temperature_lock),
      kioskDevice: panel?.kiosk_device || (!panel && this._kiosk?.devices?.length === 1 ? this._kiosk.devices[0].id : ""),
      kioskOverrides: { ...(panel?.kiosk_overrides || {}) },
      kioskEnabled: panel?.kiosk_enabled !== false,
      helperHost: panel?.helper_host || "",
    };
    this._openDialog("wall");
  }

  _updateWallPrimaryNote() {
    const note = this.shadowRoot?.getElementById("wpPrimaryNote");
    if (!note) return;
    const value = this._wallDraft.primary;
    if (!value || this._isNookClimate(value)) {
      note.className = "set-row-desc";
      note.textContent = t("wall_dlg.thermostat.nook");
    } else {
      note.className = "set-row-desc warn-note";
      note.textContent = t("wall_dlg.thermostat.not_nook");
    }
  }

  // ---- Shared dialog ----
  _dialog({ icon, title, sub, body, foot }) {
    return `
      <div class="dlg-backdrop" data-close-dialog>
        <div class="dlg" role="dialog" aria-modal="true" aria-label="${title}">
          <div class="dlg-head">
            <span class="card-icon intel">${icon}</span>
            <div class="card-head-text"><p class="dlg-title">${title}</p><p class="card-sub">${sub}</p></div>
            <button class="dlg-x" type="button" data-close-dialog aria-label="${this._escape(t("common.close"))}">
              <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
            </button>
          </div>
          <div class="dlg-body">${body}</div>
          <div class="dlg-foot">${foot}</div>
        </div>
      </div>`;
  }

  _renderDialog() {
    if (this._dialogKind === "room" && this._view === "settings") return this._renderRoomDialog();
    if (this._dialogKind === "wall" && this._view === "wall_panels") return this._renderWallDialog();
    return "";
  }

  _openDialog(kind) {
    this._dialogKind = kind;
    this._render();
    this.shadowRoot.querySelector(".dlg input:not([readonly])")?.focus();
  }

  _closeDialog() {
    this._dialogKind = null;
    this._editingRoomId = null;
    this._wallEditingId = null;
    this._render();
  }

  _previewPanelId(panels = this._cfg().wall_panels || []) {
    if (panels.some((p) => p.id === this._previewPanel)) return this._previewPanel;
    return panels[0]?.id || "";
  }

  _panelModel(id) {
    return wallModel((this._cfg().wall_panels || []).find((p) => p.id === id)?.model);
  }

  _wallPreviewSrc(id) {
    const q = new URLSearchParams({ embedded: "1", preview: "1", device: id, t: String(Date.now()) });
    return `${WALL_APP_URL}?${q}`;
  }

  _previewSizeText(model) {
    return `${model.label} · ${model.ratio}`;
  }

  _renderWallPreview(panels) {
    if (!panels.length) return "";
    const current = this._previewPanelId(panels);
    const model = this._panelModel(current);
    const options = panels
      .map((p) => `<option value="${this._escape(p.id)}" ${p.id === current ? "selected" : ""}>${this._escape(p.label || p.id)}</option>`)
      .join("");
    return `
      <div class="card">
        <p class="card-title">${t("preview.title")}</p>
        <div class="wp-preview-bar">
          <select id="wpPreviewPanel" aria-label="${this._escape(t("preview.panel"))}">${options}</select>
          <button type="button" class="secondary compact" id="wpPreviewReload">${t("kiosk.reload")}</button>
          <label class="wp-preview-taps${this._previewTaps ? " live" : ""}">
            <input type="checkbox" id="wpPreviewTaps" ${this._previewTaps ? "checked" : ""} />
            ${this._previewTaps ? t("preview.taps_live") : t("preview.taps_allow")}
          </label>
        </div>
        <div class="wp-preview-stage">
          <div class="wp-preview-device" style="max-width:${model.width + 28}px">
            <div class="wp-preview-screen" style="aspect-ratio:${model.width} / ${model.height}">
              <iframe id="wpPreviewFrame" title="${this._escape(t("preview.frame"))}" style="width:${model.width}px;height:${model.height}px"
                src="${this._escape(this._wallPreviewSrc(current))}"></iframe>
              ${this._previewTaps ? "" : `<div class="wp-preview-shield" title="${this._escape(t("preview.shield"))}"></div>`}
            </div>
          </div>
        </div>
        <p class="muted" style="margin:12px 0 0">
          ${t("preview.desc", { size: `<strong id="wpPreviewSize">${this._escape(this._previewSizeText(model))}</strong>` })}
        </p>
      </div>`;
  }

  /** Resize the preview to a model's screen without reloading the app. */
  _applyPreviewModel(model) {
    const device = this.shadowRoot?.querySelector(".wp-preview-device");
    const screen = this.shadowRoot?.querySelector(".wp-preview-screen");
    const frame = this.shadowRoot?.getElementById("wpPreviewFrame");
    if (!device || !screen || !frame) return;
    this._previewWidth = model.width;
    device.style.maxWidth = `${model.width + 28}px`;
    screen.style.aspectRatio = `${model.width} / ${model.height}`;
    frame.style.width = `${model.width}px`;
    frame.style.height = `${model.height}px`;
    screen.style.setProperty("--wp-scale", String(screen.clientWidth / model.width));
    const size = this.shadowRoot.getElementById("wpPreviewSize");
    if (size) size.textContent = this._previewSizeText(model);
  }

  _showPreviewPanel(id) {
    this._previewPanel = id;
    const select = this.shadowRoot?.getElementById("wpPreviewPanel");
    const frame = this.shadowRoot?.getElementById("wpPreviewFrame");
    if (select) select.value = id;
    this._applyPreviewModel(this._panelModel(id));
    if (frame) frame.src = this._wallPreviewSrc(id);
  }

  /**
   * Drag room tiles to reorder them; the order is saved on the HA config entry.
   * Mouse: drag after a few px. Touch: press and hold, then drag (so scrolling still works).
   */
  _bindRoomDrag() {
    const hero = this.shadowRoot.querySelector(".hero-rooms.reorderable");
    if (hero) this._bindRoomDragGrid(hero, ".hero-room", "zone");
    const page = this.shadowRoot.querySelector(".room-grid.reorderable");
    if (page) this._bindRoomDragGrid(page, ".room-card", "roomId");
  }

  _bindRoomDragGrid(grid, tileSel, idKey) {
    let drag = null; // { tile, pointerId, x, y, started, timer }

    const begin = () => {
      if (!drag || drag.started) return;
      drag.started = true;
      this._dragging = true;
      drag.tile.classList.add("dragging");
      grid.classList.add("is-dragging");
      try {
        drag.tile.setPointerCapture(drag.pointerId);
      } catch {
        // Pointer already released.
      }
      navigator.vibrate?.(10);
    };
    const end = async (commit) => {
      if (!drag) return;
      const { tile, started, timer, before } = drag;
      clearTimeout(timer);
      drag = null;
      if (!started) return;
      tile.classList.remove("dragging");
      grid.classList.remove("is-dragging");
      this._suppressZoneClick = true;
      setTimeout(() => (this._suppressZoneClick = false), 0);
      const order = [...grid.querySelectorAll(tileSel)].map((el) => el.dataset[idKey]);
      if (!commit || order.join() === before) {
        if (!commit) this._render();
        this._dragging = false;
        return;
      }
      await this._saveRoomOrder(order);
      this._dragging = false;
    };

    grid.querySelectorAll(tileSel).forEach((tile) => {
      tile.addEventListener("pointerdown", (ev) => {
        if (ev.button !== 0 || drag || ev.target.closest(".switch")) return;
        drag = {
          tile, pointerId: ev.pointerId, x: ev.clientX, y: ev.clientY, started: false, timer: null,
          before: [...grid.querySelectorAll(tileSel)].map((el) => el.dataset[idKey]).join(),
        };
        if (ev.pointerType !== "mouse") drag.timer = setTimeout(begin, 350);
      });
      // A touch drag must stop the page scrolling once it has begun.
      tile.addEventListener("touchmove", (ev) => {
        if (drag?.started) ev.preventDefault();
      }, { passive: false });
      tile.addEventListener("contextmenu", (ev) => {
        if (drag) ev.preventDefault();
      });
    });

    grid.addEventListener("pointermove", (ev) => {
      if (!drag || ev.pointerId !== drag.pointerId) return;
      const moved = Math.hypot(ev.clientX - drag.x, ev.clientY - drag.y);
      if (!drag.started) {
        if (ev.pointerType === "mouse" && moved > 5) begin();
        else if (ev.pointerType !== "mouse" && moved > 8) {
          // Finger moved before the hold finished: it's a scroll, not a drag.
          clearTimeout(drag.timer);
          drag = null;
        }
        return;
      }
      // Move the lifted tile into the slot under the pointer.
      const target = [...grid.querySelectorAll(tileSel)].find((el) => {
        if (el === drag.tile) return false;
        const r = el.getBoundingClientRect();
        return ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom;
      });
      if (!target) return;
      const tiles = [...grid.querySelectorAll(tileSel)];
      const from = tiles.indexOf(drag.tile);
      const to = tiles.indexOf(target);
      grid.insertBefore(drag.tile, from < to ? target.nextSibling : target);
    });
    grid.addEventListener("pointerup", (ev) => {
      if (drag && ev.pointerId === drag.pointerId) end(true);
    });
    grid.addEventListener("pointercancel", (ev) => {
      if (drag && ev.pointerId === drag.pointerId) end(false);
    });
  }

  async _saveRoomOrder(visibleOrder) {
    const rooms = this._cfg().rooms || [];
    // Rooms hidden from the hero (disabled) keep their place at the end.
    const ids = [...visibleOrder, ...rooms.map((r) => r.id).filter((id) => !visibleOrder.includes(id))];
    const previous = rooms;
    this._state.config.rooms = ids.map((id) => rooms.find((r) => r.id === id)).filter(Boolean);
    this._orderSavedAt = Date.now();
    try {
      await this._ws("nook/reorder_rooms", { room_ids: ids });
      this._showToast(t("rooms.order_saved"));
    } catch (e) {
      this._state.config.rooms = previous;
      this._showToast(t("rooms.order_failed", { error: e?.message || e }), "err");
      this._render();
    }
  }

  _bindWallPreview() {
    this._previewResize?.disconnect();
    this._previewResize = null;
    const screen = this.shadowRoot.querySelector(".wp-preview-screen");
    const frame = this.shadowRoot.getElementById("wpPreviewFrame");
    if (!screen || !frame) return;
    this._previewWidth = this._panelModel(this._previewPanelId()).width;
    this._previewResize = new ResizeObserver(() => {
      screen.style.setProperty("--wp-scale", String(screen.clientWidth / this._previewWidth));
    });
    this._previewResize.observe(screen);
    this.shadowRoot.getElementById("wpPreviewPanel")?.addEventListener("change", (ev) => {
      this._showPreviewPanel(ev.target.value);
    });
    this.shadowRoot.getElementById("wpPreviewReload")?.addEventListener("click", () => {
      frame.src = this._wallPreviewSrc(this._previewPanelId());
    });
    // Picking a model in the form resizes the preview straight away when it's the panel on show.
    this.shadowRoot.getElementById("wpModel")?.addEventListener("change", (ev) => {
      const formId = String(this.shadowRoot.getElementById("wpId")?.value || "").trim().toLowerCase().replace(/\s+/g, "-");
      if (formId && formId === this._previewPanelId()) this._applyPreviewModel(wallModel(ev.target.value));
    });
    this.shadowRoot.getElementById("wpPreviewTaps")?.addEventListener("change", (ev) => {
      this._previewTaps = ev.target.checked;
      const label = ev.target.closest(".wp-preview-taps");
      label.classList.toggle("live", this._previewTaps);
      label.lastChild.textContent = ` ${this._previewTaps ? t("preview.taps_live") : t("preview.taps_allow")}`;
      let shield = screen.querySelector(".wp-preview-shield");
      if (this._previewTaps) shield?.remove();
      else if (!shield) {
        shield = document.createElement("div");
        shield.className = "wp-preview-shield";
        shield.title = t("preview.shield");
        screen.appendChild(shield);
      }
    });
    // A missing wall app would otherwise show HA's bare 404 page inside the frame.
    fetch(WALL_APP_URL, { method: "HEAD", cache: "no-store" })
      .then((res) => {
        if (res.ok) return;
        const stage = this.shadowRoot.querySelector(".wp-preview-stage");
        if (stage) {
          stage.innerHTML = `<p class="muted wp-preview-missing">${t("preview.missing", { url: `<code>${WALL_APP_URL}</code>` })}</p>`;
        }
      })
      .catch(() => {});
  }

  _loadWallPanelIntoForm(panel) {
    if (!panel) return;
    if (panel.id !== this._previewPanelId()) this._showPreviewPanel(panel.id);
    const cards = this.shadowRoot.querySelectorAll(".wp-card");
    cards.forEach((c) => c.classList.toggle("selected", cards.length > 1 && c.dataset.id === panel.id));
  }

  async _mountWallPickers() {
    if (this._view !== "wall_panels" || !this._hass) return;
    const gen = ++this._wallPickerMountGen;
    const hosts = [...(this.shadowRoot?.querySelectorAll("[data-wall-picker]") || [])];
    if (!hosts.length) return;
    for (const host of hosts) {
      if (!host.querySelector("ha-entity-picker")) {
        host.innerHTML = `<p class="entity-picker-loading">${t("picker.loading")}</p>`;
      }
    }
    try {
      await ensureHaEntityPickerLoaded();
    } catch (err) {
      if (gen !== this._wallPickerMountGen) return;
      for (const host of hosts) {
        host.innerHTML = `<p class="entity-picker-error">${this._escape(err?.message || t("picker.unavailable"))}</p>`;
      }
      return;
    }
    if (gen !== this._wallPickerMountGen || this._view !== "wall_panels") return;

    const mountSingle = (key, { domains, filter }) => {
      const host = this.shadowRoot.querySelector(`[data-wall-picker="${key}"]`);
      if (!host) return;
      let picker = host.querySelector("ha-entity-picker");
      if (!picker) {
        host.replaceChildren();
        picker = document.createElement("ha-entity-picker");
        picker.setAttribute("allow-custom-entity", "");
        if (this._hass.userData?.showEntityIdPicker) picker.setAttribute("show-entity-id", "");
        // No picker label: the dialog's own field label is enough.
        picker.includeDomains = domains;
        if (filter) picker.entityFilter = filter;
        picker.addEventListener("value-changed", (ev) => {
          this._wallDraft[key] = ev.detail?.value || "";
          if (key === "primary") this._updateWallPrimaryNote();
        });
        host.appendChild(picker);
      }
      picker.hass = this._hass;
      const value = this._wallDraft[key] || "";
      if (picker.value !== value) picker.value = value || undefined;
    };

    mountSingle("primary", { domains: ["climate"] });
    mountSingle("insideTemp", { domains: ["sensor"], filter: temperatureSensorFilter });
    mountSingle("outsideTemp", { domains: ["sensor"], filter: temperatureSensorFilter });
    mountSingle("humidity", { domains: ["sensor"], filter: humiditySensorFilter });
    mountSingle("weather", { domains: ["weather"] });
    this._updateWallPrimaryNote();
  }

  _readWallPickerValues() {
    for (const key of ["primary", "insideTemp", "outsideTemp", "humidity", "weather"]) {
      const picker = this.shadowRoot.querySelector(`[data-wall-picker="${key}"] ha-entity-picker`);
      if (picker?.value != null) this._wallDraft[key] = String(picker.value || "");
    }
    return this._wallDraft;
  }

  async _mountSettingsPickers() {
    if (this._view !== "settings" || !this._hass) return;
    const gen = ++this._settingsPickerMountGen;
    const hosts = [...(this.shadowRoot?.querySelectorAll("[data-settings-picker]") || [])];
    if (!hosts.length) return;
    for (const host of hosts) {
      if (!host.querySelector("ha-entity-picker")) {
        host.innerHTML = `<p class="entity-picker-loading">${t("picker.loading")}</p>`;
      }
    }
    try {
      await ensureHaEntityPickerLoaded();
    } catch (err) {
      if (gen !== this._settingsPickerMountGen) return;
      for (const host of hosts) {
        host.innerHTML = `<p class="entity-picker-error">${this._escape(err?.message || t("picker.unavailable"))}</p>`;
      }
      return;
    }
    if (gen !== this._settingsPickerMountGen || this._view !== "settings") return;
    const draft = this._settingsDraft;

    const makePicker = (host, { domains, filter, placeholder }) => {
      host.replaceChildren();
      const picker = document.createElement("ha-entity-picker");
      picker.setAttribute("allow-custom-entity", "");
      if (this._hass.userData?.showEntityIdPicker) picker.setAttribute("show-entity-id", "");
      picker.includeDomains = domains;
      if (filter) picker.entityFilter = filter;
      if (placeholder) picker.placeholder = placeholder;
      picker.hass = this._hass;
      host.appendChild(picker);
      return picker;
    };

    // Single entities: the picker is the value.
    const single = (key, opts) => {
      const host = this.shadowRoot.querySelector(`[data-settings-picker="${key}"]`);
      if (!host) return;
      const picker = host.querySelector("ha-entity-picker") || makePicker(host, opts);
      picker.addEventListener("value-changed", (ev) => {
        draft[key] = ev.detail?.value || "";
      });
      picker.hass = this._hass;
      picker.value = draft[key] || undefined;
    };

    // Lists (presence, windows): our own list above an "add" picker that empties after each pick.
    const list = (key, opts) => {
      const host = this.shadowRoot.querySelector(`[data-settings-picker="${key}"]`);
      if (!host) return;
      const picker = host.querySelector("ha-entity-picker") || makePicker(host, opts);
      picker.hass = this._hass;
      picker.value = undefined;
      picker.addEventListener("value-changed", (ev) => {
        const id = ev.detail?.value;
        if (!id) return;
        if (!draft[key].includes(id)) draft[key] = [...draft[key], id];
        this._refreshSettingsList(key);
        // Clear for the next pick (after HA's own update settles).
        setTimeout(() => (picker.value = undefined), 0);
      });
    };

    single("heater", { domains: ["switch", "input_boolean", "climate"] });
    single("temperature_sensor", { domains: ["sensor"], filter: temperatureSensorFilter });
    single("backup_temperature_sensor", { domains: ["sensor"], filter: temperatureSensorFilter });
    single("outdoor_temp_sensor", { domains: ["sensor"], filter: temperatureSensorFilter });
    single("energy_sensor", { domains: ["sensor"], filter: energySensorFilter });
    list("presence_entities", { domains: ["person", "device_tracker"], placeholder: t("settings.presence.add") });
    list("window_sensors", { domains: ["binary_sensor"], placeholder: t("settings.windows.add") });

    // Watch-only sensors: picked → saved at once (the card lists them from live state).
    const watchHost = this.shadowRoot.querySelector('[data-settings-picker="watch_add"]');
    if (watchHost) {
      const picker = watchHost.querySelector("ha-entity-picker")
        || makePicker(watchHost, { domains: ["sensor"], filter: temperatureSensorFilter, placeholder: t("sensors.watch_add") });
      picker.hass = this._hass;
      picker.value = undefined;
      picker.addEventListener("value-changed", (ev) => {
        const id = ev.detail?.value;
        if (!id) return;
        setTimeout(() => (picker.value = undefined), 0);
        const list = this._cfg().watch_temperature_sensors || [];
        if (list.includes(id)) return;
        void this._saveWatchSensors([...list, id], "sensors.watch_added", id);
      });
    }
  }

  _readSettingsPickerValues() {
    // Pickers write into the draft as they change; lists are only ever edited in the draft.
    return this._settingsDraft || this._settingsDraftFromCfg();
  }

  _settingsDraftFromCfg() {
    const cfg = this._cfg();
    const presence = [...(cfg.presence_entities || [])];
    if (cfg.person_entity && !presence.includes(cfg.person_entity)) presence.unshift(cfg.person_entity);
    return {
      heater: cfg.heater || "",
      temperature_sensor: cfg.temperature_sensor || "",
      backup_temperature_sensor: cfg.backup_temperature_sensor || "",
      outdoor_temp_sensor: cfg.outdoor_temp_sensor || "",
      energy_sensor: cfg.energy_sensor || "",
      window_sensors: [...(cfg.window_sensors || [])],
      presence_entities: presence,
    };
  }

  /** Settings list for a draft key, with an empty-state line. */
  _renderSettingsList(key) {
    const ids = this._settingsDraft?.[key] || [];
    const presence = key === "presence_entities";
    if (!ids.length) {
      return `<p class="set-list-empty">${presence ? t("settings.presence.empty") : t("settings.windows.empty")}</p>`;
    }
    return this._renderEntityRows(ids, presence ? "presence" : "window", key);
  }

  /** One row per entity: picture/initial or icon, name, live state, remove. mode: presence | window | sensor. */
  _renderEntityRows(ids, mode, removeKey) {
    const presence = mode === "presence";
    return ids
      .map((id) => {
        const st = this._entityState(id);
        const name = st?.attributes?.friendly_name || id;
        let stateText = st ? st.state : t("entities.missing");
        let tone = "";
        if (!st || st.state === "unavailable" || st.state === "unknown") tone = "bad";
        else if (presence) {
          tone = st.state === "home" ? "good" : "away";
          stateText = st.state === "home" ? t("overview.stat.home") : st.state === "not_home" ? t("overview.stat.away") : st.state;
        } else if (mode === "window") {
          tone = st.state === "on" ? "warn" : "good";
          stateText = st.state === "on" ? t("overview.stat.open") : t("overview.stat.closed");
        } else {
          stateText = `${st.state}${st.attributes?.unit_of_measurement || ""}`;
        }
        const pic = st?.attributes?.entity_picture;
        const avatar = presence
          ? pic
            ? `<img class="set-avatar" src="${this._escape(pic)}" alt="" />`
            : `<span class="set-avatar">${this._escape(String(name).trim().charAt(0).toUpperCase() || "?")}</span>`
          : `<span class="set-avatar icon">${mode === "window" ? ICONS.window : ICONS.thermo}</span>`;
        return `
          <div class="set-list-item">
            ${avatar}
            <div class="set-list-text">
              <div class="set-list-name">${this._escape(name)}</div>
              <code>${this._escape(id)}</code>
            </div>
            <span class="set-state ${tone}">${this._escape(stateText)}</span>
            <button type="button" class="set-remove" data-remove-key="${removeKey}" data-remove-id="${this._escape(id)}" aria-label="${this._escape(t("common.remove_name", { name }))}" title="${this._escape(t("common.remove"))}">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
            </button>
          </div>`;
      })
      .join("");
  }

  _refreshSettingsList(key) {
    const box = this.shadowRoot.querySelector(`[data-settings-list="${key}"]`);
    if (box) box.innerHTML = this._renderSettingsList(key);
    const count = this.shadowRoot.querySelector(`[data-settings-count="${key}"]`);
    if (count) count.textContent = String((this._settingsDraft?.[key] || []).length);
  }

  _renderSettings() {
    // Building the form before the config arrives would save blanks over the real settings.
    if (!this._state?.config) {
      return `${this._pageHeader(t("settings.title"), t("settings.lead"))}<p class="muted">${t("settings.loading")}</p>`;
    }
    const cfg = this._cfg();
    if (!this._settingsDraft) this._settingsDraft = this._settingsDraftFromCfg();
    const row = (name, desc, control) => `
      <div class="set-row">
        <div class="set-row-text"><div class="set-row-name">${name}</div>${desc ? `<div class="set-row-desc">${desc}</div>` : ""}</div>
        <div class="set-row-control">${control}</div>
      </div>`;
    const toggle = (id, on) => `<label class="switch"><input type="checkbox" id="${id}" ${on ? "checked" : ""} /><span></span></label>`;
    const num = (id, value, unit, attrs = "") =>
      `<div class="num-input"><input id="${id}" type="number" value="${this._escape(value)}" ${attrs} />${unit ? `<span>${unit}</span>` : ""}</div>`;
    // −/+ whole-number stepper that can't leave [min, max].
    const stepper = (id, value, unit, min, max, step = 1) => {
      const v = Math.min(max, Math.max(min, Math.round(Number(value) || min)));
      return `<div class="num-input stepper" data-stepper="${id}" data-min="${min}" data-max="${max}">
        <button type="button" data-step="-${step}" aria-label="${this._escape(t("common.less"))}" ${v <= min ? "disabled" : ""}>−</button>
        <input id="${id}" type="number" inputmode="numeric" min="${min}" max="${max}" step="1" value="${v}" />
        <button type="button" data-step="${step}" aria-label="${this._escape(t("common.more"))}" ${v >= max ? "disabled" : ""}>+</button>
        ${unit ? `<span>${unit}</span>` : ""}
      </div>`;
    };
    const head = (icon, cls, title, sub, extra = "") => `
      <div class="card-head">
        <span class="card-icon ${cls}">${icon}</span>
        <div class="card-head-text"><p class="card-title">${title}</p><p class="card-sub">${sub}</p></div>
        ${extra}
      </div>`;
    const field = (label, key, hint) => `
      <div class="set-field">
        <div class="set-field-label">${label}</div>
        <div class="entity-picker-host" data-settings-picker="${key}"></div>
        ${hint ? `<div class="set-row-desc">${hint}</div>` : ""}
      </div>`;
    const count = (key) => `<span class="badge" data-settings-count="${key}">${(this._settingsDraft[key] || []).length}</span>`;

    return `
      ${this._pageHeader(t("settings.title"), t("settings.lead"))}
      <div class="card">
        ${head(flameSvg(), "heat", t("settings.devices.title"), t("settings.devices.sub"))}
        <div class="set-fields">
          ${field(t("settings.heater"), "heater", t("settings.heater.desc"))}
          ${field(t("settings.house_sensor"), "temperature_sensor", t("settings.house_sensor.desc"))}
          ${field(t("settings.backup_sensor"), "backup_temperature_sensor", t("settings.backup_sensor.desc"))}
          ${field(t("settings.outdoor_sensor"), "outdoor_temp_sensor", t("settings.outdoor_sensor.desc"))}
          ${field(t("settings.energy_sensor"), "energy_sensor", t("settings.energy_sensor.desc"))}
        </div>
        ${this._sensorStatusBanner()}
        ${row(t("settings.stale"), t("settings.stale.desc"), stepper("sensorStale", cfg.sensor_stale_minutes ?? 60, t("unit.min"), 15, 720, 15))}
      </div>
      ${this._renderSensorsCard(row, head)}
      ${this._renderRoomsCard()}
      <div class="ov-grid">
        <div class="card">
          ${head(ICONS.people, "intel", t("settings.presence.title"), t("settings.presence.sub"), count("presence_entities"))}
          <div class="set-list" data-settings-list="presence_entities">${this._renderSettingsList("presence_entities")}</div>
          <div class="entity-picker-host set-add" data-settings-picker="presence_entities"></div>
          ${row(t("settings.away_delay"), t("settings.away_delay.desc"), num("awayDelay", cfg.away_delay_minutes ?? 20, t("unit.min"), 'min="0" max="180" step="5"'))}
        </div>
        <div class="card">
          ${head(ICONS.window, "", t("settings.windows.title"), t("settings.windows.sub"), count("window_sensors"))}
          <div class="set-list" data-settings-list="window_sensors">${this._renderSettingsList("window_sensors")}</div>
          <div class="entity-picker-host set-add" data-settings-picker="window_sensors"></div>
          ${row(t("settings.windows.pause_after"), t("settings.windows.pause_after.desc"), stepper("windowDelay", cfg.window_open_delay_minutes ?? 3, t("unit.min"), 0, 30, 1))}
        </div>
      </div>
      <div class="ov-grid">
        <div class="card">
          ${head(ICONS.tune, "", t("settings.temps.title"), t("settings.temps.sub"))}
          ${row(t("preset.eco"), t("settings.eco.desc"), num("ecoTemp", cfg.eco_temp ?? 16, "°C", 'step="0.5"'))}
          ${row(t("preset.boost"), t("settings.boost.desc"), num("boostTemp", cfg.boost_temp ?? 22, "°C", 'step="0.5"'))}
          ${row(t("preset.away"), t("settings.away.desc"), num("awayTemp", cfg.away_temp ?? 15, "°C", 'step="0.5"'))}
          ${row(t("overview.stat.summer"), t("settings.summer.desc"), toggle("summerMode", cfg.summer_mode))}
        </div>
        <div class="card">
          ${head(ICONS.sparkle, "intel", t("intel.title"), t("settings.intel.sub"))}
          ${row(t("intel.true_radiant"), t("settings.true_radiant.desc"), toggle("trueRadiant", cfg.true_radiant !== false))}
          ${row(t("intel.auto_schedule"), t("settings.auto_schedule.desc"), toggle("autoSchedule", cfg.auto_schedule))}
          ${row(t("intel.leaf"), t("settings.leaf.desc"), toggle("leafEnabled", cfg.leaf_enabled !== false))}
          ${row(t("settings.seasonal"), t("settings.seasonal.desc"), toggle("seasonalSavings", cfg.seasonal_savings))}
          ${row(t("settings.cold_preheat"), t("settings.cold_preheat.desc"), toggle("adaptiveComfort", cfg.adaptive_comfort))}
          ${this._warmupRow(row)}
        </div>
      </div>
      <div class="ov-grid">
        <div class="card">
          ${head(ICONS.shield, "warn", t("settings.safety.title"), t("settings.safety.sub"))}
          ${row(t("schedule.enabled"), t("settings.safety.enabled.desc"), toggle("safetyEnabled", cfg.safety_temp_enabled !== false))}
          ${row(t("settings.safety.min"), "", num("safetyMin", cfg.safety_min_temp ?? 7, "°C", 'step="0.5" min="5" max="12"'))}
          ${row(t("settings.pin"), t("settings.pin.desc"), `<div class="num-input"><input id="wallPin" type="password" inputmode="numeric" maxlength="4" value="${this._escape(cfg.wall_pin || "")}" placeholder="••••" /></div>`)}
        </div>
        <div class="card">
          ${head(ICONS.gauge, "", t("settings.boiler.title"), t("settings.boiler.sub"))}
          ${row(t("settings.cold_tol"), t("settings.cold_tol.desc"), num("coldTol", cfg.cold_tolerance ?? 0.3, "°C", 'step="0.1" min="0"'))}
          ${row(t("settings.hot_tol"), t("settings.hot_tol.desc"), num("hotTol", cfg.hot_tolerance ?? 0.3, "°C", 'step="0.1" min="0"'))}
          ${row(t("settings.min_on"), t("settings.min_on.desc"), stepper("minOnMin", cfg.min_on_minutes ?? 3, t("unit.min"), 1, 30))}
          ${row(t("settings.min_off"), t("settings.min_off.desc"), stepper("minOffMin", cfg.min_off_minutes ?? 3, t("unit.min"), 1, 30))}
          ${this._relayControlRow(row)}
        </div>
      </div>
      ${this._renderAlertsCard(cfg, { row, toggle, num, head })}
      <div class="save-bar">
        <span class="muted">${t("settings.save_hint")}</span>
        <button class="primary" id="saveSettings">${t("settings.save")}</button>
      </div>
    `;
  }

  /** Learned warm-up rate and radiator coast with a Reset (e.g. after learning from a faulty boiler). */
  _warmupRow(row) {
    const intel = this._live().intelligence || {};
    const rate = intel.warmup_c_per_hour;
    const samples = Number(intel.warmup_samples ?? 0);
    const coast = Number(intel.coast_c ?? 0.1).toFixed(2);
    const coastSamples = Number(intel.coast_samples ?? 0);
    const learned = samples
      ? tn("settings.warmup.learned", samples, { rate })
      : t("settings.warmup.default", { rate: rate ?? 1.5 });
    const coasted = coastSamples
      ? tn("settings.warmup.coast_learned", coastSamples, { coast })
      : t("settings.warmup.coast_default", { coast });
    return row(
      t("settings.warmup"),
      `${this._escape(learned)} ${this._escape(coasted)} ${t("settings.warmup.desc")}`,
      `<button type="button" class="secondary" id="resetWarmup" ${samples || coastSamples ? "" : "disabled"}>${t("common.reset")}</button>`
    );
  }

  /** Warning when Nook isn't heating from the main house sensor. */
  _sensorStatusBanner() {
    const s = this._live().house_sensor || {};
    const name = (id) => this._escape(this._hass?.states?.[id]?.attributes?.friendly_name || id || "");
    const time = s.since ? this._escape(this._ehClock(s.since)) : "";
    if (s.source === "backup") {
      const off = Number(s.offset_c || 0);
      const adjusted = Math.abs(off) >= 0.05 ? t("sensor_banner.adjusted", { offset: `${off > 0 ? "+" : ""}${off.toFixed(1)}` }) : "";
      return `<div class="banner warn">${t(s.since ? "sensor_banner.backup_since" : "sensor_banner.backup", { main: name(s.main), backup: name(s.backup), time, adjusted })}</div>`;
    }
    if (s.source === "none") {
      return `<div class="banner err">${t(s.since ? "sensor_banner.none_since" : "sensor_banner.none", { time })}</div>`;
    }
    return "";
  }

  /** Every temperature sensor Nook reads, as tiles like the room cards: one row per HA floor. */
  _renderSensorsCard(row, head) {
    return `
      <div class="card" id="sensorsCard">
        ${head(ICONS.thermo, "", t("sensors.title"), t("sensors.sub"))}
        <div data-sensor-tiles>${this._renderSensorTiles()}</div>
        <div class="set-field sensor-watch-add">
          <div class="set-field-label">${t("sensors.watch_add")}</div>
          <div class="entity-picker-host set-add" data-settings-picker="watch_add"></div>
          <div class="set-row-desc">${t("sensors.watch_add.desc")}</div>
        </div>
      </div>`;
  }

  /** The sensor tiles alone (refreshed in place on the Settings page). */
  _renderSensorTiles() {
    // Lowest floor first, no floor last (stable: keeps Nook's order within a floor).
    const rank = (s) => (s.floor ? Number(s.floor.level ?? 0) : Infinity);
    const sensors = [...(this._live().temperature_sensors || [])].sort((a, b) => rank(a) - rank(b));
    // A reading stuck for hours while others move (23 Oct: a freshly paired sensor sat on its
    // first value until ZHA's Reconfigure; it looked fine otherwise).
    const changedAt = (id) => Date.parse(this._hass?.states?.[id]?.last_changed || "") || 0;
    const STUCK_MS = 3 * 3600 * 1000;
    const stuck = (id) => {
      const at = changedAt(id);
      return at > 0 && Date.now() - at > STUCK_MS
        && sensors.some((o) => o.entity_id !== id && Date.now() - changedAt(o.entity_id) < 3600 * 1000);
    };
    const tiles = sensors.map((s) => {
      const st = this._hass?.states?.[s.entity_id];
      const friendly = st?.attributes?.friendly_name || s.entity_id;
      const title = this._escape(s.floor?.area || friendly);
      const sub = s.floor?.area ? `<span class="sensor-card-entity" title="${this._escape(s.entity_id)}">${this._escape(friendly)}</span>` : "";
      const uses = s.uses || [];
      const badges = uses
        .filter((u) => !u.startsWith("room:"))
        .map((u) => `<span class="set-state ${u === "watch" ? "" : "good"}">${t(`sensors.use.${u}`)}</span>`)
        .join("");
      const rooms = uses.filter((u) => u.startsWith("room:")).map((u) => this._escape(u.slice(5)));
      const ok = st && !["unknown", "unavailable"].includes(st.state) && Number.isFinite(Number(st.state));
      const now = ok ? `${this._escape(formatTemp(Math.round(Number(st.state) * 10) / 10))}°` : "—";
      const mins = st?.last_changed ? Math.max(0, Math.round((Date.now() - Date.parse(st.last_changed)) / 60000)) : null;
      const ago = mins == null ? ""
        : mins < 1 ? t("sensors.just_now")
        : mins < 60 ? t("time.m", { m: mins })
        : mins % 60 && mins < 600 ? t("time.hm", { h: Math.floor(mins / 60), m: mins % 60 })
        : t("time.h", { h: Math.round(mins / 60) });
      const changed = mins == null ? "" : t("sensors.changed", { ago });
      const r = s.reporting;
      let status;
      if (r && r.ok) status = r.fast ? t("reporting.fast") : t("reporting.normal");
      else if (r && r.applied && r.fast) status = t("reporting.fast_recheck");
      else if (r && r.pending) status = `${this._escape(r.error || t("reporting.waiting"))}…`;
      else if (r) status = `<span class="warn-text">${t("reporting.not_set", { error: this._escape(r.error || t("reporting.unknown_error")) })}</span>`;
      else status = s.fast ? t("reporting.queued") : t("sensors.normal");
      const watchOnly = uses.length === 1 && uses[0] === "watch";
      const remove = watchOnly
        ? `<button type="button" class="set-remove" data-watch-remove="${this._escape(s.entity_id)}" aria-label="${this._escape(t("common.remove_name", { name: friendly }))}" title="${this._escape(t("sensors.watch_stop"))}">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
          </button>`
        : "";
      const html = `
        <div class="room-card sensor-card">
          <div class="room-card-top">
            <span class="room-card-name">${title}</span>
            ${remove}
          </div>
          ${sub}
          <div class="room-card-temps">
            <span class="room-card-now${ok ? "" : " unknown"}">${now}</span>
            <span class="room-card-target">${this._escape(changed)}</span>
          </div>
          <div class="room-card-meta">
            <span class="sensor-card-badges">${badges}</span>
            ${rooms.length ? `<span class="room-card-sensors">${tn("sensors.rooms", rooms.length, { rooms: rooms.join(", ") })}</span>` : ""}
          </div>
          ${s.floor ? "" : `<div class="room-card-sensors warn-text">${t("sensors.no_floor.desc")}</div>`}
          ${ok && stuck(s.entity_id) ? `<div class="room-card-sensors warn-text">${t("sensors.stuck", { time: this._escape(this._sinceText(st.last_changed)) })}</div>` : ""}
          ${s.zigbee ? `
          <div class="room-card-calls">
            <span>${t("sensors.fast")}</span>
            <label class="switch" title="${this._escape(t("sensors.fast"))}"><input type="checkbox" data-sensor-fast="${this._escape(s.entity_id)}" ${s.fast ? "checked" : ""} /><span></span></label>
          </div>
          <div class="room-card-sensors">${status}</div>` : ""}
        </div>`;
      return { floor: s.floor?.name || t("sensors.no_floor"), noFloor: !s.floor, html };
    });
    // One row of tiles per HA floor (lowest first, as the backend sorts them).
    const groups = [];
    for (const tile of tiles) {
      if (!groups.length || groups[groups.length - 1].floor !== tile.floor) groups.push({ ...tile, tiles: [] });
      groups[groups.length - 1].tiles.push(tile.html);
    }
    const body = groups
      .map((g) => `<div class="set-group-title${g.noFloor ? " warn-text" : ""}">${this._escape(g.floor)}</div><div class="room-grid">${g.tiles.join("")}</div>`)
      .join("");
    return tiles.length ? body : `<p class="muted">${t("sensors.empty")}</p>`;
  }

  /** Settings is a form page and never re-renders in the background; the sensor tiles show
   * things that change outside Nook (HA areas/floors, readings), so they refresh on their own. */
  _refreshSensorTiles() {
    const box = this.shadowRoot?.querySelector("[data-sensor-tiles]");
    if (!box || box.contains(this.shadowRoot.activeElement)) return;
    const html = this._renderSensorTiles();
    if (box.innerHTML === html) return;
    box.innerHTML = html;
    this._bindSensorsCard(box);
  }

  /** Add/remove a watch-only sensor (saved at once). */
  async _saveWatchSensors(list, toastKey, id) {
    const name = this._hass?.states?.[id]?.attributes?.friendly_name || id;
    try {
      await this._ws("nook/update_settings", { watch_temperature_sensors: list });
      await this._loadState();
      this._showToast(t(toastKey, { name }));
    } catch (e) {
      this._showToast(t("common.save_failed", { error: e?.message || e }), "err");
    }
  }

  /** Faster updates per sensor: saved at once, like the TRV settings. */
  _bindSensorsCard(root = this.shadowRoot) {
    root.querySelectorAll("[data-watch-remove]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.watchRemove;
        const list = (this._cfg().watch_temperature_sensors || []).filter((e) => e !== id);
        void this._saveWatchSensors(list, "sensors.watch_removed", id);
      });
    });
    root.querySelectorAll("[data-sensor-fast]").forEach((box) => {
      box.addEventListener("change", async () => {
        const id = box.dataset.sensorFast;
        const list = new Set(this._cfg().fast_reporting_sensors || []);
        if (box.checked) list.add(id);
        else list.delete(id);
        const name = this._hass?.states?.[id]?.attributes?.friendly_name || id;
        try {
          await this._ws("nook/update_settings", { fast_reporting_sensors: [...list] });
          await this._loadState();
          this._showToast(t(box.checked ? "sensors.fast_on" : "sensors.fast_off", { name }));
        } catch (e) {
          box.checked = !box.checked;
          this._showToast(t("common.save_failed", { error: e?.message || e }), "err");
        }
      });
    });
  }

  /** Release the boiler relay for a hand test; Nook takes it back by itself. */
  _relayControlRow(row) {
    const until = this._live().control_released_until;
    if (until) {
      return row(
        t("settings.heater"),
        `<span class="badge warn">${t("relay.released")}</span> ${t("relay.released.desc", { time: this._escape(this._ehClock(until)) })}`,
        `<button type="button" class="primary" id="takeControl">${t("relay.take_control")}</button>`
      );
    }
    return row(
      t("settings.heater"),
      t("relay.desc"),
      `<button type="button" class="secondary" id="releaseControl">${t("relay.release")}</button>`
    );
  }

  /** Notify services that can reach a person (phones etc.), plus any saved ones that have gone. */
  _notifyServices(saved) {
    const skip = new Set(["notify", "send_message", "persistent_notification"]);
    const names = Object.keys(this._hass?.services?.notify || {}).filter((n) => !skip.has(n));
    for (const s of saved) if (!names.includes(s)) names.push(s);
    return names.sort();
  }

  _renderAlertsCard(cfg, { row, toggle, num, head }) {
    const saved = Array.isArray(cfg.alert_notify) ? cfg.alert_notify : [];
    const available = new Set(Object.keys(this._hass?.services?.notify || {}));
    const label = (name) =>
      name.startsWith("mobile_app_") ? t("alerts.phone", { name: name.slice(11).replace(/_/g, " ") }) : name.replace(/_/g, " ");
    const services = this._notifyServices(saved);
    const list = services.length
      ? services
          .map(
            (name) => `
            <div class="set-row">
              <div class="set-row-text">
                <div class="set-row-name">${this._escape(label(name))}</div>
                <div class="set-row-desc"><code>notify.${this._escape(name)}</code>${available.has(name) ? "" : t("alerts.gone")}</div>
              </div>
              <div class="set-row-control"><label class="switch"><input type="checkbox" data-alert-notify="${this._escape(name)}" ${saved.includes(name) ? "checked" : ""} /><span></span></label></div>
            </div>`
          )
          .join("")
      : `<p class="muted">${t("alerts.none")}</p>`;
    return `
      <div class="card">
        ${head(ICONS.bell, "warn", t("alerts.title"), t("alerts.sub"))}
        ${row(t("alerts.not_warming"), t("alerts.not_warming.desc"), toggle("noHeatAlert", cfg.no_heat_alert !== false))}
        ${row(t("alerts.after"), t("alerts.after.desc"), num("noHeatMinutes", cfg.no_heat_alert_minutes ?? 60, t("unit.min"), 'step="10" min="20" max="240"'))}
        <div class="set-field-label" style="margin-top:10px">${t("alerts.send_to")}</div>
        <div class="notify-list">${list}</div>
      </div>`;
  }

  _mutateSchedule(mutator) {
    if (!this._state?.config) return;
    const schedule = JSON.parse(JSON.stringify(this._cfg().schedule || {}));
    mutator(schedule);
    this._state.config.schedule = schedule;
  }

  /** Unsaved Settings fields as {key: value|checked}; room switches and dialogs aren't part of the form. */
  _settingsFormInputs() {
    if (this._view !== "settings" || !this.shadowRoot.getElementById("saveSettings")) return [];
    return [...this.shadowRoot.querySelectorAll(".main-inner input")]
      .filter((el) => !el.closest(".room-card") && (el.id || el.dataset.alertNotify))
      .map((el) => [el.id || `alert:${el.dataset.alertNotify}`, el]);
  }

  _render() {
    // A redraw (e.g. after saving a room) must not throw away Settings edits that aren't saved yet.
    if (this._settingsDraft) {
      const form = {};
      for (const [key, el] of this._settingsFormInputs()) form[key] = el.type === "checkbox" ? el.checked : el.value;
      if (Object.keys(form).length) this._settingsDraft.form = form;
    }
    const body =
      this._view === "energy"
        ? this._renderEnergy()
        : this._view === "schedule"
            ? this._renderSchedule()
            : this._view === "wall_panels"
              ? this._renderWallPanels()
              : this._view === "settings"
                ? this._renderSettings()
                : this._renderOverview();

    const tabs = NAV.map(
      (n) =>
        `<button type="button" class="tab${this._view === n.id ? " active" : ""}" data-view="${n.id}">${n.label}</button>`
    ).join("");

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="shell${this._narrow ? " narrow" : ""}">
        <header class="page-header">
          <div class="panel-header-top">
            <button type="button" class="panel-ha-menu-btn" id="haMenu" aria-label="${this._escape(t("app.menu"))}">
              <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path fill="currentColor" d="M3 6h18v2H3V6m0 5h18v2H3v-2m0 5h18v2H3v-2Z"/></svg>
            </button>
            <div class="panel-brand-row">
              <div class="panel-brand-mark" aria-hidden="true">${logoSvg()}</div>
              <div>
                <div class="panel-brand-title">${t("app.title")}</div>
                <div class="panel-brand-sub">${t("app.subtitle")}</div>
              </div>
            </div>
          </div>
          <nav class="tab-bar" aria-label="${this._escape(t("app.sections"))}">${tabs}</nav>
        </header>
        <div class="main">
          <div class="main-inner">
            ${this._error ? `<div class="banner err">${this._escape(this._error)}</div>` : ""}
            ${this._flash ? `<div class="banner ok">${this._escape(this._flash)}</div>` : ""}
            ${body}
          </div>
        </div>
        <p class="panel-build-footer">${t("app.footer", { version: PANEL_VERSION })}</p>
      </div>
      ${this._renderDialog()}
    `;
    const kept = this._settingsDraft?.form;
    if (kept) {
      for (const [key, el] of this._settingsFormInputs()) {
        if (!(key in kept)) continue;
        if (el.type === "checkbox") el.checked = kept[key];
        else el.value = kept[key];
      }
    }
    this._bind();
    this._bindWallPreview();
    if (this._view === "wall_panels") this._bindKioskCard();
    this._bindRoomDrag();
    this._layoutEnergyBubbles();
    // Overview re-renders every few seconds; keep the Entities section as the user left it.
    this.shadowRoot.getElementById("ovEntities")?.addEventListener("toggle", (ev) => {
      this._entitiesOpen = ev.target.open;
    });
    if (this._view === "settings") {
      void this._mountRoomPickers();
    }
    if (this._view === "wall_panels") {
      void this._mountWallPickers();
    }
    if (this._view === "settings") {
      void this._mountSettingsPickers();
    }
  }

  _bind() {
    this.shadowRoot.getElementById("haMenu")?.addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
    });

    this.shadowRoot.querySelectorAll(".tab[data-view]").forEach((btn) => {
      btn.addEventListener("click", () => this._setView(btn.dataset.view));
    });

    this.shadowRoot.getElementById("resetWarmup")?.addEventListener("click", async () => {
      if (!window.confirm(t("settings.warmup.reset_confirm"))) return;
      try {
        await this._ws("nook/reset_warmup");
        // Update just this row: a full redraw would drop unsaved Settings edits.
        const live = this._state?.live;
        if (live) live.intelligence = { ...(live.intelligence || {}), warmup_c_per_hour: 1.5, warmup_samples: 0, coast_c: 0.1, coast_samples: 0 };
        const btn = this.shadowRoot.getElementById("resetWarmup");
        const html = this._warmupRow((name, desc, control) => `<div class="set-row-desc">${desc}</div>${control}`);
        const tmp = document.createElement("div");
        tmp.innerHTML = html;
        btn?.closest(".set-row")?.querySelector(".set-row-desc")?.replaceWith(tmp.querySelector(".set-row-desc"));
        if (btn) btn.disabled = true;
        this._showToast(t("settings.warmup.reset_done"));
      } catch (e) {
        this._showToast(t("settings.warmup.reset_failed", { error: e?.message || e }), "err");
      }
    });

    this.shadowRoot.querySelectorAll("[data-stepper]").forEach((box) => {
      const input = box.querySelector("input");
      const min = Number(box.dataset.min);
      const max = Number(box.dataset.max);
      const set = (v) => {
        const n = Math.min(max, Math.max(min, Math.round(Number(v) || min)));
        input.value = String(n);
        box.querySelector('[data-step^="-"]').disabled = n <= min;
        box.querySelector('[data-step]:not([data-step^="-"])').disabled = n >= max;
      };
      box.querySelectorAll("[data-step]").forEach((btn) =>
        btn.addEventListener("click", () => set(Number(input.value) + Number(btn.dataset.step)))
      );
      input.addEventListener("change", () => set(input.value));
    });

    const relayAction = async (type, done) => {
      try {
        await this._ws(type);
        await this._loadState();
        this._showToast(done);
      } catch (e) {
        this._showToast(t("relay.failed", { error: e?.message || e }), "err");
      }
    };
    this.shadowRoot.getElementById("releaseControl")?.addEventListener("click", () => {
      if (!window.confirm(t("relay.release_confirm"))) return;
      void relayAction("nook/release_control", t("relay.released_toast"));
    });
    this.shadowRoot.getElementById("takeControl")?.addEventListener("click", () => {
      void relayAction("nook/take_control", t("relay.taken_toast"));
    });

    this.shadowRoot.getElementById("stopSeasonal")?.addEventListener("click", async () => {
      try {
        await this._ws("nook/stop_seasonal_savings");
        await this._loadState();
        this._showToast(t("seasonal.stopped"));
      } catch (e) {
        this._error = String(e.message || e);
        this._showToast(this._error, "err");
        this._render();
      }
    });

    // The hero controls whatever is on the dial: the house, or the selected room.
    const heroCall = async (service, data, label) => {
      const room = this._focusRoom();
      const entity = room ? this._roomEntity(room) : this._nookClimateEntities().home;
      if (!entity) {
        this._showToast(room ? t("dial.room_unavailable", { name: room.name }) : t("dial.house_unavailable"), "err");
        return;
      }
      try {
        await this._hass.callService("climate", service, { entity_id: entity, ...data });
        // The entity updates straight away; redraw once HA has pushed it.
        setTimeout(() => this._render(), 250);
        this._showToast(room ? t("hero.toast.room", { name: room.name, label }) : label);
      } catch (e) {
        this._showToast(t("hero.toast.failed", { error: e?.message || e }), "err");
      }
    };
    this.shadowRoot.querySelectorAll("[data-hero-hvac]").forEach((btn) => {
      btn.addEventListener("click", () =>
        heroCall("set_hvac_mode", { hvac_mode: btn.dataset.heroHvac }, btn.dataset.heroHvac === "off" ? t("hero.toast.heating_off") : t("hero.toast.heating_on"))
      );
    });
    this.shadowRoot.querySelectorAll("[data-hero-preset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const room = this._focusRoom();
        const current = this._entityState(room ? this._roomEntity(room) : this._nookClimateEntities().home)?.attributes?.preset_mode;
        const next = current === btn.dataset.heroPreset ? "none" : btn.dataset.heroPreset;
        heroCall("set_preset_mode", { preset_mode: next }, next === "none" ? t("hero.toast.preset_cleared") : t("hero.toast.preset_on", { preset: t(`preset.${next}`) }));
      });
    });
    this.shadowRoot.querySelectorAll(".dial-step").forEach((btn) => {
      btn.addEventListener("click", () => this._stepTarget(Number(btn.dataset.step)));
    });
    this.shadowRoot.querySelectorAll("[data-zone]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (this._suppressZoneClick) return; // the click that ends a drag
        // A room puts it on the dial; clicking it again (or Home) goes back to the house.
        const zone = btn.dataset.zone;
        this._focusZone = zone === this._focusZone ? "home" : zone;
        this._render();
      });
    });

    // Schedule interactions
    this.shadowRoot.querySelectorAll(".nest-point").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._selectedDay = btn.dataset.day;
        this._selectedPoint = { day: btn.dataset.day, index: Number(btn.dataset.index) };
        this._render();
      });
    });
    this.shadowRoot.querySelectorAll("[data-day-track]").forEach((track) => {
      track.addEventListener("click", () => {
        this._selectedDay = track.dataset.dayTrack;
        this._selectedPoint = null;
        this._render();
      });
    });

    this.shadowRoot.getElementById("schedCopy")?.addEventListener("click", () => {
      const day = this._selectedDay;
      this._clipboard = JSON.parse(JSON.stringify(this._cfg().schedule?.[day] || []));
      this._flash = t("schedule.copied", { day: DAY_SHORT[day] });
      this._render();
    });
    this.shadowRoot.getElementById("schedPaste")?.addEventListener("click", () => {
      if (!this._clipboard) {
        this._error = t("schedule.nothing_copied");
        this._render();
        return;
      }
      this._mutateSchedule((schedule) => {
        schedule[this._selectedDay] = JSON.parse(JSON.stringify(this._clipboard));
      });
      this._flash = t("schedule.pasted", { day: DAY_SHORT[this._selectedDay] });
      this._render();
    });
    this.shadowRoot.getElementById("schedRemove")?.addEventListener("click", () => {
      if (!this._selectedPoint) {
        this._error = t("schedule.select_to_remove");
        this._render();
        return;
      }
      const { day, index } = this._selectedPoint;
      this._mutateSchedule((schedule) => {
        const blocks = [...(schedule[day] || [])];
        blocks.splice(index, 1);
        schedule[day] = blocks;
      });
      this._selectedPoint = null;
      this._flash = t("schedule.removed");
      this._render();
    });
    // With a block selected, the form edits it: day, times and temperature apply as they change.
    const editSelectedBlock = () => {
      const sel = this._selectedPoint;
      if (!sel) return;
      const day = this.shadowRoot.getElementById("addDay")?.value || sel.day;
      const start = this.shadowRoot.getElementById("addStart")?.value;
      const end = this.shadowRoot.getElementById("addEnd")?.value;
      const temperature = Number(this.shadowRoot.getElementById("addTemp")?.value);
      if (!start || !end || !Number.isFinite(temperature)) return;
      let index = -1;
      this._mutateSchedule((schedule) => {
        const from = [...(schedule[sel.day] || [])];
        const [block] = from.splice(sel.index, 1);
        if (!block) return;
        schedule[sel.day] = from;
        const edited = { ...block, start, end, temperature };
        const to = day === sel.day ? from : [...(schedule[day] || [])];
        to.push(edited);
        to.sort((a, b) => parseHHMM(a.start) - parseHHMM(b.start));
        schedule[day] = to;
        index = to.indexOf(edited);
      });
      if (index < 0) return;
      this._selectedDay = day;
      this._selectedPoint = { day, index };
      this._flash = t("schedule.updated");
      this._render();
    };
    for (const id of ["addDay", "addStart", "addEnd", "addTemp"]) {
      this.shadowRoot.getElementById(id)?.addEventListener("change", editSelectedBlock);
    }

    this.shadowRoot.getElementById("schedAdd")?.addEventListener("click", () => {
      if (this._selectedPoint) {
        // The form is showing a block: switch it to a new one first.
        this._selectedPoint = null;
        this._flash = t("schedule.add_hint");
        this._render();
        return;
      }
      const day = this.shadowRoot.getElementById("addDay")?.value || this._selectedDay;
      const start = this.shadowRoot.getElementById("addStart")?.value || "06:30";
      const end = this.shadowRoot.getElementById("addEnd")?.value || "08:30";
      const temperature = Number(this.shadowRoot.getElementById("addTemp")?.value || 20);
      this._mutateSchedule((schedule) => {
        const blocks = [...(schedule[day] || [])];
        blocks.push({ start, end, temperature, enabled: true });
        blocks.sort((a, b) => parseHHMM(a.start) - parseHHMM(b.start));
        schedule[day] = blocks;
      });
      this._selectedDay = day;
      this._flash = t("schedule.added");
      this._render();
    });

    const saveSchedule = this.shadowRoot.getElementById("saveSchedule");
    if (saveSchedule) {
      saveSchedule.addEventListener("click", async () => {
        try {
          await this._ws("nook/update_schedule", {
            schedule: this._cfg().schedule || {},
            schedule_enabled: this.shadowRoot.getElementById("schedEnabled").value === "true",
          });
          await this._loadState();
          this._showToast(t("schedule.saved"));
        } catch (e) {
          this._error = String(e.message || e);
          this._showToast(this._error, "err");
          this._render();
        }
      });
    }

    const saveSettings = this.shadowRoot.getElementById("saveSettings");
    this._bindSensorsCard();
    if (saveSettings) {
      saveSettings.addEventListener("click", async () => {
        const devices = this._readSettingsPickerValues();
        if (!devices.heater || !devices.temperature_sensor) {
          this._showToast(t("settings.need_devices"), "err");
          return;
        }
        try {
          await this._ws("nook/update_settings", {
            heater: devices.heater,
            temperature_sensor: devices.temperature_sensor,
            outdoor_temp_sensor: devices.outdoor_temp_sensor || "",
            backup_temperature_sensor: devices.backup_temperature_sensor || "",
            energy_sensor: devices.energy_sensor || "",
            sensor_stale_minutes: Math.min(720, Math.max(15, Math.round(Number(this.shadowRoot.getElementById("sensorStale").value) || 60))),
            window_sensors: devices.window_sensors || [],
            window_open_delay_minutes: Math.min(30, Math.max(0, Math.round(Number(this.shadowRoot.getElementById("windowDelay")?.value ?? 3)))),
            presence_entities: devices.presence_entities || [],
            // Presence picker now holds everyone; clear the old single-person field.
            person_entity: "",
            eco_temp: Number(this.shadowRoot.getElementById("ecoTemp").value),
            boost_temp: Number(this.shadowRoot.getElementById("boostTemp").value),
            away_temp: Number(this.shadowRoot.getElementById("awayTemp").value),
            cold_tolerance: Number(this.shadowRoot.getElementById("coldTol").value),
            hot_tolerance: Number(this.shadowRoot.getElementById("hotTol").value),
            min_on_minutes: Math.min(30, Math.max(1, Math.round(Number(this.shadowRoot.getElementById("minOnMin").value) || 3))),
            min_off_minutes: Math.min(30, Math.max(1, Math.round(Number(this.shadowRoot.getElementById("minOffMin").value) || 3))),
            summer_mode: this.shadowRoot.getElementById("summerMode").checked,
            true_radiant: this.shadowRoot.getElementById("trueRadiant").checked,
            auto_schedule: this.shadowRoot.getElementById("autoSchedule").checked,
            leaf_enabled: this.shadowRoot.getElementById("leafEnabled").checked,
            seasonal_savings: this.shadowRoot.getElementById("seasonalSavings").checked,
            adaptive_comfort: this.shadowRoot.getElementById("adaptiveComfort").checked,
            safety_temp_enabled: this.shadowRoot.getElementById("safetyEnabled").checked,
            safety_min_temp: Number(this.shadowRoot.getElementById("safetyMin").value),
            wall_pin: this.shadowRoot.getElementById("wallPin").value.trim(),
            away_delay_minutes: Number(this.shadowRoot.getElementById("awayDelay").value),
            no_heat_alert: this.shadowRoot.getElementById("noHeatAlert").checked,
            no_heat_alert_minutes: Math.min(240, Math.max(20, Math.round(Number(this.shadowRoot.getElementById("noHeatMinutes").value) || 60))),
            alert_notify: [...this.shadowRoot.querySelectorAll("[data-alert-notify]")]
              .filter((el) => el.checked)
              .map((el) => el.dataset.alertNotify),
          });
          this._settingsDraft = null;
          await this._loadState();
          this._showToast(t("settings.saved"));
        } catch (e) {
          this._error = String(e.message || e);
          this._showToast(this._error, "err");
          this._render();
        }
      });
    }

    const saveRoom = this.shadowRoot.getElementById("saveRoom");
    if (saveRoom) {
      saveRoom.addEventListener("click", async () => {
        const name = this.shadowRoot.getElementById("roomName").value.trim();
        this._roomDraft.name = name;
        const draft = this._readRoomPickerValues();
        const trv = String(draft.trv || "").trim();
        const sensor = String(draft.sensor || "").trim();
        const extras = (draft.extras || []).map((s) => String(s).trim()).filter(Boolean);
        const callsForHeat = this.shadowRoot.getElementById("roomCallsForHeat")?.checked !== false;
        if (!name || !trv) {
          this._error = t("room_dlg.required");
          this._showToast(this._error, "err");
          return;
        }
        const existing = this._editingRoomId
          ? (this._cfg().rooms || []).find((r) => r.id === this._editingRoomId)
          : null;
        const id =
          existing?.id ||
          name
            .toLowerCase()
            .replace(/\s+/g, "_")
            .replace(/[^a-z0-9_]/g, "");
        const rooms = [...(this._cfg().rooms || [])];
        // Replace in place (keeps the user's room order); new rooms go at the end.
        const at = rooms.findIndex((r) => r.id === id);
        const room = {
          id,
          name,
          trv_entity: trv,
          temperature_sensor: sensor,
          extra_temperature_sensors: extras,
          enabled: existing?.enabled !== false,
          calls_for_heat: callsForHeat,
          calibrate_trv: this.shadowRoot.getElementById("roomCalibrateTrv")?.checked === true,
          ...this._readRoomTempFields(),
          boost_temp: existing?.boost_temp,
          window_sensors: existing?.window_sensors || [],
        };
        if (at >= 0) rooms[at] = room;
        else rooms.push(room);
        try {
          await this._ws("nook/update_rooms", { rooms });
          this._dialogKind = null;
          this._editingRoomId = null;
          this._roomDraft = { name: "", trv: "", sensor: "", extras: [], calls_for_heat: true };
          await this._loadState();
          this._showToast(t("room_dlg.saved", { name }));
        } catch (e) {
          this._error = String(e.message || e);
          this._showToast(this._error, "err");
          this._render();
        }
      });


      this.shadowRoot.getElementById("deleteRoom")?.addEventListener("click", async () => {
        const id = this._editingRoomId;
        if (!id) return;
        const room = (this._cfg().rooms || []).find((r) => r.id === id);
        if (!window.confirm(t("room_dlg.delete_confirm", { name: room?.name || id }))) return;
        const rooms = (this._cfg().rooms || []).filter((r) => r.id !== id);
        try {
          await this._ws("nook/update_rooms", { rooms });
          this._dialogKind = null;
          this._editingRoomId = null;
          this._roomDraft = { name: "", trv: "", sensor: "", extras: [], calls_for_heat: true };
          await this._loadState();
          this._showToast(t("room_dlg.deleted"));
        } catch (e) {
          this._error = String(e.message || e);
          this._showToast(this._error, "err");
          this._render();
        }
      });

      this.shadowRoot.getElementById("roomCallsForHeat")?.addEventListener("change", (ev) => {
        this._roomDraft.calls_for_heat = ev.target.checked;
      });
      this.shadowRoot.getElementById("roomCalibrateTrv")?.addEventListener("change", (ev) => {
        this._roomDraft.calibrate_trv = ev.target.checked;
      });
      this._bindTrvConfig();
      // Keep the draft current (the dialog can re-render) and swap offset ⇄ own temps.
      ["roomFollowHouse", "roomOffset", "roomComfort", "roomEco", "roomHoldEnds"].forEach((id) => {
        this.shadowRoot.getElementById(id)?.addEventListener("change", () => {
          Object.assign(this._roomDraft, this._readRoomTempFields());
          const follow = this._roomDraft.follow_house;
          this.shadowRoot.querySelectorAll("[data-follow]").forEach((el) => {
            el.hidden = (el.dataset.follow === "on") !== follow;
          });
        });
      });
    }

    if (this._view === "wall_panels") {
      const open = (id) => this._openWallDialog(id ? (this._cfg().wall_panels || []).find((p) => p.id === id) : null);
      this.shadowRoot.getElementById("addWallPanel")?.addEventListener("click", () => open(null));
      this.shadowRoot.getElementById("addWallPanelEmpty")?.addEventListener("click", () => open(null));
      this.shadowRoot.querySelectorAll(".edit-panel").forEach((btn) =>
        btn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          open(btn.dataset.id);
        })
      );
      this.shadowRoot.querySelectorAll(".wp-card[data-id]").forEach((card) => {
        const show = () => this._loadWallPanelIntoForm((this._cfg().wall_panels || []).find((p) => p.id === card.dataset.id));
        card.addEventListener("click", show);
        card.addEventListener("keydown", (ev) => {
          if (ev.target !== card || (ev.key !== "Enter" && ev.key !== " ")) return;
          ev.preventDefault();
          show();
        });
      });
    }
    if (this._view === "settings") {
      this.shadowRoot.getElementById("addRoom")?.addEventListener("click", () => this._loadRoomIntoForm(null));
      this.shadowRoot.getElementById("addRoomEmpty")?.addEventListener("click", () => this._loadRoomIntoForm(null));
      this.shadowRoot.querySelectorAll(".room-card[data-room-id]").forEach((card) => {
        const open = () => this._loadRoomIntoForm((this._cfg().rooms || []).find((r) => r.id === card.dataset.roomId));
        card.addEventListener("click", (ev) => {
          if (this._suppressZoneClick || ev.target.closest(".switch")) return;
          open();
        });
        card.addEventListener("keydown", (ev) => {
          if (ev.target !== card || (ev.key !== "Enter" && ev.key !== " ")) return;
          ev.preventDefault();
          open();
        });
      });
      this.shadowRoot.querySelectorAll("[data-toggle-calls]").forEach((btn) => {
        btn.addEventListener("change", async () => {
          const id = btn.dataset.toggleCalls;
          const rooms = (this._cfg().rooms || []).map((r) =>
            r.id === id ? { ...r, calls_for_heat: btn.checked } : { ...r }
          );
          try {
            await this._ws("nook/update_rooms", { rooms });
            await this._loadState();
            const next = rooms.find((r) => r.id === id);
            this._showToast(t(next?.calls_for_heat !== false ? "rooms.calls_on" : "rooms.calls_off", { name: next?.name || id }));
          } catch (e) {
            this._showToast(String(e.message || e), "err");
            this._render();
          }
        });
      });
    }

    const saveWall = this.shadowRoot.getElementById("saveWallPanel");
    if (saveWall) {
      saveWall.addEventListener("click", async () => {
        const id = slugId(this.shadowRoot.getElementById("wpId").value);
        const label = this.shadowRoot.getElementById("wpLabel").value.trim() || id;
        if (!id) {
          this._showToast(t("wall_dlg.need_name"), "err");
          return;
        }
        if (!this._wallEditingId && (this._cfg().wall_panels || []).some((p) => p.id === id)) {
          this._showToast(t("wall_dlg.id_exists", { id }), "err");
          return;
        }
        const helperHost = String(this.shadowRoot.getElementById("wpHelperHost")?.value ?? this._wallDraft.helperHost ?? "").trim();
        if (helperHost && !/[.:a-z]/i.test(helperHost)) {
          // Seen 14 Oct: the pairing code typed into the address box.
          this._showToast(t("wall_dlg.host_looks_like_code"), "err");
          return;
        }
        const draft = this._readWallPickerValues();
        // Blank = Nook's house climate (resolved to its real entity id by the backend).
        const primary = String(draft.primary || "").trim();
        const idleSec = Number(this.shadowRoot.getElementById("wpIdle").value) || 30;
        // Empty rooms list = wall UI always loads the live Nook room list
        const rooms = [];
        try {
          await this._ws("nook/upsert_wall_panel", {
            panel: {
              id,
              label,
              primary_entity: primary,
              rooms,
              sensors: {
                insideTemp: String(draft.insideTemp || "").trim(),
                outsideTemp: String(draft.outsideTemp || "").trim(),
                insideHumidity: String(draft.humidity || "").trim(),
                weather: String(draft.weather || "").trim() || "weather.home",
                sun: "sun.sun",
              },
              display: { idleMs: idleSec * 1000, panelEntity: "" },
              temperature_lock: Boolean(this.shadowRoot.getElementById("wpLock")?.checked),
              model: wallModel(this.shadowRoot.getElementById("wpModel")?.value).id,
              kiosk_enabled: this.shadowRoot.getElementById("wpKioskEnabled")?.checked ?? this._wallDraft.kioskEnabled !== false,
              helper_host: helperHost,
              ...(this.shadowRoot.getElementById("wpKioskDevice")
                ? {
                    kiosk_device: this.shadowRoot.getElementById("wpKioskDevice").value,
                    kiosk_overrides: this._readKioskControls("ko_"),
                  }
                : {
                    kiosk_device: this._wallDraft.kioskDevice || "",
                    kiosk_overrides: this._wallDraft.kioskOverrides || {},
                  }),
            },
          });
          this._previewPanel = id;
          this._dialogKind = null;
          this._wallEditingId = null;
          await this._loadState();
          await this._loadKiosk();
          this._showToast(t("wall_dlg.saved", { name: label }));
        } catch (e) {
          this._error = String(e.message || e);
          this._showToast(this._error, "err");
          this._render();
        }
      });
      // Picking Sonoff NSPanel Pro shows its section straight away.
      this.shadowRoot.getElementById("wpModel")?.addEventListener("change", (ev) => {
        this._wallDraft.model = ev.target.value;
        const section = this.shadowRoot.getElementById("wpHelperSection");
        if (section) section.hidden = ev.target.value !== "nspanel_pro";
      });
      this._bindHelperSection();
      this._bindCollapse("wpKioskToggle", "wpKioskSection", (open) => {
        this._wallDraft.kioskOpen = open;
      });
      this.shadowRoot.getElementById("wpKioskEnabled")?.addEventListener("change", (ev) => {
        this._wallDraft.kioskEnabled = ev.target.checked;
        const body = this.shadowRoot.getElementById("wpKioskBody");
        if (body) body.hidden = !ev.target.checked;
      });
      this.shadowRoot.getElementById("deleteWallPanel")?.addEventListener("click", async () => {
        const id = this._wallEditingId;
        const panel = (this._cfg().wall_panels || []).find((p) => p.id === id);
        if (!id || !window.confirm(t("wall_dlg.delete_confirm", { name: panel?.label || id }))) return;
        try {
          await this._ws("nook/delete_wall_panel", { panel_id: id });
          this._dialogKind = null;
          this._wallEditingId = null;
          await this._loadState();
          this._showToast(t("wall_dlg.deleted"));
        } catch (e) {
          this._showToast(String(e.message || e), "err");
        }
      });
      // New panel: the ID follows the name until the user types their own.
      const wpId = this.shadowRoot.getElementById("wpId");
      const wpLabel = this.shadowRoot.getElementById("wpLabel");
      wpLabel?.addEventListener("input", () => {
        this._wallDraft.label = wpLabel.value;
        if (!this._wallEditingId && !this._wallIdTouched && wpId) wpId.value = slugId(wpLabel.value);
      });
      wpId?.addEventListener("input", () => {
        this._wallIdTouched = Boolean(wpId.value);
      });
    }
  }
}

const versionTag = `nook-panel-${PANEL_VERSION.replaceAll(".", "_")}`;
if (!customElements.get(versionTag)) {
  customElements.define(versionTag, NookPanel);
}
// Plain alias. A class can only be registered once per page, so it needs its own subclass
// (re-using NookPanel threw "this constructor has already been used").
if (!customElements.get("nook-panel")) {
  customElements.define("nook-panel", class extends NookPanel {});
}
