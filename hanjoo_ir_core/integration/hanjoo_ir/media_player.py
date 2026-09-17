"""Semantic media-player entities for IR TVs/projectors/audio devices."""
from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, DEVICE_TYPE_MEDIA_PLAYER
from .entity import HanJooEntity
from .manager import HanJooIRManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager: HanJooIRManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    async_add_entities(
        HanJooMediaPlayer(manager, device_id)
        for device_id, device in manager.get_devices().items()
        if device.get("type") == DEVICE_TYPE_MEDIA_PLAYER
    )


class HanJooMediaPlayer(HanJooEntity, MediaPlayerEntity):
    """Optimistic semantic media-player wrapper around learned/profile IR."""

    _attr_assumed_state = True

    def __init__(self, manager: HanJooIRManager, device_id: str) -> None:
        HanJooEntity.__init__(self, manager, device_id, "media_player")
        self._attr_name = None
        self._attr_state = MediaPlayerState.OFF
        self._attr_is_volume_muted = False
        if self.device.get("kind") == "tv":
            self._attr_device_class = MediaPlayerDeviceClass.TV
        self._refresh_capabilities()

    def _refresh_capabilities(self) -> None:
        commands = self.device.get("commands") or {}
        features = MediaPlayerEntityFeature(0)
        if any(commands.get(k, {}).get("codes") for k in ("on", "power")):
            features |= MediaPlayerEntityFeature.TURN_ON
        if any(commands.get(k, {}).get("codes") for k in ("off", "power")):
            features |= MediaPlayerEntityFeature.TURN_OFF
        if commands.get("volume_up", {}).get("codes") and commands.get(
            "volume_down", {}
        ).get("codes"):
            features |= MediaPlayerEntityFeature.VOLUME_STEP
        if commands.get("mute", {}).get("codes"):
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        sources = [
            command_id.split(":", 1)[1]
            for command_id, item in commands.items()
            if command_id.startswith("source:") and item.get("codes")
        ]
        if sources:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
            self._attr_source_list = sources
        if commands.get("play", {}).get("codes"):
            features |= MediaPlayerEntityFeature.PLAY
        if commands.get("pause", {}).get("codes"):
            features |= MediaPlayerEntityFeature.PAUSE
        if commands.get("stop", {}).get("codes"):
            features |= MediaPlayerEntityFeature.STOP
        self._attr_supported_features = features

    def _apply_received_state(self, state: dict | None) -> None:
        if not state or state.get("type") != "command":
            return
        command_id = str(state.get("command_id") or "")
        if command_id == "on":
            self._attr_state = MediaPlayerState.ON
        elif command_id == "off":
            self._attr_state = MediaPlayerState.OFF
        elif command_id == "power":
            self._attr_state = (
                MediaPlayerState.OFF
                if self._attr_state != MediaPlayerState.OFF
                else MediaPlayerState.ON
            )
        elif command_id == "mute":
            self._attr_is_volume_muted = not bool(self._attr_is_volume_muted)
        elif command_id == "play":
            self._attr_state = MediaPlayerState.PLAYING
        elif command_id == "pause":
            self._attr_state = MediaPlayerState.PAUSED
        elif command_id == "stop":
            self._attr_state = MediaPlayerState.IDLE
        elif command_id.startswith("source:"):
            self._attr_source = command_id.split(":", 1)[1]

    async def _send_first(self, ids: tuple[str, ...]) -> str:
        commands = self.device.get("commands") or {}
        for command_id in ids:
            if commands.get(command_id, {}).get("codes"):
                await self.manager.send_command(self.device_id, command_id)
                return command_id
        raise HomeAssistantError(f"Chưa học/có lệnh: {', '.join(ids)}")

    async def async_turn_on(self) -> None:
        await self._send_first(("on", "power"))
        self._attr_state = MediaPlayerState.ON
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        await self._send_first(("off", "power"))
        self._attr_state = MediaPlayerState.OFF
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        await self.manager.send_command(self.device_id, "volume_up")

    async def async_volume_down(self) -> None:
        await self.manager.send_command(self.device_id, "volume_down")

    async def async_mute_volume(self, mute: bool) -> None:
        await self.manager.send_command(self.device_id, "mute")
        self._attr_is_volume_muted = mute
        self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        await self.manager.send_command(self.device_id, f"source:{source}")
        self._attr_source = source
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        await self.manager.send_command(self.device_id, "play")
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        await self.manager.send_command(self.device_id, "pause")
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        await self.manager.send_command(self.device_id, "stop")
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()
