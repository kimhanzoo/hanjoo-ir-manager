"""Persistent database and runtime manager for HanJoo IR."""
from __future__ import annotations

import asyncio
import time
from copy import deepcopy
import re
import unicodedata
from typing import Any, Callable
from types import SimpleNamespace
import uuid

from homeassistant.components.infrared import (
    InfraredReceivedSignal,
    async_get_emitters,
    async_get_receivers,
    async_send_command,
    async_subscribe_receiver,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_FREQUENCY,
    DEFAULT_LEARN_TIMEOUT,
    DOMAIN,
    DEVICE_TYPE_CLIMATE,
    DEVICE_TYPE_FAN,
    DEVICE_TYPE_MEDIA_PLAYER,
    DEVICE_TYPE_REMOTE,
    FALLBACK_KIND_TO_TYPE,
    REMOTE_TEMPLATES,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .importers import (
    ImportResult,
    export_hanjoo_library,
    export_hanjoo_profile,
    import_profiles_text,
    profile_summary,
)
from .ir_code import code_from_timings, command_from_code
from .core_client import HanJooCoreClient, HanJooCoreError


def _slug(value: str) -> str:
    """Create a stable ASCII command id while preserving Vietnamese readability."""
    value = value.replace("Đ", "D").replace("đ", "d")
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return value or "item"


def _copy_command(command: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(command)
    item.setdefault("name", "Command")
    item.setdefault("codes", [])
    item["send_count"] = max(1, int(item.get("send_count") or 1))
    return item


class HanJooIRManager:
    """Own the HA-side IR library and dispatch commands to infrared emitters."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self.data: dict[str, Any] = {
            "schema": 2,
            "devices": {},
            "profiles": {},
            "online_sources": {
                "smartir": True,
                "flipper_irdb": False,
            },
            "discovery_sources": {
                "native_ha": True,
                "protocol_engine": True,
                "learn_custom": True,
            },
        }
        self._listeners: set[Callable[[], None]] = set()
        self._learn_lock = asyncio.Lock()
        self._pending_captures: dict[str, dict[str, Any]] = {}
        self._active_capture_futures: dict[
            str, asyncio.Future[InfraredReceivedSignal]
        ] = {}
        self._receiver_unsubs: dict[str, Callable[[], None]] = {}
        self._receiver_monitor_started = False
        self._receiver_refresh_lock = asyncio.Lock()
        self._rx_states: dict[str, dict[str, Any]] = {}
        self._rx_sequence = 0
        self._suppress_receivers_until: dict[str, float] = {}
        # Receivers currently reserved by the explicit Learn workflow.
        # Background remote-state synchronization ignores these receivers until
        # capture finishes/cancels/times out.
        self._learning_receivers: set[str] = set()
        self.core = HanJooCoreClient(hass)

    async def async_load(self) -> None:
        """Load persisted data and migrate the v0.1 proof-of-concept if needed."""
        loaded = await self.store.async_load()
        if isinstance(loaded, dict):
            self.data = loaded
        self.data.setdefault("devices", {})
        self.data.setdefault("profiles", {})
        sources = self.data.setdefault("online_sources", {})
        sources.setdefault("smartir", True)
        sources.setdefault("flipper_irdb", False)
        discovery = self.data.setdefault("discovery_sources", {})
        discovery.setdefault("native_ha", True)
        discovery.setdefault("protocol_engine", True)
        discovery.setdefault("learn_custom", True)
        changed = False
        if self.data.get("schema") != 2:
            changed = self._migrate_v01() or changed
            self.data["schema"] = 2
            changed = True
        # Defensive normalization: one damaged row should not take down HA.
        for device_id, device in list(self.data["devices"].items()):
            if not isinstance(device, dict):
                self.data["devices"].pop(device_id, None)
                changed = True
                continue
            device.setdefault("id", device_id)
            device.setdefault("commands", {})
            device.setdefault("emitter_entity_ids", [])
            device.setdefault("receiver_entity_id", None)
            device.setdefault("source", "learned")
        if changed:
            await self.async_save()

    def _migrate_v01(self) -> bool:
        """Migrate v0.1.x device rows in place.

        AC rows from v0.1 are intentionally migrated as generic remotes:
        v0.1 incorrectly modeled Temp+/- as independent commands. Preserving
        the learned codes is safe; pretending they form a climate state model
        would be misleading.
        """
        changed = False
        migrated: dict[str, Any] = {}
        old_devices = self.data.get("devices", {})
        if not isinstance(old_devices, dict):
            old_devices = {}
        for key, old in old_devices.items():
            if not isinstance(old, dict):
                continue
            old_type = str(old.get("type") or "custom")
            kind = old_type
            semantic = {
                "tv": DEVICE_TYPE_MEDIA_PLAYER,
                "projector": DEVICE_TYPE_MEDIA_PLAYER,
                "fan": DEVICE_TYPE_FAN,
            }.get(old_type, DEVICE_TYPE_REMOTE)
            if old_type == "air_conditioner":
                kind = "legacy_air_conditioner"
                semantic = DEVICE_TYPE_REMOTE

            commands: dict[str, Any] = {}
            for command_id, old_cmd in (old.get("commands") or {}).items():
                if not isinstance(old_cmd, dict):
                    continue
                code = old_cmd.get("code")
                commands[str(command_id)] = {
                    "name": str(old_cmd.get("name") or command_id),
                    "codes": [deepcopy(code)] if isinstance(code, dict) else [],
                    "send_count": 1,
                }

            emitter = old.get("emitter")
            migrated[str(key)] = {
                "id": str(old.get("id") or key),
                "name": str(old.get("name") or key),
                "type": semantic,
                "kind": kind,
                "brand": None,
                "model": None,
                "source": "legacy_v0_1",
                "emitter_entity_ids": [emitter] if emitter else [],
                "receiver_entity_id": old.get("receiver"),
                "commands": commands,
            }
            changed = True
        self.data["devices"] = migrated
        self.data.setdefault("profiles", {})
        return changed

    async def async_save(self) -> None:
        await self.store.async_save(self.data)
        self._notify()
        self._schedule_receiver_refresh()

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        @callback
        def remove() -> None:
            self._listeners.discard(listener)
        return remove

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def get_received_state(self, device_id: str) -> dict[str, Any] | None:
        """Return the latest receiver-derived state for a logical device."""
        state = self._rx_states.get(device_id)
        return deepcopy(state) if state else None

    async def async_start_receiver_monitoring(self) -> None:
        """Subscribe continuously to all receivers assigned to HanJoo devices."""
        self._receiver_monitor_started = True
        await self.async_refresh_receiver_monitoring()

    async def async_stop_receiver_monitoring(self) -> None:
        """Remove all continuous receiver subscriptions."""
        self._receiver_monitor_started = False
        for unsubscribe in list(self._receiver_unsubs.values()):
            try:
                unsubscribe()
            except Exception:
                pass
        self._receiver_unsubs.clear()

    async def async_refresh_receiver_monitoring(self) -> None:
        """Reconcile receiver subscriptions after devices/routing change."""
        if not self._receiver_monitor_started:
            return
        async with self._receiver_refresh_lock:
            wanted = {
                str(device.get("receiver_entity_id"))
                for device in self.get_devices().values()
                if device.get("receiver_entity_id")
            }
            for receiver in list(self._receiver_unsubs):
                if receiver not in wanted:
                    try:
                        self._receiver_unsubs.pop(receiver)()
                    except Exception:
                        pass

            for receiver in sorted(wanted):
                if receiver in self._receiver_unsubs:
                    continue

                @callback
                def got_signal(
                    signal: InfraredReceivedSignal,
                    receiver_entity_id: str = receiver,
                ) -> None:
                    self._handle_background_signal(receiver_entity_id, signal)

                try:
                    self._receiver_unsubs[receiver] = async_subscribe_receiver(
                        self.hass, receiver, got_signal
                    )
                except HomeAssistantError:
                    # A temporarily unavailable receiver should not prevent the
                    # whole HanJoo integration from loading.
                    continue

    def _schedule_receiver_refresh(self) -> None:
        if not self._receiver_monitor_started:
            return
        create_task = getattr(self.hass, "async_create_task", None)
        if callable(create_task):
            create_task(self.async_refresh_receiver_monitoring())

    @staticmethod
    def _normalize_rx_timings(values: list[Any]) -> list[int]:
        out: list[int] = []
        for idx, value in enumerate(values):
            try:
                if hasattr(value, "duration"):
                    value = getattr(value, "duration")
                duration = abs(int(value))
            except (TypeError, ValueError):
                return []
            if duration <= 0:
                continue
            out.append(duration if idx % 2 == 0 else -duration)
        return out

    @staticmethod
    def _raw_timings_match(
        received: list[int],
        stored: list[int],
        *,
        tolerance: float = 0.30,
    ) -> bool:
        """Compare captures while ignoring variable long trailing silence."""
        if not received or not stored:
            return False
        # Raw captures commonly differ only in their final "idle" gap.
        r = list(received)
        s = list(stored)
        if r and r[-1] < 0:
            r = r[:-1]
        if s and s[-1] < 0:
            s = s[:-1]
        if len(r) != len(s) or len(r) < 4:
            return False
        for actual, expected in zip(r, s):
            a = abs(int(actual))
            e = abs(int(expected))
            if (actual > 0) != (expected > 0):
                return False
            if abs(a - e) > max(160, e * tolerance):
                return False
        return True

    def _match_stored_signal(
        self,
        device: dict[str, Any],
        timings: list[int],
        modulation: int | None,
    ) -> dict[str, Any] | None:
        """Match learned/imported RAW codes to semantic command/state metadata."""
        def code_matches(code: dict[str, Any]) -> bool:
            if not isinstance(code, dict) or code.get("format") != "raw":
                return False
            stored = code.get("timings")
            if not isinstance(stored, list):
                return False
            frequency = int(code.get("frequency") or DEFAULT_FREQUENCY)
            if modulation:
                # Carrier measurements can be rough; reject only clear mismatch.
                if abs(int(modulation) - frequency) > 6000:
                    return False
            return self._raw_timings_match(timings, stored)

        climate = device.get("climate") or {}
        for key in ("off", "on"):
            item = climate.get(key)
            if isinstance(item, dict) and any(
                code_matches(code) for code in item.get("codes") or []
            ):
                return {
                    "type": "climate",
                    "mode": "off" if key == "off" else None,
                    "power": key == "on",
                    "matched": key,
                }

        for cell in climate.get("cells") or []:
            if any(code_matches(code) for code in cell.get("codes") or []):
                return {
                    "type": "climate",
                    "mode": cell.get("mode"),
                    "temp": cell.get("temp"),
                    "fan": cell.get("fan"),
                    "swing": cell.get("swing"),
                    "power": True,
                    "matched": "state",
                }

        for command_id, item in (device.get("commands") or {}).items():
            if any(code_matches(code) for code in item.get("codes") or []):
                return {
                    "type": "command",
                    "command_id": str(command_id),
                    "matched": str(command_id),
                }
        return None

    def _record_received_state(
        self,
        device_id: str,
        update: dict[str, Any],
        *,
        receiver: str,
    ) -> None:
        previous = self._rx_states.get(device_id, {})
        merged = dict(previous)
        # Protocol/command updates should not erase fields they don't carry.
        for key, value in update.items():
            if value is not None:
                merged[key] = value
        self._rx_sequence += 1
        merged["sequence"] = self._rx_sequence
        merged["receiver"] = receiver
        merged["received_at"] = time.time()
        self._rx_states[device_id] = merged
        self._notify()

    def _handle_background_signal(
        self,
        receiver: str,
        signal: InfraredReceivedSignal,
    ) -> None:
        """Decode/match an IR signal and push semantic state into HA entities."""
        # Learn has absolute priority. The dedicated capture subscription still
        # receives the signal, while the background state-sync path stays quiet.
        if receiver in self._learning_receivers:
            return
        if time.monotonic() < self._suppress_receivers_until.get(receiver, 0.0):
            return
        timings = self._normalize_rx_timings(list(signal.timings))
        if len(timings) < 4:
            return
        modulation = getattr(signal, "modulation", None)

        for device_id, device in self.get_devices().items():
            if device.get("receiver_entity_id") != receiver:
                continue

            protocol = device.get("protocol_engine")
            if isinstance(protocol, dict):
                # Protocol decoding lives in the compiled Core add-on. Do not
                # block the infrared receiver callback while waiting for local RPC.
                self.hass.async_create_task(
                    self._async_decode_protocol_signal(
                        device_id, protocol, receiver, list(timings)
                    )
                )
                continue

            matched = self._match_stored_signal(device, timings, modulation)
            if matched:
                matched["source"] = "raw_match"
                self._record_received_state(device_id, matched, receiver=receiver)

    async def _async_decode_protocol_signal(
        self,
        device_id: str,
        protocol: dict[str, Any],
        receiver: str,
        timings: list[int],
    ) -> None:
        try:
            decoded = await self.core.decode(protocol, timings)
        except HanJooCoreError:
            return
        if not decoded:
            return
        update = {
            "type": "climate",
            "source": "protocol_decoder",
            **decoded,
        }
        self._record_received_state(device_id, update, receiver=receiver)

    def get_online_source_settings(self) -> dict[str, bool]:
        sources = self.data.setdefault("online_sources", {})
        return {
            "smartir": bool(sources.get("smartir", True)),
            "flipper_irdb": bool(sources.get("flipper_irdb", False)),
        }

    async def set_online_source_enabled(self, source_id: str, enabled: bool) -> None:
        if source_id not in {"smartir", "flipper_irdb"}:
            raise HomeAssistantError("Nguồn thư viện này chưa được HanJoo hỗ trợ")
        self.data.setdefault("online_sources", {})[source_id] = bool(enabled)
        await self.async_save()

    def get_discovery_source_settings(self) -> dict[str, bool]:
        """Return all user-selectable input sources used by auto discovery."""
        discovery = self.data.setdefault("discovery_sources", {})
        online = self.get_online_source_settings()
        return {
            "native_ha": bool(discovery.get("native_ha", True)),
            "protocol_engine": bool(discovery.get("protocol_engine", True)),
            "smartir": bool(online.get("smartir", True)),
            "flipper_irdb": bool(online.get("flipper_irdb", False)),
            "learn_custom": bool(discovery.get("learn_custom", True)),
        }

    async def set_discovery_source_enabled(
        self, source_id: str, enabled: bool
    ) -> None:
        if source_id in {"smartir", "flipper_irdb"}:
            await self.set_online_source_enabled(source_id, enabled)
            return
        if source_id not in {"native_ha", "protocol_engine", "learn_custom"}:
            raise HomeAssistantError("Nguồn tìm thiết bị này chưa được hỗ trợ")
        self.data.setdefault("discovery_sources", {})[source_id] = bool(enabled)
        await self.async_save()

    def get_devices(self) -> dict[str, dict[str, Any]]:
        return self.data["devices"]

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        return self.get_devices().get(device_id)

    def get_profiles(self) -> dict[str, dict[str, Any]]:
        return self.data["profiles"]

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        return self.get_profiles().get(profile_id)

    def device_summary(self, device: dict[str, Any]) -> dict[str, Any]:
        climate = device.get("climate") or {}
        commands = device.get("commands") or {}
        learned = sum(1 for item in commands.values() if item.get("codes"))
        registry = dr.async_get(self.hass)
        ha_device = registry.async_get_device(
            identifiers={(DOMAIN, str(device.get("id")))}
        )
        has_rx_match_data = (
            isinstance(device.get("protocol_engine"), dict)
            or any(item.get("codes") for item in commands.values())
            or bool(climate.get("on") and climate.get("on", {}).get("codes"))
            or bool(climate.get("off") and climate.get("off", {}).get("codes"))
            or any(cell.get("codes") for cell in climate.get("cells") or [])
        )
        return {
            "id": device.get("id"),
            "name": device.get("name"),
            "type": device.get("type"),
            "kind": device.get("kind"),
            "brand": device.get("brand"),
            "model": device.get("model"),
            "source": device.get("source"),
            "profile_id": device.get("profile_id"),
            "emitter_entity_ids": list(device.get("emitter_entity_ids") or []),
            "receiver_entity_id": device.get("receiver_entity_id"),
            "two_way_enabled": bool(device.get("receiver_entity_id")) and has_rx_match_data,
            "last_received_state": self.get_received_state(str(device.get("id"))),
            "command_count": len(commands),
            "learned_command_count": learned,
            "climate_cell_count": len(climate.get("cells") or []),
            "ha_device_id": ha_device.id if ha_device else None,
        }

    def device_full(self, device_id: str) -> dict[str, Any] | None:
        device = self.get_device(device_id)
        if not device:
            return None
        full = deepcopy(device)
        full["summary"] = self.device_summary(device)
        return full

    async def list_hardware(self) -> dict[str, list[str]]:
        return {
            "emitters": list(async_get_emitters(self.hass)),
            "receivers": list(async_get_receivers(self.hass)),
        }

    async def create_custom_device(
        self,
        *,
        name: str,
        kind: str,
        emitters: list[str],
        receiver: str | None,
    ) -> str:
        semantic = FALLBACK_KIND_TO_TYPE.get(kind, DEVICE_TYPE_REMOTE)
        device_id = self._unique_device_id(name)
        commands: dict[str, Any] = {}
        for command_id, label in REMOTE_TEMPLATES.get(kind, {}).items():
            commands[command_id] = {
                "name": label,
                "codes": [],
                "send_count": 1,
            }

        device: dict[str, Any] = {
            "id": device_id,
            "name": name.strip() or device_id,
            "type": semantic,
            "kind": kind,
            "brand": None,
            "model": None,
            "source": "learned",
            "profile_id": None,
            "emitter_entity_ids": list(dict.fromkeys(emitters)),
            "receiver_entity_id": receiver,
            "commands": commands,
        }
        if semantic == DEVICE_TYPE_CLIMATE:
            device["climate"] = {
                "min_temp": 16.0,
                "max_temp": 30.0,
                "precision": 1.0,
                "unit": "C",
                "modes": ["cool", "dry", "fan_only", "heat", "auto"],
                "fan_modes": ["auto", "low", "medium", "high"],
                "swing_modes": ["off", "on"],
                "off": None,
                "on": None,
                "cells": [],
            }
            # Stateful climate does not get fake Temp+ / Temp- buttons.
            device["commands"] = {
                "turbo": {"name": "Turbo", "codes": [], "send_count": 1},
                "sleep": {"name": "Sleep", "codes": [], "send_count": 1},
                "timer": {"name": "Hẹn giờ", "codes": [], "send_count": 1},
            }

        self.get_devices()[device_id] = device
        await self.async_save()
        return device_id

    async def create_device_from_profile(
        self,
        *,
        profile_id: str,
        name: str,
        emitters: list[str],
        receiver: str | None,
    ) -> str:
        profile = self.get_profile(profile_id)
        if not profile:
            raise HomeAssistantError("Không tìm thấy profile")
        device_id = self._unique_device_id(name or str(profile.get("name") or "IR device"))
        device = deepcopy(profile)
        device["id"] = device_id
        device["name"] = name.strip() or str(profile.get("name") or device_id)
        device["profile_id"] = profile_id
        device["source"] = f"profile:{profile.get('source') or 'imported'}"
        device["emitter_entity_ids"] = list(dict.fromkeys(emitters))
        device["receiver_entity_id"] = receiver
        # Import-only metadata should not be copied to every runtime device.
        device.pop("import_warnings", None)
        device.pop("import_filename", None)
        self.get_devices()[device_id] = device
        await self.async_save()
        return device_id

    async def create_device_from_protocol(
        self,
        *,
        candidate_id: str,
        name: str,
        emitters: list[str],
        receiver: str | None,
    ) -> str:
        """Create a runtime device backed by the local dynamic protocol engine."""
        try:
            profile = await self.core.profile(candidate_id)
        except HanJooCoreError as err:
            raise HomeAssistantError(str(err)) from err
        device_id = self._unique_device_id(name or str(profile.get("name") or "IR device"))
        device = deepcopy(profile)
        device["id"] = device_id
        device["name"] = name.strip() or str(profile.get("name") or device_id)
        device["profile_id"] = None
        device["source"] = "protocol_engine"
        device["emitter_entity_ids"] = list(dict.fromkeys(emitters))
        device["receiver_entity_id"] = receiver
        self.get_devices()[device_id] = device
        await self.async_save()
        return device_id

    async def delete_device(self, device_id: str) -> None:
        self.get_devices().pop(device_id, None)
        # Remove the HA device-registry node too; core removes its attached
        # entity-registry rows. This prevents deleted dynamic buttons/entities
        # from lingering as stale entities after the integration reloads.
        registry = dr.async_get(self.hass)
        ha_device = registry.async_get_device(identifiers={(DOMAIN, device_id)})
        if ha_device is not None:
            registry.async_remove_device(ha_device.id)
        await self.async_save()

    async def update_routing(
        self, device_id: str, emitters: list[str], receiver: str | None
    ) -> None:
        device = self._require_device(device_id)
        device["emitter_entity_ids"] = list(dict.fromkeys(emitters))
        device["receiver_entity_id"] = receiver
        await self.async_save()

    async def add_custom_command(self, device_id: str, name: str) -> str:
        device = self._require_device(device_id)
        base = _slug(name)
        command_id = base
        suffix = 2
        while command_id in device["commands"]:
            command_id = f"{base}_{suffix}"
            suffix += 1
        device["commands"][command_id] = {
            "name": name.strip() or command_id,
            "codes": [],
            "send_count": 1,
        }
        await self.async_save()
        return command_id

    async def delete_command(self, device_id: str, command_id: str) -> None:
        device = self._require_device(device_id)
        device.get("commands", {}).pop(command_id, None)
        # Remove the corresponding entity-registry row so a deleted custom/
        # fallback button does not linger as a permanently unavailable ghost.
        registry = er.async_get(self.hass)
        unique_id = f"{self.entry_id}_{device_id}_button_{command_id}"
        for entry in er.async_entries_for_config_entry(registry, self.entry_id):
            if entry.unique_id == unique_id:
                registry.async_remove(entry.entity_id)
                break
        await self.async_save()

    async def clear_command(self, device_id: str, command_id: str) -> None:
        device = self._require_device(device_id)
        item = device.get("commands", {}).get(command_id)
        if not item:
            raise HomeAssistantError("Không tìm thấy lệnh")
        item["codes"] = []

        await self.async_save()

    @staticmethod
    def _capture_quality(timings: list[int]) -> tuple[str, str | None]:
        """Classify obviously incomplete/noise captures without guessing protocol."""
        if len(timings) < 6:
            return (
                "invalid",
                "Tín hiệu quá ngắn để coi là một lệnh IR hoàn chỉnh "
                f"({len(timings)} timing). Hãy học lại.",
            )

        positive = sum(1 for value in timings if value > 0)
        negative = sum(1 for value in timings if value < 0)
        if positive < 3 or negative < 2:
            return (
                "invalid",
                "Cấu trúc mark/space không giống một frame IR hoàn chỉnh. "
                "Hãy học lại.",
            )

        if len(timings) < 20:
            return (
                "warning",
                "Frame khá ngắn hoặc có thể chỉ là một burst phụ của lệnh nhiều frame. "
                "HanJoo sẽ chờ gom các burst liên tiếp trước khi kết luận.",
            )

        return ("good", None)

    def _cleanup_pending_captures(self, now: float) -> None:
        stale = [
            token
            for token, pending in self._pending_captures.items()
            if now - float(pending.get("created") or 0) > 180
        ]
        for token in stale:
            self._pending_captures.pop(token, None)

    async def capture_receiver_for_identification(
        self,
        receiver_entity_id: str,
        timeout: int = DEFAULT_LEARN_TIMEOUT,
    ) -> dict[str, Any]:
        """Capture one temporary frame for pre-device remote identification.

        Nothing is persisted. The normal Learn lock/reservation is reused so
        background remote-state synchronization cannot consume the same frame.
        """
        receiver = str(receiver_entity_id or "").strip()
        if not receiver:
            raise HomeAssistantError("Hãy chọn IR Receiver")
        device = {
            "id": f"__identify__:{receiver}",
            "receiver_entity_id": receiver,
        }
        signal = await self._capture_signal(device, timeout)
        code = code_from_timings(
            signal.timings, signal.modulation or DEFAULT_FREQUENCY
        )
        timings = list(code.get("timings") or [])
        quality, quality_message = self._capture_quality(timings)
        total_us = sum(abs(int(value)) for value in timings)
        protocol_hints: list[dict[str, Any]] = []
        try:
            protocol_hints = await self.core.classify_timings(timings)
        except HanJooCoreError:
            protocol_hints = []
        return {
            "frequency": int(code.get("frequency") or DEFAULT_FREQUENCY),
            "timings": timings,
            "timing_count": len(timings),
            "frame_count": int(getattr(signal, "frame_count", 1) or 1),
            "protocol_hints": protocol_hints,
            "duration_ms": round(total_us / 1000, 2),
            "preview": timings[:24],
            "truncated": len(timings) > 24,
            "quality": quality,
            "quality_message": quality_message,
            "usable": quality != "invalid",
        }

    async def capture_for_preview(
        self,
        device_id: str,
        timeout: int = DEFAULT_LEARN_TIMEOUT,
    ) -> dict[str, Any]:
        """Capture one IR frame but do not persist it yet."""
        device = self._require_device(device_id)
        signal = await self._capture_signal(device, timeout)
        code = code_from_timings(
            signal.timings, signal.modulation or DEFAULT_FREQUENCY
        )
        timings = code.get("timings") or []
        quality, quality_message = self._capture_quality(timings)

        loop = asyncio.get_running_loop()
        now = loop.time()
        self._cleanup_pending_captures(now)

        token = uuid.uuid4().hex
        self._pending_captures[token] = {
            "device_id": device_id,
            "code": code,
            "created": now,
            "quality": quality,
            "quality_message": quality_message,
        }

        total_us = sum(abs(int(value)) for value in timings)
        return {
            "token": token,
            "frequency": int(code.get("frequency") or DEFAULT_FREQUENCY),
            "timing_count": len(timings),
            "frame_count": int(getattr(signal, "frame_count", 1) or 1),
            "duration_ms": round(total_us / 1000, 2),
            "preview": timings[:24],
            "truncated": len(timings) > 24,
            "quality": quality,
            "quality_message": quality_message,
            "can_save": quality != "invalid",
        }

    def _consume_capture(self, token: str, device_id: str) -> dict[str, Any]:
        pending = self._pending_captures.pop(token, None)
        if not pending:
            raise HomeAssistantError(
                "Mã IR tạm đã hết hạn hoặc không còn tồn tại. Hãy học lại."
            )
        if pending.get("device_id") != device_id:
            raise HomeAssistantError("Mã IR tạm không thuộc thiết bị này")
        age = asyncio.get_running_loop().time() - float(pending.get("created") or 0)
        if age > 180:
            raise HomeAssistantError("Mã IR tạm đã quá 3 phút. Hãy học lại.")
        if pending.get("quality") == "invalid":
            raise HomeAssistantError(
                str(
                    pending.get("quality_message")
                    or "Tín hiệu IR không đủ chất lượng để lưu. Hãy học lại."
                )
            )
        return deepcopy(pending["code"])

    def discard_capture(self, token: str) -> None:
        self._pending_captures.pop(token, None)

    async def save_captured_command(
        self, device_id: str, command_id: str, token: str
    ) -> None:
        device = self._require_device(device_id)
        item = device.get("commands", {}).get(command_id)
        if not item:
            raise HomeAssistantError("Không tìm thấy nút cần lưu")
        item["codes"] = [self._consume_capture(token, device_id)]
        item["send_count"] = 1
        await self.async_save()

    async def save_captured_climate_state(
        self,
        device_id: str,
        token: str,
        *,
        mode: str,
        temp: float | None,
        fan: str | None,
        swing: str | None,
        power: str = "state",
    ) -> None:
        device = self._require_device(device_id)
        if device.get("type") != DEVICE_TYPE_CLIMATE:
            raise HomeAssistantError("Thiết bị này không phải climate")
        climate = device.setdefault("climate", {})
        learned = {
            "codes": [self._consume_capture(token, device_id)],
            "send_count": 1,
        }
        if power == "off":
            climate["off"] = learned
        elif power == "on":
            climate["on"] = learned
        else:
            cell = {
                "mode": str(mode),
                "temp": None if temp is None else float(temp),
                "fan": fan or None,
                "swing": swing or None,
                "extras": [],
                **learned,
            }
            cells = climate.setdefault("cells", [])
            key = self._climate_key(cell)
            for idx, old in enumerate(cells):
                if self._climate_key(old) == key:
                    cells[idx] = cell
                    break
            else:
                cells.append(cell)
            self._extend_unique(climate.setdefault("modes", []), str(mode))
            if fan:
                self._extend_unique(climate.setdefault("fan_modes", []), fan)
            if swing:
                self._extend_unique(climate.setdefault("swing_modes", []), swing)
        await self.async_save()

    async def learn_command(
        self,
        device_id: str,
        command_id: str,
        timeout: int = DEFAULT_LEARN_TIMEOUT,
    ) -> None:
        """Backward-compatible one-step learning used by remote.learn_command."""
        preview = await self.capture_for_preview(device_id, timeout)
        await self.save_captured_command(device_id, command_id, preview["token"])

    async def learn_climate_state(
        self,
        device_id: str,
        *,
        mode: str,
        temp: float | None,
        fan: str | None,
        swing: str | None,
        power: str = "state",
        timeout: int = DEFAULT_LEARN_TIMEOUT,
    ) -> None:
        """Backward-compatible one-step climate learning."""
        preview = await self.capture_for_preview(device_id, timeout)
        await self.save_captured_climate_state(
            device_id,
            preview["token"],
            mode=mode,
            temp=temp,
            fan=fan,
            swing=swing,
            power=power,
        )

    def cancel_capture_wait(self, device_id: str) -> None:
        """Cancel an in-progress capture for one logical device."""
        future = self._active_capture_futures.get(device_id)
        if future is not None and not future.done():
            future.set_exception(HomeAssistantError("Đã hủy học tín hiệu IR"))

    async def _capture_signal(
        self, device: dict[str, Any], timeout: int
    ) -> Any:
        """Capture one *physical button press*, not merely one receiver event.

        Some A/C remotes (notably several Daikin families) transmit one command
        as multiple bursts/frames separated by short gaps. Home Assistant may
        publish those bursts as separate InfraredReceivedSignal events. The old
        one-shot capture returned after the first event, so the automatic wizard
        immediately armed the next step and accidentally consumed the remaining
        bursts as 25 C / 26 C / OFF samples.

        We now keep the receiver armed until it has been quiet for a short guard
        interval. Every event belonging to that press is concatenated, preserving
        the inter-frame space, and returned as one logical sample. Holding a key
        keeps extending the quiet timer, so the next wizard step cannot steal a
        repeat from the same press.
        """
        receiver = device.get("receiver_entity_id")
        if not receiver:
            raise HomeAssistantError("Thiết bị chưa chọn IR Receiver")
        timeout = max(2, min(int(timeout), 120))
        quiet_window = 0.45

        async with self._learn_lock:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[Any] = loop.create_future()
            device_id = str(device.get("id") or "")
            if device_id:
                self._active_capture_futures[device_id] = future

            self._learning_receivers.add(str(receiver))
            frames: list[list[int]] = []
            modulations: list[int] = []
            quiet_handle: asyncio.TimerHandle | None = None

            def finish_press() -> None:
                nonlocal quiet_handle
                quiet_handle = None
                if future.done() or not frames:
                    return
                merged: list[int] = []
                for frame in frames:
                    if not frame:
                        continue
                    # Each HA receiver event starts with a mark. If the previous
                    # event ended without an explicit space, insert a conservative
                    # inter-frame idle gap instead of creating two adjacent marks.
                    if merged and merged[-1] > 0 and frame[0] > 0:
                        merged.append(-10_000)
                    merged.extend(frame)
                modulation = modulations[0] if modulations else DEFAULT_FREQUENCY
                future.set_result(
                    SimpleNamespace(
                        timings=merged,
                        modulation=modulation,
                        frame_count=len(frames),
                    )
                )

            @callback
            def got_signal(signal: InfraredReceivedSignal) -> None:
                nonlocal quiet_handle
                if future.done():
                    return
                frame = self._normalize_rx_timings(list(signal.timings))
                if not frame:
                    return
                frames.append(frame)
                modulation = getattr(signal, "modulation", None)
                if modulation:
                    try:
                        modulations.append(int(modulation))
                    except (TypeError, ValueError):
                        pass
                if quiet_handle is not None:
                    quiet_handle.cancel()
                quiet_handle = loop.call_later(quiet_window, finish_press)

            try:
                unsubscribe = async_subscribe_receiver(self.hass, receiver, got_signal)
            except HomeAssistantError:
                raise
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except TimeoutError as err:
                raise HomeAssistantError(
                    f"Hết {timeout} giây nhưng chưa nhận được tín hiệu IR hoàn chỉnh"
                ) from err
            finally:
                if quiet_handle is not None:
                    quiet_handle.cancel()
                unsubscribe()
                self._learning_receivers.discard(str(receiver))
                if device_id and self._active_capture_futures.get(device_id) is future:
                    self._active_capture_futures.pop(device_id, None)

    async def send_command(
        self, device_id: str, command_id: str, repeat_override: int | None = None
    ) -> None:
        device = self._require_device(device_id)
        item = device.get("commands", {}).get(command_id)
        if not item:
            raise HomeAssistantError(f"Không tìm thấy lệnh '{command_id}'")
        await self._send_item(device, item, repeat_override=repeat_override)

    async def _send_item(
        self,
        device: dict[str, Any],
        item: dict[str, Any] | None,
        *,
        repeat_override: int | None = None,
    ) -> None:
        if not item or not item.get("codes"):
            raise HomeAssistantError("Lệnh/trạng thái này chưa có mã IR")
        emitters = list(device.get("emitter_entity_ids") or [])
        if not emitters:
            raise HomeAssistantError("Thiết bị chưa chọn IR Transmitter")
        send_count = (
            max(1, int(repeat_override))
            if repeat_override is not None
            else max(1, int(item.get("send_count") or 1))
        )
        # IR receivers commonly hear reflections from the local transmitter.
        # Ignore a short window so a command sent by HanJoo is not mistaken for
        # a physical-remote state update (especially dangerous for toggles).
        suppress_until = time.monotonic() + 0.65
        for receiver in {
            str(d.get("receiver_entity_id"))
            for d in self.get_devices().values()
            if d.get("receiver_entity_id")
        }:
            self._suppress_receivers_until[receiver] = suppress_until

        for emitter in emitters:
            for iteration in range(send_count):
                for code_index, code in enumerate(item["codes"]):
                    await async_send_command(self.hass, emitter, command_from_code(code))
                    if code_index + 1 < len(item["codes"]):
                        await asyncio.sleep(0.04)
                if iteration + 1 < send_count:
                    await asyncio.sleep(0.08)

    async def send_climate_power(self, device_id: str, on: bool) -> bool:
        """Send a dedicated or dynamically-generated climate on/off frame."""
        device = self._require_device(device_id)
        protocol = device.get("protocol_engine")
        if isinstance(protocol, dict):
            if on:
                # Let HanJooClimate call send_climate_state() with the entity's
                # current mode/temp/fan so turning on does not reset user state.
                return False
            try:
                item = await self.core.generate(
                    protocol,
                    mode="off",
                    temp=None,
                    fan=None,
                )
            except HanJooCoreError as err:
                raise HomeAssistantError(str(err)) from err
            await self._send_item(device, item)
            return True

        climate = device.get("climate") or {}
        item = climate.get("on" if on else "off")
        if not item or not item.get("codes"):
            return False
        await self._send_item(device, item)
        return True

    async def send_climate_state(
        self,
        device_id: str,
        *,
        mode: str | None,
        temp: float | None,
        fan: str | None,
        swing: str | None,
    ) -> dict[str, Any]:
        device = self._require_device(device_id)
        climate = device.get("climate") or {}
        protocol = device.get("protocol_engine")
        if isinstance(protocol, dict):
            try:
                item = await self.core.generate(
                    protocol,
                    mode=mode,
                    temp=temp,
                    fan=fan,
                )
            except HanJooCoreError as err:
                raise HomeAssistantError(str(err)) from err
            await self._send_item(device, item)
            return {
                "mode": "off" if mode in (None, "off") else mode,
                "temp": temp,
                "fan": fan,
                "swing": swing,
            }

        if mode in (None, "off"):
            await self._send_item(device, climate.get("off"))
            return {"mode": "off", "temp": temp, "fan": fan, "swing": swing}

        match = self.find_climate_cell(
            climate, mode=mode, temp=temp, fan=fan, swing=swing
        )
        if match is None:
            raise HomeAssistantError(
                "Chưa có mã IR cho đúng tổ hợp trạng thái này. "
                "Hãy học thêm trạng thái hoặc dùng profile đầy đủ."
            )
        await self._send_item(device, match)
        return {
            "mode": match.get("mode"),
            "temp": match.get("temp"),
            "fan": match.get("fan"),
            "swing": match.get("swing"),
        }

    @staticmethod
    def find_climate_cell(
        climate: dict[str, Any],
        *,
        mode: str | None,
        temp: float | None,
        fan: str | None,
        swing: str | None,
    ) -> dict[str, Any] | None:
        """Return the most specific compatible climate state cell.

        Imported matrices can have branches without temperature/fan/swing.
        Missing dimensions in a cell act as wildcards; a cell that explicitly
        specifies a dimension must match the requested value.
        """
        candidates: list[tuple[int, dict[str, Any]]] = []
        for cell in climate.get("cells") or []:
            if str(cell.get("mode")) != str(mode):
                continue
            score = 10
            mismatch = False
            for field, requested in (("fan", fan), ("swing", swing)):
                stored = cell.get(field)
                if stored is None:
                    continue
                if requested is None or str(stored) != str(requested):
                    mismatch = True
                    break
                score += 2
            if mismatch:
                continue

            stored_temp = cell.get("temp")
            if stored_temp is not None:
                if temp is None:
                    continue
                precision = float(climate.get("precision") or 1)
                if abs(float(stored_temp) - float(temp)) > max(0.01, precision / 2):
                    continue
                score += 3
            candidates.append((score, cell))

        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates[0][1]

    async def store_import_result(self, result: ImportResult) -> str:
        """Persist one already-normalized profile result."""
        profile = result.profile
        profile_id = str(profile["id"])
        self.get_profiles()[profile_id] = profile
        await self.async_save()
        return profile_id

    async def import_profiles(self, text: str, filename: str = "") -> list[ImportResult]:
        results = import_profiles_text(text, filename)
        for result in results:
            profile = result.profile
            self.get_profiles()[str(profile["id"])] = profile
        await self.async_save()
        return results

    async def import_profile(self, text: str, filename: str = "") -> ImportResult:
        """Backward-compatible single-profile helper used by tests/services."""
        results = await self.import_profiles(text, filename)
        if len(results) != 1:
            raise HomeAssistantError("File chứa nhiều profile; hãy dùng import_profiles")
        return results[0]

    async def delete_profile(self, profile_id: str) -> None:
        self.get_profiles().pop(profile_id, None)
        await self.async_save()

    def export_device(self, device_id: str) -> str:
        """Export a runtime device as a portable HanJoo profile."""
        device = self._require_device(device_id)
        profile = deepcopy(device)
        profile["id"] = uuid.uuid4().hex
        profile["source"] = "user_export"
        for key in (
            "emitter_entity_ids",
            "receiver_entity_id",
            "profile_id",
            "summary",
        ):
            profile.pop(key, None)
        return export_hanjoo_profile(profile)

    def export_library(self) -> str:
        return export_hanjoo_library(list(self.get_profiles().values()))

    def export_profile(self, profile_id: str) -> str:
        profile = self.get_profile(profile_id)
        if not profile:
            raise HomeAssistantError("Không tìm thấy profile")
        return export_hanjoo_profile(profile)

    async def test_protocol_candidate(
        self, candidate_id: str, emitter: str
    ) -> dict[str, Any]:
        """Generate and send a safe representative state without storing it."""
        try:
            profile = await self.core.profile(candidate_id)
            protocol = profile.get("protocol_engine") or {}
            climate = profile.get("climate") or {}
            temp = max(
                float(climate.get("min_temp", 16)),
                min(float(climate.get("max_temp", 30)), 25.0),
            )
            item = await self.core.generate(
                protocol,
                mode="cool",
                temp=temp,
                fan="auto",
            )
        except HanJooCoreError as err:
            raise HomeAssistantError(str(err)) from err
        pseudo = {"emitter_entity_ids": [emitter]}
        await self._send_item(pseudo, item)
        return {
            "sent": True,
            "label": f"Cool {int(temp)}°C · Fan Auto",
            "raw_value": item.get("raw_value"),
        }

    async def test_profile_data(
        self, profile: dict[str, Any], emitter: str
    ) -> dict[str, Any]:
        """Send one representative command from a profile without storing it."""
        pseudo = {
            "emitter_entity_ids": [emitter],
        }
        if profile.get("type") == DEVICE_TYPE_CLIMATE:
            climate = profile.get("climate") or {}
            item = climate.get("on") or climate.get("off")
            label = "Power"
            if not item and climate.get("cells"):
                item = climate["cells"][0]
                label = self._climate_key(item)
        else:
            commands = profile.get("commands") or {}
            preferred = next(
                (
                    key
                    for key in ("power", "on", "off")
                    if commands.get(key, {}).get("codes")
                ),
                None,
            )
            if preferred is None:
                preferred = next(
                    (key for key, val in commands.items() if val.get("codes")), None
                )
            if preferred is None:
                raise HomeAssistantError("Profile không có mã có thể test")
            item = commands[preferred]
            label = item.get("name") or preferred
        if not item:
            raise HomeAssistantError("Profile không có mã có thể test")
        await self._send_item(pseudo, item)
        return {"sent": True, "label": label}

    async def test_profile(self, profile_id: str, emitter: str) -> dict[str, Any]:
        profile = self.get_profile(profile_id)
        if not profile:
            raise HomeAssistantError("Không tìm thấy profile")
        return await self.test_profile_data(profile, emitter)

    def profile_summaries(self) -> list[dict[str, Any]]:
        return [profile_summary(profile) for profile in self.get_profiles().values()]

    def _require_device(self, device_id: str) -> dict[str, Any]:
        device = self.get_device(device_id)
        if not device:
            raise HomeAssistantError("Không tìm thấy thiết bị")
        return device

    def _unique_device_id(self, name: str) -> str:
        base = _slug(name)
        candidate = base
        n = 2
        while candidate in self.get_devices():
            candidate = f"{base}_{n}"
            n += 1
        return candidate

    @staticmethod
    def _climate_key(cell: dict[str, Any]) -> str:
        return "|".join(
            str(cell.get(key) if cell.get(key) is not None else "")
            for key in ("mode", "fan", "swing", "temp")
        )

    @staticmethod
    def _extend_unique(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)
