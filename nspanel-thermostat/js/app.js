import { HomeAssistantClient } from "./ha-client.js";
import { EmbeddedHomeAssistantClient } from "./ha-embedded.js";
import { ScreenSaver } from "./screensaver.js";
import { DisplayPower } from "./display-power.js";
import {
  loadConfig,
  loadRegistry,
  isConfiguredForStandalone,
  isEmbeddedInHomeAssistant,
  setStoredDeviceId,
  getStoredDeviceId,
} from "./config.js";
import { listDevices, slugifyDeviceId } from "./device-registry.js";
import { readWeatherSnapshot } from "./weather.js";
import { UsagePage } from "./usage.js";
import { RoomSettings } from "./room-settings.js";

const ui = {
  app: document.getElementById("app"),
  errorOverlay: document.getElementById("errorOverlay"),
  errorMessage: document.getElementById("errorMessage"),
  retrySetup: document.getElementById("retrySetup"),
  deviceOverlay: document.getElementById("deviceOverlay"),
  devicePickList: document.getElementById("devicePickList"),
  customDeviceId: document.getElementById("customDeviceId"),
  saveDeviceId: document.getElementById("saveDeviceId"),
  openSetupFromPicker: document.getElementById("openSetupFromPicker"),
  connectionDot: document.getElementById("connectionDot"),
  connectionLabel: document.getElementById("connectionLabel"),
  actionPill: document.getElementById("actionPill"),
  weatherBlock: document.getElementById("weatherBlock"),
  weatherIcon: document.getElementById("weatherIcon"),
  weatherTemp: document.getElementById("weatherTemp"),
  weatherLabel: document.getElementById("weatherLabel"),
  sunriseTime: document.getElementById("sunriseTime"),
  sunsetTime: document.getElementById("sunsetTime"),
  heroLabel: document.getElementById("heroLabel"),
  currentTempInt: document.getElementById("currentTempInt"),
  currentTempDec: document.getElementById("currentTempDec"),
  heroSubtitle: document.getElementById("heroSubtitle"),
  targetTemp: document.getElementById("targetTemp"),
  tempDown: document.getElementById("tempDown"),
  tempUp: document.getElementById("tempUp"),
  insideTemp: document.getElementById("insideTemp"),
  outsideTemp: document.getElementById("outsideTemp"),
  insideHumidity: document.getElementById("insideHumidity"),
  roomStrip: document.getElementById("roomStrip"),
  backToHome: document.getElementById("backToHome"),
  modeButtons: [...document.querySelectorAll(".mode-btn")],
  modeDrawer: document.getElementById("modeDrawer"),
  modeFace: document.getElementById("modeFace"),
  modeIcon: document.getElementById("modeIcon"),
  ringLeaf: document.getElementById("ringLeaf"),
  dialBox: document.getElementById("dialBox"),
  thermoRing: document.getElementById("thermoRing"),
  dialFill: document.getElementById("dialFill"),
  dialHit: document.getElementById("dialHit"),
  dialKnob: document.getElementById("dialKnob"),
  nowDot: document.getElementById("nowDot"),
  dialG0: document.getElementById("dialG0"),
  dialG1: document.getElementById("dialG1"),
  dialCaption: document.getElementById("dialCaption"),
  topStatus: document.getElementById("topStatus"),
  notices: document.querySelector(".notices"),
  currentTemp: document.getElementById("currentTemp"),
  zonePill: document.getElementById("zonePill"),
  windowBanner: document.getElementById("windowBanner"),
  statusRow: document.getElementById("statusRow"),
  summerPill: document.getElementById("summerPill"),
  screensaver: document.getElementById("screensaver"),
  pinOverlay: document.getElementById("pinOverlay"),
  pinDisplay: document.getElementById("pinDisplay"),
  pinPad: document.getElementById("pinPad"),
  pinError: document.getElementById("pinError"),
  roomSettingsBtn: document.getElementById("roomSettingsBtn"),
};

// Swipe right-to-left from the dial for the last 24 hours. Not from the dial's arc (that drag sets
// the temperature) or a room strip that scrolls sideways, nor through an overlay.
const usage = new UsagePage({
  dialPage: ui.app,
  getClient: () => client,
  swipeAllowed: (ev) => {
    const target = ev.target instanceof Element ? ev.target : null;
    if (!target) return false;
    if (target.closest("#dialHit, .room-strip--many, .overlay, .screensaver, .room-settings, .top-cog")) return false;
    return !document.querySelector(".overlay:not(.hidden)") && !roomSettings.isOpen;
  },
});
const roomSettings = new RoomSettings({ getClient: () => client });
let config = await loadConfig();
let client = null;
let screenSaver = null;
let displayPower = null;
let activeEntity = config.primary.entity;
let activeLabel = config.primary.name;
let activeStep = config.primary.step ?? 0.5;
let embeddedMode = false;
let panelUnlocked = false;
let pinBuffer = "";
let pendingUnlockAction = null;
let configPollTimer = null;
/** Optimistic setpoint while HA catches up (instant +/- feedback). */
let optimisticTarget = null;
let tempSendTimer = null;
let tempSendSeq = 0;
/** Wait for a pause in +/- taps before writing to Home Assistant. */
const TEMP_SEND_IDLE_MS = 2500;
/** Optimistic HVAC mode / preset while HA catches up. */
let optimisticMode = null;

function getDisplayLabel() {
  return activeLabel;
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function formatTemp(value, suffix = "°") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(1).replace(/\.0$/, "")}${suffix}`;
}

function setCurrentTempDisplay(value) {
  const empty = value === null || value === undefined || Number.isNaN(Number(value));
  ui.currentTemp?.classList.toggle("is-empty", empty);
  ui.currentTemp?.classList.remove("is-off");
  if (empty) {
    if (ui.currentTempInt) ui.currentTempInt.textContent = "–";
    if (ui.currentTempDec) ui.currentTempDec.textContent = "";
    return;
  }
  const n = Number(value);
  const fixed = n.toFixed(1);
  const [intPart, decPart] = fixed.split(".");
  if (ui.currentTempInt) ui.currentTempInt.textContent = intPart;
  if (ui.currentTempDec) {
    ui.currentTempDec.textContent = decPart === "0" ? "" : `.${decPart}`;
  }
}

function updateCentreControls(state, target = getEffectiveTarget(state)) {
  const off = state?.state === "off";
  ui.tempDown?.classList.toggle("hidden", off);
  ui.tempUp?.classList.toggle("hidden", off);
  ui.currentTemp?.classList.toggle("is-off", off);
  if (off) {
    ui.currentTemp?.classList.remove("is-empty");
    if (ui.currentTempInt) ui.currentTempInt.textContent = "OFF";
    if (ui.currentTempDec) ui.currentTempDec.textContent = "";
    return;
  }
  setCurrentTempDisplay(target);
}

// One icon set for modes, matching the Nook dashboard card (flame / power / leaf).
const MODE_ICONS = {
  heat: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2c.5 3.2-1.6 5-3.2 6.9C7.4 10.6 6 12.4 6 15a6 6 0 0 0 12 0c0-2.6-1.3-4.6-2.6-6.1-.3 1.6-1.1 2.7-2.3 3.2.6-3.7-.3-7.6-1.1-10.1z"/></svg>`,
  off: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" d="M12 3v8M6.4 6.6a8 8 0 1 0 11.2 0"/></svg>`,
  eco: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6.6 17.4C4.6 9.9 10.6 4.3 20 4z"/><path fill="currentColor" opacity=".68" d="M20 4c.3 9.4-5.4 15.4-13.4 13.4z"/><path fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" d="M3.6 20.4 7.4 16.6"/></svg>`,
  boost: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M13.5 2 5 13.5h6L10 22l9-12h-6.2z"/></svg>`,
  away: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M4 10.5 12 4l8 6.5V20h-5.5v-5h-5v5H4z"/></svg>`,
};
const MODE_NAMES = { heat: "Heat", off: "Off", eco: "Eco", boost: "Boost", away: "Away" };

function modeKey(state) {
  const preset = state?.attributes?.preset_mode;
  if (state?.state === "off") return "off";
  if (preset === "eco" || preset === "boost" || preset === "away") return preset;
  return "heat";
}

function modeGlyph(state) {
  const key = modeKey(state);
  return `${MODE_ICONS[key]}<span class="mode-word">${MODE_NAMES[key]}</span>`;
}

function formatSensor(value, suffix = "") {
  if (value === null || value === undefined || value === "unavailable" || value === "unknown") {
    return "--";
  }
  const numeric = Number(value);
  if (!Number.isNaN(numeric)) {
    return `${numeric.toFixed(1).replace(/\.0$/, "")}${suffix}`;
  }
  return `${value}${suffix}`;
}

function getOutsideTempDisplay() {
  const sensorId = config.sensors?.outsideTemp?.trim();
  if (sensorId) {
    const formatted = formatSensor(client?.getState(sensorId)?.state, "°");
    if (formatted !== "--") return formatted;
  }

  // Fall back to weather entity outdoor temp when panel sensor is missing/unavailable
  const weatherId = resolveWeatherEntityId();
  if (weatherId) {
    const weather = client?.getState(weatherId);
    const temp = weather?.attributes?.temperature;
    const formatted = formatSensor(temp, "°");
    if (formatted !== "--") return formatted;
  }

  return "--";
}

function formatHumidity(value) {
  const formatted = formatSensor(value, "%");
  if (formatted === "--") return "--";
  return formatted.includes("%") ? formatted : `${formatted}%`;
}

function getHumidityDisplay() {
  const sensorId = config.sensors?.insideHumidity?.trim();
  if (sensorId) {
    const formatted = formatHumidity(client?.getState(sensorId)?.state);
    if (formatted !== "--") return formatted;
  }

  // Climate entities often expose current_humidity
  const climate = getActiveState() || getPrimaryState();
  const fromClimate = climate?.attributes?.current_humidity;
  if (fromClimate != null && fromClimate !== "") {
    const formatted = formatHumidity(fromClimate);
    if (formatted !== "--") return formatted;
  }

  // Weather entity humidity
  const weatherId = resolveWeatherEntityId();
  if (weatherId) {
    const formatted = formatHumidity(client?.getState(weatherId)?.attributes?.humidity);
    if (formatted !== "--") return formatted;
  }

  // Auto-discover a humidity sensor (prefer common home ids)
  const ids = client?.listEntityIds?.() ?? [];
  const preferred = [
    "sensor.home_humidity",
    "sensor.indoor_humidity",
    "sensor.humidity",
    ...ids.filter((id) => id.includes("humidity")),
  ];
  const seen = new Set();
  for (const id of preferred) {
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const state = client?.getState(id);
    if (!state) continue;
    if (
      state.attributes?.device_class === "humidity" ||
      id.includes("humidity") ||
      state.attributes?.unit_of_measurement === "%"
    ) {
      const formatted = formatHumidity(state.state);
      if (formatted !== "--") return formatted;
    }
  }

  for (const id of ids) {
    if (seen.has(id) || !id.startsWith("sensor.")) continue;
    const state = client.getState(id);
    if (state?.attributes?.device_class !== "humidity") continue;
    const formatted = formatHumidity(state.state);
    if (formatted !== "--") return formatted;
  }

  return "--";
}

function getClimateState(entityId) {
  return client?.getState(entityId);
}

function getPrimaryState() {
  return getClimateState(config.primary.entity);
}

function getActiveState() {
  return getClimateState(activeEntity);
}

function getTargetTemperature(state) {
  if (!state) return null;
  const value = state.attributes.target_temp_high ?? state.attributes.temperature ?? null;
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Number(value);
}

function getEffectiveTarget(state = getActiveState()) {
  if (optimisticTarget != null) return optimisticTarget;
  return getTargetTemperature(state);
}

function clearOptimisticTarget() {
  optimisticTarget = null;
  clearTimeout(tempSendTimer);
  tempSendTimer = null;
  tempSendSeq += 1;
}

function clearOptimisticMode() {
  optimisticMode = null;
}

function getEffectiveClimateState(state = getActiveState()) {
  if (!state || !optimisticMode) return state;
  return {
    ...state,
    state: optimisticMode.mode ?? state.state,
    attributes: {
      ...state.attributes,
      preset_mode: optimisticMode.preset ?? state.attributes?.preset_mode,
    },
  };
}

function syncOptimisticFromHa(state) {
  const ha = getTargetTemperature(state);
  if (optimisticTarget != null && ha != null && Math.abs(ha - optimisticTarget) < 0.05) {
    optimisticTarget = null;
  }
}

function syncOptimisticModeFromHa(state) {
  if (!optimisticMode || !state) return;
  const haMode = state.state;
  const haPreset = state.attributes?.preset_mode || "none";
  const wantMode = optimisticMode.mode;
  const wantPreset = optimisticMode.preset || "none";
  const modeOk = wantMode == null || haMode === wantMode;
  const presetOk = haPreset === wantPreset || (wantPreset === "none" && (!haPreset || haPreset === "none"));
  if (modeOk && presetOk) optimisticMode = null;
}

function applyOptimisticMode(next) {
  optimisticMode = next;
  const view = getEffectiveClimateState(getActiveState());
  applyTheme(view);
  updateModeButtons(view);
  updateCentreControls(view, getEffectiveTarget());
}

function getCurrentTemperature(state) {
  const fromClimate = state?.attributes?.current_temperature;
  if (fromClimate != null && !Number.isNaN(Number(fromClimate))) {
    return Number(fromClimate);
  }

  // The house can fall back to its inside sensor; a room never borrows the
  // house's temperature (an offline TRV would otherwise show the hall's).
  const isHouse = !state || state.entity_id === config.primary.entity;
  const sensorId = isHouse ? config.sensors?.insideTemp?.trim() : "";
  if (sensorId) {
    const raw = client?.getState(sensorId)?.state;
    if (raw != null && raw !== "unavailable" && raw !== "unknown" && !Number.isNaN(Number(raw))) {
      return Number(raw);
    }
  }
  return null;
}

function getHvacAction(state) {
  if (!state) return "unknown";
  return state.attributes.hvac_action || state.state || "unknown";
}

/* —— Dial: a 270° arc like the Nook dashboard card (same path, same colours) —— */
// viewBox is x 0..200, y viewTop..viewTop+viewH (empty space above and below the arc cropped).
const DIAL = {
  cx: 100, cy: 100, r: 84, startDeg: 135, sweepDeg: 270, defaultMin: 5, defaultMax: 30, viewTop: 8, viewH: 166,
};
// [start, end] of the arc gradient per state.
const DIAL_COLOURS = {
  heating: ["#FFB74D", "#F4511E"],
  boost: ["#FFD54F", "#F4511E"],
  eco: ["#9CCC65", "#43A047"],
  off: ["#5f656b", "#8a9096"],
  idle: ["#FFD180", "#FF9800"],
};

// The centre text was tuned on a square screen, where the dial is 50.5vmin tall. Tall and
// landscape layouts give the dial far more room, so its text follows the dial (--d), not the screen.
const DIAL_SQUARE_VMIN = 50.5;

/** Fit the dial into its box at the arc's own aspect (a stretched box would break drag maths). */
function fitDial() {
  const box = ui.dialBox;
  const dial = ui.thermoRing;
  if (!box || !dial) return;
  const w = box.clientWidth;
  const h = box.clientHeight;
  if (!w || !h) return;
  const aspect = 200 / DIAL.viewH;
  const height = Math.min(h, w / aspect);
  dial.style.height = `${height.toFixed(1)}px`;
  dial.style.width = `${(height * aspect).toFixed(1)}px`;
  ui.app?.style.setProperty("--d", `${(height / DIAL_SQUARE_VMIN).toFixed(3)}px`);
}

if (ui.dialBox) {
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(fitDial).observe(ui.dialBox);
  }
  window.addEventListener("resize", fitDial);
  window.addEventListener("orientationchange", fitDial);
}

function getGaugeRange(state) {
  const min = Number(state?.attributes?.min_temp);
  const max = Number(state?.attributes?.max_temp);
  return {
    min: Number.isFinite(min) ? min : DIAL.defaultMin,
    max: Number.isFinite(max) && max > min ? max : DIAL.defaultMax,
  };
}

/** 0..1 along the arc for a temperature, or null. */
function dialPos(temp, min, max) {
  if (temp == null || !Number.isFinite(Number(temp))) return null;
  return Math.min(1, Math.max(0, (Number(temp) - min) / (max - min || 1)));
}

function placeOnArc(el, p) {
  if (!el) return;
  if (p == null) {
    el.style.display = "none";
    return;
  }
  const ang = ((DIAL.startDeg + DIAL.sweepDeg * p) * Math.PI) / 180;
  el.style.display = "";
  el.setAttribute("cx", (DIAL.cx + DIAL.r * Math.cos(ang)).toFixed(1));
  el.setAttribute("cy", (DIAL.cy + DIAL.r * Math.sin(ang)).toFixed(1));
}

function updateRingGauge(state, current, target) {
  const { min, max } = getGaugeRange(state);
  const off = state?.state === "off";
  const p = off ? null : dialPos(target, min, max);
  if (ui.dialFill) {
    const fill = (p ?? 0) * 100;
    ui.dialFill.setAttribute("stroke-dasharray", `${fill.toFixed(1)} 100`);
    ui.dialFill.style.display = fill > 0 ? "" : "none";
  }
  placeOnArc(ui.dialKnob, p);
  placeOnArc(ui.nowDot, dialPos(current, min, max));
  ui.currentTemp?.classList.toggle("pending", optimisticTarget != null);
}

/** Temperature under a pointer on the dial (snapped to the step), or null in the gap. */
function tempFromPointer(ev) {
  const rect = ui.thermoRing.getBoundingClientRect();
  const x = ((ev.clientX - rect.left) / rect.width) * 200 - DIAL.cx;
  const y = ((ev.clientY - rect.top) / rect.height) * DIAL.viewH + DIAL.viewTop - DIAL.cy;
  let deg = (Math.atan2(y, x) * 180) / Math.PI; // 0 = 3 o'clock, clockwise
  let along = (deg - DIAL.startDeg + 360) % 360;
  if (along > DIAL.sweepDeg) {
    // In the bottom gap: snap to whichever end is nearer.
    along = along - DIAL.sweepDeg < (360 - DIAL.sweepDeg) / 2 ? DIAL.sweepDeg : 0;
  }
  const state = getActiveState();
  const { min, max } = getGaugeRange(state);
  const raw = min + (along / DIAL.sweepDeg) * (max - min);
  const step = activeStep || 0.5;
  return Math.min(max, Math.max(min, Math.round(raw / step) * step));
}

function applyTheme(state) {
  const action = getHvacAction(state);
  const preset = state?.attributes?.preset_mode;
  const mode = state?.state;
  const current = getCurrentTemperature(state);
  const target = getEffectiveTarget(state);
  const needsHeat =
    current != null &&
    target != null &&
    target > current + 0.05 &&
    mode !== "off";

  // Heating = what Nook reports (the boiler really is on for this zone); a
  // fresh tap upwards shows it straight away, before HA catches up.
  const heating = action === "heating" || (optimisticTarget != null && needsHeat);

  let ringState = "idle";
  if (mode === "off") ringState = "off";
  else if (preset === "eco") ringState = "eco";
  else if (preset === "boost") ringState = heating ? "boost" : "idle";
  else if (heating) ringState = "heating";
  else ringState = "idle";

  ui.thermoRing?.setAttribute("data-state", ringState);
  if (ui.app) ui.app.dataset.state = ringState;
  const [c0, c1] = DIAL_COLOURS[ringState] || DIAL_COLOURS.idle;
  ui.dialG0?.setAttribute("stop-color", c0);
  ui.dialG1?.setAttribute("stop-color", c1);
  // Boiler only kept on for its minimum run time: it isn't heating to the target.
  const finishing = Boolean(boilerHoldUntil(state)) && heating && !state?.attributes?.boiler_demand;
  if (ui.dialCaption) {
    ui.dialCaption.textContent =
      mode === "off"
        ? ""
        : state?.attributes?.preheating
          ? "Preheating to"
          : heating && !finishing
            ? "Heating to"
            : preset === "eco"
              ? "Eco"
              : "Set to";
  }
  if (ui.topStatus) ui.topStatus.textContent = statusText(state, { heating, current, target });
  document.body.style.background = "";

  const labels = [];
  if (preset === "eco") labels.push("Eco");
  if (preset === "boost") labels.push("Boost");
  if (mode === "off") labels.push("Off");
  else if (!state || action === "unknown") labels.push("Idle overview");
  else labels.push(action === "idle" || action === "off" ? "Idle overview" : action.replace("_", " "));
  if (ui.actionPill) ui.actionPill.textContent = labels.filter(Boolean).join(" · ");

  if (ui.modeIcon) {
    ui.modeIcon.innerHTML = modeGlyph(state);
    ui.modeIcon.dataset.mode = modeKey(state);
  }
  ui.ringLeaf?.classList.toggle(
    "is-active",
    mode === "off" || preset === "eco" || preset === "away"
  );
}

/** House view only: the boiler is held on/off (minimum on/off time) until this clock time. */
function boilerHoldUntil(state) {
  const until = state?.attributes?.boiler_hold_until;
  if (!until || state?.state === "off" || !isPrimaryView()) return "";
  const d = new Date(until);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** One line under the name: what the heating is doing, in words. */
function statusText(state, { heating, current, target }) {
  const a = state?.attributes || {};
  const primary = getPrimaryState()?.attributes || {};
  if (!state) return "Connecting…";
  if (state.state === "unavailable") return "Unavailable";
  const trv = a.trv_entity ? client?.getState(a.trv_entity) : null;
  if (a.trv_entity && (!trv || ["unavailable", "unknown"].includes(trv.state))) {
    return "Radiator valve offline";
  }
  if (state.state === "off") return "Heating is off";
  const holdUntil = boilerHoldUntil(state);
  if (holdUntil) {
    return a.boiler_on ? `Boiler off at ${holdUntil}` : `Boiler on at ${holdUntil}`;
  }
  if (primary.summer_mode_state) return "Summer mode";
  if (a.window_open || primary.window_open) return "Window open — paused";
  if (a.preheating) return `Warming up for ${a.preheat_for || "the schedule"}`;
  if (heating) return isPrimaryView() ? "Warming the house" : "Warming the room";
  if (a.preset_mode === "away") return "Away";
  if (current != null && target != null && current >= target - 0.05) return "Up to temperature";
  return "Holding temperature";
}

function updateModeButtons(state) {
  const mode = state?.state;
  const preset = state?.attributes?.preset_mode;

  for (const button of ui.modeButtons) {
    const buttonMode = button.dataset.mode;
    const buttonPreset = button.dataset.preset;

    let active = false;
    if (buttonPreset) {
      active = preset === buttonPreset;
    } else if (buttonMode) {
      active = mode === buttonMode && preset !== "eco" && preset !== "boost";
    }

    button.classList.toggle("active", active);
  }
}

function renderBetterThermostatStatus() {
  const primaryState = getPrimaryState();
  const windowOpen = Boolean(primaryState?.attributes?.window_open);
  const summerMode = Boolean(primaryState?.attributes?.summer_mode_state);
  ui.windowBanner?.classList.toggle("hidden", !windowOpen);
  ui.summerPill?.classList.toggle("hidden", !summerMode);
  ui.notices?.classList.toggle("hidden", !windowOpen && !summerMode);
}

function renderActiveClimate() {
  const state = getActiveState();
  syncOptimisticFromHa(state);
  syncOptimisticModeFromHa(state);
  const viewState = getEffectiveClimateState(state);
  const current = getCurrentTemperature(state);
  const target = getEffectiveTarget(state);
  const etaMins =
    state?.attributes?.time_to_temp_minutes ?? config.time_to_temp_minutes ?? null;
  let etaText = "";
  if (etaMins != null && Number.isFinite(Number(etaMins))) {
    const m = Math.round(Number(etaMins));
    etaText =
      m < 60
        ? `~${m} min to go`
        : `~${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ""} to go`;
  }
  // Only while it's actually heating towards the target.
  if (getHvacAction(state) !== "heating" || viewState?.state === "off") etaText = "";

  if (ui.heroLabel) ui.heroLabel.textContent = getDisplayLabel();
  // Centre dial = setpoint (or OFF); bottom-left = live room temp
  updateCentreControls(viewState, target);
  if (ui.targetTemp) ui.targetTemp.textContent = formatTemp(current, "°");
  if (ui.heroSubtitle) ui.heroSubtitle.textContent = etaText;

  applyTheme(viewState);
  updateRingGauge(state, current, target);
  updateModeButtons(viewState);
  renderBetterThermostatStatus();
}

function lockRequired() {
  return Boolean(config.temperatureLock) && Boolean(config.pinConfigured !== false);
}

function updatePinDisplay() {
  if (!ui.pinDisplay) return;
  const shown = pinBuffer.padEnd(4, "•").slice(0, 4).split("").join(" ");
  ui.pinDisplay.textContent = shown || "• • • •";
}

function showPinOverlay(action) {
  pendingUnlockAction = action;
  pinBuffer = "";
  ui.pinError?.classList.add("hidden");
  updatePinDisplay();
  ui.pinOverlay?.classList.remove("hidden");
}

function hidePinOverlay() {
  ui.pinOverlay?.classList.add("hidden");
  pendingUnlockAction = null;
  pinBuffer = "";
}

/** Room settings change Nook itself: behind the PIN whenever one is set (not just with the dial lock). */
async function ensureSettingsUnlocked(action) {
  if (!config.pinConfigured || panelUnlocked) {
    await action();
    return;
  }
  showPinOverlay(action);
}

/** The Nook room behind the room view (the panel config says; the room entity too). */
function activeRoomId() {
  if (isPrimaryView()) return null;
  return (
    config.rooms?.find((room) => room.entity === activeEntity)?.id ||
    getActiveState()?.attributes?.room_id ||
    null
  );
}

async function ensureUnlocked(action) {
  if (!lockRequired() || panelUnlocked) {
    await action();
    return;
  }
  showPinOverlay(action);
}

async function submitPin() {
  if (!client?.request || pinBuffer.length !== 4) return;
  try {
    const result = await client.request("nook/verify_wall_pin", {
      pin: pinBuffer,
      panel_id: config.deviceId,
    });
    if (result?.ok) {
      panelUnlocked = true;
      const action = pendingUnlockAction;
      hidePinOverlay();
      if (action) await action();
      return;
    }
  } catch {
    // fall through
  }
  ui.pinError?.classList.remove("hidden");
  pinBuffer = "";
  updatePinDisplay();
}

function renderSensors() {
  const inside = client?.getState(config.sensors.insideTemp);

  if (ui.insideTemp) ui.insideTemp.textContent = formatSensor(inside?.state, "°");
  if (ui.outsideTemp) ui.outsideTemp.textContent = getOutsideTempDisplay();
  if (ui.insideHumidity) ui.insideHumidity.textContent = getHumidityDisplay();
  renderWeather();
}

function resolveWeatherEntityId() {
  const preferred = config.sensors.weather?.trim();
  if (preferred) {
    const state = client?.getState(preferred);
    if (state && state.state !== "unavailable" && state.state !== "unknown") {
      return preferred;
    }
  }

  const ids = client?.listEntityIds?.() ?? [];
  const match = ids.find((id) => {
    if (!id.startsWith("weather.")) return false;
    const state = client.getState(id);
    return state && state.state !== "unavailable" && state.state !== "unknown";
  });
  return match || preferred || "";
}

function renderWeather() {
  if (!ui.weatherBlock || !client) return;

  if (!isPrimaryView()) {
    ui.weatherBlock.hidden = true;
    return;
  }

  const sunId = config.sensors.sun || "sun.sun";
  const snapshot = readWeatherSnapshot(
    (entityId) => client.getState(entityId),
    () => client.listEntityIds?.() ?? [],
    config.sensors.weather,
    sunId
  );

  if (!snapshot.available && !snapshot.hasSun) {
    ui.weatherBlock.hidden = true;
    return;
  }

  ui.weatherBlock.hidden = false;

  if (snapshot.available) {
    if (ui.weatherIcon.getAttribute("src") !== snapshot.iconUrl) {
      ui.weatherIcon.src = snapshot.iconUrl;
    }
    ui.weatherTemp.textContent = snapshot.temperature;
    ui.weatherLabel.textContent = snapshot.label;
    ui.weatherIcon.hidden = false;
    ui.weatherTemp.hidden = false;
    ui.weatherLabel.hidden = false;
  } else {
    ui.weatherIcon.hidden = true;
    ui.weatherTemp.hidden = true;
    ui.weatherLabel.hidden = true;
  }

  ui.sunriseTime.textContent = snapshot.sunrise;
  ui.sunsetTime.textContent = snapshot.sunset;
}

function isPrimaryView() {
  return activeEntity === config.primary.entity;
}

function updateRoomNavigation() {
  const inRoom = !isPrimaryView();
  ui.backToHome.classList.toggle("hidden", !inRoom);
  if (ui.backToHome) {
    const homeName = config.primary?.name || "Heating";
    ui.backToHome.setAttribute("aria-label", `Back to ${homeName}`);
  }
  ui.app.classList.toggle("room-view", inRoom);
  // A room shown from a bare TRV (no Nook room) has no settings to open.
  ui.roomSettingsBtn?.classList.toggle("hidden", !activeRoomId());
  renderWeather();
}

function goToPrimaryView() {
  roomSettings.close();
  clearOptimisticTarget();
  clearOptimisticMode();
  activeEntity = config.primary.entity;
  activeLabel = config.primary.name;
  activeStep = config.primary.step ?? 0.5;
  updateRoomNavigation();
  renderActiveClimate();
  renderRooms();
}

function renderRooms() {
  ui.roomStrip.innerHTML = "";

  const rooms = config.rooms || [];
  if (!rooms.length) {
    ui.roomStrip.classList.add("hidden");
    return;
  }
  ui.roomStrip.classList.remove("hidden");
  ui.roomStrip.classList.toggle("room-strip--many", rooms.length > 4);

  for (const room of rooms) {
    const state = getClimateState(room.entity);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "room-chip";
    if (room.entity === activeEntity) chip.classList.add("active");

    // The room's own temperature (not the TRV's); never fall back to the house sensor here.
    const raw = state?.attributes?.current_temperature;
    const current = raw != null && Number.isFinite(Number(raw)) ? Number(raw) : null;
    const target = getTargetTemperature(state);
    const heat = state?.attributes?.hvac_action === "heating";
    const trvId = state?.attributes?.trv_entity;
    const trv = trvId ? client?.getState(trvId) : null;
    const offline =
      !state || state.state === "unavailable" || (trvId && (!trv || ["unavailable", "unknown"].includes(trv.state)));
    chip.classList.toggle("heat", heat && !offline);
    const name = escapeHtml(room.name);
    const setLine = offline
      ? `<span class="room-off">Offline</span>`
      : state.state === "off"
        ? "Off"
        : `${heat ? "Heating to" : "Set"} ${formatTemp(target)}`;

    chip.innerHTML = `
      <span class="room-top"><span class="room-name">${name}</span>${heat && !offline ? MODE_ICONS.heat : ""}</span>
      <span class="room-temp${current == null ? " unknown" : ""}">${formatTemp(current)}</span>
      <span class="room-set">${setLine}</span>
    `;

    chip.addEventListener("click", () => {
      if (room.entity === activeEntity) {
        goToPrimaryView();
        return;
      }

      activeEntity = room.entity;
      activeLabel = room.name;
      activeStep = 0.5;
      clearOptimisticTarget();
      clearOptimisticMode();
      updateRoomNavigation();
      renderActiveClimate();
      renderRooms();
    });

    ui.roomStrip.appendChild(chip);
  }
}

// A reconnect on wake takes a second or two and the last states are on screen
// meanwhile, so only say "Offline" when it lasts.
const OFFLINE_PILL_DELAY_MS = 4000;
let offlinePillTimer = null;

function setConnectionState(connected) {
  clearTimeout(offlinePillTimer);
  ui.connectionDot?.classList.toggle("online", connected);
  if (connected) {
    ui.connectionDot?.classList.remove("offline");
    // Straight away, not on the poll: picks up config changes made while asleep.
    if (!embeddedMode) refreshConfigFromCentral();
  } else {
    offlinePillTimer = setTimeout(() => ui.connectionDot?.classList.add("offline"), OFFLINE_PILL_DELAY_MS);
  }
  if (ui.connectionLabel) {
    ui.connectionLabel.textContent = connected
      ? embeddedMode
        ? "HA Companion"
        : "Connected"
      : "Offline";
  }
}

/* —— Clean start: the page stays blank (body.booting) until it can show the real
   thermostat — Nook's config plus the house state — so a reload (e.g. waking from
   screen-off) never flashes setup screens or an empty dial. —— */
const BOOT_STATES_KEY = "nook-wall-states-v1";
const BOOT_STATES_EVERY_MS = 10000;
let revealed = false;
let bootStatesSavedAt = 0;

function revealApp() {
  if (revealed) return;
  revealed = true;
  (window.__nookCssReady || Promise.resolve()).then(() =>
    requestAnimationFrame(() => document.body.classList.remove("booting"))
  );
}

// Never stay blank: if the data doesn't come, show what there is.
setTimeout(revealApp, 6000);

function readyToShow() {
  return Boolean(config.fromNook && getPrimaryState());
}

/** The last states this panel showed, so the first frame after a reload is complete. */
function readBootStates() {
  try {
    const saved = JSON.parse(localStorage.getItem(BOOT_STATES_KEY) || "null");
    return saved && saved.deviceId === getStoredDeviceId() ? saved.states || {} : {};
  } catch {
    return {};
  }
}

function saveBootStates() {
  if (!client || Date.now() - bootStatesSavedAt < BOOT_STATES_EVERY_MS) return;
  bootStatesSavedAt = Date.now();
  const ids = new Set(getWatchedEntities());
  for (const room of config.rooms || []) {
    const trv = client.getState(room.entity)?.attributes?.trv_entity;
    if (trv) ids.add(trv);
  }
  const states = {};
  for (const id of ids) {
    const state = client.getState(id);
    if (state) states[id] = state;
  }
  try {
    localStorage.setItem(BOOT_STATES_KEY, JSON.stringify({ deviceId: getStoredDeviceId(), states }));
  } catch {
    // Storage full/blocked: just no instant start next time.
  }
}

function showApp() {
  ui.errorOverlay.classList.add("hidden");
  ui.deviceOverlay?.classList.add("hidden");
  ui.app.hidden = false;
  fitDial(); // the box had no size while hidden (and old WebViews lack ResizeObserver)
}

function showError(message) {
  usage.resetToDial();
  ui.errorMessage.textContent = message;
  ui.errorOverlay.classList.remove("hidden");
  ui.deviceOverlay?.classList.add("hidden");
  ui.app.hidden = true;
  revealApp();
}

function openSetupPage() {
  window.location.href = "setup.html";
}

function applyConfig(nextConfig, { keepRoom = false } = {}) {
  config = nextConfig;
  if (!keepRoom || !config.rooms.some((room) => room.entity === activeEntity)) {
    activeEntity = config.primary.entity;
    activeLabel = config.primary.name;
    activeStep = config.primary.step ?? 0.5;
  }
  updateRoomNavigation();
  renderActiveClimate();
  renderSensors();
  renderRooms();

  const idleMs = config.display?.idleMs ?? config.screensaverIdleMs ?? 30000;
  if (screenSaver) screenSaver.idleMs = idleMs;
  if (displayPower) displayPower.config = config;
}

async function refreshConfigFromCentral() {
  if (!getStoredDeviceId()) return;
  try {
    const next = await loadConfig(client);
    const before = JSON.stringify({
      primary: config.primary,
      rooms: config.rooms,
      sensors: config.sensors,
      display: config.display,
    });
    const after = JSON.stringify({
      primary: next.primary,
      rooms: next.rooms,
      sensors: next.sensors,
      display: next.display,
    });
    if (before !== after) {
      applyConfig(next, { keepRoom: true });
    } else {
      config = next;
    }
    if (readyToShow()) revealApp();
  } catch {
    // Keep current config if refresh fails.
  }
}

async function showDevicePicker() {
  ui.app.hidden = true;
  ui.errorOverlay.classList.add("hidden");
  ui.deviceOverlay.classList.remove("hidden");
  revealApp();

  let devices = [];
  try {
    const result = await client?.request?.("nook/list_wall_panels");
    devices = (result?.wall_panels || []).map((p) => ({
      id: p.id,
      label: p.label || p.id,
    }));
  } catch {
    const registry = await loadRegistry(client);
    devices = listDevices(registry);
  }

  ui.devicePickList.innerHTML = "";

  for (const device of devices) {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `<strong>${device.label}</strong><span class="id">${device.id}</span>`;
    button.addEventListener("click", async () => {
      setStoredDeviceId(device.id);
      config = await loadConfig(client);
      applyConfig(config);
      showApp();
      connect();
    });
    ui.devicePickList.appendChild(button);
  }

  if (!devices.length) {
    ui.devicePickList.innerHTML =
      `<p style="margin:0;color:rgba(255,255,255,0.65);font-size:14px;line-height:1.4">No wall panels in Nook yet. Add them in Home Assistant → Nook → Wall panels, or open setup.html.</p>`;
  }
}

function getWatchedEntities() {
  const weatherId = resolveWeatherEntityId();
  return new Set([
    activeEntity,
    config.primary.entity,
    ...config.rooms.map((room) => room.entity),
    config.sensors.insideTemp,
    config.sensors.outsideTemp,
    config.sensors.insideHumidity,
    config.sensors.weather,
    config.sensors.sun || "sun.sun",
    weatherId,
  ].filter(Boolean));
}

function handleStateChange(entityId) {
  if (!revealed && readyToShow()) {
    renderActiveClimate();
    renderSensors();
    renderRooms();
    revealApp();
  }
  saveBootStates();
  const weatherRelated =
    entityId.startsWith("weather.") ||
    entityId.endsWith("_weather_condition") ||
    entityId === (config.sensors.sun || "sun.sun") ||
    entityId === config.sensors.weather;
  if (!weatherRelated && !getWatchedEntities().has(entityId)) return;
  renderActiveClimate();
  renderSensors();
  renderRooms();
}

async function adjustTemperature(delta) {
  await ensureUnlocked(() => {
    const state = getEffectiveClimateState(getActiveState());
    if (state?.state === "off") return;

    const base = getEffectiveTarget(state);
    if (base === null) return;

    const min = Number(state?.attributes?.min_temp);
    const max = Number(state?.attributes?.max_temp);
    const lo = Number.isFinite(min) ? min : 5;
    const hi = Number.isFinite(max) ? max : 30;
    showTarget(Math.min(hi, Math.max(lo, Number((base + delta).toFixed(1)))));
  });
}

/** Show a new target at once; send it to HA after a short pause (or not yet, mid-drag). */
function showTarget(next, { send = true } = {}) {
  const state = getEffectiveClimateState(getActiveState());
  optimisticTarget = next;
  updateCentreControls(state, next);
  const current = getCurrentTemperature(state);
  if (ui.targetTemp) ui.targetTemp.textContent = formatTemp(current, "°");
  updateRingGauge(state, current, next);
  applyTheme(getEffectiveClimateState(state));

  // Debounce HA write so rapid taps stay instant and only the final value is sent
  clearTimeout(tempSendTimer);
  const seq = ++tempSendSeq;
  if (!send) return;
  const entity = activeEntity;
  const value = next;
  tempSendTimer = setTimeout(() => {
    tempSendTimer = null;
    if (!client || seq !== tempSendSeq) return;
    client.setTemperature(entity, value).catch(() => {
      if (seq === tempSendSeq) {
        clearOptimisticTarget();
        renderActiveClimate();
      }
    });
  }, 280);
}

/* Drag the dial: follow the finger, send when it lifts. */
let dragging = false;
let dragValue = null;

function dialPointer(ev) {
  const value = tempFromPointer(ev);
  if (value == null || value === dragValue) return;
  dragValue = value;
  showTarget(value, { send: false });
}

ui.dialHit?.addEventListener("pointerdown", (ev) => {
  const state = getEffectiveClimateState(getActiveState());
  if (!state || state.state === "off") return;
  ev.preventDefault();
  ensureUnlocked(() => {
    dragging = true;
    dragValue = null;
    ui.thermoRing.classList.add("dragging");
    try {
      ui.dialHit.setPointerCapture(ev.pointerId);
    } catch {
      // Capture can fail if the pointer already lifted (e.g. after the PIN pad).
    }
    dialPointer(ev);
  });
});
ui.dialHit?.addEventListener("pointermove", (ev) => {
  if (dragging) dialPointer(ev);
});
for (const type of ["pointerup", "pointercancel"]) {
  ui.dialHit?.addEventListener(type, () => {
    if (!dragging) return;
    dragging = false;
    ui.thermoRing.classList.remove("dragging");
    if (dragValue != null) showTarget(dragValue);
  });
}

async function connect() {
  client?.disconnect();
  clearInterval(configPollTimer);
  embeddedMode = isEmbeddedInHomeAssistant();

  if (!getStoredDeviceId()) {
    await showDevicePicker();
    return;
  }

  if (!embeddedMode && !isConfiguredForStandalone(config)) {
    openSetupPage();
    return;
  }

  const callbacks = {
    onConnectionChange: setConnectionState,
    onStateChange: handleStateChange,
  };

  try {
    if (embeddedMode) {
      client = new EmbeddedHomeAssistantClient(callbacks);
      await client.connect();
    } else {
      client = new HomeAssistantClient({
        url: config.haUrl,
        token: config.accessToken,
        ...callbacks,
      });
      // Start from what the panel last showed; live states replace these in a moment.
      for (const [id, state] of Object.entries(readBootStates())) client.states.set(id, state);
      client.connect();
    }

    setTimeout(() => refreshConfigFromCentral(), 800);
    configPollTimer = setInterval(() => refreshConfigFromCentral(), 60000);

    showApp();
    updateRoomNavigation();
    goToPrimaryView();
    renderSensors();
    if (readyToShow()) revealApp();

    screenSaver?.destroy();
    displayPower?.destroy();
    screenSaver = null;
    displayPower = null;

    // The Nook panel's Wall panels preview: never blank the preview, and never
    // send the real panel's display to sleep from someone's browser.
    if (new URLSearchParams(window.location.search).get("preview") === "1") return;

    const idleMs = config.display?.idleMs ?? config.screensaverIdleMs ?? 30000;

    screenSaver = new ScreenSaver({
      overlay: ui.screensaver,
      idleMs,
      useHardwareSleep: Boolean(config.display?.panelEntity),
      onShow: () => {
        panelUnlocked = false;
        usage.resetToDial();
        roomSettings.close();
      },
    });

    displayPower = new DisplayPower({
      client,
      config,
      onInteraction: () => screenSaver.wake(),
      onVisualSleep: () => screenSaver.showOverlay(),
    });
  } catch (error) {
    showError(error.message);
  }
}

// Waking up (screen back on, page visible again, network back): make sure the HA
// connection is really live now, instead of trusting a socket that died while asleep.
function checkConnectionOnWake() {
  client?.checkAlive?.();
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    usage.resetToDial();
    roomSettings.close();
  } else checkConnectionOnWake();
});
window.addEventListener("online", checkConnectionOnWake);
// Fully's screenOn (display-power.js): the screen was off, so start from the dial.
window.__nookScreenOn = () => {
  usage.resetToDial();
  roomSettings.close();
  checkConnectionOnWake();
};

ui.retrySetup.addEventListener("click", openSetupPage);
ui.openSetupFromPicker?.addEventListener("click", openSetupPage);
ui.saveDeviceId?.addEventListener("click", async () => {
  const id = slugifyDeviceId(ui.customDeviceId.value);
  if (!id) return;
  setStoredDeviceId(id);
  config = await loadConfig(client);
  applyConfig(config);
  showApp();
  connect();
});
ui.tempDown.addEventListener("click", () => adjustTemperature(-activeStep));
ui.tempUp.addEventListener("click", () => adjustTemperature(activeStep));
ui.backToHome.addEventListener("click", goToPrimaryView);
ui.roomSettingsBtn?.addEventListener("click", () => {
  const roomId = activeRoomId();
  if (!roomId) return;
  ensureSettingsUnlocked(() => roomSettings.open(roomId, activeLabel));
});
ui.zonePill?.addEventListener("click", () => {
  if (!isPrimaryView()) goToPrimaryView();
});

ui.pinPad?.addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-digit]");
  if (!btn) return;
  const digit = btn.dataset.digit;
  ui.pinError?.classList.add("hidden");
  if (digit === "clear") {
    pinBuffer = "";
    updatePinDisplay();
    return;
  }
  if (digit === "ok") {
    await submitPin();
    return;
  }
  if (pinBuffer.length >= 4) return;
  pinBuffer += digit;
  updatePinDisplay();
  if (pinBuffer.length === 4) await submitPin();
});

// The modes are always on screen now (no drawer to close).
function closeModeDrawer() {}

for (const button of ui.modeButtons) {
  const key = button.dataset.preset || button.dataset.mode;
  if (MODE_ICONS[key]) button.insertAdjacentHTML("afterbegin", MODE_ICONS[key]);
  button.dataset.icon = key;
  button.addEventListener("click", async () => {
    await ensureUnlocked(async () => {
      const entity = activeEntity;

      if (button.dataset.preset === "eco") {
        // Eco toggles, like Boost: tap again to go back to the normal setting.
        const state = getActiveState();
        const ecoOn = state?.attributes?.preset_mode === "eco" || optimisticMode?.preset === "eco";
        const nextPreset = ecoOn ? "none" : "eco";
        applyOptimisticMode({ mode: "heat", preset: nextPreset });
        try {
          await client.setPresetMode(entity, nextPreset);
        } catch {
          clearOptimisticMode();
          renderActiveClimate();
        }
        return;
      }

      if (button.dataset.preset === "boost") {
        const state = getActiveState();
        const nextPreset = state?.attributes?.preset_mode === "boost" || optimisticMode?.preset === "boost"
          ? "none"
          : "boost";
        applyOptimisticMode({
          mode: nextPreset === "boost" ? (state?.state === "off" ? "heat" : state?.state || "heat") : state?.state || "heat",
          preset: nextPreset,
        });
        closeModeDrawer();
        try {
          await client.setPresetMode(entity, nextPreset);
        } catch {
          clearOptimisticMode();
          renderActiveClimate();
        }
        return;
      }

      if (button.dataset.mode) {
        const nextMode = button.dataset.mode;
        applyOptimisticMode({ mode: nextMode, preset: "none" });
        closeModeDrawer();
        try {
          const preset = getActiveState()?.attributes?.preset_mode;
          if (preset && preset !== "none") {
            await client.setPresetMode(entity, "none");
          }
          await client.setHvacMode(entity, nextMode);
        } catch {
          clearOptimisticMode();
          renderActiveClimate();
        }
      }
    });
  });
}

connect();
