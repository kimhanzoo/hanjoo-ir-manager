"""WebSocket API used by the HanJoo IR administration panel."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import (
    AUTHOR_NAME,
    AUTHOR_FACEBOOK,
    AUTHOR_EMAIL,
    DEFAULT_LEARN_TIMEOUT,
    DOMAIN,
    FALLBACK_KIND_TO_TYPE,
    NATIVE_INTEGRATIONS,
    VERSION,
    WS_PREFIX,
)
from .importers import ProfileImportError
from .ir_code import IRCodeError
from .manager import HanJooIRManager
from .online_library import OnlineLibrary, OnlineLibraryError
from .protocol_engine import ENGINE_SOURCE_ID

_LOGGER = logging.getLogger(__name__)


def _runtime(hass: HomeAssistant) -> tuple[HanJooIRManager, str] | None:
    entries = hass.data.get(DOMAIN, {})
    for entry_id, value in entries.items():
        if isinstance(value, dict) and isinstance(value.get("manager"), HanJooIRManager):
            return value["manager"], entry_id
    return None


def _reload_soon(hass: HomeAssistant, entry_id: str) -> None:
    async def _delayed_reload() -> None:
        # Let the websocket response reach the panel before its config entry
        # unload briefly removes/recreates dynamic entities and the sidebar.
        await asyncio.sleep(0.35)
        await hass.config_entries.async_reload(entry_id)

    hass.async_create_task(_delayed_reload())


def _error(
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    err: Exception,
) -> None:
    if isinstance(err, (HomeAssistantError, ProfileImportError, IRCodeError, OnlineLibraryError, ValueError)):
        connection.send_error(msg["id"], "hanjoo_ir_error", str(err))
        return
    _LOGGER.exception("Unexpected HanJoo IR websocket error", exc_info=err)
    connection.send_error(msg["id"], "unknown_error", "Lỗi không xác định; xem Home Assistant Logs")


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register panel commands once per HA process."""
    flag = f"{DOMAIN}_ws_registered"
    if hass.data.get(flag):
        return
    hass.data[flag] = True
    for handler in (
        ws_summary,
        ws_hardware,
        ws_native_catalog,
        ws_native_devices,
        ws_sources,
        ws_source_set,
        ws_discover,
        ws_remote_identify_capture,
        ws_protocol_identify,
        ws_fusion_identify,
        ws_identify_test_capture,
        ws_protocol_test,
        ws_device_create_from_protocol,
        ws_online_sources,
        ws_online_source_set,
        ws_online_source_refresh,
        ws_online_search,
        ws_online_test,
        ws_online_install,
        ws_devices,
        ws_device,
        ws_device_create_custom,
        ws_device_create_from_captures,
        ws_device_create_from_profile,
        ws_device_delete,
        ws_device_update_routing,
        ws_device_add_command,
        ws_device_delete_command,
        ws_device_clear_command,
        ws_device_capture,
        ws_device_save_capture,
        ws_device_discard_capture,
        ws_device_learn,
        ws_device_learn_climate,
        ws_device_send,
        ws_device_export,
        ws_profiles,
        ws_profile_import,
        ws_profile_delete,
        ws_profile_export,
        ws_profile_export_library,
        ws_profile_test,
    ):
        websocket_api.async_register_command(hass, handler)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{WS_PREFIX}/summary"})
@websocket_api.async_response
async def ws_summary(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    hardware = await manager.list_hardware()
    connection.send_result(
        msg["id"],
        {
            "version": VERSION,
            "author": AUTHOR_NAME,
            "author_facebook": AUTHOR_FACEBOOK,
            "author_email": AUTHOR_EMAIL,
            "devices": len(manager.get_devices()),
            "profiles": len(manager.get_profiles()),
            "emitters": len(hardware["emitters"]),
            "receivers": len(hardware["receivers"]),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{WS_PREFIX}/hardware"})
@websocket_api.async_response
async def ws_hardware(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_result(msg["id"], {"emitters": [], "receivers": []})
        return
    manager, _ = runtime
    connection.send_result(msg["id"], await manager.list_hardware())


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{WS_PREFIX}/native_catalog"})
@websocket_api.async_response
async def ws_native_catalog(hass, connection, msg) -> None:
    result = []
    for item in NATIVE_INTEGRATIONS:
        row = dict(item)
        row["installed_entries"] = len(hass.config_entries.async_entries(item["domain"]))
        result.append(row)
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{WS_PREFIX}/native_devices"})
@websocket_api.async_response
async def ws_native_devices(hass, connection, msg) -> None:
    """Aggregate official HA IR device integrations into the HanJoo panel."""
    registry = dr.async_get(hass)
    catalog = {item["domain"]: item for item in NATIVE_INTEGRATIONS}
    rows = []
    for domain, item in catalog.items():
        for entry in hass.config_entries.async_entries(domain):
            devices = list(dr.async_entries_for_config_entry(registry, entry.entry_id))
            if devices:
                for device in devices:
                    rows.append(
                        {
                            "id": f"native:{domain}:{entry.entry_id}:{device.id}",
                            "name": device.name_by_user or device.name or entry.title,
                            "native": True,
                            "native_domain": domain,
                            "entry_id": entry.entry_id,
                            "ha_device_id": device.id,
                            "brand": item.get("brand"),
                            "source": "native_ha",
                            "semantic_entities": item.get("semantic_entities", []),
                            "device_types": item.get("device_types", []),
                        }
                    )
            else:
                rows.append(
                    {
                        "id": f"native:{domain}:{entry.entry_id}",
                        "name": entry.title,
                        "native": True,
                        "native_domain": domain,
                        "entry_id": entry.entry_id,
                        "ha_device_id": None,
                        "brand": item.get("brand"),
                        "source": "native_ha",
                        "semantic_entities": item.get("semantic_entities", []),
                        "device_types": item.get("device_types", []),
                    }
                )
    connection.send_result(msg["id"], rows)


def _online_library(hass: HomeAssistant) -> OnlineLibrary | None:
    runtime = _runtime(hass)
    if runtime is None:
        return None
    _manager, entry_id = runtime
    data = hass.data.get(DOMAIN, {}).get(entry_id, {})
    online = data.get("online_library")
    return online if isinstance(online, OnlineLibrary) else None



async def _source_descriptors(
    hass: HomeAssistant,
    manager: HanJooIRManager,
    online: OnlineLibrary | None,
) -> list[dict[str, Any]]:
    settings = manager.get_discovery_source_settings()
    native_installed = sum(
        len(hass.config_entries.async_entries(item["domain"]))
        for item in NATIVE_INTEGRATIONS
    )
    rows: list[dict[str, Any]] = [
        {
            "id": "native_ha",
            "name": "Native Home Assistant",
            "enabled": settings["native_ha"],
            "can_toggle": True,
            "local": True,
            "catalog_count": len(NATIVE_INTEGRATIONS),
            "installed_count": native_installed,
            "kinds": sorted(
                {
                    kind
                    for item in NATIVE_INTEGRATIONS
                    for kind in item.get("device_types", [])
                }
            ),
            "note_vi": (
                "Ưu tiên cao nhất khi Home Assistant có integration IR chính thức; "
                "entity và config flow do HA quản lý."
            ),
            "note_en": (
                "Highest priority when Home Assistant provides an official IR integration; "
                "entities and config flows are managed by Home Assistant."
            ),
        },
        await manager.core.source_descriptor(settings["protocol_engine"]),
    ]
    online_rows = {row["id"]: row for row in (online.sources() if online else [])}
    for source_id in ("smartir", "flipper_irdb"):
        if source_id in online_rows:
            row = dict(online_rows[source_id])
            row["enabled"] = settings[source_id]
            rows.append(row)
    rows.append(
        {
            "id": "learn_custom",
            "name": "Learn / Custom",
            "enabled": settings["learn_custom"],
            "can_toggle": True,
            "local": True,
            "catalog_count": None,
            "kinds": list(FALLBACK_KIND_TO_TYPE),
            "note_vi": (
                "Fallback cuối cùng: học trực tiếp remote thật và tự thêm nút. "
                "Không cần Internet."
            ),
            "note_en": (
                "Final fallback: learn directly from the physical remote and add custom buttons. "
                "No Internet connection is required."
            ),
        }
    )
    return rows


def _kind_matches_native(kind: str | None, device_types: list[str]) -> bool:
    if not kind:
        return True
    aliases = {
        "climate": {"air_conditioner"},
        "air_conditioner": {"air_conditioner"},
        "media_player": {"tv", "speaker", "soundbar", "receiver", "amplifier", "projector"},
        "tv": {"tv"},
        "speaker": {"speaker", "soundbar"},
        "soundbar": {"soundbar", "speaker"},
        "receiver": {"receiver", "amplifier"},
        "projector": {"projector"},
    }
    wanted = aliases.get(str(kind).lower(), {str(kind).lower()})
    return bool(wanted & {str(x).lower() for x in device_types})


def _native_identification_candidates(
    hass: HomeAssistant,
    result: dict[str, Any],
    kind_hint: str,
) -> list[dict[str, Any]]:
    """Map strong Core brand/type evidence to official Home Assistant IR integrations.

    Native HA is a device-management preference, not an IR decoder. We only
    surface it after Core has decoded the remote strongly enough to establish a
    brand. This prevents a broad native catalog entry from influencing protocol
    recognition while still giving an official HA integration highest priority
    once the identity is known.
    """
    candidates = list(result.get("candidates") or [])
    recommended_id = str(result.get("recommended_id") or "")
    detected_kind = None
    brand_rows: dict[str, dict[str, Any]] = {}

    for row in candidates:
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        brand = str(candidate.get("brand") or "").strip()
        if not brand:
            continue
        confidence = int(row.get("confidence") or 0)
        key = brand.casefold()
        previous = brand_rows.get(key)
        if previous is None or confidence > int(previous.get("confidence") or 0):
            brand_rows[key] = {
                "brand": brand,
                "confidence": confidence,
                "matched_captures": int(row.get("matched_captures") or 0),
                "capture_count": int(row.get("capture_count") or 0),
                "core_candidate_id": str(candidate.get("id") or ""),
                "kind": str(candidate.get("kind") or ""),
            }
        if str(candidate.get("id") or "") == recommended_id:
            detected_kind = str(candidate.get("kind") or "") or detected_kind

    for hint in result.get("brand_hints") or []:
        brand = str(hint or "").strip()
        if brand:
            brand_rows.setdefault(
                brand.casefold(),
                {
                    "brand": brand,
                    "confidence": 0,
                    "matched_captures": 0,
                    "capture_count": 0,
                    "core_candidate_id": "",
                    "kind": "",
                },
            )

    requested_kind = str(kind_hint or "").strip().lower()
    if requested_kind in {"", "auto"}:
        requested_kind = str(detected_kind or "").strip().lower()
    if requested_kind == "custom":
        requested_kind = ""

    out: list[dict[str, Any]] = []
    for native in NATIVE_INTEGRATIONS:
        brand = str(native.get("brand") or "").strip()
        evidence = brand_rows.get(brand.casefold())
        if evidence is None:
            continue

        device_types = [str(x).lower() for x in native.get("device_types") or []]
        if requested_kind and not _kind_matches_native(requested_kind, device_types):
            continue

        # In auto mode, a generic non-A/C protocol often reaches Brain as
        # kind="custom". If the matching official integration has exactly one
        # non-A/C device type (e.g. LG/Samsung TV), that type is unambiguous
        # enough for routing without pretending Core decoded the product model.
        inferred_native_kind = requested_kind
        if not inferred_native_kind:
            evidence_kind = str(evidence.get("kind") or "").strip().lower()
            if evidence_kind and evidence_kind not in {"custom", "auto"}:
                inferred_native_kind = evidence_kind
            else:
                non_ac_types = [x for x in device_types if x != "air_conditioner"]
                if len(non_ac_types) == 1:
                    inferred_native_kind = non_ac_types[0]

        confidence = int(evidence.get("confidence") or 0)
        core_id = str(evidence.get("core_candidate_id") or "")
        strong = (
            bool(result.get("recommended"))
            and bool(core_id)
            and core_id == recommended_id
            and confidence >= 90
        )
        native_kind = inferred_native_kind or (native.get("device_types") or ["custom"])[0]

        domain = str(native["domain"])
        installed = len(hass.config_entries.async_entries(domain))
        candidate_id = f"native_ha:{domain}"
        out.append(
            {
                "candidate": {
                    "id": candidate_id,
                    "brand": brand,
                    "model": str(native.get("name") or ""),
                    "kind": native_kind,
                    "source": "native_ha",
                    "action": "native",
                    "native_domain": domain,
                    "installed_entries": installed,
                    "device_types": list(native.get("device_types") or []),
                    "recognition_only": False,
                },
                "group_id": f"native_ha:{domain}",
                "confidence": confidence,
                "matched_captures": int(evidence.get("matched_captures") or 0),
                "capture_count": int(evidence.get("capture_count") or 0),
                "distinct_matches": None,
                "evidence_sources": ["hanjoo_core_brain", "native_ha_catalog"],
                "evidence": "official_ha_integration_for_detected_brand",
                "_core_recommended": strong,
                "_native_priority": True,
            }
        )

    out.sort(
        key=lambda row: (
            -int(bool(row.get("_core_recommended"))),
            -int((row.get("candidate") or {}).get("installed_entries") or 0),
            -int(row.get("confidence") or 0),
        )
    )
    return out


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in ("brand", "model", "name", "note", "kind", "controller")
    ).lower()


def _rank_candidate(
    candidate: dict[str, Any],
    *,
    query: str,
    kind: str | None,
) -> int:
    """Rank explicit searches by textual relevance first, source priority second."""
    source = candidate.get("source")
    is_ac = kind in {"air_conditioner", "climate"} or candidate.get("kind") == "air_conditioner"
    if is_ac:
        source_base = {
            "native_ha": 500,
            "protocol_engine": 460,
            "smartir": 420,
            "flipper_irdb": 410,
            "saved_profile": 360,
            "learn_custom": 50,
        }.get(source, 100)
    else:
        source_base = {
            "native_ha": 500,
            "smartir": 440,
            "flipper_irdb": 430,
            "protocol_engine": 400,
            "saved_profile": 360,
            "learn_custom": 50,
        }.get(source, 100)

    q = " ".join(query.lower().split())
    if not q:
        return source_base

    brand = str(candidate.get("brand") or "").lower().strip()
    model = str(candidate.get("model") or "").lower().strip()
    name = str(candidate.get("name") or "").lower().strip()
    text = _candidate_text(candidate)

    # A specific model match must always outrank a broad source-priority match.
    relevance = 0
    if q == model:
        relevance = 7
    elif model and model.startswith(q):
        relevance = 6
    elif q == name:
        relevance = 6
    elif name and name.startswith(q):
        relevance = 5
    elif q == brand:
        relevance = 5
    elif brand and brand.startswith(q):
        relevance = 4
    elif q in model or q in name:
        relevance = 3
    elif q in brand:
        relevance = 2

    tokens = [token for token in re.split(r"[^a-z0-9]+", q) if token]
    token_hits = sum(1 for token in tokens if token in text)
    relevance_score = relevance * 1000 + min(token_hits, 9) * 40

    # Saved profiles remain reusable search results, but being previously saved
    # is not itself a reason to outrank live Protocol/SmartIR/Flipper matches.
    return relevance_score + source_base


def _protocol_group_id(protocol: dict[str, Any], candidate: dict[str, Any]) -> str:
    """Group catalog aliases/models that are backed by the same actual protocol."""
    engine = str(protocol.get("engine") or candidate.get("engine") or "protocol").strip().lower()
    variant = str(
        protocol.get("variant")
        or protocol.get("protocol")
        or protocol.get("family")
        or candidate.get("variant")
        or candidate.get("protocol")
        or ""
    ).strip().lower()
    if variant:
        return f"protocol:{engine}:{variant}"
    cid = str(candidate.get("id") or "")
    # Broad irtxrx ids are already protocol-family ids.
    if cid.startswith("protocol:irtxrx:"):
        return cid.lower()
    return cid


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{WS_PREFIX}/sources"})
@websocket_api.async_response
async def ws_sources(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_result(msg["id"], [])
        return
    manager, _entry_id = runtime
    connection.send_result(
        msg["id"],
        await _source_descriptors(hass, manager, _online_library(hass)),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/source/set",
        vol.Required("source_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_source_set(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _entry_id = runtime
    source_id = msg["source_id"]
    enabled = bool(msg["enabled"])
    try:
        if source_id in {"smartir", "flipper_irdb"}:
            online = _online_library(hass)
            if online is None:
                raise HomeAssistantError("Online Library chưa sẵn sàng")
            result = await online.async_set_source_enabled(source_id, enabled)
        else:
            await manager.set_discovery_source_enabled(source_id, enabled)
            result = {"source_id": source_id, "enabled": enabled}
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/discover",
        vol.Optional("query", default=""): str,
        vol.Optional("kind"): vol.Any(str, None),
        vol.Optional("limit", default=80): vol.All(int, vol.Range(min=1, max=200)),
    }
)
@websocket_api.async_response
async def ws_discover(hass, connection, msg) -> None:
    """Search all enabled sources and return one ranked candidate list."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_result(msg["id"], {"items": [], "sources": []})
        return
    manager, _entry_id = runtime
    settings = manager.get_discovery_source_settings()
    query = str(msg.get("query") or "").strip()
    kind = msg.get("kind")
    limit = int(msg.get("limit") or 80)
    items: list[dict[str, Any]] = []
    errors: list[str] = []

    # 1) Official HA native integrations.
    if settings.get("native_ha", True):
        q = query.lower()
        for native in NATIVE_INTEGRATIONS:
            if not _kind_matches_native(kind, list(native.get("device_types") or [])):
                continue
            text = (
                f"{native.get('brand','')} {native.get('name','')} "
                f"{' '.join(native.get('device_types') or [])} {native.get('note','')}"
            ).lower()
            if q and q not in text:
                continue
            items.append(
                {
                    "id": f"native:{native['domain']}",
                    "source": "native_ha",
                    "source_name": "Native HA",
                    "action": "native",
                    "native_domain": native["domain"],
                    "name": native["name"],
                    "brand": native.get("brand"),
                    "model": "",
                    "kind": (native.get("device_types") or ["custom"])[0],
                    "device_types": list(native.get("device_types") or []),
                    "note": native.get("note"),
                    "installed_entries": len(
                        hass.config_entries.async_entries(native["domain"])
                    ),
                }
            )

    # 2) Local dynamic protocol engine.
    if settings.get("protocol_engine", True):
        try:
            protocol_rows = await manager.core.search(query, kind, limit=limit)
            for row in protocol_rows:
                row["action"] = "protocol"
                items.append(row)
        except Exception as err:
            errors.append({"source": "protocol_engine", "error": str(err)})

    # 3) Already saved/imported profiles. They are local and known-good enough
    # to rank above re-downloading the same class of online profile.
    q = query.lower()
    for profile in manager.get_profiles().values():
        profile_kind = str(profile.get("kind") or "")
        profile_type = str(profile.get("type") or "")
        if kind and kind not in {profile_kind, profile_type}:
            aliases = {"air_conditioner": "climate", "tv": "media_player"}
            if aliases.get(kind) not in {profile_kind, profile_type}:
                continue
        text = (
            f"{profile.get('name','')} {profile.get('brand','')} "
            f"{profile.get('model','')} {profile_kind} {profile_type}"
        ).lower()
        if q and q not in text:
            continue
        items.append(
            {
                "id": f"saved:{profile.get('id')}",
                "profile_id": profile.get("id"),
                "source": "saved_profile",
                "source_name": "Profile đã lưu",
                "action": "saved",
                "name": profile.get("name"),
                "brand": profile.get("brand"),
                "model": profile.get("model"),
                "kind": profile_kind or profile_type,
                "note": f"{len(profile.get('commands') or {})} lệnh đã lưu",
            }
        )

    # 4) SmartIR + Flipper aggregation, respecting their toggles.
    if settings.get("smartir") or settings.get("flipper_irdb"):
        online = _online_library(hass)
        if online is not None:
            try:
                result = await online.async_search(query, kind, limit=limit)
                for row in result.get("items") or []:
                    row = dict(row)
                    row["action"] = "online"
                    row["source_name"] = (
                        "Flipper-IRDB"
                        if row.get("source") == "flipper_irdb"
                        else "SmartIR"
                    )
                    items.append(row)
            except Exception as err:
                errors.append(str(err))

    # 5) Learn/Custom is always an explicit last candidate when enabled.
    if settings.get("learn_custom", True):
        fallback_kind = kind or "custom"
        items.append(
            {
                "id": f"custom:{fallback_kind}",
                "source": "learn_custom",
                "source_name": "Learn / Custom",
                "action": "custom",
                "name": "Tự học từ remote",
                "brand": None,
                "model": None,
                "kind": fallback_kind,
                "note": "Dùng khi các cấu hình phía trên không điều khiển đúng thiết bị.",
            }
        )

    for item in items:
        item["score"] = _rank_candidate(item, query=query, kind=kind)
    items.sort(
        key=lambda row: (
            -int(row.get("score") or 0),
            str(row.get("brand") or "").lower(),
            str(row.get("model") or row.get("name") or "").lower(),
        )
    )
    items = items[:limit]
    if items:
        q_norm = " ".join(query.lower().split())
        recommendable = [
            row for row in items
            if row.get("source") != "learn_custom"
        ]
        chosen = recommendable[0] if recommendable else items[0]

        # A previously saved profile is useful to reuse, but a broad brand-only
        # query (e.g. "lg") should prefer a live protocol/library candidate.
        if chosen.get("source") == "saved_profile" and q_norm:
            saved_brand = str(chosen.get("brand") or "").lower().strip()
            saved_model = str(chosen.get("model") or "").lower().strip()
            saved_name = str(chosen.get("name") or "").lower().strip()
            specific_saved = q_norm in {saved_model, saved_name} and len(q_norm) >= 4
            if not specific_saved:
                alternative = next(
                    (
                        row for row in recommendable
                        if row.get("source") != "saved_profile"
                    ),
                    None,
                )
                if alternative is not None:
                    chosen = alternative
        chosen["recommended"] = True

    connection.send_result(
        msg["id"],
        {
            "items": items,
            "sources": await _source_descriptors(hass, manager, _online_library(hass)),
            "errors": errors,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/remote_identify/capture",
        vol.Required("receiver"): str,
        vol.Optional("timeout", default=DEFAULT_LEARN_TIMEOUT): vol.All(int, vol.Range(min=2, max=120)),
    }
)
@websocket_api.async_response
async def ws_remote_identify_capture(hass, connection, msg) -> None:
    """Capture a temporary physical-remote frame before a device exists."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _entry_id = runtime
    try:
        result = await manager.capture_receiver_for_identification(
            msg["receiver"], int(msg.get("timeout", DEFAULT_LEARN_TIMEOUT))
        )
        # Capture only; analysis identifies the protocol after the sample set is complete.
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/protocol/identify",
        vol.Required("captures"): [dict],
    }
)
@websocket_api.async_response
async def ws_protocol_identify(hass, connection, msg) -> None:
    """Ask protected Core to rank protocols from guided remote captures."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _entry_id = runtime
    captures = list(msg.get("captures") or [])[:6]
    if len(captures) < 2:
        connection.send_error(msg["id"], "not_enough_captures", "Cần ít nhất 2 mẫu remote")
        return
    cleaned = []
    try:
        for capture in captures:
            timings = [int(x) for x in list(capture.get("timings") or [])[:20000]]
            expected = dict(capture.get("expected") or {})
            cleaned.append({"timings": timings, "expected": expected, "label": str(capture.get("label") or "")[:100]})
        result = await manager.core.identify(cleaned)
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)




def _decoded_expected_agreement(decoded: dict[str, Any], expected: dict[str, Any]) -> float:
    """Return 0..1 agreement for guided semantic fields."""
    keys = [k for k, v in expected.items() if v is not None and k in {"power", "mode", "temp", "fan", "swing"}]
    if not keys:
        return 1.0
    good = 0.0
    for key in keys:
        actual = decoded.get(key)
        wanted = expected.get(key)
        if key == "temp":
            try:
                good += 1.0 if abs(float(actual) - float(wanted)) <= 0.51 else 0.0
            except (TypeError, ValueError):
                pass
        elif key == "power":
            # Some canonical decoders use mode=off instead of a power boolean.
            if actual is None and str(decoded.get("mode") or "").lower() == "off":
                actual = False
            good += 1.0 if bool(actual) is bool(wanted) else 0.0
        else:
            good += 1.0 if str(actual).lower() == str(wanted).lower() else 0.0
    return good / len(keys)


def _decoded_signature(decoded: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(decoded.get(k) for k in ("power", "mode", "temp", "fan", "swing"))


async def _fallback_identify_via_specific_decoders(manager, captures: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-check every structured A/C candidate with its specific decoder.

    This path intentionally does not use the registry's first-match dispatcher.
    Each candidate is decoded independently. It is both a fallback for ambiguous
    registry identification and a real-hardware guard against one permissive
    decoder hiding a later, correct decoder.
    """
    rows = await manager.core.search("", "air_conditioner", limit=250)
    if not rows:
        return {"recommended": False, "recommended_id": None, "candidates": [], "method": "specific_decode"}

    sem = asyncio.Semaphore(12)

    async def _one(row: dict[str, Any]) -> dict[str, Any] | None:
        candidate_id = str(row.get("id") or "")
        if not candidate_id:
            return None
        try:
            async with sem:
                profile = await manager.core.profile(candidate_id)
            protocol = profile.get("protocol_engine") or {}
            if not isinstance(protocol, dict) or not protocol:
                return None

            decoded_states: list[dict[str, Any]] = []
            agreements: list[float] = []
            for capture in captures:
                async with sem:
                    decoded = await manager.core.decode(protocol, list(capture.get("timings") or []))
                if not isinstance(decoded, dict) or not decoded:
                    continue
                decoded_states.append(decoded)
                agreements.append(_decoded_expected_agreement(decoded, dict(capture.get("expected") or {})))

            total = len(captures)
            valid = len(decoded_states)
            if valid < 2 or total < 2:
                return None
            valid_ratio = valid / total
            semantic_ratio = sum(agreements) / len(agreements) if agreements else 0.0
            rich = sum(
                1 for key in ("power", "mode", "temp", "fan")
                if any(state.get(key) is not None for state in decoded_states)
            )
            distinct = len({_decoded_signature(state) for state in decoded_states})
            guided = any(bool(c.get("expected")) for c in captures)

            # A real stateful A/C decoder should decode the same protocol across
            # several button presses and expose useful state, not only accept raw
            # timings. Guided A/C captures also have to agree with 24/25/26°C.
            confidence = round(
                65 * valid_ratio
                + 25 * semantic_ratio
                + (5 if rich >= 2 else 0)
                + (5 if distinct >= 2 else 0)
            )
            safe = (
                total >= 3
                and valid >= 3
                and valid_ratio >= 0.75
                and confidence >= 90
                and rich >= 2
                and (semantic_ratio >= 0.90 if guided else distinct >= 2)
            )
            candidate = {
                "id": candidate_id,
                "brand": row.get("brand") or profile.get("brand"),
                "model": row.get("model") or profile.get("model") or profile.get("name"),
                "kind": "air_conditioner",
                "source": "protocol_engine",
                "engine": protocol.get("engine"),
                "variant": protocol.get("variant") or protocol.get("protocol"),
            }
            return {
                "candidate": candidate,
                "group_id": _protocol_group_id(protocol, candidate),
                "confidence": max(0, min(100, confidence)),
                "matched_captures": valid,
                "capture_count": total,
                "semantic_ratio": round(semantic_ratio, 4),
                "distinct_matches": distinct,
                "decoded_states": decoded_states[:4],
                "evidence_sources": ["hanjoo_protocol_specific_decode"],
                "evidence": "protocol_decode",
                "_core_recommended": safe,
            }
        except Exception:
            return None

    # Run candidate checks concurrently; all traffic stays inside HA's local
    # container network and is bounded by the semaphore above.
    checked = await asyncio.gather(*(_one(dict(row)) for row in rows))
    candidates = [row for row in checked if row is not None]
    candidates.sort(key=lambda x: (-int(x.get("confidence") or 0), -int(x.get("matched_captures") or 0)))

    # The final ambiguity margin is applied by Fusion Matcher. Mark only the
    # individually safe rows here; do not pick a winner in this helper.
    return {
        "recommended": False,
        "recommended_id": None,
        "candidates": candidates,
        "method": "specific_decode",
    }




def _probe_state_signature(match: dict[str, Any]) -> tuple[Any, ...]:
    state = match.get("canonical") if isinstance(match.get("canonical"), dict) else {}
    return tuple(state.get(k) for k in ("power", "mode", "temp", "temperature", "fan", "swingV", "swingH"))


async def _exhaustive_codec_candidates(manager, captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Local-only recognition using irtxrx plus pinned upstream IRremoteESP8266."""
    if not captures:
        return []
    probed = await asyncio.gather(
        *(manager.core.probe_all(list(cap.get("timings") or [])) for cap in captures),
        return_exceptions=True,
    )
    groups: dict[str, dict[str, Any]] = {}
    def add(protocol, brand, source, canonical, can_encode, is_ac, expected):
        protocol=str(protocol or "").strip()
        if not protocol: return
        gid=protocol.lower().replace(" ","_")
        row=groups.setdefault(gid,{"protocol":protocol,"brand":brand,"sources":set(),"states":[],"agreements":[],"can_encode":False,"structured":False,"is_ac":False})
        row["sources"].add(source); row["states"].append(canonical or {})
        row["can_encode"] = row["can_encode"] or bool(can_encode)
        row["structured"] = row["structured"] or bool(canonical)
        row["is_ac"] = row["is_ac"] or bool(is_ac)
        row["agreements"].append(_decoded_expected_agreement(canonical, expected) if canonical else 1.0)

    for cap,result in zip(captures,probed):
        if isinstance(result,Exception) or not isinstance(result,dict): continue
        expected=dict(cap.get("expected") or {})
        irtxrx=result.get("irtxrx") if isinstance(result.get("irtxrx"),dict) else {}
        for match in irtxrx.get("matches") or []:
            if not isinstance(match,dict): continue
            canonical=match.get("canonical") if isinstance(match.get("canonical"),dict) else {}
            add(match.get("protocol"),match.get("brand"),"irtxrx",canonical,bool(match.get("can_encode")),str(match.get("type") or "").lower()=="ac",expected)
        upstream=result.get("irremoteesp8266") if isinstance(result.get("irremoteesp8266"),dict) else {}
        um=upstream.get("match") if isinstance(upstream.get("match"),dict) else None
        if um: add(um.get("protocol"),um.get("brand"),"irremoteesp8266",{},False,bool(um.get("ac_state")),expected)

    out=[]; total=len(captures)
    for gid,row in groups.items():
        valid=len(row["states"])
        if valid<2: continue
        valid_ratio=valid/total if total else 0.0
        semantic=sum(row["agreements"])/len(row["agreements"]) if row["agreements"] else 0.0
        distinct=len({tuple(sorted(s.items())) for s in row["states"] if s})
        confidence=round(64*valid_ratio+20*semantic+(8 if row["structured"] else 0)+(5 if row["can_encode"] else 0)+(3 if distinct>=2 else 0))
        safe=total>=3 and valid>=3 and valid_ratio>=.75 and confidence>=88
        out.append({"candidate":{"id":f"codec:{gid}","brand":row.get("brand"),"model":row["protocol"],"kind":"air_conditioner" if row["is_ac"] else "custom","source":"protocol_engine","engine":"irtxrx" if "irtxrx" in row["sources"] else "irremoteesp8266","variant":row["protocol"],"protocol":row["protocol"],"recognition_only":not row["can_encode"]},"group_id":f"protocol:{gid}","confidence":min(100,max(0,confidence)),"matched_captures":valid,"capture_count":total,"semantic_ratio":round(semantic,4),"distinct_matches":distinct,"evidence_sources":sorted(row["sources"]),"evidence":"protocol_decode","_core_recommended":safe})
    out.sort(key=lambda x:(-int(x.get("confidence") or 0),-int(x.get("matched_captures") or 0)))
    return out


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/fusion/identify",
        vol.Required("captures"): [dict],
        vol.Optional("kind_hint", default="auto"): str,
        vol.Optional("query_hint", default=""): str,
    }
)
@websocket_api.async_response
async def ws_fusion_identify(hass, connection, msg) -> None:
    """Thin orchestration layer; all recognition/scoring policy lives in Core Brain."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _entry_id = runtime
    online = _online_library(hass)
    captures = list(msg.get("captures") or [])[:6]
    if len(captures) < 2:
        connection.send_error(msg["id"], "not_enough_captures", "Cần ít nhất 2 mẫu remote")
        return

    cleaned = [
        {
            "timings": [int(x) for x in list(capture.get("timings") or [])[:20000]],
            "frequency": int(capture.get("frequency") or 38000),
            "expected": dict(capture.get("expected") or {}),
            "label": str(capture.get("label") or "")[:100],
        }
        for capture in captures
    ]
    kind_hint = str(msg.get("kind_hint") or "auto").strip().lower()
    settings = manager.get_discovery_source_settings()
    errors: list[dict[str, Any]] = []

    # Phase 1: Core Brain derives protocol families/brands locally. No matching
    # algorithm is exposed in this integration.
    try:
        preliminary = await manager.core.fuse_identification(
            cleaned, kind_hint=kind_hint
        )
    except Exception as err:
        _error(connection, msg, err)
        return

    profile_inputs: list[dict[str, Any]] = []
    for profile in manager.get_profiles().values():
        profile_inputs.append(
            {
                "profile": profile,
                "source": "saved_profile",
                "candidate_id": f"saved:{profile.get('id')}",
                "catalog_id": None,
                "group_id": f"profile:saved:{profile.get('id')}",
            }
        )

    query_hint = str(msg.get("query_hint") or "").strip()
    online_queries: list[str] = []
    if query_hint:
        online_queries.append(query_hint)
    for brand in preliminary.get("brand_hints") or []:
        brand = str(brand or "").strip()
        if brand and brand.lower() not in {q.lower() for q in online_queries}:
            online_queries.append(brand)
        if len(online_queries) >= 5:
            break

    online_profiles_checked = 0
    catalog_rows: dict[str, dict[str, Any]] = {}
    suggestion_rows: dict[str, dict[str, Any]] = {}
    search_kind = None if kind_hint in {"", "auto"} else kind_hint

    # Reuse the detected brand/model hints to build a browseable list similar
    # to the normal brand/model search.  These are suggestions, not recognition
    # evidence, so they never increase confidence or trigger auto-recommendation.
    for query in online_queries:
        if settings.get("protocol_engine", True):
            try:
                for item0 in await manager.core.search(query, search_kind, limit=30):
                    item = dict(item0)
                    cid = str(item.get("id") or "")
                    if not cid:
                        continue
                    item.setdefault("source", "protocol_engine")
                    item.setdefault("source_name", "HanJoo Protocol")
                    item["testable"] = True
                    suggestion_rows.setdefault(f"protocol:{cid}", item)
            except Exception as err:
                errors.append({"source": "protocol_suggestion_search", "error": str(err)})

        q_lower = query.lower()
        for profile in manager.get_profiles().values():
            text0 = f"{profile.get('brand','')} {profile.get('model','')} {profile.get('name','')}".lower()
            if q_lower and q_lower not in text0:
                continue
            pkind = str(profile.get("kind") or profile.get("type") or "")
            if search_kind and search_kind not in {pkind, {"air_conditioner":"climate","tv":"media_player"}.get(pkind, pkind)}:
                aliases = {"air_conditioner":"climate","tv":"media_player"}
                if aliases.get(search_kind) != pkind:
                    continue
            pid = str(profile.get("id") or "")
            if not pid:
                continue
            suggestion_rows.setdefault(
                f"saved:{pid}",
                {
                    "id": f"saved:{pid}",
                    "profile_id": pid,
                    "source": "saved_profile",
                    "source_name": "Profile đã lưu",
                    "name": profile.get("name"),
                    "brand": profile.get("brand"),
                    "model": profile.get("model"),
                    "kind": pkind,
                    "testable": True,
                },
            )

    if online is not None and (settings.get("smartir") or settings.get("flipper_irdb")) and online_queries:
        for query in online_queries:
            try:
                found = await online.async_search(query, search_kind, limit=40)
                for item0 in found.get("items") or []:
                    item = dict(item0)
                    cid = str(item.get("id") or "")
                    if cid:
                        catalog_rows.setdefault(cid, item)
                        item["catalog_id"] = cid
                        item["testable"] = True
                        item["source_name"] = (
                            "Flipper-IRDB" if item.get("source") == "flipper_irdb" else "SmartIR"
                        )
                        suggestion_rows.setdefault(f"online:{cid}", item)
            except Exception as err:
                errors.append({"source": "online_profile_search", "error": str(err)})

        sem = asyncio.Semaphore(6)
        async def _fetch_profile(item: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal online_profiles_checked
            cid = str(item.get("id") or "")
            if not cid:
                return None
            try:
                async with sem:
                    imported = await online.async_fetch_profile(cid)
                online_profiles_checked += 1
                return {
                    "profile": imported.profile,
                    "source": str(item.get("source") or "online"),
                    "candidate_id": cid,
                    "catalog_id": cid,
                    "group_id": f"profile:{cid}",
                }
            except Exception as err:
                errors.append({"source": "online_profile_fetch", "error": str(err)})
                return None

        fetched = await asyncio.gather(
            *(_fetch_profile(item) for item in list(catalog_rows.values())[:60])
        )
        profile_inputs.extend(item for item in fetched if item is not None)

    try:
        result = await manager.core.fuse_identification(
            cleaned,
            kind_hint=kind_hint,
            profiles=profile_inputs,
        )
    except Exception as err:
        _error(connection, msg, err)
        return

    native_identified: list[dict[str, Any]] = []
    if settings.get("native_ha", True):
        native_identified = _native_identification_candidates(
            hass, result, kind_hint
        )
        if native_identified:
            existing_ids = {
                str((row.get("candidate") or {}).get("id") or "")
                for row in result.get("candidates") or []
            }
            result["candidates"] = native_identified + [
                row
                for row in result.get("candidates") or []
                if str((row.get("candidate") or {}).get("id") or "") not in {
                    str((native_row.get("candidate") or {}).get("id") or "")
                    for native_row in native_identified
                }
            ]
            best_native = native_identified[0]
            if best_native.get("_core_recommended"):
                native_id = str((best_native.get("candidate") or {}).get("id") or "")
                result["recommended"] = True
                result["recommended_id"] = native_id
                result["equivalent_candidate_ids"] = [native_id]
                native_candidate = best_native.get("candidate") or {}
                brand = str(native_candidate.get("brand") or "")
                name = str(native_candidate.get("model") or "Native Home Assistant")
                result["message_vi"] = (
                    f"Core đã nhận diện {brand}; Home Assistant có integration chính thức "
                    f"{name} nên HanJoo ưu tiên dùng Native HA."
                )
                result["message_en"] = (
                    f"Core identified {brand}; Home Assistant provides the official "
                    f"{name} integration, so HanJoo prioritizes Native HA."
                )
                result["message"] = result["message_en"]

    best_recognition: dict[str, Any] | None = None
    recommended_id = str(result.get("recommended_id") or "")
    for row in result.get("candidates") or []:
        row.pop("_core_recommended", None)
        row.pop("_native_priority", None)
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        if str(candidate.get("id") or "") == recommended_id:
            best_recognition = row

    # A generic wire protocol (e.g. NEC) identifies the transport family, not
    # the semantic device class. When the guided flow is explicitly TV/fan/etc,
    # preserve that user-selected class instead of displaying "Custom".
    inferred = None
    if best_recognition is not None:
        inferred = str((best_recognition.get("candidate") or {}).get("kind") or "")
    if kind_hint not in {"", "auto"} and inferred in {"", "custom", "remote"}:
        inferred = kind_hint
        for row in result.get("candidates") or []:
            candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
            if candidate.get("recognition_only") and str(candidate.get("kind") or "") in {"", "custom", "remote"}:
                candidate["kind"] = kind_hint

    best_candidate = (best_recognition or {}).get("candidate") if isinstance((best_recognition or {}).get("candidate"), dict) else {}
    detected_brand = str(best_candidate.get("brand") or "").strip()
    recognition_confidence = int((best_recognition or {}).get("confidence") or 0)
    detected_protocol = str(best_candidate.get("protocol") or best_candidate.get("variant") or "").strip()

    matched_ids = {str((row.get("candidate") or {}).get("id") or "") for row in result.get("candidates") or []}
    suggestions: list[dict[str, Any]] = []
    rank_query = query_hint or (online_queries[0] if online_queries else "")

    def _kind_compatible(value: Any) -> bool:
        if not inferred or inferred in {"auto", "custom"}:
            return True
        actual = str(value or "").lower()
        aliases = {
            "tv": {"tv", "media_player"},
            "speaker": {"speaker", "soundbar", "media_player"},
            "projector": {"projector", "media_player"},
            "air_conditioner": {"air_conditioner", "climate"},
            "fan": {"fan"},
        }
        return actual in aliases.get(str(inferred).lower(), {str(inferred).lower()})

    for row0 in suggestion_rows.values():
        row = dict(row0)
        cid = str(row.get("id") or row.get("catalog_id") or "")
        if cid and cid in matched_ids:
            continue
        row["suggestion_score"] = _rank_candidate(row, query=rank_query, kind=search_kind)
        row["recognition_match"] = False

        row_brand = str(row.get("brand") or "").strip()
        brand_match = bool(
            detected_brand and row_brand
            and row_brand.casefold() == detected_brand.casefold()
        )
        kind_match = _kind_compatible(row.get("kind") or row.get("type"))
        model_text = str(row.get("model") or row.get("name") or "").strip()
        query_match = bool(
            query_hint and model_text
            and str(query_hint).casefold() in model_text.casefold()
        )

        compatibility = 0
        if brand_match:
            compatibility += 55
        if kind_match:
            compatibility += 25
        if recognition_confidence >= 90:
            compatibility += 10
        if query_match:
            compatibility += 10
        row["compatibility_score"] = min(100, compatibility)
        row["recognition_brand_match"] = brand_match
        row["recognition_kind_match"] = kind_match
        row["protocol_hint"] = detected_protocol or None
        if brand_match and kind_match and recognition_confidence >= 90:
            row["high_compatibility"] = True
            row["suggestion_score"] = int(row.get("suggestion_score") or 0) + 500
            row["recommendation_reason_vi"] = (
                f"Cùng hãng {detected_brand}"
                + (f", loại {inferred}" if inferred else "")
                + (f"; remote đã xác nhận protocol {detected_protocol}" if detected_protocol else "")
            )
            row["recommendation_reason_en"] = (
                f"Same brand {detected_brand}"
                + (f", device type {inferred}" if inferred else "")
                + (f"; the remote confirmed protocol {detected_protocol}" if detected_protocol else "")
            )
        suggestions.append(row)

    suggestions.sort(
        key=lambda row: (
            -int(bool(row.get("high_compatibility"))),
            -int(row.get("compatibility_score") or 0),
            -int(row.get("suggestion_score") or 0),
            str(row.get("brand") or "").lower(),
            str(row.get("model") or row.get("name") or "").lower(),
        )
    )

    result.update(
        {
            "mode": "core_brain",
            "inferred_kind": inferred,
            "profile_suggestions": suggestions[:16],
            "sources_used": {
                "native_ha": bool(settings.get("native_ha") and native_identified),
                "hanjoo_core_brain": True,
                "irremoteesp8266": any(
                    "irremoteesp8266" in (row.get("evidence_sources") or [])
                    for row in result.get("candidates") or []
                ),
                "saved_profile": any(
                    str((row.get("candidate") or {}).get("source") or "") == "saved_profile"
                    for row in result.get("candidates") or []
                ),
                "smartir": any(
                    str((row.get("candidate") or {}).get("source") or "") == "smartir"
                    for row in result.get("candidates") or []
                ),
                "flipper_irdb": any(
                    str((row.get("candidate") or {}).get("source") or "") == "flipper_irdb"
                    for row in result.get("candidates") or []
                ),
            },
            "search_sources": {
                "saved_profile": True,
                "smartir": bool(settings.get("smartir") and online_queries),
                "flipper_irdb": bool(settings.get("flipper_irdb") and online_queries),
            },
            "online_profiles_checked": online_profiles_checked,
            "errors": (list(result.get("errors") or []) + errors)[:8],
        }
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/remote_identify/test_capture",
        vol.Required("emitter"): str,
        vol.Required("timings"): vol.All([vol.Coerce(int)], vol.Length(min=6, max=20000)),
        vol.Optional("frequency", default=38000): vol.All(int, vol.Range(min=20000, max=80000)),
    }
)
@websocket_api.async_response
async def ws_identify_test_capture(hass, connection, msg) -> None:
    """Replay one freshly captured RAW command without persisting it.

    This verifies the physical receive/replay path even when recognition has
    only identified a protocol family and no exact model/profile exists yet.
    Replaying a capture does *not* prove the inferred family/model itself.
    """
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _entry_id = runtime
    try:
        result = await manager.test_raw_capture(
            timings=list(msg.get("timings") or []),
            frequency=int(msg.get("frequency") or 38000),
            emitter=msg["emitter"],
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/protocol/test",
        vol.Required("candidate_id"): str,
        vol.Required("emitter"): str,
    }
)
@websocket_api.async_response
async def ws_protocol_test(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _entry_id = runtime
    try:
        result = await manager.test_protocol_candidate(
            msg["candidate_id"], msg["emitter"]
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/create_from_protocol",
        vol.Required("candidate_id"): str,
        vol.Required("name"): str,
        vol.Required("emitters"): [str],
        vol.Optional("receiver"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_device_create_from_protocol(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        device_id = await manager.create_device_from_protocol(
            candidate_id=msg["candidate_id"],
            name=msg["name"],
            emitters=msg["emitters"],
            receiver=msg.get("receiver"),
        )
        connection.send_result(msg["id"], {"device_id": device_id})
        _reload_soon(hass, entry_id)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{WS_PREFIX}/online/sources"})
@websocket_api.async_response
async def ws_online_sources(hass, connection, msg) -> None:
    online = _online_library(hass)
    if online is None:
        connection.send_result(msg["id"], [])
        return
    connection.send_result(msg["id"], online.sources())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/online/source/set",
        vol.Required("source_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_online_source_set(hass, connection, msg) -> None:
    online = _online_library(hass)
    if online is None:
        connection.send_error(
            msg["id"], "not_configured", "HanJoo IR chưa được cấu hình"
        )
        return
    try:
        result = await online.async_set_source_enabled(
            msg["source_id"], bool(msg["enabled"])
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/online/source/refresh",
        vol.Required("source_id"): str,
    }
)
@websocket_api.async_response
async def ws_online_source_refresh(hass, connection, msg) -> None:
    online = _online_library(hass)
    if online is None:
        connection.send_error(
            msg["id"], "not_configured", "HanJoo IR chưa được cấu hình"
        )
        return
    try:
        result = await online.async_refresh_source(msg["source_id"])
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/online/search",
        vol.Optional("query", default=""): str,
        vol.Optional("kind"): vol.Any(str, None),
        vol.Optional("limit", default=100): vol.All(int, vol.Range(min=1, max=250)),
        vol.Optional("force", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_online_search(hass, connection, msg) -> None:
    online = _online_library(hass)
    if online is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    try:
        result = await online.async_search(
            msg.get("query", ""),
            msg.get("kind"),
            limit=int(msg.get("limit", 100)),
            force=bool(msg.get("force", False)),
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/online/test",
        vol.Required("catalog_id"): str,
        vol.Required("emitter"): str,
    }
)
@websocket_api.async_response
async def ws_online_test(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    online = _online_library(hass)
    if runtime is None or online is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        result = await online.async_fetch_profile(msg["catalog_id"])
        sent = await manager.test_profile_data(result.profile, msg["emitter"])
        connection.send_result(
            msg["id"],
            {
                **sent,
                "profile_name": result.profile.get("name"),
                "warnings": result.warnings,
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/online/install",
        vol.Required("catalog_id"): str,
    }
)
@websocket_api.async_response
async def ws_online_install(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    online = _online_library(hass)
    if runtime is None or online is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        result = await online.async_fetch_profile(msg["catalog_id"])
        # Avoid accidental duplicate installs of exactly the same online
        # catalog entry. Existing devices are unaffected.
        source_ref = result.profile.get("source_ref") or {}

        def same_source_ref(profile: dict[str, Any]) -> bool:
            existing = profile.get("source_ref") or {}
            if existing.get("provider") != source_ref.get("provider"):
                return False
            provider = source_ref.get("provider")
            if provider == "smartir":
                return (
                    existing.get("kind") == source_ref.get("kind")
                    and existing.get("code") == source_ref.get("code")
                )
            if provider == "flipper_irdb":
                return (
                    existing.get("repository") == source_ref.get("repository")
                    and existing.get("path") == source_ref.get("path")
                )
            return existing == source_ref

        existing_id = next(
            (
                profile_id
                for profile_id, profile in manager.get_profiles().items()
                if same_source_ref(profile)
            ),
            None,
        )
        if existing_id:
            connection.send_result(
                msg["id"],
                {
                    "profile_id": existing_id,
                    "already_installed": True,
                    "warnings": [],
                },
            )
            return
        profile_id = await manager.store_import_result(result)
        connection.send_result(
            msg["id"],
            {
                "profile_id": profile_id,
                "already_installed": False,
                "warnings": result.warnings,
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{WS_PREFIX}/devices"})
@websocket_api.async_response
async def ws_devices(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_result(msg["id"], [])
        return
    manager, _ = runtime
    connection.send_result(
        msg["id"],
        [manager.device_summary(d) for d in manager.get_devices().values()],
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/device", vol.Required("device_id"): str}
)
@websocket_api.async_response
async def ws_device(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    device = manager.device_full(msg["device_id"])
    if device is None:
        connection.send_error(msg["id"], "not_found", "Không tìm thấy thiết bị")
        return
    connection.send_result(msg["id"], device)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/create_custom",
        vol.Required("name"): str,
        vol.Required("kind"): vol.In(list(FALLBACK_KIND_TO_TYPE)),
        vol.Required("emitters"): [str],
        vol.Optional("receiver"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_device_create_custom(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        device_id = await manager.create_custom_device(
            name=msg["name"],
            kind=msg["kind"],
            emitters=msg["emitters"],
            receiver=msg.get("receiver"),
        )
        connection.send_result(msg["id"], {"device_id": device_id})
        _reload_soon(hass, entry_id)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/create_from_captures",
        vol.Required("name"): str,
        vol.Required("kind"): str,
        vol.Optional("brand"): vol.Any(str, None),
        vol.Optional("protocol"): vol.Any(str, None),
        vol.Required("captures"): [dict],
        vol.Required("emitters"): [str],
        vol.Optional("receiver"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_device_create_from_captures(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        device_id = await manager.create_device_from_captures(
            name=msg["name"],
            kind=msg["kind"],
            brand=msg.get("brand"),
            protocol=msg.get("protocol"),
            captures=list(msg.get("captures") or []),
            emitters=msg["emitters"],
            receiver=msg.get("receiver"),
        )
        connection.send_result(msg["id"], {"device_id": device_id})
        _reload_soon(hass, entry_id)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/create_from_profile",
        vol.Required("profile_id"): str,
        vol.Required("name"): str,
        vol.Required("emitters"): [str],
        vol.Optional("receiver"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_device_create_from_profile(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        device_id = await manager.create_device_from_profile(
            profile_id=msg["profile_id"],
            name=msg["name"],
            emitters=msg["emitters"],
            receiver=msg.get("receiver"),
        )
        connection.send_result(msg["id"], {"device_id": device_id})
        _reload_soon(hass, entry_id)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/device/delete", vol.Required("device_id"): str}
)
@websocket_api.async_response
async def ws_device_delete(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_result(msg["id"], {"ok": True})
        return
    manager, entry_id = runtime
    try:
        await manager.delete_device(msg["device_id"])
        connection.send_result(msg["id"], {"ok": True})
        _reload_soon(hass, entry_id)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/update_routing",
        vol.Required("device_id"): str,
        vol.Required("emitters"): [str],
        vol.Optional("receiver"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_device_update_routing(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        await manager.update_routing(msg["device_id"], msg["emitters"], msg.get("receiver"))
        connection.send_result(msg["id"], {"ok": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/add_command",
        vol.Required("device_id"): str,
        vol.Required("name"): str,
    }
)
@websocket_api.async_response
async def ws_device_add_command(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        command_id = await manager.add_custom_command(
            msg["device_id"], msg["name"]
        )

        # Button platform registers a live entity-adder at setup time. This
        # avoids a full integration reload just because one arbitrary custom
        # button was added.
        runtime_data = hass.data.get(DOMAIN, {}).get(entry_id, {})
        add_button = runtime_data.get("add_command_button")
        if callable(add_button):
            add_button(msg["device_id"], command_id)
        else:
            # Defensive fallback for an unusual partial platform setup.
            _reload_soon(hass, entry_id)

        connection.send_result(msg["id"], {"command_id": command_id})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/delete_command",
        vol.Required("device_id"): str,
        vol.Required("command_id"): str,
    }
)
@websocket_api.async_response
async def ws_device_delete_command(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        await manager.delete_command(msg["device_id"], msg["command_id"])
        connection.send_result(msg["id"], {"ok": True})
        _reload_soon(hass, entry_id)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/clear_command",
        vol.Required("device_id"): str,
        vol.Required("command_id"): str,
    }
)
@websocket_api.async_response
async def ws_device_clear_command(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        await manager.clear_command(msg["device_id"], msg["command_id"])
        connection.send_result(msg["id"], {"ok": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/capture",
        vol.Required("device_id"): str,
        vol.Optional("timeout", default=DEFAULT_LEARN_TIMEOUT): vol.All(
            int, vol.Range(min=2, max=120)
        ),
    }
)
@websocket_api.async_response
async def ws_device_capture(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(
            msg["id"], "not_configured", "HanJoo IR chưa được cấu hình"
        )
        return
    manager, _entry_id = runtime
    try:
        result = await manager.capture_for_preview(
            msg["device_id"], int(msg["timeout"])
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/save_capture",
        vol.Required("device_id"): str,
        vol.Required("token"): str,
        vol.Required("target"): vol.In(["command", "climate"]),
        vol.Optional("command_id"): str,
        vol.Optional("mode", default="cool"): str,
        vol.Optional("temp"): vol.Any(vol.Coerce(float), None),
        vol.Optional("fan"): vol.Any(str, None),
        vol.Optional("swing"): vol.Any(str, None),
        vol.Optional("power", default="state"): vol.In(["state", "on", "off"]),
    }
)
@websocket_api.async_response
async def ws_device_save_capture(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(
            msg["id"], "not_configured", "HanJoo IR chưa được cấu hình"
        )
        return
    manager, _entry_id = runtime
    try:
        if msg["target"] == "command":
            command_id = msg.get("command_id")
            if not command_id:
                raise ValueError("Thiếu command_id")
            await manager.save_captured_command(
                msg["device_id"], command_id, msg["token"]
            )
        else:
            await manager.save_captured_climate_state(
                msg["device_id"],
                msg["token"],
                mode=msg["mode"],
                temp=msg.get("temp"),
                fan=msg.get("fan"),
                swing=msg.get("swing"),
                power=msg["power"],
            )
        connection.send_result(msg["id"], {"ok": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/discard_capture",
        vol.Optional("token"): str,
        vol.Optional("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_device_discard_capture(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_result(msg["id"], {"ok": True})
        return
    manager, _entry_id = runtime
    if msg.get("device_id"):
        manager.cancel_capture_wait(msg["device_id"])
    if msg.get("token"):
        manager.discard_capture(msg["token"])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/learn",
        vol.Required("device_id"): str,
        vol.Required("command_id"): str,
        vol.Optional("timeout", default=DEFAULT_LEARN_TIMEOUT): vol.All(int, vol.Range(min=2, max=120)),
    }
)
@websocket_api.async_response
async def ws_device_learn(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        await manager.learn_command(
            msg["device_id"], msg["command_id"], int(msg["timeout"])
        )
        connection.send_result(msg["id"], {"ok": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/learn_climate",
        vol.Required("device_id"): str,
        vol.Optional("mode", default="cool"): str,
        vol.Optional("temp"): vol.Any(vol.Coerce(float), None),
        vol.Optional("fan"): vol.Any(str, None),
        vol.Optional("swing"): vol.Any(str, None),
        vol.Optional("power", default="state"): vol.In(["state", "on", "off"]),
        vol.Optional("timeout", default=DEFAULT_LEARN_TIMEOUT): vol.All(int, vol.Range(min=2, max=120)),
    }
)
@websocket_api.async_response
async def ws_device_learn_climate(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, entry_id = runtime
    try:
        await manager.learn_climate_state(
            msg["device_id"],
            mode=msg["mode"],
            temp=msg.get("temp"),
            fan=msg.get("fan"),
            swing=msg.get("swing"),
            power=msg["power"],
            timeout=int(msg["timeout"]),
        )
        connection.send_result(msg["id"], {"ok": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/device/send",
        vol.Required("device_id"): str,
        vol.Required("command_id"): str,
    }
)
@websocket_api.async_response
async def ws_device_send(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        await manager.send_command(msg["device_id"], msg["command_id"])
        connection.send_result(msg["id"], {"ok": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/device/export", vol.Required("device_id"): str}
)
@websocket_api.async_response
async def ws_device_export(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        connection.send_result(
            msg["id"],
            {
                "filename": f"{msg['device_id']}.hanjoo-ir.json",
                "text": manager.export_device(msg["device_id"]),
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{WS_PREFIX}/profiles"})
@websocket_api.async_response
async def ws_profiles(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_result(msg["id"], [])
        return
    manager, _ = runtime
    connection.send_result(msg["id"], manager.profile_summaries())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/profile/import",
        vol.Required("filename"): str,
        vol.Required("text"): str,
    }
)
@websocket_api.async_response
async def ws_profile_import(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        results = await manager.import_profiles(msg["text"], msg["filename"])
        connection.send_result(
            msg["id"],
            {
                "count": len(results),
                "source_format": results[0].source_format if results else "unknown",
                "warnings": [warning for result in results for warning in result.warnings],
                "profiles": [
                    {
                        "id": result.profile.get("id"),
                        "name": result.profile.get("name"),
                    }
                    for result in results
                ],
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/profile/delete", vol.Required("profile_id"): str}
)
@websocket_api.async_response
async def ws_profile_delete(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_result(msg["id"], {"ok": True})
        return
    manager, _ = runtime
    try:
        await manager.delete_profile(msg["profile_id"])
        connection.send_result(msg["id"], {"ok": True})
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/profile/export", vol.Required("profile_id"): str}
)
@websocket_api.async_response
async def ws_profile_export(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        profile = manager.get_profile(msg["profile_id"]) or {}
        connection.send_result(
            msg["id"],
            {
                "filename": f"{profile.get('name') or msg['profile_id']}.hanjoo-ir.json",
                "text": manager.export_profile(msg["profile_id"]),
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/profile/export_library"}
)
@websocket_api.async_response
async def ws_profile_export_library(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        connection.send_result(
            msg["id"],
            {
                "filename": "hanjoo-ir-library.json",
                "text": manager.export_library(),
            },
        )
    except Exception as err:
        _error(connection, msg, err)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/profile/test",
        vol.Required("profile_id"): str,
        vol.Required("emitter"): str,
    }
)
@websocket_api.async_response
async def ws_profile_test(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_configured", "HanJoo IR chưa được cấu hình")
        return
    manager, _ = runtime
    try:
        connection.send_result(
            msg["id"], await manager.test_profile(msg["profile_id"], msg["emitter"])
        )
    except Exception as err:
        _error(connection, msg, err)
