"""Constants for Nook."""

from __future__ import annotations

DOMAIN = "nook"
PLATFORMS = ["climate"]

CONF_HEATER = "heater"
HEATER_DOMAINS = ("switch", "input_boolean", "climate")
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_WINDOW_SENSORS = "window_sensors"
CONF_ROOMS = "rooms"
CONF_ECO_TEMP = "eco_temp"
CONF_BOOST_TEMP = "boost_temp"
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_HOT_TOLERANCE = "hot_tolerance"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_AWAY_TEMP = "away_temp"
CONF_SCHEDULE = "schedule"
CONF_WALL_PANELS = "wall_panels"
CONF_SUMMER_MODE = "summer_mode"
CONF_PERSON_ENTITY = "person_entity"
CONF_PRESENCE_ENTITIES = "presence_entities"
CONF_TRUE_RADIANT = "true_radiant"
CONF_AUTO_SCHEDULE = "auto_schedule"
CONF_AWAY_DELAY_MINUTES = "away_delay_minutes"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"
CONF_LEAF_ENABLED = "leaf_enabled"
CONF_SAFETY_TEMP_ENABLED = "safety_temp_enabled"
CONF_SAFETY_MIN_TEMP = "safety_min_temp"
CONF_SEASONAL_SAVINGS = "seasonal_savings"
CONF_ADAPTIVE_COMFORT = "adaptive_comfort"
CONF_WALL_PIN = "wall_pin"

DEFAULT_ECO_TEMP = 16.0
DEFAULT_BOOST_TEMP = 22.0
DEFAULT_AWAY_TEMP = 15.0
DEFAULT_TARGET_TEMP = 20.0
DEFAULT_COLD_TOLERANCE = 0.3
DEFAULT_HOT_TOLERANCE = 0.3
DEFAULT_MIN_TEMP = 5.0
# Boiler anti-short-cycle protection (minutes). Boiler makers generally
# want runs and rests of a few minutes; 1 min let the relay chatter.
DEFAULT_MIN_ON_MINUTES = 3.0
DEFAULT_MIN_OFF_MINUTES = 3.0
DEFAULT_MAX_TEMP = 30.0
DEFAULT_TRUE_RADIANT = True
DEFAULT_AUTO_SCHEDULE = False
DEFAULT_AWAY_DELAY_MINUTES = 20
# A window or door must stay open this long before the heating stops, so someone
# walking out (or airing a room for a moment) doesn't switch it off.
DEFAULT_WINDOW_OPEN_DELAY_MINUTES = 3.0
DEFAULT_LEAF_ENABLED = True
DEFAULT_SAFETY_TEMP_ENABLED = True
DEFAULT_SAFETY_MIN_TEMP = 7.0
DEFAULT_SEASONAL_SAVINGS = False
DEFAULT_ADAPTIVE_COMFORT = False
DEFAULT_WALL_PIN = ""
# Alert when this many boiler-on minutes haven't warmed the house.
DEFAULT_NO_HEAT_ALERT = True
DEFAULT_NO_HEAT_ALERT_MINUTES = 60
# A house sensor silent this long is treated as dead (ZHA's default heartbeat
# is 15 min, so this is several missed reports).
DEFAULT_SENSOR_STALE_MINUTES = 60
# Wall panel screen shape (stored as "model"): picks the preview size in the panel JS.
# The wall app lays itself out from its real screen, so this never changes the panel.
# "nspanel_pro" is a square Sonoff NSPanel Pro, which can also run the Nook Panel Helper.
WALL_PANEL_SHAPES = ("square", "tall", "landscape", "wide", "nspanel_pro")
DEFAULT_WALL_PANEL_MODEL = "square"
# Seasonal Savings: over this many days, take this much off each schedule
# block every few days, up to the max; blocks the user turns up are left be.
SEASONAL_SAVINGS_DAYS = 21
SEASONAL_STEP_DAYS = 3
SEASONAL_STEP_C = 0.1
SEASONAL_MAX_C = 0.5
ENERGY_HISTORY_KEEP_DAYS = 45

ATTR_WINDOW_OPEN = "window_open"
ATTR_SUMMER_MODE = "summer_mode_state"
ATTR_SCHEDULE_ACTIVE = "schedule_active"
ATTR_AWAY_MODE = "away_mode"
ATTR_PREHEATING = "preheating"
ATTR_PREHEAT_FOR = "preheat_for"
ATTR_TRUE_RADIANT = "true_radiant"
ATTR_LEAF = "leaf"
ATTR_LEAF_THRESHOLD = "leaf_threshold"
ATTR_LEAF_BASELINE = "leaf_baseline"
ATTR_SAFETY_ACTIVE = "safety_active"
ATTR_TIME_TO_TEMP = "time_to_temp_minutes"

PRESET_NONE = "none"
PRESET_ECO = "eco"
PRESET_BOOST = "boost"
PRESET_AWAY = "away"

# How long a room's own setpoint change lasts: until the house changes (dial,
# preset, mode or schedule block), until the next schedule block, or until
# the room is changed again.
ROOM_HOLD_ENDS = ("house_change", "block_change", "manual")

# Wall panel room settings (the cog): the Room Temperature fields a panel may
# change, and the TRV device settings it shows — simple ones a finger can set
# (no option lists, text or times).
WALL_ROOM_FIELDS = ("follow_house", "house_offset", "target_temp", "eco_temp", "hold_ends")
WALL_TRV_SETTING_DOMAINS = ("number", "switch", "button")

PANEL_URL_PATH = "nook"
PANEL_TITLE = "Nook"
PANEL_ICON = "mdi:thermostat"
PANEL_STATIC_URL = f"/{DOMAIN}/static"
PANEL_COMPONENT = "nook-panel"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.config"

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
