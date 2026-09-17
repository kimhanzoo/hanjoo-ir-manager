"""Remote platform for HanJoo IR."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import HanJooEntity
from .manager import HanJooIRManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager: HanJooIRManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    async_add_entities(
        HanJooRemote(manager, device_id)
        for device_id in manager.get_devices()
    )


class HanJooRemote(HanJooEntity, RemoteEntity):
    """Advanced/fallback remote entity for every HanJoo-managed device."""

    _attr_is_on = True
    _attr_assumed_state = True
    _attr_supported_features = (
        RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND
    )

    def __init__(self, manager: HanJooIRManager, device_id: str) -> None:
        HanJooEntity.__init__(self, manager, device_id, "remote")
        self._attr_name = "Remote"

    async def async_send_command(
        self, command: Iterable[str], **kwargs: Any
    ) -> None:
        repeats = kwargs.get("num_repeats")
        for command_id in command:
            await self.manager.send_command(
                self.device_id, str(command_id),
                repeat_override=int(repeats) if repeats is not None else None,
            )

    async def async_learn_command(self, **kwargs: Any) -> None:
        commands = kwargs.get("command")
        if not commands:
            raise HomeAssistantError("Hãy cung cấp command cần học")
        if isinstance(commands, str):
            commands = [commands]
        timeout = int(kwargs.get("timeout") or 20)
        device = self.device
        for command_id in commands:
            command_id = str(command_id)
            if command_id not in (device.get("commands") or {}):
                command_id = await self.manager.add_custom_command(
                    self.device_id, command_id
                )
            await self.manager.learn_command(self.device_id, command_id, timeout)

    async def async_delete_command(self, **kwargs: Any) -> None:
        commands = kwargs.get("command")
        if not commands:
            raise HomeAssistantError("Hãy cung cấp command cần xóa mã")
        if isinstance(commands, str):
            commands = [commands]
        for command_id in commands:
            await self.manager.clear_command(self.device_id, str(command_id))

    async def async_turn_on(self, **kwargs: Any) -> None:
        commands = self.device.get("commands") or {}
        for command_id in ("on", "power"):
            if commands.get(command_id, {}).get("codes"):
                await self.manager.send_command(self.device_id, command_id)
                return
        raise HomeAssistantError("Chưa có mã Bật/Power")

    async def async_turn_off(self, **kwargs: Any) -> None:
        commands = self.device.get("commands") or {}
        for command_id in ("off", "power"):
            if commands.get(command_id, {}).get("codes"):
                await self.manager.send_command(self.device_id, command_id)
                return
        raise HomeAssistantError("Chưa có mã Tắt/Power")
