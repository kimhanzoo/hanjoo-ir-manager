"""Semantic climate entities backed by full-state IR matrices."""
from __future__ import annotations

from typing import Any
from datetime import datetime
import logging
import math
import time

from homeassistant.helpers.event import async_call_later

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
try:
    # Home Assistant 2026.10 supports horizontal swing as a first-class
    # climate capability. Keep a soft import fallback for slightly older cores.
    from homeassistant.components.climate.const import (
        ATTR_SWING_HORIZONTAL_MODE,
    )
except ImportError:  # pragma: no cover - compatibility with older HA
    ATTR_SWING_HORIZONTAL_MODE = "swing_horizontal_mode"

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
_PRESET_COMMANDS = ("turbo", "quiet", "econo", "sleep", "clean")
_LOGGER = logging.getLogger(__name__)


def _ha_mode(source: str) -> HVACMode | None:
    return _MODE_ALIASES.get(str(source).strip().lower().replace(" ", "_"))


def _source_mode(climate: dict, ha_mode: HVACMode) -> str | None:
    for source in climate.get("modes") or []:
        if _ha_mode(str(source)) == ha_mode:
            return str(source)
    if ha_mode is not HVACMode.OFF:
        return str(ha_mode)
    return None


def _ordered_unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        item = str(value)
        if item and item not in out:
            out.append(item)
    return out


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
    """Climate wrapper for imported, learned, or dynamic full-state IR."""

    _attr_assumed_state = True

    def __init__(self, manager: HanJooIRManager, device_id: str) -> None:
        HanJooEntity.__init__(self, manager, device_id, "climate")
        self._attr_name = None
        self._climate: dict[str, Any] = {}
        self._default_on_mode = HVACMode.COOL
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 24.0
        self._attr_fan_mode = None
        self._attr_swing_mode = None
        self._attr_swing_horizontal_mode = None
        self._attr_preset_mode = None
        self._rx_extra: dict[str, Any] = {}
        self._last_rx_sequence = -1
        self._timer_cancel = None
        self._timer_deadline = None
        self._timer_action = None
        self._timer_error = None
        self._refresh_capabilities(initial=True)

    def _refresh_capabilities(self, *, initial: bool = False) -> None:
        """Refresh all capabilities from the current runtime device/profile."""
        climate = self.device.get("climate") or {}
        self._climate = climate
        cells = [cell for cell in (climate.get("cells") or []) if isinstance(cell, dict)]
        first_cell = cells[0] if cells else {}

        modes: list[HVACMode] = [HVACMode.OFF]
        for source in climate.get("modes") or []:
            mode = _ha_mode(str(source))
            if mode and mode not in modes:
                modes.append(mode)
        if len(modes) == 1:
            modes.extend([HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.HEAT])
        self._attr_hvac_modes = modes

        self._attr_min_temp = float(climate.get("min_temp", 16))
        self._attr_max_temp = float(climate.get("max_temp", 30))
        self._attr_target_temperature_step = float(climate.get("precision", 1))
        self._attr_temperature_unit = (
            UnitOfTemperature.FAHRENHEIT
            if str(climate.get("unit") or "C").upper().startswith("F")
            else UnitOfTemperature.CELSIUS
        )

        if initial:
            first_temp = first_cell.get("temp")
            self._attr_target_temperature = (
                float(first_temp)
                if first_temp is not None
                else float(climate.get("default_temp", self._attr_min_temp))
            )

        fan_modes = _ordered_unique(
            list(climate.get("fan_modes") or [])
            + [cell.get("fan") for cell in cells]
        )
        self._attr_fan_modes = fan_modes or None
        if self._attr_fan_mode not in fan_modes:
            self._attr_fan_mode = (
                str(first_cell.get("fan"))
                if first_cell.get("fan") is not None
                else (fan_modes[0] if fan_modes else None)
            )

        swing_modes = _ordered_unique(
            list(climate.get("swing_modes") or [])
            + [cell.get("swing") for cell in cells]
        )
        self._attr_swing_modes = swing_modes or None
        if self._attr_swing_mode not in swing_modes:
            self._attr_swing_mode = (
                str(first_cell.get("swing"))
                if first_cell.get("swing") is not None
                else (swing_modes[0] if swing_modes else None)
            )

        swing_h_modes = _ordered_unique(
            list(climate.get("swing_horizontal_modes") or climate.get("horizontal_swing_modes") or [])
            + [cell.get("swing_horizontal") for cell in cells]
        )
        self._attr_swing_horizontal_modes = swing_h_modes or None
        if self._attr_swing_horizontal_mode not in swing_h_modes:
            self._attr_swing_horizontal_mode = (
                str(first_cell.get("swing_horizontal"))
                if first_cell.get("swing_horizontal") is not None
                else (swing_h_modes[0] if swing_h_modes else None)
            )

        commands = self.device.get("commands") or {}
        presets = _ordered_unique(
            list(climate.get("preset_modes") or [])
            + [cell.get("preset") for cell in cells]
            + [
                command_id
                for command_id in _PRESET_COMMANDS
                if isinstance(commands.get(command_id), dict)
                and commands[command_id].get("codes")
            ]
        )
        self._attr_preset_modes = presets or None
        if self._attr_preset_mode not in presets:
            self._attr_preset_mode = None

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
        if swing_h_modes and hasattr(ClimateEntityFeature, "SWING_HORIZONTAL_MODE"):
            features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE
        if presets:
            features |= ClimateEntityFeature.PRESET_MODE
        self._attr_supported_features = features

        device = self.device
        has_feedback_path = bool(device.get("receiver_entity_id")) and bool(
            device.get("protocol_engine")
            or device.get("rx_protocol_hint")
            or cells
            or climate.get("on")
            or climate.get("off")
        )
        # Once a receiver is configured with a decodable/matchable profile, the
        # climate entity is no longer purely optimistic.
        self._attr_assumed_state = not has_feedback_path

    def _apply_received_state(self, state: dict[str, Any] | None) -> None:
        """Apply a physical-remote state decoded/matched by HanJoo manager."""
        if not state or state.get("type") != "climate":
            return
        sequence = state.get("sequence")
        if sequence is not None:
            if sequence == self._last_rx_sequence:
                return
            self._last_rx_sequence = sequence
        mode = state.get("mode")
        if mode is not None:
            ha_mode = _ha_mode(str(mode))
            if ha_mode in self._attr_hvac_modes:
                self._attr_hvac_mode = ha_mode
        if state.get("power") is False:
            self._attr_hvac_mode = HVACMode.OFF
        elif state.get("power") is True and self._attr_hvac_mode is HVACMode.OFF:
            self._attr_hvac_mode = self._default_on_mode

        temp = state.get("temp")
        if temp is not None:
            try:
                value = float(temp)
                if self._attr_min_temp <= value <= self._attr_max_temp:
                    self._attr_target_temperature = value
            except (TypeError, ValueError):
                pass

        fan = state.get("fan")
        if fan is not None:
            fan = str(fan)
            if fan in (self._attr_fan_modes or []):
                self._attr_fan_mode = fan

        swing = state.get("swing")
        if swing is not None:
            swing = str(swing)
            if swing in (self._attr_swing_modes or []):
                self._attr_swing_mode = swing

        swing_h = state.get("swing_horizontal")
        if swing_h is not None:
            swing_h = str(swing_h)
            if swing_h in (self._attr_swing_horizontal_modes or []):
                self._attr_swing_horizontal_mode = swing_h

        preset = state.get("preset")
        if preset is not None and str(preset) in (self._attr_preset_modes or []):
            self._attr_preset_mode = str(preset)
        elif preset == "none":
            self._attr_preset_mode = None

        self._rx_extra = {
            key: state.get(key)
            for key in (
                "protocol", "source", "quiet", "turbo", "econo", "light",
                "filter", "clean", "beep", "sleep", "clock", "received_at",
            )
            if state.get(key) is not None
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose non-standard decoded A/C state without hiding it."""
        return {
            "hanjoo_device_id": self.device_id,
            "hanjoo_timer_deadline": self._timer_deadline,
            "hanjoo_timer_action": self._timer_action,
            "hanjoo_timer_error": self._timer_error,
            **{f"hanjoo_{key}": value for key, value in self._rx_extra.items()},
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        self.async_on_remove(self._cancel_timer_callback)
        if state is None:
            self._apply_received_state(self.manager.get_received_state(self.device_id))
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
        swing_h = state.attributes.get(ATTR_SWING_HORIZONTAL_MODE)
        if swing_h in (self._attr_swing_horizontal_modes or []):
            self._attr_swing_horizontal_mode = swing_h
        preset = state.attributes.get(ATTR_PRESET_MODE)
        if preset in (self._attr_preset_modes or []):
            self._attr_preset_mode = preset
        self._apply_received_state(self.manager.get_received_state(self.device_id))
        deadline = state.attributes.get("hanjoo_timer_deadline")
        action = state.attributes.get("hanjoo_timer_action")
        if isinstance(deadline, (int, float)) and action in ("on", "off"):
            if deadline > time.time():
                self._arm_timer(deadline, action)

    def _cancel_timer_callback(self) -> None:
        if self._timer_cancel is not None:
            self._timer_cancel()
            self._timer_cancel = None

    def _arm_timer(self, deadline: float, action: str) -> None:
        self._cancel_timer_callback()
        self._timer_deadline = deadline
        self._timer_action = action
        self._timer_error = None

        async def execute(_now: datetime) -> None:
            self._timer_cancel = None
            self._timer_deadline = None
            self._timer_action = None
            try:
                if action == "off":
                    await self.async_turn_off()
                else:
                    await self.async_turn_on()
            except HomeAssistantError as err:
                self._timer_error = str(err)
                _LOGGER.warning("HanJoo timer failed for %s: %s", self.entity_id, err)
            finally:
                self.async_write_ha_state()

        self._timer_cancel = async_call_later(
            self.hass, max(0, deadline - time.time()), execute
        )

    async def async_set_timer(self, minutes: float, action: str = "off") -> None:
        """Schedule a local HA power command; zero cancels the pending timer."""
        if not math.isfinite(minutes) or not 0 <= minutes <= 10080:
            raise HomeAssistantError("Hẹn giờ phải nằm trong 0–10080 phút")
        if action not in ("on", "off"):
            raise HomeAssistantError("Hẹn giờ chỉ hỗ trợ bật hoặc tắt")
        self._cancel_timer_callback()
        self._timer_deadline = None
        self._timer_action = None
        self._timer_error = None
        if minutes:
            self._arm_timer(time.time() + minutes * 60, action)
        self.async_write_ha_state()

    async def _send_current(
        self,
        *,
        mode: HVACMode | None = None,
        temp: float | None = None,
        fan: str | None = None,
        swing: str | None = None,
        swing_horizontal: str | None = None,
        preset: str | None = None,
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
                    swing_horizontal=(
                        swing_horizontal
                        if swing_horizontal is not None
                        else self._attr_swing_horizontal_mode
                    ),
                    preset=preset if preset is not None else self._attr_preset_mode,
                )
            return

        source = _source_mode(self._climate, target_mode)
        if source is None:
            raise HomeAssistantError(f"Profile không hỗ trợ chế độ {target_mode}")
        await self.manager.send_climate_state(
            self.device_id,
            mode=source,
            temp=temp if temp is not None else self._attr_target_temperature,
            fan=fan if fan is not None else self._attr_fan_mode,
            swing=swing if swing is not None else self._attr_swing_mode,
            swing_horizontal=(
                swing_horizontal
                if swing_horizontal is not None
                else self._attr_swing_horizontal_mode
            ),
            preset=preset if preset is not None else self._attr_preset_mode,
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

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        await self._send_current(swing_horizontal=swing_horizontal_mode)
        self._attr_swing_horizontal_mode = swing_horizontal_mode
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        # Prefer an explicit full-state matrix dimension when the profile has
        # one. Otherwise use a dedicated extra command such as Turbo/Sleep.
        has_matrix_preset = any(
            cell.get("preset") is not None
            for cell in (self._climate.get("cells") or [])
            if isinstance(cell, dict)
        )
        if has_matrix_preset or isinstance(self.device.get("protocol_engine"), dict):
            await self._send_current(preset=preset_mode)
        else:
            command = (self.device.get("commands") or {}).get(preset_mode)
            if not isinstance(command, dict) or not command.get("codes"):
                raise HomeAssistantError(f"Profile không có mã cho chế độ {preset_mode}")
            await self.manager.send_command(self.device_id, preset_mode)
        self._attr_preset_mode = preset_mode
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
