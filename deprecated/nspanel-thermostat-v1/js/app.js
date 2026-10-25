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
  currentTemp: document.getElementById("currentTemp"),
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
  windowBanner: document.getElementById("windowBanner"),
  statusRow: document.getElementById("statusRow"),
  summerPill: document.getElementById("summerPill"),
  screensaver: document.getElementById("screensaver"),
  pinOverlay: document.getElementById("pinOverlay"),
  pinDisplay: document.getElementById("pinDisplay"),
  pinPad: document.getElementById("pinPad"),
  pinError: document.getElementById("pinError"),
};

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

function getDisplayLabel() {
  return activeLabel;
}

function formatTemp(value, suffix = "°") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(1).replace(/\.0$/, "")}${suffix}`;
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
  return state.attributes.target_temp_high ?? state.attributes.temperature ?? null;
}

function getCurrentTemperature(state) {
  if (!state) return null;
  return state.attributes.current_temperature ?? null;
}

function getHvacAction(state) {
  if (!state) return "unknown";
  return state.attributes.hvac_action || state.state || "unknown";
}

function applyTheme(state) {
  const action = getHvacAction(state);
  const preset = state?.attributes?.preset_mode;
  let background = "var(--bg-idle)";

  if (preset === "eco") background = "var(--bg-eco)";
  else if (preset === "boost") background = "var(--bg-boost)";
  else if (action === "heating") background = "var(--bg-heating)";
  else if (action === "cooling") background = "var(--bg-cooling)";

  document.body.style.background = background;

  const labels = [];
  if (preset === "eco") labels.push("Eco");
  if (preset === "boost") labels.push("Boost");
  labels.push(action.replace("_", " "));
  ui.actionPill.textContent = labels.filter(Boolean).join(" · ");
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

  ui.windowBanner.classList.toggle("hidden", !windowOpen);
  ui.summerPill.classList.toggle("hidden", !summerMode);
  ui.statusRow.classList.toggle("hidden", !summerMode);
}

function renderActiveClimate() {
  const state = getActiveState();
  const current = getCurrentTemperature(state);
  const target = getTargetTemperature(state);
  const etaMins =
    state?.attributes?.time_to_temp_minutes ?? config.time_to_temp_minutes ?? null;
  let etaText = "";
  if (etaMins != null && Number.isFinite(Number(etaMins))) {
    const m = Math.round(Number(etaMins));
    etaText =
      m < 60
        ? ` · ~${m} min`
        : ` · ~${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ""}`;
  }

  ui.heroLabel.textContent = getDisplayLabel();
  ui.currentTemp.textContent = formatTemp(current, "");
  ui.targetTemp.textContent = formatTemp(target, "");
  ui.heroSubtitle.textContent = `Target ${formatTemp(target)} · ${state?.state ?? "unknown"}${etaText}`;

  applyTheme(state);
  updateModeButtons(state);
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
  const outside = client?.getState(config.sensors.outsideTemp);
  const humidity = client?.getState(config.sensors.insideHumidity);

  ui.insideTemp.textContent = formatSensor(inside?.state, "°");
  ui.outsideTemp.textContent = formatSensor(outside?.state, "°");
  ui.insideHumidity.textContent = formatSensor(humidity?.state, "%");
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
  ui.app.classList.toggle("room-view", inRoom);
  renderWeather();
}

function goToPrimaryView() {
  activeEntity = config.primary.entity;
  activeLabel = config.primary.name;
  activeStep = config.primary.step ?? 0.5;
  updateRoomNavigation();
  renderActiveClimate();
  renderRooms();
}

function renderRooms() {
  ui.roomStrip.innerHTML = "";

  for (const room of config.rooms) {
    const state = getClimateState(room.entity);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "room-chip";
    if (room.entity === activeEntity) chip.classList.add("active");

    const current = getCurrentTemperature(state);
    const target = getTargetTemperature(state);
    const action = getHvacAction(state);

    chip.innerHTML = `
      <div class="name">${room.name}</div>
      <div class="temp">${formatTemp(target ?? current)}</div>
      <div class="state">${action}</div>
    `;

    chip.addEventListener("click", () => {
      if (room.entity === activeEntity) {
        goToPrimaryView();
        return;
      }

      activeEntity = room.entity;
      activeLabel = room.name;
      activeStep = 0.5;
      updateRoomNavigation();
      renderActiveClimate();
      renderRooms();
    });

    ui.roomStrip.appendChild(chip);
  }
}

function setConnectionState(connected) {
  ui.connectionDot.classList.toggle("offline", !connected);
  ui.connectionLabel.textContent = connected
    ? embeddedMode
      ? "HA Companion"
      : "Connected"
    : "Offline";
}

function showApp() {
  ui.errorOverlay.classList.add("hidden");
  ui.deviceOverlay?.classList.add("hidden");
  ui.app.hidden = false;
}

function showError(message) {
  ui.errorMessage.textContent = message;
  ui.errorOverlay.classList.remove("hidden");
  ui.deviceOverlay?.classList.add("hidden");
  ui.app.hidden = true;
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
  } catch {
    // Keep current config if refresh fails.
  }
}

async function showDevicePicker() {
  ui.app.hidden = true;
  ui.errorOverlay.classList.add("hidden");
  ui.deviceOverlay.classList.remove("hidden");

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
  await ensureUnlocked(async () => {
    const state = getActiveState();
    const currentTarget = getTargetTemperature(state);
    if (currentTarget === null) return;

    const next = Number((currentTarget + delta).toFixed(1));
    ui.targetTemp.textContent = formatTemp(next, "");
    await client.setTemperature(activeEntity, next);
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
      client.connect();
    }

    setTimeout(() => refreshConfigFromCentral(), 800);
    configPollTimer = setInterval(() => refreshConfigFromCentral(), 60000);

    showApp();
    updateRoomNavigation();
    goToPrimaryView();
    renderSensors();

    screenSaver?.destroy();
    displayPower?.destroy();

    const idleMs = config.display?.idleMs ?? config.screensaverIdleMs ?? 30000;

    screenSaver = new ScreenSaver({
      overlay: ui.screensaver,
      idleMs,
      useHardwareSleep: Boolean(config.display?.panelEntity),
      onShow: () => {
        panelUnlocked = false;
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

for (const button of ui.modeButtons) {
  button.addEventListener("click", async () => {
    await ensureUnlocked(async () => {
      if (button.dataset.preset === "eco") {
        await client.setPresetMode(activeEntity, "eco");
        return;
      }

      if (button.dataset.preset === "boost") {
        const state = getActiveState();
        const nextPreset = state?.attributes?.preset_mode === "boost" ? "none" : "boost";
        await client.setPresetMode(activeEntity, nextPreset);
        return;
      }

      if (button.dataset.mode) {
        const preset = getActiveState()?.attributes?.preset_mode;
        if (preset && preset !== "none") {
          await client.setPresetMode(activeEntity, "none");
        }
        await client.setHvacMode(activeEntity, button.dataset.mode);
      }
    });
  });
}

connect();
