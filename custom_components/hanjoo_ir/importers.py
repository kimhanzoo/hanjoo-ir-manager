"""Third-party profile import funnel for HanJoo IR.

Supported in v0.2:
- HanJoo portable profile JSON (hanjoo-ir-profile/1)
- HAIR wig JSON (hair-wig/1, /2, /3)
- SmartIR media_player, fan, and climate JSON

All imports are normalized to raw timing codes before persistence. This keeps
replay independent of the original vendor controller (Broadlink/Tuya/etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
import json
import re
from typing import Any
import uuid

from .const import (
    DEVICE_TYPE_CLIMATE,
    DEVICE_TYPE_FAN,
    DEVICE_TYPE_MEDIA_PLAYER,
    DEVICE_TYPE_REMOTE,
    MAX_IMPORT_BYTES,
)
from .ir_code import IRCodeError, decode_external_code


class ProfileImportError(ValueError):
    """Raised when a library file cannot be safely imported."""


@dataclass
class ImportResult:
    """Normalized imported profile and non-fatal warnings."""

    profile: dict[str, Any]
    source_format: str
    warnings: list[str] = field(default_factory=list)


def _slug(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return value or "command"


def _title(value: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    spaced = spaced.replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in spaced.split()) or value


_MEDIA_ALIASES = {
    "on": "on",
    "off": "off",
    "power": "power",
    "volumeup": "volume_up",
    "volumedown": "volume_down",
    "mute": "mute",
    "nextchannel": "channel_up",
    "previouschannel": "channel_down",
    "channelup": "channel_up",
    "channeldown": "channel_down",
    "input": "input",
    "source": "input",
    "home": "home",
    "menu": "menu",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "ok": "ok",
    "enter": "ok",
    "back": "back",
    "return": "back",
    "play": "play",
    "pause": "pause",
    "stop": "stop",
    "next": "next",
    "previous": "previous",
}


def _canonical_media_key(key: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return _MEDIA_ALIASES.get(compact, _slug(key))


def _decode_value(value: Any, encoding: str, warnings: list[str], label: str) -> dict[str, Any] | None:
    """Normalize one command value, preserving multi-code sequences."""
    values: list[Any]
    if isinstance(value, list):
        values = value
    else:
        values = [value]

    codes: list[dict[str, Any]] = []
    for idx, raw in enumerate(values):
        try:
            codes.append(decode_external_code(raw, encoding))
        except (IRCodeError, ValueError, TypeError) as err:
            warnings.append(f"{label}[{idx}]: {err}")
    if not codes:
        return None

    # Identical sequence is better represented as a repeat count; unlike a
    # generic list this also maps directly to common IR key-repeat semantics.
    send_count = 1
    if len(codes) > 1 and all(code == codes[0] for code in codes[1:]):
        send_count = len(codes)
        codes = [codes[0]]
    return {"codes": codes, "send_count": send_count}


def _command_item(name: str, value: Any, encoding: str, warnings: list[str], label: str) -> dict[str, Any] | None:
    decoded = _decode_value(value, encoding, warnings, label)
    if decoded is None:
        return None
    return {"name": name, **decoded}


def _walk_leaves(node: Any, path: tuple[str, ...] = ()):
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).startswith("$"):
                continue
            yield from _walk_leaves(value, (*path, str(key)))
    else:
        yield path, node


def _base_profile(*, name: str, device_type: str, brand: str | None, model: str | None, source: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "type": device_type,
        "brand": brand or None,
        "model": model or None,
        "source": source,
        "commands": {},
    }


def _smartir_encoding(data: dict[str, Any]) -> str:
    """Return a content/controller-aware decoder name for SmartIR."""
    encoding = str(data.get("commandsEncoding") or "")
    controller = str(data.get("supportedController") or "").strip().lower()
    if controller == "xiaomi" and encoding.strip().lower() == "raw":
        return "xiaomi_raw"
    return encoding


def _smartir_meta(data: dict[str, Any]) -> tuple[str, str, str]:
    brand = str(data.get("manufacturer") or "").strip()
    models = data.get("supportedModels") or []
    model = str(models[0]).strip() if isinstance(models, list) and models else ""
    name = " ".join(part for part in (brand, model) if part) or "SmartIR profile"
    return brand, model, name


def _convert_smartir_media(data: dict[str, Any]) -> ImportResult:
    warnings: list[str] = []
    encoding = _smartir_encoding(data)
    brand, model, name = _smartir_meta(data)
    profile = _base_profile(
        name=name,
        device_type=DEVICE_TYPE_MEDIA_PLAYER,
        brand=brand,
        model=model,
        source="smartir",
    )
    profile["kind"] = "media_player"
    sources: list[str] = []

    commands = data.get("commands") or {}
    if not isinstance(commands, dict):
        raise ProfileImportError("SmartIR commands must be an object")

    for key, value in commands.items():
        if isinstance(value, dict) and key.lower() in {"sources", "source", "inputs", "input"}:
            for source_name, source_value in value.items():
                item = _command_item(
                    str(source_name), source_value, encoding, warnings, f"sources/{source_name}"
                )
                if item:
                    command_id = f"source:{source_name}"
                    profile["commands"][command_id] = item
                    sources.append(str(source_name))
            continue

        if isinstance(value, dict):
            for path, leaf in _walk_leaves(value, (str(key),)):
                label = " / ".join(path)
                item = _command_item(label, leaf, encoding, warnings, label)
                if item:
                    profile["commands"][_slug(label)] = item
            continue

        canonical = _canonical_media_key(str(key))
        item = _command_item(_title(str(key)), value, encoding, warnings, str(key))
        if item:
            profile["commands"][canonical] = item

    profile["media_player"] = {"sources": sources}
    if not profile["commands"]:
        raise ProfileImportError("No usable commands were found in this SmartIR media profile")
    return ImportResult(profile, "smartir_media_player", warnings)


def _convert_smartir_fan(data: dict[str, Any]) -> ImportResult:
    warnings: list[str] = []
    encoding = _smartir_encoding(data)
    brand, model, name = _smartir_meta(data)
    profile = _base_profile(
        name=name,
        device_type=DEVICE_TYPE_FAN,
        brand=brand,
        model=model,
        source="smartir",
    )
    speed_modes = [str(v) for v in (data.get("speed") or [])]
    profile["fan"] = {"speed_modes": speed_modes}

    commands = data.get("commands") or {}
    if not isinstance(commands, dict):
        raise ProfileImportError("SmartIR commands must be an object")

    for key, value in commands.items():
        key_l = str(key).lower()
        if isinstance(value, dict) and key_l in {"default", "speed", "speeds"}:
            for speed, code_value in value.items():
                item = _command_item(
                    f"Tốc độ {speed}", code_value, encoding, warnings, f"speed/{speed}"
                )
                if item:
                    profile["commands"][f"speed:{speed}"] = item
            continue
        if isinstance(value, dict):
            for path, leaf in _walk_leaves(value, (str(key),)):
                label = " / ".join(path)
                item = _command_item(label, leaf, encoding, warnings, label)
                if item:
                    profile["commands"][_slug(label)] = item
            continue
        canonical = _slug(str(key))
        item = _command_item(_title(str(key)), value, encoding, warnings, str(key))
        if item:
            profile["commands"][canonical] = item

    if not profile["commands"]:
        raise ProfileImportError("No usable commands were found in this SmartIR fan profile")
    return ImportResult(profile, "smartir_fan", warnings)


def _classify_climate_path(
    path: tuple[str, ...],
    fan_modes: list[str],
    swing_modes: list[str],
    min_temp: float,
    max_temp: float,
) -> dict[str, Any]:
    fan = None
    swing = None
    temp = None
    extras: list[str] = []
    fan_lookup = {str(v): str(v) for v in fan_modes}
    swing_lookup = {str(v): str(v) for v in swing_modes}
    for part in path:
        if fan is None and part in fan_lookup:
            fan = fan_lookup[part]
            continue
        if swing is None and part in swing_lookup:
            swing = swing_lookup[part]
            continue
        try:
            number = float(part)
        except ValueError:
            extras.append(part)
        else:
            if temp is None and min_temp - 5 <= number <= max_temp + 5:
                temp = number
            else:
                extras.append(part)
    return {"fan": fan, "swing": swing, "temp": temp, "extras": extras}


def _convert_smartir_climate(data: dict[str, Any]) -> ImportResult:
    warnings: list[str] = []
    encoding = _smartir_encoding(data)
    brand, model, name = _smartir_meta(data)
    profile = _base_profile(
        name=name,
        device_type=DEVICE_TYPE_CLIMATE,
        brand=brand,
        model=model,
        source="smartir",
    )

    min_temp = float(data.get("minTemperature", 16))
    max_temp = float(data.get("maxTemperature", 30))
    precision = float(data.get("precision", 1))
    modes = [str(v) for v in (data.get("operationModes") or [])]
    fan_modes = [str(v) for v in (data.get("fanModes") or [])]
    swing_modes = [str(v) for v in (data.get("swingModes") or [])]
    commands = data.get("commands") or {}
    if not isinstance(commands, dict):
        raise ProfileImportError("SmartIR climate commands must be an object")

    climate: dict[str, Any] = {
        "min_temp": min_temp,
        "max_temp": max_temp,
        "precision": precision,
        "unit": str(data.get("temperatureUnit") or "C").upper()[0],
        "modes": modes,
        "fan_modes": fan_modes,
        "swing_modes": swing_modes,
        "off": None,
        "on": None,
        "cells": [],
    }

    if "off" in commands:
        climate["off"] = _decode_value(commands["off"], encoding, warnings, "off")
    if "on" in commands:
        climate["on"] = _decode_value(commands["on"], encoding, warnings, "on")

    if not modes:
        # Some third-party SmartIR files omit operationModes but still use
        # mode-named top-level command branches.
        inferred = [
            str(key)
            for key, value in commands.items()
            if key not in {"off", "on"} and isinstance(value, dict)
        ]
        modes = inferred
        climate["modes"] = list(inferred)
    mode_set = set(modes)
    for top_key, top_value in commands.items():
        if top_key in {"off", "on"}:
            continue
        if top_key in mode_set:
            for path, leaf in _walk_leaves(top_value):
                decoded = _decode_value(leaf, encoding, warnings, "/".join((top_key, *path)))
                if decoded is None:
                    continue
                dims = _classify_climate_path(path, fan_modes, swing_modes, min_temp, max_temp)
                climate["cells"].append(
                    {
                        "mode": str(top_key),
                        "fan": dims["fan"],
                        "swing": dims["swing"],
                        "temp": dims["temp"],
                        "extras": dims["extras"],
                        **decoded,
                    }
                )
            continue

        # Depth-0 extras (sleep/turbo/etc.) remain ordinary buttons.
        if not isinstance(top_value, dict):
            item = _command_item(
                _title(str(top_key)), top_value, encoding, warnings, str(top_key)
            )
            if item:
                profile["commands"][_slug(str(top_key))] = item

    if not climate["cells"]:
        raise ProfileImportError("SmartIR climate file contains no usable state cells")
    profile["climate"] = climate
    return ImportResult(profile, "smartir_climate", warnings)


def _convert_hair_wig(data: dict[str, Any]) -> ImportResult:
    fmt = str(data.get("format") or "")
    if not re.fullmatch(r"hair-wig/[123]", fmt):
        raise ProfileImportError(f"Unsupported HAIR wig format: {fmt or 'missing'}")
    warnings: list[str] = []
    brand = str(data.get("brand") or "").strip()
    model = str(data.get("model") or "").strip()
    kind = str(data.get("kind") or "").strip().lower()
    climate_block = data.get("climate") if isinstance(data.get("climate"), dict) else None
    if climate_block:
        device_type = DEVICE_TYPE_CLIMATE
    elif kind == "fan":
        device_type = DEVICE_TYPE_FAN
    elif kind in {"tv", "soundbar", "receiver", "settopbox", "projector"}:
        device_type = DEVICE_TYPE_MEDIA_PLAYER
    else:
        device_type = DEVICE_TYPE_REMOTE

    profile = _base_profile(
        name=str(data.get("name") or "HAIR wig"),
        device_type=device_type,
        brand=brand,
        model=model,
        source="hair_wig",
    )
    profile["kind"] = kind or None

    for index, signal in enumerate(data.get("signals") or []):
        if not isinstance(signal, dict):
            warnings.append(f"signals[{index}]: not an object")
            continue
        alias = str(signal.get("alias") or f"Command {index + 1}")
        pronto = signal.get("pronto")
        try:
            code = decode_external_code(pronto, "pronto")
        except (IRCodeError, ValueError, TypeError) as err:
            warnings.append(f"{alias}: {err}")
            continue
        item = {
            "name": alias,
            "codes": [code],
            "send_count": max(1, int(signal.get("send_count") or 1)),
        }
        profile["commands"][_slug(alias)] = item

    if climate_block:
        climate = {
            "min_temp": float(climate_block.get("min_temp", 16)),
            "max_temp": float(climate_block.get("max_temp", 30)),
            "precision": float(climate_block.get("precision", 1)),
            "unit": str(climate_block.get("unit") or "C").upper()[0],
            "modes": [str(v) for v in (climate_block.get("modes") or [])],
            "fan_modes": [str(v) for v in (climate_block.get("fan_modes") or [])],
            "swing_modes": [str(v) for v in (climate_block.get("swing_modes") or [])],
            "off": None,
            "on": None,
            "cells": [],
        }
        for key in ("off", "on"):
            if climate_block.get(key):
                try:
                    climate[key] = {
                        "codes": [decode_external_code(climate_block[key], "pronto")],
                        "send_count": 1,
                    }
                except (IRCodeError, ValueError, TypeError) as err:
                    warnings.append(f"climate/{key}: {err}")
        for idx, cell in enumerate(climate_block.get("cells") or []):
            if not isinstance(cell, dict) or not cell.get("pronto"):
                warnings.append(f"climate/cell[{idx}]: missing Pronto")
                continue
            try:
                code = decode_external_code(cell["pronto"], "pronto")
            except (IRCodeError, ValueError, TypeError) as err:
                warnings.append(f"climate/cell[{idx}]: {err}")
                continue
            climate["cells"].append(
                {
                    "mode": str(cell.get("mode") or "auto"),
                    "fan": None if cell.get("fan") is None else str(cell.get("fan")),
                    "swing": None if cell.get("swing") is None else str(cell.get("swing")),
                    "temp": None if cell.get("temp") is None else float(cell.get("temp")),
                    "extras": [],
                    "codes": [code],
                    "send_count": max(1, int(cell.get("send_count") or 1)),
                }
            )
        if not climate["cells"]:
            raise ProfileImportError("HAIR climate wig contains no usable cells")
        profile["climate"] = climate
    if not profile.get("commands") and not profile.get("climate"):
        raise ProfileImportError("HAIR wig contains no usable IR codes")
    return ImportResult(profile, fmt, warnings)


def _normalize_hanjoo_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize every IR payload in a portable HanJoo profile."""
    normalized = deepcopy(profile)
    dtype = normalized.get("type")
    if dtype not in {
        DEVICE_TYPE_REMOTE,
        DEVICE_TYPE_MEDIA_PLAYER,
        DEVICE_TYPE_FAN,
        DEVICE_TYPE_CLIMATE,
    }:
        raise ProfileImportError("HanJoo profile has an unsupported device type")

    commands = normalized.setdefault("commands", {})
    if not isinstance(commands, dict):
        raise ProfileImportError("HanJoo commands must be an object")
    for command_id, item in commands.items():
        if not isinstance(item, dict):
            raise ProfileImportError(f"Command {command_id!r} is invalid")
        raw_codes = item.get("codes") or []
        if not isinstance(raw_codes, list):
            raise ProfileImportError(f"Command {command_id!r} codes must be a list")
        codes = []
        for index, raw in enumerate(raw_codes):
            try:
                codes.append(decode_external_code(raw))
            except IRCodeError as err:
                raise ProfileImportError(
                    f"Command {command_id!r} code {index}: {err}"
                ) from err
        item["codes"] = codes
        item["send_count"] = max(1, int(item.get("send_count") or 1))
        item["name"] = str(item.get("name") or command_id)

    climate = normalized.get("climate")
    if climate is not None:
        if not isinstance(climate, dict):
            raise ProfileImportError("HanJoo climate block must be an object")
        for key in ("off", "on"):
            item = climate.get(key)
            if item is None:
                continue
            if not isinstance(item, dict):
                raise ProfileImportError(f"Climate {key} frame is invalid")
            item["codes"] = [decode_external_code(code) for code in (item.get("codes") or [])]
            item["send_count"] = max(1, int(item.get("send_count") or 1))
        cells = climate.setdefault("cells", [])
        if not isinstance(cells, list):
            raise ProfileImportError("Climate cells must be a list")
        for index, cell in enumerate(cells):
            if not isinstance(cell, dict):
                raise ProfileImportError(f"Climate cell {index} is invalid")
            cell["codes"] = [decode_external_code(code) for code in (cell.get("codes") or [])]
            if not cell["codes"]:
                raise ProfileImportError(f"Climate cell {index} has no IR code")
            cell["send_count"] = max(1, int(cell.get("send_count") or 1))
    return normalized


def _convert_hanjoo(data: dict[str, Any]) -> ImportResult:
    if data.get("format") != "hanjoo-ir-profile/1":
        raise ProfileImportError("Unsupported HanJoo profile version")
    profile = deepcopy(data.get("profile"))
    if not isinstance(profile, dict):
        raise ProfileImportError("HanJoo profile is missing the profile object")
    profile = _normalize_hanjoo_profile(profile)
    profile["id"] = uuid.uuid4().hex
    profile["source"] = "hanjoo_file"
    return ImportResult(profile, "hanjoo-ir-profile/1", [])


def sniff_format(data: dict[str, Any]) -> str:
    fmt = str(data.get("format") or "")
    if fmt.startswith("hanjoo-ir-profile/"):
        return "hanjoo"
    if fmt.startswith("hanjoo-ir-library/"):
        return "hanjoo_library"
    if fmt.startswith("hair-wig/"):
        return "hair_wig"
    if isinstance(data.get("commands"), dict) and any(
        key in data for key in ("manufacturer", "commandsEncoding", "supportedController")
    ):
        if any(
            key in data
            for key in (
                "minTemperature",
                "maxTemperature",
                "operationModes",
                "fanModes",
                "swingModes",
            )
        ):
            return "smartir_climate"
        if isinstance(data.get("speed"), list):
            return "smartir_fan"
        return "smartir_media"
    return "unknown"


def import_profile_text(text: str, filename: str = "") -> ImportResult:
    """Import a supported library/profile file."""
    if not isinstance(text, str):
        raise ProfileImportError("Profile content must be text")
    if len(text.encode("utf-8", errors="ignore")) > MAX_IMPORT_BYTES:
        raise ProfileImportError("Profile file is too large")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise ProfileImportError(f"Invalid JSON: {err.msg}") from err
    if not isinstance(data, dict):
        raise ProfileImportError("Profile root must be a JSON object")

    fmt = sniff_format(data)
    if fmt == "hanjoo":
        result = _convert_hanjoo(data)
    elif fmt == "hair_wig":
        result = _convert_hair_wig(data)
    elif fmt == "smartir_climate":
        result = _convert_smartir_climate(data)
    elif fmt == "smartir_fan":
        result = _convert_smartir_fan(data)
    elif fmt == "smartir_media":
        result = _convert_smartir_media(data)
    else:
        raise ProfileImportError(
            "Unsupported file. Use a HanJoo profile, HAIR wig, or SmartIR JSON file."
        )

    result.profile["import_filename"] = filename or None
    result.profile["import_warnings"] = list(result.warnings)
    return result



def import_profiles_text(text: str, filename: str = "") -> list[ImportResult]:
    """Import one profile or a HanJoo bundle containing many profiles."""
    if not isinstance(text, str):
        raise ProfileImportError("Profile content must be text")
    if len(text.encode("utf-8", errors="ignore")) > MAX_IMPORT_BYTES:
        raise ProfileImportError("Profile/library file is too large")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise ProfileImportError(f"Invalid JSON: {err.msg}") from err

    if isinstance(data, dict) and data.get("format") == "hanjoo-ir-library/1":
        rows = data.get("profiles")
        if not isinstance(rows, list) or not rows:
            raise ProfileImportError("HanJoo library has no profiles")
        if len(rows) > 5000:
            raise ProfileImportError("HanJoo library contains too many profiles")
        results: list[ImportResult] = []
        for index, profile in enumerate(rows):
            if not isinstance(profile, dict):
                raise ProfileImportError(f"Library profile {index} is invalid")
            wrapper = {"format": "hanjoo-ir-profile/1", "profile": profile}
            result = _convert_hanjoo(wrapper)
            result.source_format = "hanjoo-ir-library/1"
            result.profile["import_filename"] = filename or None
            results.append(result)
        return results

    return [import_profile_text(text, filename)]


def export_hanjoo_library(profiles: list[dict[str, Any]]) -> str:
    """Export multiple profiles in a single portable library file."""
    rows = []
    for source in profiles:
        profile = deepcopy(source)
        profile.pop("id", None)
        profile.pop("import_warnings", None)
        rows.append(profile)
    return json.dumps(
        {"format": "hanjoo-ir-library/1", "profiles": rows},
        ensure_ascii=False,
        indent=2,
    )

def export_hanjoo_profile(profile: dict[str, Any]) -> str:
    """Serialize a profile as HanJoo's portable JSON format."""
    payload = {
        "format": "hanjoo-ir-profile/1",
        "profile": deepcopy(profile),
    }
    payload["profile"].pop("id", None)
    payload["profile"].pop("import_warnings", None)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    climate = profile.get("climate") or {}
    return {
        "id": profile.get("id"),
        "name": profile.get("name"),
        "type": profile.get("type"),
        "brand": profile.get("brand"),
        "model": profile.get("model"),
        "source": profile.get("source"),
        "kind": profile.get("kind"),
        "command_count": len(profile.get("commands") or {}),
        "climate_cell_count": len(climate.get("cells") or []),
        "warnings": list(profile.get("import_warnings") or []),
        "filename": profile.get("import_filename"),
    }
