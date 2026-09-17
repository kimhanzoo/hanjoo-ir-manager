"""Semantic climate entities backed by full-state IR matrices."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_SWING_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, DEVICE_TYPE_CLIMATE
from .entity import HanJooEntity
from .manager import HanJooIRManager


_MODE_ALIASES = {
    "off": HVACMode.OFF,
    "auto": HVACMode.AUTO,
    "automatic": HVACMode.AUTO,
    "heat": HVACMode.HEAT,
    "heating": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "cooling": HVACMode.COOL,
    "heat_cool": HVACMode.HEAT_COOL,
    "heatcool": HVACMode.HEAT_COOL,
    "dry": HVACMode.DRY,
    "dehumidify": HVACMode.DRY,
    "fan": HVACMode.FAN_ONLY,
    "fan_only": HVACMode.FAN_ONLY,
    "fanonly": HVACMode.FAN_ONLY,
}


def _ha_mode(source: str) -> HVACMode | None:
    return _MODE_ALIASES.get(str(source).strip().lower().replace(" ", "_"))


def _source_mode(climate: dict, ha_mode: HVACMode) -> str | None:
    for source in climate.get("modes") or []:
        if _ha_mode(str(source)) == ha_mode:
            return str(source)
    # Learned custom devices use HA's canonical vocabulary.
    if ha_mode is not HVACMode.OFF:
        return str(ha_mode)
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager: HanJooIRManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    async_add_entities(
        HanJooClimate(manager, device_id)
        for device_id, device in manager.get_devices().items()
        if device.get("type") == DEVICE_TYPE_CLIMATE
    )


class HanJooClimate(HanJooEntity, ClimateEntity, RestoreEntity):
    """Climate wrapper for imported or learned full-state IR frames."""

    _attr_assumed_state = True

    def __init__(self, manager: HanJooIRManager, device_id: str) -> None:
        HanJooEntity.__init__(self, manager, device_id, "climate")
        self._attr_name = None
        climate = self.device.get("climate") or {}
        self._climate = climate

        modes: list[HVACMode] = [HVACMode.OFF]
        for source in climate.get("modes") or []:
            mode = _ha_mode(str(source))
            if mode and mode not in modes:
                modes.append(mode)
        if len(modes) == 1:
            # A custom stateful AC begins useful, but it still refuses to send
            # a combination until that exact state is learned.
            modes.extend(
                [HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.HEAT]
            )
        self._attr_hvac_modes = modes
        self._attr_hvac_mode = HVACMode.OFF

        self._attr_min_temp = float(climate.get("min_temp", 16))
        self._attr_max_temp = float(climate.get("max_temp", 30))
        self._attr_target_temperature_step = float(climate.get("precision", 1))
        self._attr_temperature_unit = (
            UnitOfTemperature.FAHRENHEIT
            if str(climate.get("unit") or "C").upper().startswith("F")
            else UnitOfTemperature.CELSIUS
        )
        cells = climate.get("cells") or []
        first_cell = cells[0] if cells else {}
        first_temp = first_cell.get("temp")
        self._attr_target_temperature = (
            float(first_temp)
            if first_temp is not None
            else float(climate.get("default_temp", self._attr_min_temp))
        )

        fan_modes = [str(v) for v in (climate.get("fan_modes") or [])]
        self._attr_fan_modes = fan_modes or None
        self._attr_fan_mode = (
            str(first_cell.get("fan"))
            if first_cell.get("fan") is not None
            else (fan_modes[0] if fan_modes else None)
        )

        swing_modes = [str(v) for v in (climate.get("swing_modes") or [])]
        self._attr_swing_modes = swing_modes or None
        self._attr_swing_mode = (
            str(first_cell.get("swing"))
            if first_cell.get("swing") is not None
            else (swing_modes[0] if swing_modes else None)
        )
        first_mode = _ha_mode(str(first_cell.get("mode") or ""))
        self._default_on_mode = (
            first_mode
            if first_mode in modes and first_mode is not HVACMode.OFF
            else next((m for m in modes if m is not HVACMode.OFF), HVACMode.COOL)
        )

        has_temp = any(cell.get("temp") is not None for cell in cells)
        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if has_temp or not cells:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if fan_modes:
            features |= ClimateEntityFeature.FAN_MODE
        if swing_modes:
            features |= ClimateEntityFeature.SWING_MODE
        self._attr_supported_features = features

    def _apply_received_state(self, state: dict[str, Any] | None) -> None:
        """Apply a physical-remote state decoded/matched by HanJoo manager."""
        if not state or state.get("type") != "climate":
            return
        mode = state.get("mode")
        if mode is not None:
            ha_mode = _ha_mode(str(mode))
            if ha_mode in self._attr_hvac_modes:
                self._attr_hvac_mode = ha_mode
        if state.get("power") is False:
            self._attr_hvac_mode = HVACMode.OFF

        temp = state.get("temp")
        if temp is not None:
            try:
                value = float(temp)
                if self._attr_min_temp <= value <= self._attr_max_temp:
                    self._attr_target_temperature = value
            except (TypeError, ValueError):
                pass

        fan = state.get("fan")
        if fan in (self._attr_fan_modes or []):
            self._attr_fan_mode = fan
        swing = state.get("swing")
        if swing in (self._attr_swing_modes or []):
            self._attr_swing_mode = swing

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is None:
            return
        try:
            restored_mode = HVACMode(state.state)
        except ValueError:
            restored_mode = None
        if restored_mode in self.hvac_modes:
            self._attr_hvac_mode = restored_mode
        temp = state.attributes.get(ATTR_TEMPERATURE)
        if temp is not None:
            try:
                self._attr_target_temperature = float(temp)
            except (TypeError, ValueError):
                pass
        fan = state.attributes.get(ATTR_FAN_MODE)
        if fan in (self._attr_fan_modes or []):
            self._attr_fan_mode = fan
        swing = state.attributes.get(ATTR_SWING_MODE)
        if swing in (self._attr_swing_modes or []):
            self._attr_swing_mode = swing

    async def _send_current(
        self,
        *,
        mode: HVACMode | None = None,
        temp: float | None = None,
        fan: str | None = None,
        swing: str | None = None,
    ) -> None:
        target_mode = mode or self._attr_hvac_mode or HVACMode.OFF
        if target_mode is HVACMode.OFF:
            sent = await self.manager.send_climate_power(self.device_id, False)
            if not sent:
                await self.manager.send_climate_state(
                    self.device_id,
                    mode="off",
                    temp=temp if temp is not None else self._attr_target_temperature,
                    fan=fan if fan is not None else self._attr_fan_mode,
                    swing=swing if swing is not None else self._attr_swing_mode,
                )
            return

        source = _source_mode(self._climate, target_mode)
        if source is None:
            raise HomeAssistantError(
                f"Profile không hỗ trợ chế độ {target_mode}"
            )
        await self.manager.send_climate_state(
            self.device_id,
            mode=source,
            temp=temp if temp is not None else self._attr_target_temperature,
            fan=fan if fan is not None else self._attr_fan_mode,
            swing=swing if swing is not None else self._attr_swing_mode,
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._send_current(mode=hvac_mode)
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = float(kwargs[ATTR_TEMPERATURE])
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        mode = HVACMode(hvac_mode) if hvac_mode is not None else None
        await self._send_current(mode=mode, temp=temperature)
        self._attr_target_temperature = temperature
        if mode is not None:
            self._attr_hvac_mode = mode
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._send_current(fan=fan_mode)
        self._attr_fan_mode = fan_mode
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._send_current(swing=swing_mode)
        self._attr_swing_mode = swing_mode
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        await self._send_current(mode=HVACMode.OFF)
        self._attr_hvac_mode = HVACMode.OFF
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        if await self.manager.send_climate_power(self.device_id, True):
            if self._attr_hvac_mode is HVACMode.OFF:
                self._attr_hvac_mode = self._default_on_mode
            self.async_write_ha_state()
            return
        target = (
            self._attr_hvac_mode
            if self._attr_hvac_mode is not HVACMode.OFF
            else self._default_on_mode
        )
        await self._send_current(mode=target)
        self._attr_hvac_mode = target
        self.async_write_ha_state()
