"""Button entities for extra/fallback IR commands."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DOMAIN,
    DEVICE_TYPE_CLIMATE,
    DEVICE_TYPE_FAN,
    DEVICE_TYPE_MEDIA_PLAYER,
    DEVICE_TYPE_REMOTE,
)
from .entity import HanJooEntity
from .manager import HanJooIRManager

_MEDIA_SEMANTIC = {
    "power", "on", "off", "volume_up", "volume_down", "mute",
    "play", "pause", "stop",
}
_FAN_SEMANTIC = {"power", "on", "off", "oscillate"}


def _is_extra(device: dict, command_id: str) -> bool:
    dtype = device.get("type")
    if dtype == DEVICE_TYPE_REMOTE:
        return True
    if dtype == DEVICE_TYPE_CLIMATE:
        return True
    if dtype == DEVICE_TYPE_MEDIA_PLAYER:
        return not (
            command_id in _MEDIA_SEMANTIC
            or command_id.startswith("source:")
        )
    if dtype == DEVICE_TYPE_FAN:
        return not (
            command_id in _FAN_SEMANTIC
            or command_id.startswith("speed:")
            or (
                command_id.startswith("speed_")
                and command_id.removeprefix("speed_").isdigit()
            )
        )
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    manager: HanJooIRManager = runtime["manager"]
    known: set[tuple[str, str]] = set()
    entities = []

    for device_id, device in manager.get_devices().items():
        for command_id in (device.get("commands") or {}):
            if _is_extra(device, command_id):
                known.add((device_id, command_id))
                entities.append(
                    HanJooCommandButton(manager, device_id, command_id)
                )

    async_add_entities(entities)

    def add_command_button(device_id: str, command_id: str) -> bool:
        """Materialize a newly-created fallback/custom ButtonEntity immediately."""
        device = manager.get_device(device_id)
        key = (device_id, command_id)
        if not device or key in known or not _is_extra(device, command_id):
            return False
        known.add(key)
        async_add_entities(
            [HanJooCommandButton(manager, device_id, command_id)]
        )
        return True

    runtime["add_command_button"] = add_command_button


class HanJooCommandButton(HanJooEntity, ButtonEntity):
    """One learned command not represented by a semantic entity method."""

    def __init__(
        self, manager: HanJooIRManager, device_id: str, command_id: str
    ) -> None:
        HanJooEntity.__init__(self, manager, device_id, f"button_{command_id}")
        self.command_id = command_id
        command = self.device.get("commands", {}).get(command_id, {})
        self._attr_name = str(command.get("name") or command_id)

    @property
    def available(self) -> bool:
        command = self.device.get("commands", {}).get(self.command_id)
        return (
            command is not None
            and bool(command.get("codes"))
            and super().available
        )

    async def async_press(self) -> None:
        await self.manager.send_command(self.device_id, self.command_id)
