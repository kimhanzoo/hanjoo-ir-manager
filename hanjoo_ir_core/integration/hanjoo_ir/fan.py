"""Semantic fan entities backed by IR commands."""
from __future__ import annotations

import math

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, DEVICE_TYPE_FAN
from .entity import HanJooEntity
from .manager import HanJooIRManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager: HanJooIRManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    async_add_entities(
        HanJooFan(manager, device_id)
        for device_id, device in manager.get_devices().items()
        if device.get("type") == DEVICE_TYPE_FAN
    )


class HanJooFan(HanJooEntity, FanEntity):
    """Optimistic fan entity mapping IR speed presets to percentages."""

    _attr_assumed_state = True

    def __init__(self, manager: HanJooIRManager, device_id: str) -> None:
        HanJooEntity.__init__(self, manager, device_id, "fan")
        self._attr_name = None
        self._attr_is_on = False
        self._attr_percentage = None
        self._attr_oscillating = False
        self._speed_commands = []
        self._refresh_capabilities()

    def _refresh_capabilities(self) -> None:
        self._speed_commands = self._find_speed_commands()
        features = FanEntityFeature(0)
        commands = self.device.get("commands") or {}
        if any(commands.get(k, {}).get("codes") for k in ("on", "power")):
            features |= FanEntityFeature.TURN_ON
        if any(commands.get(k, {}).get("codes") for k in ("off", "power")):
            features |= FanEntityFeature.TURN_OFF
        if self._speed_commands:
            features |= FanEntityFeature.SET_SPEED
        if commands.get("oscillate", {}).get("codes"):
            features |= FanEntityFeature.OSCILLATE
        self._attr_supported_features = features

    def _find_speed_commands(self) -> list[tuple[str, str]]:
        commands = self.device.get("commands") or {}
        out: list[tuple[str, str]] = []
        declared = [str(v) for v in (self.device.get("fan") or {}).get("speed_modes", [])]
        for speed in declared:
            command_id = f"speed:{speed}"
            if commands.get(command_id, {}).get("codes"):
                out.append((speed, command_id))
        if out:
            return out
        for command_id, item in commands.items():
            if not item.get("codes"):
                continue
            if command_id.startswith("speed:"):
                out.append((command_id.split(":", 1)[1], command_id))
            elif (
                command_id.startswith("speed_")
                and command_id.removeprefix("speed_").isdigit()
            ):
                out.append((command_id.split("_", 1)[1], command_id))
        return out

    def _apply_received_state(self, state: dict | None) -> None:
        if not state or state.get("type") != "command":
            return
        command_id = str(state.get("command_id") or "")
        if command_id == "on":
            self._attr_is_on = True
        elif command_id == "off":
            self._attr_is_on = False
            self._attr_percentage = None
        elif command_id == "power":
            self._attr_is_on = not bool(self._attr_is_on)
            if not self._attr_is_on:
                self._attr_percentage = None
        elif command_id == "oscillate":
            self._attr_oscillating = not bool(self._attr_oscillating)
        else:
            speed_id = None
            if command_id.startswith("speed:"):
                speed_id = command_id.split(":", 1)[1]
            elif command_id.startswith("speed_") and command_id.removeprefix("speed_").isdigit():
                speed_id = command_id.split("_", 1)[1]
            if speed_id is not None:
                for idx, (label, stored_id) in enumerate(self._speed_commands):
                    if stored_id == command_id or label == speed_id:
                        self._attr_percentage = round((idx + 1) * 100 / len(self._speed_commands))
                        self._attr_is_on = True
                        break

    @property
    def percentage_step(self) -> float | None:
        if not self._speed_commands:
            return None
        return 100 / len(self._speed_commands)

    async def _send_power(self, on: bool) -> None:
        commands = self.device.get("commands") or {}
        choices = ("on", "power") if on else ("off", "power")
        for command_id in choices:
            if commands.get(command_id, {}).get("codes"):
                await self.manager.send_command(self.device_id, command_id)
                self._attr_is_on = on
                self.async_write_ha_state()
                return
        raise HomeAssistantError("Chưa có mã nguồn phù hợp")

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs
    ) -> None:
        await self._send_power(True)
        if percentage is not None and self._speed_commands:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs) -> None:
        await self._send_power(False)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage <= 0:
            await self.async_turn_off()
            return
        if not self._speed_commands:
            raise HomeAssistantError("Thiết bị chưa có các mức tốc độ IR")
        position = max(
            0,
            min(
                len(self._speed_commands) - 1,
                math.ceil(percentage * len(self._speed_commands) / 100) - 1,
            ),
        )
        _, command_id = self._speed_commands[position]
        await self.manager.send_command(self.device_id, command_id)
        self._attr_percentage = round((position + 1) * 100 / len(self._speed_commands))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_oscillate(self, oscillating: bool) -> None:
        # Many IR fans expose only a toggle button. State is therefore optimistic.
        await self.manager.send_command(self.device_id, "oscillate")
        self._attr_oscillating = oscillating
        self.async_write_ha_state()
