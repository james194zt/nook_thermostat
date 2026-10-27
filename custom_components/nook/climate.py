"""Climate entities for Nook."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_AWAY_MODE,
    ATTR_LEAF,
    ATTR_LEAF_BASELINE,
    ATTR_LEAF_THRESHOLD,
    ATTR_PREHEAT_FOR,
    ATTR_PREHEATING,
    ATTR_SAFETY_ACTIVE,
    ATTR_SCHEDULE_ACTIVE,
    ATTR_SUMMER_MODE,
    ATTR_TIME_TO_TEMP,
    ATTR_TRUE_RADIANT,
    ATTR_WINDOW_OPEN,
    DOMAIN,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_ECO,
    PRESET_NONE,
)
from .coordinator import NookCoordinator
from .models import RoomConfig


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NookCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    # Fixed entity ids (climate.nook_home, climate.nook_<room>), whatever the entity names say.
    registry = er.async_get(hass)
    for unique_id in ["nook_home", *(f"nook_{room.id}" for room in coordinator.config.rooms)]:
        registry.async_get_or_create(
            "climate", DOMAIN, unique_id, suggested_object_id=unique_id, config_entry=entry
        )
    entities: list[ClimateEntity] = [NookHomeClimate(coordinator)]
    for room in coordinator.config.rooms:
        entities.append(NookRoomClimate(coordinator, room))
    async_add_entities(entities)


class NookHomeClimate(CoordinatorEntity[NookCoordinator], ClimateEntity):
    """House-level Nook climate (boiler demand + schedule)."""

    _attr_name = "Nook Home"
    _attr_unique_id = "nook_home"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_NONE, PRESET_ECO, PRESET_BOOST, PRESET_AWAY]

    def __init__(self, coordinator: NookCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "Nook",
            "manufacturer": "Nook",
            "model": "Thermostat Hub",
        }

    @property
    def min_temp(self) -> float:
        return self.coordinator.config.min_temp

    @property
    def max_temp(self) -> float:
        return self.coordinator.config.max_temp

    @property
    def target_temperature_step(self) -> float:
        return 0.5

    @property
    def current_temperature(self) -> float | None:
        # The house sensor, or the backup if it has gone silent.
        return self.coordinator._house_temp()  # noqa: SLF001

    @property
    def target_temperature(self) -> float | None:
        temp, _ = self.coordinator.effective_main_target()
        return temp

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self.coordinator.main_hvac_mode == "heat" else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self.coordinator.data.get("summer_mode"):
            return HVACAction.OFF
        if self.coordinator.data.get("window_open"):
            return HVACAction.OFF
        if self.coordinator.data.get("boiler_on"):
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        if self.coordinator.data.get("away"):
            return PRESET_AWAY
        return self.coordinator.main_preset or PRESET_NONE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, schedule_active = self.coordinator.effective_main_target()
        preheat = self.coordinator.data.get("preheat") or {}
        leaf = self.coordinator.data.get("leaf") or {}
        return {
            ATTR_WINDOW_OPEN: bool(self.coordinator.data.get("window_open")),
            ATTR_SUMMER_MODE: bool(self.coordinator.data.get("summer_mode")),
            ATTR_SCHEDULE_ACTIVE: schedule_active,
            ATTR_AWAY_MODE: bool(self.coordinator.data.get("away")),
            ATTR_TRUE_RADIANT: bool(self.coordinator.config.true_radiant),
            ATTR_PREHEATING: bool(preheat.get("preheating")),
            ATTR_PREHEAT_FOR: preheat.get("block_start") if preheat.get("preheating") else None,
            # The room the preheat is timed for (None: the house sensor).
            "preheat_room": preheat.get("preheat_room"),
            "preheat_start": preheat.get("preheat_start"),
            ATTR_LEAF: bool(leaf.get("active")),
            ATTR_LEAF_THRESHOLD: leaf.get("threshold"),
            ATTR_LEAF_BASELINE: leaf.get("baseline"),
            "leaf_minutes_week": leaf.get("minutes_week"),
            "leaf_minutes_total": leaf.get("minutes_total"),
            "leaf_days_streak": leaf.get("days_streak"),
            ATTR_SAFETY_ACTIVE: bool(self.coordinator.data.get("safety_active")),
            ATTR_TIME_TO_TEMP: self.coordinator.data.get("time_to_temp_minutes"),
            "boiler_on": bool(self.coordinator.data.get("boiler_on")),
            "boiler_demand": bool(self.coordinator.data.get("boiler_demand")),
            "heater_entity": self.coordinator.config.heater,
            "heater_available": bool(self.coordinator.data.get("heater_available", True)),
            "boiler_cycle_wait_seconds": self.coordinator.data.get(
                "boiler_cycle_wait_seconds"
            ),
            # Minimum on/off time: the boiler stays as it is (against the demand) until then.
            "boiler_hold_until": self.coordinator.data.get("boiler_hold_until"),
            "warmup_c_per_hour": self.coordinator.intel.state.warmup.c_per_hour,
            "radiator_coast_c": self.coordinator.intel.state.warmup.coast_c,
            # main / backup / none: which house sensor Nook is heating from.
            "temperature_source": self.coordinator.intel.state.sensor_health.source,
            # Relay released for a hand test (Nook takes it back at this time).
            "relay_released_until": self.coordinator.data.get("control_released_until"),
            # Boiler time isn't warming the house (see the Nook notification).
            "heating_fault": self.coordinator.data.get("heating_fault") is not None,
            # Nook room climates in the user's order (the dashboard card lists them).
            "room_entities": [
                entity_id
                for room in self.coordinator.config.rooms
                if room.enabled is not False
                and (entity_id := self.coordinator.nook_entity_id(f"nook_{room.id}"))
            ],
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self.coordinator.set_main_temperature(float(temperature))
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self.coordinator.set_main_hvac_mode(
            "heat" if hvac_mode == HVACMode.HEAT else "off"
        )
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self.coordinator.set_main_preset(preset_mode)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)


class NookRoomClimate(CoordinatorEntity[NookCoordinator], ClimateEntity):
    """Per-room Nook climate wrapping a TRV."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_NONE, PRESET_ECO, PRESET_BOOST]

    def __init__(
        self, coordinator: NookCoordinator, room: RoomConfig
    ) -> None:
        super().__init__(coordinator)
        self._room = room
        self._attr_name = f"Nook {room.name}"
        self._attr_unique_id = f"nook_{room.id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "Nook",
            "manufacturer": "Nook",
            "model": "Thermostat Hub",
        }

    @property
    def room(self) -> RoomConfig:
        for room in self.coordinator.config.rooms:
            if room.id == self._room.id:
                return room
        return self._room

    @property
    def min_temp(self) -> float:
        return self.coordinator.config.min_temp

    @property
    def max_temp(self) -> float:
        return self.coordinator.config.max_temp

    @property
    def target_temperature_step(self) -> float:
        return 0.5

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.room_current_temp(self.room)

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.effective_room_target(self.room)

    @property
    def hvac_mode(self) -> HVACMode:
        mode = self.coordinator.room_control(self.room.id).get("hvac_mode", "heat")
        return HVACMode.HEAT if mode == "heat" else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self.coordinator.config.summer_mode:
            return HVACAction.OFF
        if self.coordinator._room_follows_house_off(self.room):  # noqa: SLF001
            return HVACAction.OFF
        if self.coordinator._any_window_open(self.room.window_sensors):  # noqa: SLF001
            return HVACAction.OFF
        if (
            self.coordinator.data.get("rooms", {})
            .get(self.room.id, {})
            .get("needs_heat")
        ):
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        return self.coordinator.room_control(self.room.id).get("preset", PRESET_NONE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_WINDOW_OPEN: self.coordinator._any_window_open(  # noqa: SLF001
                self.room.window_sensors
            ),
            ATTR_SUMMER_MODE: bool(self.coordinator.config.summer_mode),
            "room_id": self.room.id,
            "room_name": self.room.name,
            "trv_entity": self.room.trv_entity,
            "calls_for_heat": bool(getattr(self.room, "calls_for_heat", True)),
            # Manual setpoint in force until this time (ISO), then the schedule resumes.
            "hold_until": self.coordinator.room_hold_until(self.room),
            # A change made on the room is in force (hold_until is None when it
            # lasts until the house changes or the room is changed again).
            "held": self.coordinator.room_held(self.room),
            "hold_ends": self.room.hold_ends,
            "follow_house": self.room.follow_house,
            "house_offset": self.room.house_offset,
            "needs_heat": bool(
                self.coordinator.data.get("rooms", {})
                .get(self.room.id, {})
                .get("needs_heat")
            ),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self.coordinator.set_room_temperature(self.room.id, float(temperature))
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self.coordinator.set_room_hvac_mode(
            self.room.id, "heat" if hvac_mode == HVACMode.HEAT else "off"
        )
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self.coordinator.set_room_preset(self.room.id, preset_mode)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._room = self.room
        super()._handle_coordinator_update()
