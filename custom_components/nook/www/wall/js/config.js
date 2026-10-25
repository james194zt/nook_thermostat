import {
  cacheRegistry,
  configFromRegistry,
  fetchDevicesJson,
  getStoredDeviceId,
  loadRegistryFromHass,
  normalizeRegistry,
  readCachedRegistry,
  setStoredDeviceId,
  slugifyDeviceId,
} from "./device-registry.js";

export const STORAGE_KEY = "nspanel-thermostat-config-v3";
export const LEGACY_STORAGE_KEYS = [
  "nspanel-thermostat-config",
  "nspanel-thermostat-config-v2",
];
export const LOCAL_SECRETS_KEY = "nspanel-thermostat-local-secrets";
// The copy Nook ships is served by Home Assistant itself, so its own origin is the right default.
export const DEFAULT_HA_URL = /^https?:$/.test(window.location.protocol)
  ? window.location.origin
  : "http://homeassistant.local:8123";
export const CONFIG_VERSION = 11;

export const DEFAULT_CONFIG = {
  haUrl: DEFAULT_HA_URL,
  accessToken: "",
  primary: {
    entity: "climate.nook_home",
    name: "Heating",
    step: 0.5,
  },
  rooms: [],
  sensors: {
    insideTemp: "",
    insideHumidity: "",
    outsideTemp: "",
    weather: "weather.home",
    sun: "sun.sun",
  },
  display: {
    idleMs: 30000,
    panelEntity: "",
  },
  screensaverIdleMs: 30000,
  deviceId: "",
  deviceLabel: "",
  temperatureLock: false,
  pinConfigured: false,
  time_to_temp_minutes: null,
};

export function mergeConfig(base, override = {}) {
  return {
    ...base,
    ...override,
    primary: { ...base.primary, ...override.primary },
    sensors: { ...base.sensors, ...override.sensors },
    display: { ...base.display, ...override.display },
    rooms: override.rooms ?? base.rooms,
  };
}

export function sanitizeConfig(next) {
  const primary = { ...DEFAULT_CONFIG.primary, ...next.primary };

  if (
    primary.entity === "climate.nest_thermostat" ||
    primary.name?.toLowerCase() === "nest"
  ) {
    primary.entity = DEFAULT_CONFIG.primary.entity;
    primary.name = DEFAULT_CONFIG.primary.name;
  }

  const idleMs = Number(next.display?.idleMs ?? next.screensaverIdleMs ?? DEFAULT_CONFIG.display.idleMs);

  const sensors = { ...DEFAULT_CONFIG.sensors, ...next.sensors };
  if (sensors.insideHumidity === "sensor.bathroom_temperature_humidity") {
    sensors.insideHumidity = DEFAULT_CONFIG.sensors.insideHumidity;
  }
  if (sensors.outsideTemp === "sensor.garden_temperature") {
    sensors.outsideTemp = DEFAULT_CONFIG.sensors.outsideTemp;
  }

  return mergeConfig(next, {
    primary,
    sensors,
    display: {
      ...DEFAULT_CONFIG.display,
      ...next.display,
      idleMs: Number.isFinite(idleMs) ? idleMs : DEFAULT_CONFIG.display.idleMs,
    },
    screensaverIdleMs: Number.isFinite(idleMs) ? idleMs : DEFAULT_CONFIG.screensaverIdleMs,
    deviceId: slugifyDeviceId(next.deviceId || "") || "",
    deviceLabel: next.deviceLabel || "",
  });
}

export function clearLegacyStorage() {
  for (const key of LEGACY_STORAGE_KEYS) {
    localStorage.removeItem(key);
  }
}

/** Local-only secrets / emergency overrides (token, temporary tweaks). */
export function loadLocalSecrets() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_SECRETS_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

export function saveLocalSecrets(secrets) {
  localStorage.setItem(LOCAL_SECRETS_KEY, JSON.stringify(secrets || {}));
  return secrets;
}

export function loadSavedOverrides() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    return saved ?? {};
  } catch {
    return {};
  }
}

export function saveConfigToStorage(config) {
  const sanitized = sanitizeConfig(config);
  // Keep legacy local save for emergency offline edits; prefer central registry.
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitized));
  if (sanitized.deviceId) setStoredDeviceId(sanitized.deviceId);
  if (sanitized.accessToken || sanitized.haUrl) {
    saveLocalSecrets({
      haUrl: sanitized.haUrl,
      accessToken: sanitized.accessToken,
    });
  }
  return sanitized;
}

async function resolveRegistry(hassClient = null) {
  const fromHass = hassClient ? await loadRegistryFromHass(hassClient) : null;
  if (fromHass && Object.keys(fromHass.devices).length) {
    cacheRegistry(fromHass);
    return fromHass;
  }

  const fromFile = await fetchDevicesJson(CONFIG_VERSION);
  if (fromFile) {
    cacheRegistry(fromFile);
    return fromFile;
  }

  const cached = readCachedRegistry();
  if (Object.keys(cached.devices).length) return cached;

  return fromHass || fromFile || cached;
}

export async function loadRegistry(hassClient = null) {
  return normalizeRegistry(await resolveRegistry(hassClient));
}

const NOOK_CONFIG_CACHE_PREFIX = "nook-wall-nook-config:";

/** Last config Nook gave this panel, so a (re)load starts with the real setup. */
function readCachedNookConfig(deviceId) {
  if (!deviceId) return null;
  try {
    return JSON.parse(localStorage.getItem(NOOK_CONFIG_CACHE_PREFIX + deviceId) || "null");
  } catch {
    return null;
  }
}

/** This screen's size, so Nook can show which shape the panel really is. Not from
 *  Nook's own preview or a test page (those aren't the panel). */
function realScreen() {
  const params = new URLSearchParams(location.search);
  if (params.has("embedded") || params.has("preview") || window.top !== window) return {};
  return {
    screen: {
      width: Math.round(window.innerWidth),
      height: Math.round(window.innerHeight),
      scale: Number(window.devicePixelRatio || 1),
    },
  };
}

async function loadFromNook(hassClient, deviceId) {
  if (!deviceId) return null;
  if (!hassClient?.request) {
    // Not connected yet (page load): the last config Nook sent beats the stale
    // bundled devices.json/defaults, which point at a different thermostat.
    return readCachedNookConfig(deviceId);
  }
  try {
    const result = await hassClient.request("nook/get_wall_panel_config", {
      panel_id: deviceId,
      ...realScreen(),
    });
    const config = result?.config || null;
    if (config) {
      try {
        localStorage.setItem(NOOK_CONFIG_CACHE_PREFIX + deviceId, JSON.stringify(config));
      } catch {
        // Storage full/blocked: just no fast start next time.
      }
    }
    return config;
  } catch {
    return readCachedNookConfig(deviceId);
  }
}

async function loadBundledSensorDefaults() {
  const sensors = {};
  try {
    const response = await fetch(`config.json?v=${CONFIG_VERSION}`, { cache: "no-store" });
    if (response.ok) {
      const bundled = await response.json();
      Object.assign(sensors, bundled.sensors || {});
    }
  } catch {
    // optional
  }
  try {
    const registry = await resolveRegistry(null);
    const deviceId = getStoredDeviceId();
    const device = deviceId ? registry?.devices?.[deviceId] : null;
    const shared = registry?.shared?.sensors || {};
    Object.assign(sensors, shared, device?.sensors || {});
  } catch {
    // optional
  }
  return sensors;
}

function fillBlankSensors(target, fallback) {
  const sensors = { ...(target.sensors || {}) };
  for (const [key, value] of Object.entries(fallback || {})) {
    if (!String(sensors[key] || "").trim() && String(value || "").trim()) {
      sensors[key] = value;
    }
  }
  return { ...target, sensors };
}

export async function loadConfig(hassClient = null) {
  clearLegacyStorage();

  const deviceId = getStoredDeviceId();
  const secrets = loadLocalSecrets();
  const localOverrides = {
    ...secrets,
    deviceId,
  };

  const bundledSensors = await loadBundledSensorDefaults();

  // Prefer central Nook wall-panel config (source of truth).
  const fromNook = await loadFromNook(hassClient, deviceId);
  if (fromNook) {
    // Nook often omits humidity; fill blanks from local devices.json / config.json
    const merged = fillBlankSensors(
      mergeConfig(DEFAULT_CONFIG, mergeConfig(fromNook, localOverrides)),
      bundledSensors
    );
    return { ...sanitizeConfig(merged), fromNook: true };
  }

  // Fallback: legacy devices.json / HA user-data registry (pre-Nook).
  const registry = await resolveRegistry(hassClient);
  let bundled = {};
  try {
    const response = await fetch(`config.json?v=${CONFIG_VERSION}`, { cache: "no-store" });
    if (response.ok) bundled = await response.json();
  } catch {
    // optional legacy single-file config
  }

  const fromRegistry = deviceId
    ? configFromRegistry(registry, deviceId, DEFAULT_CONFIG, localOverrides)
    : mergeConfig(DEFAULT_CONFIG, localOverrides);

  return sanitizeConfig(
    fillBlankSensors(mergeConfig(DEFAULT_CONFIG, mergeConfig(bundled, fromRegistry)), bundledSensors)
  );
}

export function isConfiguredForStandalone(config) {
  return Boolean(config.accessToken?.trim() && config.haUrl?.trim());
}

export function isEmbeddedInHomeAssistant() {
  if (window.location.search.includes("embedded=1")) return true;
  if (window.location.pathname.startsWith("/local/")) {
    try {
      return window.parent !== window;
    } catch {
      return false;
    }
  }
  return false;
}

export { getStoredDeviceId, setStoredDeviceId, slugifyDeviceId };
