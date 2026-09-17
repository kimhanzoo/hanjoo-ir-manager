"""Shared entity helpers for HanJoo IR."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .manager import HanJooIRManager


class HanJooEntity(Entity):
    """Base class for all semantic HanJoo entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, manager: HanJooIRManager, device_id: str, suffix: str) -> None:
        self.manager = manager
        self.device_id = device_id
        device = manager.get_device(device_id) or {}
        self._attr_unique_id = f"{manager.entry_id}_{device_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=str(device.get("name") or device_id),
            manufacturer=str(device.get("brand") or "HanJoo IR"),
            model=str(device.get("model") or device.get("kind") or "IR device"),
        )


    async def async_added_to_hass(self) -> None:
        """Refresh entity state/capabilities when HanJoo data changes."""
        await super().async_added_to_hass()

        def _updated() -> None:
            refresh = getattr(self, "_refresh_capabilities", None)
            if callable(refresh):
                refresh()
            apply_received = getattr(self, "_apply_received_state", None)
            if callable(apply_received):
                apply_received(self.manager.get_received_state(self.device_id))
            if self.hass is not None:
                self.async_write_ha_state()

        self.async_on_remove(self.manager.add_listener(_updated))

    @property
    def device(self):
        return self.manager.get_device(self.device_id) or {}

    @property
    def available(self) -> bool:
        device = self.manager.get_device(self.device_id)
        if not device:
            return False
        emitters = device.get("emitter_entity_ids") or []
        if not emitters:
            return False
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state != "unavailable"
            for entity_id in emitters
        )
