"""Config flow for Nook."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_HEATER,
    CONF_TEMPERATURE_SENSOR,
    CONF_WINDOW_SENSORS,
    DEFAULT_AWAY_TEMP,
    DEFAULT_BOOST_TEMP,
    DEFAULT_ECO_TEMP,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    HEATER_DOMAINS,
)
from .models import RoomConfig, default_schedule


def _heater_selector():
    return selector.EntitySelector(
        config=selector.EntitySelectorConfig(domain=list(HEATER_DOMAINS))
    )


def _temp_selector():
    return selector.EntitySelector(
        config=selector.EntitySelectorConfig(domain=["sensor"], device_class=["temperature"])
    )


def _binary_multi():
    return selector.EntitySelector(
        config=selector.EntitySelectorConfig(
            domain=["binary_sensor"],
            multiple=True,
        )
    )


def _climate_selector():
    return selector.EntitySelector(
        config=selector.EntitySelectorConfig(domain=["climate"])
    )


class NookConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup: heater + house sensor (+ optional rooms later)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            rooms: list[dict[str, Any]] = []
            # Seed rooms from common TRV entities if provided in options later
            data = {
                CONF_HEATER: user_input[CONF_HEATER],
                CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
            }
            options = {
                CONF_WINDOW_SENSORS: user_input.get(CONF_WINDOW_SENSORS) or [],
                "eco_temp": user_input.get("eco_temp", DEFAULT_ECO_TEMP),
                "boost_temp": user_input.get("boost_temp", DEFAULT_BOOST_TEMP),
                "away_temp": user_input.get("away_temp", DEFAULT_AWAY_TEMP),
                "target_temp": user_input.get("target_temp", DEFAULT_TARGET_TEMP),
                "rooms": rooms,
                "schedule": default_schedule(),
                "wall_panels": [],
                "schedule_enabled": True,
                "summer_mode": False,
                "person_entity": user_input.get("person_entity") or "",
            }
            return self.async_create_entry(
                title="Nook",
                data=data,
                options=options,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_HEATER): _heater_selector(),
                vol.Required(CONF_TEMPERATURE_SENSOR): _temp_selector(),
                vol.Optional(CONF_WINDOW_SENSORS): _binary_multi(),
                vol.Optional("person_entity"): selector.EntitySelector(
                    config=selector.EntitySelectorConfig(domain=["person"])
                ),
                vol.Optional("eco_temp", default=DEFAULT_ECO_TEMP): vol.Coerce(float),
                vol.Optional("boost_temp", default=DEFAULT_BOOST_TEMP): vol.Coerce(float),
                vol.Optional("away_temp", default=DEFAULT_AWAY_TEMP): vol.Coerce(float),
                vol.Optional("target_temp", default=DEFAULT_TARGET_TEMP): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return NookOptionsFlow(config_entry)


class NookOptionsFlow(config_entries.OptionsFlow):
    """Options: add rooms, summer mode, temps."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        current = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            rooms = list(current.get("rooms") or [])
            # Allow quick-add one room from options
            if user_input.get("add_room_name") and user_input.get("add_room_trv"):
                name = str(user_input["add_room_name"]).strip()
                room_id = name.lower().replace(" ", "_")
                rooms = [r for r in rooms if r.get("id") != room_id]
                rooms.append(
                    RoomConfig(
                        id=room_id,
                        name=name,
                        trv_entity=user_input["add_room_trv"],
                        temperature_sensor=user_input.get("add_room_sensor") or "",
                    ).to_dict()
                )
            return self.async_create_entry(
                title="",
                data={
                    **{k: v for k, v in current.items() if k not in ("heater", "temperature_sensor")},
                    CONF_WINDOW_SENSORS: user_input.get(
                        CONF_WINDOW_SENSORS, current.get(CONF_WINDOW_SENSORS) or []
                    ),
                    "eco_temp": user_input.get("eco_temp", current.get("eco_temp", DEFAULT_ECO_TEMP)),
                    "boost_temp": user_input.get(
                        "boost_temp", current.get("boost_temp", DEFAULT_BOOST_TEMP)
                    ),
                    "away_temp": user_input.get(
                        "away_temp", current.get("away_temp", DEFAULT_AWAY_TEMP)
                    ),
                    "summer_mode": user_input.get(
                        "summer_mode", current.get("summer_mode", False)
                    ),
                    "schedule_enabled": user_input.get(
                        "schedule_enabled", current.get("schedule_enabled", True)
                    ),
                    "person_entity": user_input.get(
                        "person_entity", current.get("person_entity") or ""
                    )
                    or "",
                    "rooms": rooms,
                    "schedule": current.get("schedule") or default_schedule(),
                    "wall_panels": current.get("wall_panels") or [],
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_WINDOW_SENSORS,
                    default=current.get(CONF_WINDOW_SENSORS) or [],
                ): _binary_multi(),
                vol.Optional(
                    "person_entity", default=current.get("person_entity") or vol.UNDEFINED
                ): selector.EntitySelector(
                    config=selector.EntitySelectorConfig(domain=["person"])
                ),
                vol.Optional(
                    "eco_temp", default=current.get("eco_temp", DEFAULT_ECO_TEMP)
                ): vol.Coerce(float),
                vol.Optional(
                    "boost_temp", default=current.get("boost_temp", DEFAULT_BOOST_TEMP)
                ): vol.Coerce(float),
                vol.Optional(
                    "away_temp", default=current.get("away_temp", DEFAULT_AWAY_TEMP)
                ): vol.Coerce(float),
                vol.Optional(
                    "summer_mode", default=current.get("summer_mode", False)
                ): bool,
                vol.Optional(
                    "schedule_enabled",
                    default=current.get("schedule_enabled", True),
                ): bool,
                vol.Optional("add_room_name"): str,
                vol.Optional("add_room_trv"): _climate_selector(),
                vol.Optional("add_room_sensor"): _temp_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
