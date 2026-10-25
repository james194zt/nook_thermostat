/** Google Weather icons — same set as Fox Plant (icons/weather/v1). */

const ICON_VER = 3;
const ICON_BASE = "assets/weather/v1/dark";

const HA_CONDITION_LABELS = {
  "clear-night": "Clear",
  sunny: "Sunny",
  clear: "Clear",
  partlycloudy: "Partly cloudy",
  "partly-cloudy": "Partly cloudy",
  cloudy: "Cloudy",
  rainy: "Rain",
  pouring: "Heavy rain",
  snowy: "Snow",
  "snowy-rainy": "Sleet",
  fog: "Fog",
  hail: "Hail",
  windy: "Windy",
  "windy-variant": "Windy",
  lightning: "Thunderstorms",
  "lightning-rainy": "Storms",
  exceptional: "Severe",
  hurricane: "Hurricane",
};

function dayNight(dayFile, nightFile, isNight) {
  return isNight ? nightFile : dayFile;
}

function normalizeGoogleType(raw) {
  if (raw == null || raw === "") return "";
  return String(raw).trim().toUpperCase().replace(/-/g, "_");
}

function isNightFromSources(sunState, conditionAttrs) {
  if (typeof conditionAttrs?.is_daytime === "boolean") {
    return !conditionAttrs.is_daytime;
  }
  if (sunState?.state === "below_horizon") return true;
  if (sunState?.state === "above_horizon") return false;
  return false;
}

function iconFromGoogleType(type, isNight) {
  const token = normalizeGoogleType(type);
  if (!token || token === "TYPE_UNSPECIFIED") return null;
  if (token === "CLEAR" || token === "FAIR") {
    return dayNight("clear_day.svg", "clear_night.svg", isNight);
  }
  if (token === "MOSTLY_CLEAR") {
    return dayNight("clear_day.svg", "mostly_clear_night.svg", isNight);
  }
  if (token === "PARTLY_CLOUDY") {
    return dayNight("partly_cloudy_day.svg", "partly_cloudy_night.svg", isNight);
  }
  if (token === "MOSTLY_CLOUDY" || token === "OVERCAST") {
    return dayNight("mostly_cloudy_day.svg", "mostly_cloudy_night.svg", isNight);
  }
  if (token === "CLOUDY") return "cloudy.svg";
  if (token === "WINDY" || token === "WIND" || token === "GALE" || token === "BREEZY") {
    return "windy.svg";
  }
  if (token === "WIND_AND_RAIN") return "rain_showers.svg";
  if (
    token === "LIGHT_RAIN_SHOWERS" ||
    token === "CHANCE_OF_SHOWERS" ||
    token === "SCATTERED_SHOWERS"
  ) {
    return dayNight(
      "scattered_rain_showers_day.svg",
      "scattered_rain_showers_night.svg",
      isNight
    );
  }
  if (token === "RAIN_SHOWERS") return "rain_showers.svg";
  if (
    token === "HEAVY_RAIN_SHOWERS" ||
    token === "HEAVY_RAIN" ||
    token === "MODERATE_TO_HEAVY_RAIN" ||
    token === "RAIN_PERIODICALLY_HEAVY"
  ) {
    return "heavy_rain.svg";
  }
  if (
    token === "LIGHT_TO_MODERATE_RAIN" ||
    token === "RAIN" ||
    token === "LIGHT_RAIN" ||
    token === "DRIZZLE"
  ) {
    return "drizzle.svg";
  }
  if (
    token === "LIGHT_SNOW_SHOWERS" ||
    token === "CHANCE_OF_SNOW_SHOWERS" ||
    token === "SCATTERED_SNOW_SHOWERS"
  ) {
    return dayNight(
      "scattered_snow_showers_day.svg",
      "scattered_snow_showers_night.svg",
      isNight
    );
  }
  if (token === "SNOW_SHOWERS") return "snow_showers.svg";
  if (
    token === "HEAVY_SNOW_SHOWERS" ||
    token === "HEAVY_SNOW" ||
    token === "MODERATE_TO_HEAVY_SNOW" ||
    token === "SNOW_PERIODICALLY_HEAVY" ||
    token === "SNOWSTORM" ||
    token === "HEAVY_SNOW_STORM" ||
    token === "BLIZZARD"
  ) {
    return "heavy_snow.svg";
  }
  if (
    token === "LIGHT_TO_MODERATE_SNOW" ||
    token === "SNOW" ||
    token === "LIGHT_SNOW" ||
    token === "FLURRIES"
  ) {
    return "flurries.svg";
  }
  if (token === "BLOWING_SNOW") return "blowing_snow.svg";
  if (
    token === "RAIN_AND_SNOW" ||
    token === "SLEET" ||
    token === "WINTRY_MIX" ||
    token === "GLAZE" ||
    token === "FREEZING_RAIN" ||
    token === "ICE_STORM" ||
    token === "WINTER_STORM"
  ) {
    return "wintry_mix.svg";
  }
  if (token === "MIXED_RAIN_HAIL_SLEET") return "mixed_rain_hail_sleet.svg";
  if (token === "HAIL" || token === "HAIL_SHOWERS") return "sleet_hail.svg";
  if (token === "ICY") return "icy.svg";
  if (
    token === "FOG" ||
    token === "HAZE" ||
    token === "MIST" ||
    token === "SMOG" ||
    token === "DUST" ||
    token === "DUST_STORM" ||
    token === "SAND" ||
    token === "SANDSTORM"
  ) {
    return "haze_fog_dust_smoke.svg";
  }
  if (token === "ISOLATED_THUNDERSTORMS") return "isolated_tstorms.svg";
  if (
    token === "THUNDERSTORM" ||
    token === "THUNDERSHOWER" ||
    token === "LIGHT_THUNDERSTORM_RAIN"
  ) {
    return dayNight("thunderstorms_day.svg", "thunderstorms_night.svg", isNight);
  }
  if (token === "SCATTERED_THUNDERSTORMS") {
    return dayNight(
      "isolated_scattered_tstorms_day.svg",
      "isolated_scattered_tstorms_night.svg",
      isNight
    );
  }
  if (
    token === "HEAVY_THUNDERSTORM" ||
    token === "SEVERE_THUNDERSTORM" ||
    token === "STRONG_THUNDERSTORMS"
  ) {
    return "strong_thunderstorms.svg";
  }
  if (token === "TORNADO") return "tornado.svg";
  if (
    token === "HURRICANE" ||
    token === "TROPICAL_STORM" ||
    token === "TYPHOON" ||
    token === "CYCLONE" ||
    token === "TROPICAL_CYCLONE" ||
    token === "EXTRATROPICAL_CYCLONE"
  ) {
    return "hurricane.svg";
  }
  if (token === "HEAT" || token === "HOT") return "hot.svg";
  if (token === "COLD" || token === "WIND_CHILL" || token === "VERY_COLD") return "cold.svg";
  return null;
}

function iconFromHaCondition(condition, isNight) {
  const token = String(condition || "").toLowerCase();
  if (!token) return null;
  if (token === "clear-night") return "clear_night.svg";
  if (token === "sunny" || token === "clear") {
    return dayNight("clear_day.svg", "clear_night.svg", isNight);
  }
  if (token === "partlycloudy" || token === "partly-cloudy") {
    return dayNight("partly_cloudy_day.svg", "partly_cloudy_night.svg", isNight);
  }
  if (token === "cloudy") return "cloudy.svg";
  if (token === "pouring") return "heavy_rain.svg";
  if (token === "rainy") return "rain_showers.svg";
  if (token === "snowy") return "heavy_snow.svg";
  if (token === "snowy-rainy") return "wintry_mix.svg";
  if (token === "fog") return "haze_fog.svg";
  if (token === "hail") return "sleet_hail.svg";
  if (token === "windy" || token === "windy-variant") return "windy.svg";
  if (token === "lightning") {
    return dayNight("thunderstorms_day.svg", "thunderstorms_night.svg", isNight);
  }
  if (token === "lightning-rainy") return "strong_thunderstorms.svg";
  if (token === "exceptional" || token === "hurricane") return "hurricane.svg";
  return null;
}

export function resolveWeatherIconFile({ conditionType, haCondition, isNight }) {
  return (
    iconFromGoogleType(conditionType, isNight) ||
    iconFromHaCondition(haCondition || conditionType, isNight) ||
    "not_available.svg"
  );
}

export function weatherIconUrl(opts) {
  const file = resolveWeatherIconFile(opts);
  return `${ICON_BASE}/${file}?v=${ICON_VER}`;
}

function titleCaseWords(value) {
  return String(value)
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

export function formatConditionLabel({ conditionType, haCondition, conditionText }) {
  if (conditionText && String(conditionText).trim()) {
    return String(conditionText).trim();
  }
  const google = normalizeGoogleType(conditionType);
  if (google && google !== "TYPE_UNSPECIFIED") {
    return titleCaseWords(google.replace(/_/g, " "));
  }
  const token = String(haCondition || "").toLowerCase();
  if (!token || token === "unavailable" || token === "unknown") return "--";
  if (HA_CONDITION_LABELS[token]) return HA_CONDITION_LABELS[token];
  return titleCaseWords(token);
}

export function formatWeatherTemp(value, unit = "°C") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const num = Number(value);
  const suffix = String(unit || "").includes("F") ? "°F" : "°C";
  return `${Math.round(num)}${suffix}`;
}

export function formatSunTime(iso) {
  if (!iso) return "--:--";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function resolveWeatherEntities(listEntityIds, preferredWeatherId) {
  const ids = listEntityIds?.() ?? [];
  let weatherId = "";
  let conditionId = "";

  if (preferredWeatherId) {
    const preferred = preferredWeatherId.trim();
    if (preferred && ids.includes(preferred)) weatherId = preferred;
  }

  if (!weatherId) {
    weatherId = ids.find((id) => id.startsWith("weather.")) || "";
  }

  if (weatherId) {
    const stem = weatherId.slice("weather.".length);
    const exact = `sensor.${stem}_weather_condition`;
    if (ids.includes(exact)) {
      conditionId = exact;
    }
  }

  if (!conditionId) {
    conditionId =
      ids.find((id) => id.startsWith("sensor.") && id.endsWith("_weather_condition")) || "";
  }

  return { weatherId, conditionId };
}

export function readWeatherSnapshot(getState, listEntityIds, preferredWeatherId, sunEntityId = "sun.sun") {
  const { weatherId, conditionId } = resolveWeatherEntities(listEntityIds, preferredWeatherId);
  const weather = weatherId ? getState(weatherId) : null;
  const condition = conditionId ? getState(conditionId) : null;
  const sun = getState(sunEntityId);

  const conditionAttrs = condition?.attributes ?? {};
  const isNight = isNightFromSources(sun, conditionAttrs);

  // Google Weather: state is label ("Clear"), attributes.type is CLEAR / PARTLY_CLOUDY.
  const conditionText =
    condition?.state && condition.state !== "unavailable" && condition.state !== "unknown"
      ? condition.state
      : "";
  const conditionType =
    (typeof conditionAttrs.type === "string" && conditionAttrs.type) ||
    (typeof conditionAttrs.condition === "string" && conditionAttrs.condition) ||
    "";
  const haCondition =
    weather?.state && weather.state !== "unavailable" && weather.state !== "unknown"
      ? weather.state
      : "";

  const temp =
    weather?.attributes?.temperature ??
    weather?.attributes?.temp ??
    conditionAttrs.temperature ??
    null;
  const unit =
    weather?.attributes?.temperature_unit ||
    weather?.attributes?.unit_of_measurement ||
    "°C";

  const available = Boolean(haCondition || conditionText || conditionType);

  return {
    available,
    weatherId,
    conditionId,
    label: formatConditionLabel({ conditionType, haCondition, conditionText }),
    temperature: formatWeatherTemp(temp, unit),
    iconUrl: weatherIconUrl({ conditionType, haCondition, isNight }),
    sunrise: formatSunTime(sun?.attributes?.next_rising),
    sunset: formatSunTime(sun?.attributes?.next_setting),
    hasSun: Boolean(sun),
  };
}
