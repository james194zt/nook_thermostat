/** Central multi-device registry for NSPanel thermostat configs. */

export const DEVICE_ID_KEY = "nspanel-thermostat-device-id";
export const REGISTRY_USER_DATA_KEY = "nspanel_thermostat_devices";
export const REGISTRY_CACHE_KEY = "nspanel-thermostat-registry-cache";
export const REGISTRY_VERSION = 1;

export function slugifyDeviceId(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

export function emptyRegistry(shared = {}) {
  return {
    version: REGISTRY_VERSION,
    updatedAt: new Date().toISOString(),
    shared: { ...shared },
    devices: {},
  };
}

export function normalizeRegistry(raw) {
  const base = emptyRegistry();
  if (!raw || typeof raw !== "object") return base;

  const devices = {};
  for (const [id, entry] of Object.entries(raw.devices || {})) {
    const slug = slugifyDeviceId(id);
    if (!slug || !entry || typeof entry !== "object") continue;
    devices[slug] = {
      label: entry.label || slug,
      ...entry,
      label: entry.label || slug,
    };
  }

  return {
    version: Number(raw.version) || REGISTRY_VERSION,
    updatedAt: raw.updatedAt || base.updatedAt,
    shared: raw.shared && typeof raw.shared === "object" ? { ...raw.shared } : {},
    devices,
  };
}

export function listDevices(registry) {
  return Object.entries(registry?.devices || {})
    .map(([id, entry]) => ({
      id,
      label: entry.label || id,
      updatedAt: entry.updatedAt || registry.updatedAt || null,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function getDeviceEntry(registry, deviceId) {
  const id = slugifyDeviceId(deviceId);
  if (!id) return null;
  return registry?.devices?.[id] ?? null;
}

export function upsertDevice(registry, deviceId, entry) {
  const id = slugifyDeviceId(deviceId);
  if (!id) throw new Error("Device ID is required");
  const next = normalizeRegistry(registry);
  next.devices[id] = {
    ...entry,
    label: entry.label || id,
    updatedAt: new Date().toISOString(),
  };
  next.updatedAt = new Date().toISOString();
  return next;
}

export function deleteDevice(registry, deviceId) {
  const id = slugifyDeviceId(deviceId);
  const next = normalizeRegistry(registry);
  delete next.devices[id];
  next.updatedAt = new Date().toISOString();
  return next;
}

export function getStoredDeviceId() {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("device");
    if (fromUrl) {
      const slug = slugifyDeviceId(fromUrl);
      if (slug) return slug;
    }
    return slugifyDeviceId(localStorage.getItem(DEVICE_ID_KEY) || "") || "";
  } catch {
    return "";
  }
}

export function setStoredDeviceId(deviceId) {
  const slug = slugifyDeviceId(deviceId);
  if (!slug) {
    localStorage.removeItem(DEVICE_ID_KEY);
    return "";
  }
  localStorage.setItem(DEVICE_ID_KEY, slug);
  return slug;
}

export function cacheRegistry(registry) {
  localStorage.setItem(REGISTRY_CACHE_KEY, JSON.stringify(normalizeRegistry(registry)));
}

export function readCachedRegistry() {
  try {
    return normalizeRegistry(JSON.parse(localStorage.getItem(REGISTRY_CACHE_KEY) || "null"));
  } catch {
    return emptyRegistry();
  }
}

export async function fetchDevicesJson(version = REGISTRY_VERSION) {
  try {
    const response = await fetch(`devices.json?v=${version}&t=${Date.now()}`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    return normalizeRegistry(await response.json());
  } catch {
    return null;
  }
}

export async function loadRegistryFromHass(client) {
  if (!client?.getUserData) return null;
  try {
    const value = await client.getUserData(REGISTRY_USER_DATA_KEY);
    if (!value) return null;
    return normalizeRegistry(value);
  } catch {
    return null;
  }
}

export async function saveRegistryToHass(client, registry) {
  if (!client?.setUserData) {
    throw new Error("Home Assistant connection required to save centrally");
  }
  const normalized = normalizeRegistry(registry);
  normalized.updatedAt = new Date().toISOString();
  await client.setUserData(REGISTRY_USER_DATA_KEY, normalized);
  cacheRegistry(normalized);
  return normalized;
}

/**
 * Resolve effective config for a device.
 * Precedence: defaults < devices.json/shared < device entry < local panel overrides (token etc.)
 */
export function configFromRegistry(registry, deviceId, defaults, localOverrides = {}) {
  const shared = registry?.shared || {};
  const device = getDeviceEntry(registry, deviceId) || {};
  const { label, updatedAt, ...deviceConfig } = device;

  return {
    ...defaults,
    ...shared,
    ...deviceConfig,
    ...localOverrides,
    primary: {
      ...defaults.primary,
      ...shared.primary,
      ...deviceConfig.primary,
      ...localOverrides.primary,
    },
    sensors: {
      ...defaults.sensors,
      ...shared.sensors,
      ...deviceConfig.sensors,
      ...localOverrides.sensors,
    },
    display: {
      ...defaults.display,
      ...shared.display,
      ...deviceConfig.display,
      ...localOverrides.display,
    },
    rooms: localOverrides.rooms ?? deviceConfig.rooms ?? shared.rooms ?? defaults.rooms,
    deviceId: slugifyDeviceId(deviceId) || "",
    deviceLabel: label || slugifyDeviceId(deviceId) || "",
  };
}

export function deviceEntryFromConfig(config, label) {
  return {
    label: label || config.deviceLabel || config.deviceId || "Panel",
    primary: { ...config.primary },
    rooms: [...(config.rooms || [])],
    sensors: { ...config.sensors },
    display: { ...config.display },
    screensaverIdleMs: config.screensaverIdleMs,
    // haUrl stays in shared; token never stored in registry files
  };
}

export function downloadRegistryJson(registry, filename = "devices.json") {
  const blob = new Blob([JSON.stringify(normalizeRegistry(registry), null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
