"""HanJoo IR Manager integration."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_FILENAME,
    PANEL_ICON,
    PANEL_STATIC_PATH,
    PANEL_TITLE,
    PANEL_URL,
)
from .manager import HanJooIRManager
from .online_library import OnlineLibrary
from .websocket_api import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.REMOTE,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.FAN,
    Platform.CLIMATE,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager = HanJooIRManager(hass, entry.entry_id)
    await manager.async_load()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "manager": manager,
        "online_library": OnlineLibrary(hass, manager),
        "entry": entry,
    }

    async_register_websocket_commands(hass)
    await _async_register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await manager.async_start_receiver_monitoring()
    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("_panel_registered"):
        return

    bundle_path = Path(__file__).parent / "frontend" / PANEL_FILENAME
    if not bundle_path.exists():
        _LOGGER.error("HanJoo IR frontend bundle is missing: %s", bundle_path)
        return

    raw = await hass.async_add_executor_job(bundle_path.read_bytes)
    content_hash = hashlib.sha256(raw).hexdigest()[:10]
    try:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    PANEL_STATIC_PATH,
                    str(bundle_path),
                    cache_headers=False,
                )
            ]
        )
    except RuntimeError:
        _LOGGER.debug("HanJoo IR static path was already registered")

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="hanjoo-ir-panel",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL,
        config={},
        require_admin=True,
        embed_iframe=False,
        trust_external=False,
        module_url=f"{PANEL_STATIC_PATH}?v={content_hash}",
    )
    data["_panel_registered"] = True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime and runtime.get("manager"):
        await runtime["manager"].async_stop_receiver_monitoring()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    # IMPORTANT: do not remove the sidebar panel during a config-entry reload.
    # Entity-topology reloads are normal after adding/deleting a device; removing
    # the route even briefly makes Home Assistant redirect the user to Overview.
    # The panel is removed only when the config entry itself is deleted.
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Deliberately keep the storage file. Reinstalling the integration should
    # not silently erase a user's learned IR library. It remains part of HA Backup.
    try:
        frontend.async_remove_panel(hass, PANEL_URL)
    except Exception:
        _LOGGER.debug("HanJoo IR panel was already removed")
    hass.data.get(DOMAIN, {}).pop("_panel_registered", None)
