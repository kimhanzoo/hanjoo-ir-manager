"""Flipper-IRDB catalog and .ir profile adapter.

The provider targets the community Lucaslhm/Flipper-IRDB repository (CC0).
Raw entries pass through directly. Common parsed protocols are converted to
controller-neutral raw timings so the resulting HanJoo profile can be sent by
any Home Assistant infrared emitter.
"""
from __future__ import annotations

import re
from typing import Any
import uuid

from .const import (
    DEFAULT_FREQUENCY,
    DEVICE_TYPE_FAN,
    DEVICE_TYPE_MEDIA_PLAYER,
    DEVICE_TYPE_REMOTE,
)
from .importers import ImportResult
from .ir_code import code_from_timings

FLIPPER_REPO = "Lucaslhm/Flipper-IRDB"
FLIPPER_REF = "main"
FLIPPER_LICENSE = "CC0-1.0"

# Flipper repositories are community-maintained, so folder spelling varies.
_MEDIA_TOKENS = (
    "tv", "television", "projector", "soundbar", "audio", "receiver",
    "amplifier", "stream", "set_top", "set-top", "cable", "satellite",
    "dvd", "blu", "media", "home_theater", "home-theater",
)
_FAN_TOKENS = ("fan", "ceiling_fan")
_AC_TOKENS = ("air_conditioner", "air-conditioner", "aircon", "hvac", "ac")
_LIGHT_TOKENS = ("led", "light", "lighting", "lamp")
_CAMERA_TOKENS = ("camera",)
_CONSOLE_TOKENS = ("console", "gaming")
_AIR_TOKENS = ("air_purifier", "purifier")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def classify_flipper_path(path: str) -> tuple[str, str]:
    """Return (logical kind, HA semantic type) for a Flipper path."""
    first = _norm(path.split("/", 1)[0])
    whole = _norm(path)
    if any(token in first or token in whole for token in _FAN_TOKENS):
        return ("fan", DEVICE_TYPE_FAN)
    if any(token in first or token in whole for token in _AC_TOKENS):
        # AC files are often button/state collections but do not provide a
        # guaranteed full state matrix. Keep them honest as remotes.
        return ("air_conditioner", DEVICE_TYPE_REMOTE)
    if any(token in first or token in whole for token in _LIGHT_TOKENS):
        return ("light", DEVICE_TYPE_REMOTE)
    if any(token in first or token in whole for token in _AIR_TOKENS):
        return ("air_purifier", DEVICE_TYPE_REMOTE)
    if any(token in first or token in whole for token in _CAMERA_TOKENS):
        return ("camera", DEVICE_TYPE_REMOTE)
    if any(token in first or token in whole for token in _CONSOLE_TOKENS):
        return ("console", DEVICE_TYPE_REMOTE)
    if any(token in first or token in whole for token in _MEDIA_TOKENS):
        if "projector" in whole:
            return ("projector", DEVICE_TYPE_MEDIA_PLAYER)
        if "soundbar" in whole:
            return ("soundbar", DEVICE_TYPE_MEDIA_PLAYER)
        if "receiver" in whole or "amplifier" in whole or "audio" in first:
            return ("receiver", DEVICE_TYPE_MEDIA_PLAYER)
        return ("tv", DEVICE_TYPE_MEDIA_PLAYER)
    return ("custom", DEVICE_TYPE_REMOTE)


def catalog_row_from_path(path: str) -> dict[str, Any] | None:
    """Convert one GitHub tree .ir path into a searchable catalog row."""
    if not path.lower().endswith(".ir"):
        return None
    lowered = path.lower()
    if "/_converted_/" in f"/{lowered}/" or lowered.startswith("_converted_/"):
        return None
    parts = path.split("/")
    if len(parts) < 2:
        return None

    kind, semantic = classify_flipper_path(path)
    # Flipper-IRDB convention is Device Type / Brand / optional Series / file.
    brand_part = parts[1] if len(parts) >= 3 else parts[-2]
    brand = brand_part.replace("_", " ").strip() or "Unknown"
    filename = parts[-1][:-3]
    model = filename.replace("_", " ").strip() or "Unknown model"
    category = parts[0].replace("_", " ").strip()
    catalog_id = f"flipper:{path}"
    return {
        "id": catalog_id,
        "source": "flipper_irdb",
        "kind": kind,
        "semantic_type": semantic,
        "brand": brand,
        "model": model,
        "name": f"{brand} · {model}",
        "path": path,
        "category": category,
        "controller": "Flipper .ir",
        "search": f"{brand} {model} {category} {kind} {path}".lower(),
    }


def parse_github_tree(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse GitHub recursive tree API response into Flipper catalog rows."""
    if payload.get("truncated") is True:
        raise ValueError(
            "GitHub trả catalog Flipper bị truncated; không dùng danh mục thiếu"
        )
    tree = payload.get("tree")
    if not isinstance(tree, list):
        raise ValueError("GitHub tree payload does not contain a tree list")
    rows: list[dict[str, Any]] = []
    for item in tree:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path = item.get("path")
        if not isinstance(path, str):
            continue
        row = catalog_row_from_path(path)
        if row is not None:
            rows.append(row)
    rows.sort(
        key=lambda row: (
            str(row.get("kind")),
            str(row.get("brand")).lower(),
            str(row.get("model")).lower(),
        )
    )
    return rows


def _parse_hex_bytes(value: str) -> list[int]:
    out: list[int] = []
    for token in value.strip().split():
        token = token.strip()
        if not token:
            continue
        out.append(int(token, 16))
    return out


def _parse_flipper_entries(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if current.get("name") and current.get("type"):
                entries.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"filetype", "version"}:
            continue
        if key == "name" and current.get("name") and current.get("type"):
            entries.append(current)
            current = {}
        current[key] = value
    if current.get("name") and current.get("type"):
        entries.append(current)
    return entries


def _append_bits_lsb(
    timings: list[int],
    value: int,
    count: int,
    *,
    mark: int,
    zero_space: int,
    one_space: int,
) -> None:
    for bit in range(count):
        timings.append(mark)
        timings.append(-(one_space if (value >> bit) & 1 else zero_space))


def _encode_nec(protocol: str, address: list[int], command: list[int]) -> tuple[list[int], int]:
    if not address or not command:
        raise ValueError("NEC entry missing address/command")
    p = protocol.lower()
    data: list[int]
    if p == "nec":
        a = address[0]
        c = command[0]
        data = [a, a ^ 0xFF, c, c ^ 0xFF]
    elif p == "necext":
        a0 = address[0]
        a1 = address[1] if len(address) > 1 else 0
        c = command[0]
        data = [a0, a1, c, c ^ 0xFF]
    else:
        raise ValueError(f"Unsupported NEC variant: {protocol}")
    timings = [9000, -4500]
    for byte in data:
        _append_bits_lsb(
            timings, byte, 8, mark=560, zero_space=560, one_space=1690
        )
    timings.append(560)
    return timings, 38000


def _encode_samsung32(address: list[int], command: list[int]) -> tuple[list[int], int]:
    if not address or not command:
        raise ValueError("Samsung32 entry missing address/command")
    # Samsung32 is a 32-bit LSB-first pulse-distance protocol. Flipper stores
    # address and command separately as little-endian bytes.
    a0 = address[0]
    a1 = address[1] if len(address) > 1 else a0
    c = command[0]
    data = [a0, a1, c, c ^ 0xFF]
    timings = [4500, -4500]
    for byte in data:
        _append_bits_lsb(
            timings, byte, 8, mark=560, zero_space=560, one_space=1690
        )
    timings.append(560)
    return timings, 38000


def _encode_sirc(protocol: str, address: list[int], command: list[int]) -> tuple[list[int], int]:
    if not address or not command:
        raise ValueError("SIRC entry missing address/command")
    bits = {"sirc": 12, "sirc15": 15, "sirc20": 20}[protocol.lower()]
    cmd = command[0] & 0x7F
    addr = int.from_bytes(bytes(address[:2] or [0]), "little")
    addr_bits = bits - 7
    payload = cmd | ((addr & ((1 << addr_bits) - 1)) << 7)
    timings = [2400, -600]
    for i in range(bits):
        timings.append(1200 if (payload >> i) & 1 else 600)
        timings.append(-600)
    if timings and timings[-1] < 0:
        timings.pop()
    return timings, 40000


def _append_signed(timings: list[int], value: int) -> None:
    if timings and (timings[-1] > 0) == (value > 0):
        timings[-1] += value
    else:
        timings.append(value)


def _encode_rc5(address: list[int], command: list[int]) -> tuple[list[int], int]:
    if not address or not command:
        raise ValueError("RC5 entry missing address/command")
    addr = address[0] & 0x1F
    cmd = command[0] & 0x7F
    s2 = 0 if cmd & 0x40 else 1
    cmd6 = cmd & 0x3F
    bits = [1, s2, 0]
    bits.extend((addr >> i) & 1 for i in range(4, -1, -1))
    bits.extend((cmd6 >> i) & 1 for i in range(5, -1, -1))
    timings: list[int] = []
    for bit in bits:
        if bit:
            _append_signed(timings, -889)
            _append_signed(timings, 889)
        else:
            _append_signed(timings, 889)
            _append_signed(timings, -889)
    if timings and timings[0] < 0:
        timings.pop(0)
    if timings and timings[-1] < 0:
        timings.pop()
    return timings, 36000


def encode_parsed(
    protocol: str, address_text: str, command_text: str
) -> tuple[list[int], int]:
    """Encode common Flipper parsed protocols into raw timings."""
    p = protocol.strip().lower()
    address = _parse_hex_bytes(address_text)
    command = _parse_hex_bytes(command_text)
    if p in {"nec", "necext"}:
        return _encode_nec(protocol, address, command)
    if p == "samsung32":
        return _encode_samsung32(address, command)
    if p in {"sirc", "sirc15", "sirc20"}:
        return _encode_sirc(protocol, address, command)
    if p in {"rc5", "rc5x"}:
        return _encode_rc5(address, command)
    raise ValueError(f"Parsed protocol chưa được HanJoo hỗ trợ: {protocol}")


def _raw_timings(data: str) -> list[int]:
    values = [int(token) for token in data.split() if token.strip()]
    if len(values) < 2:
        raise ValueError("Flipper raw entry has too few timings")
    timings: list[int] = []
    sign = 1
    for value in values:
        value = abs(int(value))
        if value == 0:
            continue
        timings.append(value if sign > 0 else -value)
        sign *= -1
    return timings


_CANONICAL = {
    "power": "power",
    "power_toggle": "power",
    "power_on": "on",
    "on": "on",
    "power_off": "off",
    "off": "off",
    "vol_up": "volume_up",
    "volume_up": "volume_up",
    "vol_dn": "volume_down",
    "vol_down": "volume_down",
    "volume_down": "volume_down",
    "mute": "mute",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "ok": "ok",
    "enter": "ok",
    "back": "back",
    "menu": "menu",
    "home": "home",
    "input": "input",
    "source": "input",
    "ch_next": "channel_up",
    "channel_up": "channel_up",
    "ch_prev": "channel_down",
    "channel_down": "channel_down",
    "play": "play",
    "pause": "pause",
    "stop": "stop",
    "next": "next",
    "prev": "previous",
    "previous": "previous",
    "oscillate": "oscillate",
    "swing": "oscillate",
    "timer": "timer",
    "mode": "mode",
    "light": "light",
}


def canonical_command_id(name: str, existing: set[str]) -> str:
    raw = _norm(name)
    base = _CANONICAL.get(raw, raw or "command")
    if re.fullmatch(r"speed_?\d+", raw):
        digits = re.sub(r"\D", "", raw)
        base = f"speed_{digits}"
    if re.fullmatch(r"\d", raw):
        base = f"num_{raw}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def parse_flipper_profile(
    text: str,
    *,
    path: str,
    catalog_row: dict[str, Any] | None = None,
) -> ImportResult:
    """Convert one Flipper .ir file into a HanJoo profile."""
    row = catalog_row or catalog_row_from_path(path)
    if row is None:
        raise ValueError("Flipper profile path is invalid")

    warnings: list[str] = []
    commands: dict[str, dict[str, Any]] = {}
    unsupported = 0
    entries = _parse_flipper_entries(text)
    for entry in entries:
        name = entry.get("name") or "Command"
        try:
            etype = (entry.get("type") or "").strip().lower()
            if etype == "raw":
                frequency = int(entry.get("frequency") or DEFAULT_FREQUENCY)
                timings = _raw_timings(entry.get("data") or "")
            elif etype == "parsed":
                timings, frequency = encode_parsed(
                    entry.get("protocol") or "",
                    entry.get("address") or "",
                    entry.get("command") or "",
                )
            else:
                raise ValueError(f"Loại Flipper không hỗ trợ: {etype}")
            code = code_from_timings(timings, frequency)
        except (ValueError, TypeError) as err:
            unsupported += 1
            warnings.append(f"{name}: {err}")
            continue

        command_id = canonical_command_id(name, set(commands))
        commands[command_id] = {
            "name": name.replace("_", " "),
            "codes": [code],
            "send_count": 1,
        }

    if not commands:
        detail = f" ({unsupported} lệnh không hỗ trợ)" if unsupported else ""
        raise ValueError(f"Flipper profile không có lệnh có thể dùng{detail}")

    profile = {
        "id": uuid.uuid4().hex,
        "name": row.get("model") or row.get("name") or "Flipper IR device",
        "type": row.get("semantic_type") or DEVICE_TYPE_REMOTE,
        "kind": row.get("kind") or "custom",
        "brand": row.get("brand"),
        "model": row.get("model"),
        "source": "flipper_irdb",
        "commands": commands,
        "source_ref": {
            "provider": "flipper_irdb",
            "repository": FLIPPER_REPO,
            "ref": FLIPPER_REF,
            "path": path,
            "license": FLIPPER_LICENSE,
        },
    }
    if profile["type"] == DEVICE_TYPE_FAN:
        speed_modes = []
        for command_id in commands:
            if command_id.startswith("speed_") and command_id[6:].isdigit():
                speed_modes.append(command_id[6:])
        profile["fan"] = {"speed_modes": speed_modes}

    if unsupported:
        warnings.insert(
            0,
            f"Đã bỏ qua {unsupported}/{len(entries)} lệnh parsed/raw chưa chuyển đổi được.",
        )
    return ImportResult(profile=profile, source_format="flipper-ir", warnings=warnings)
