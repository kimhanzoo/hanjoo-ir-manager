"""IR code conversion and replay helpers.

HanJoo stores one portable representation: signed microsecond timings plus a
carrier frequency. Importers may accept Pronto, Broadlink Base64/Hex, Tuya
FastLZ Base64, or decimal raw timings; everything is converted before it enters
the device/profile store.
"""
from __future__ import annotations

import abc
import base64
import binascii
import re
import struct
from typing import Any

try:
    import heatshrink2
except ImportError:  # standalone tests / HA before requirement installation
    heatshrink2 = None

try:
    from infrared_protocols.commands import Command
except ImportError:  # pragma: no cover - used by the standalone test harness
    class Command(abc.ABC):  # type: ignore[no-redef]
        """Small compatible stand-in for tests outside Home Assistant."""

        def __init__(self, *, modulation: int, repeat_count: int = 0) -> None:
            self.modulation = modulation
            self.repeat_count = repeat_count

        @abc.abstractmethod
        def get_raw_timings(self) -> list[int]:
            """Return signed mark/space timings."""

from .const import (
    DEFAULT_FREQUENCY,
    MAX_DURATION_US,
    MAX_IMPORT_BYTES,
    MAX_TIMINGS,
    MAX_TOTAL_AIRTIME_US,
    TRAILING_SPACE_US,
)

_PRONTO_FREQ_FACTOR = 0.241246
_BROADLINK_TICK_US = 1_000_000 / 32_768
_BROADLINK_TYPES = (0x26, 0xB2, 0xD7)
_TUYA_MAX_INFLATED_BYTES = 8192


class IRCodeError(ValueError):
    """Raised when an imported IR code is malformed or unsafe."""


def _normalize_signed(timings: list[int]) -> list[int]:
    """Return alternating positive mark / negative space timings."""
    if not timings:
        raise IRCodeError("IR timings are empty")
    if len(timings) > MAX_TIMINGS:
        raise IRCodeError(f"IR code has too many timings ({len(timings)})")

    out: list[int] = []
    total = 0
    for idx, raw in enumerate(timings):
        try:
            value = abs(int(raw))
        except (TypeError, ValueError) as err:
            raise IRCodeError("IR timing is not an integer") from err
        if value <= 0:
            raise IRCodeError("IR timings must be greater than zero")
        if value > MAX_DURATION_US:
            # A receiver's learning timeout is commonly stored as a huge final
            # silence. It is safe to clamp only the last SPACE; interior values
            # are rejected because changing them would alter the protocol.
            if idx == len(timings) - 1 and idx % 2 == 1:
                value = TRAILING_SPACE_US
            else:
                raise IRCodeError(f"IR timing {value} us is implausibly long")
        total += value
        if total > MAX_TOTAL_AIRTIME_US:
            raise IRCodeError("IR code is implausibly long")
        out.append(value if idx % 2 == 0 else -value)

    # Stored identity does not need a receiver-side capture timeout. Keep a
    # normal short trailing space, but clamp very long tail gaps.
    if out[-1] < 0 and -out[-1] > TRAILING_SPACE_US:
        out[-1] = -TRAILING_SPACE_US
    return out


def _wire_timings(timings: list[int]) -> list[int]:
    """Prepare stored timings for transmission.

    Some emitters behave better when a command ends on silence. The bounded
    50 ms terminator is below uint16 limits and is ignored by the target.
    """
    out = list(_normalize_signed(timings))
    if out[-1] > 0:
        out.append(-TRAILING_SPACE_US)
    elif -out[-1] > TRAILING_SPACE_US:
        out[-1] = -TRAILING_SPACE_US
    return out


class RawIRCommand(Command):
    """infrared_protocols Command backed by stored raw timings."""

    def __init__(
        self,
        timings: list[int],
        *,
        frequency: int = DEFAULT_FREQUENCY,
        repeat_count: int = 0,
    ) -> None:
        if frequency < 20_000 or frequency > 80_000:
            raise IRCodeError(f"Unsupported carrier frequency: {frequency}")
        self._timings = _normalize_signed(timings)
        super().__init__(modulation=int(frequency), repeat_count=int(repeat_count))

    def get_raw_timings(self) -> list[int]:
        return _wire_timings(self._timings)



def raw_to_pronto(timings: list[int], frequency: int = DEFAULT_FREQUENCY) -> str:
    """Convert signed/unsigned microsecond timings to learned Pronto hex."""
    normalized = _normalize_signed(timings)
    if frequency <= 0:
        raise IRCodeError("Carrier frequency must be positive")
    freq_word = round(1_000_000 / (frequency * _PRONTO_FREQ_FACTOR))
    if freq_word <= 0 or freq_word > 0xFFFF:
        raise IRCodeError("Carrier frequency cannot be represented as Pronto")
    period_us = freq_word * _PRONTO_FREQ_FACTOR

    pairs: list[tuple[int, int]] = []
    for idx in range(0, len(normalized), 2):
        mark = abs(normalized[idx])
        space = abs(normalized[idx + 1]) if idx + 1 < len(normalized) else 0
        pairs.append((round(mark / period_us), round(space / period_us)))
    if len(pairs) > 0xFFFF:
        raise IRCodeError("Pronto command has too many pairs")

    words = [0x0000, freq_word, len(pairs), 0x0000]
    for mark, space in pairs:
        words.extend([mark, space])
    return " ".join(f"{word:04X}" for word in words)



def pronto_to_raw(pronto: str) -> tuple[list[int], int]:
    """Decode learned Pronto hex to signed microsecond timings + frequency."""
    if not isinstance(pronto, str):
        raise IRCodeError("Pronto code must be text")
    try:
        words = [int(part, 16) for part in pronto.strip().split()]
    except ValueError as err:
        raise IRCodeError("Pronto code contains non-hex data") from err
    if len(words) < 4:
        raise IRCodeError("Pronto code is too short")
    if words[0] != 0x0000:
        raise IRCodeError("Only learned/raw Pronto (0000) is supported")
    freq_word = words[1]
    if freq_word == 0:
        raise IRCodeError("Pronto frequency word is zero")
    pair_count = words[2] + words[3]
    if pair_count <= 0 or len(words) < 4 + pair_count * 2:
        raise IRCodeError("Pronto timing count is invalid")

    period_us = freq_word * _PRONTO_FREQ_FACTOR
    frequency = round(1_000_000 / period_us)
    timings: list[int] = []
    for i in range(pair_count):
        mark_word = words[4 + i * 2]
        space_word = words[5 + i * 2]
        mark_us = max(1, round(mark_word * period_us))
        space_us = round(space_word * period_us)
        timings.append(mark_us)
        if space_us > 0:
            timings.append(-space_us)
    return _normalize_signed(timings), frequency



def broadlink_packet_to_raw(packet: bytes) -> tuple[list[int], int]:
    """Decode a Broadlink 0x26 IR packet."""
    if len(packet) < 6 or packet[0] != 0x26:
        raise IRCodeError("Not a Broadlink IR packet")
    payload_len = packet[2] | (packet[3] << 8)
    if payload_len <= 0 or 4 + payload_len > len(packet):
        raise IRCodeError("Broadlink payload length is invalid")
    payload = packet[4 : 4 + payload_len]

    ticks: list[int] = []
    i = 0
    while i < len(payload):
        value = payload[i]
        if value == 0:
            if i + 2 >= len(payload):
                raise IRCodeError("Broadlink duration is truncated")
            value = (payload[i + 1] << 8) | payload[i + 2]
            i += 3
        else:
            i += 1
        if value:
            ticks.append(value)
    if len(ticks) < 2:
        raise IRCodeError("Broadlink packet has no usable IR timings")

    durations = [max(1, round(tick * _BROADLINK_TICK_US)) for tick in ticks]
    # Broadlink captures typically append a learning-timeout space. Drop only
    # that final space; the sender will add a bounded terminator again.
    if len(durations) % 2 == 0:
        durations.pop()
    return _normalize_signed(durations), DEFAULT_FREQUENCY



def broadlink_b64_to_raw(code: str) -> tuple[list[int], int]:
    cleaned = code.strip()
    if len(cleaned) % 4:
        cleaned += "=" * (-len(cleaned) % 4)
    try:
        packet = base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError) as err:
        raise IRCodeError("Invalid Base64") from err
    return broadlink_packet_to_raw(packet)



def broadlink_hex_to_raw(code: str) -> tuple[list[int], int]:
    try:
        packet = bytes.fromhex(re.sub(r"\s+", "", code))
    except ValueError as err:
        raise IRCodeError("Invalid hexadecimal Broadlink code") from err
    return broadlink_packet_to_raw(packet)



def fastlz1_decompress(data: bytes, *, max_output: int = _TUYA_MAX_INFLATED_BYTES) -> bytes | None:
    """Small bounds-checked FastLZ level-1 decoder for Tuya IR containers."""
    if not data:
        return None
    out = bytearray()
    i = 0
    while i < len(data):
        ctrl = data[i]
        i += 1
        if ctrl < 0x20:
            length = ctrl + 1
            if i + length > len(data) or len(out) + length > max_output:
                return None
            out += data[i : i + length]
            i += length
            continue

        length = ctrl >> 5
        ref = (ctrl & 0x1F) << 8
        if length == 7:
            if i >= len(data):
                return None
            length += data[i]
            i += 1
        if i >= len(data):
            return None
        ref |= data[i]
        i += 1
        length += 2
        start = len(out) - ref - 1
        if start < 0 or len(out) + length > max_output:
            return None
        for _ in range(length):
            out.append(out[start])
            start += 1
    return bytes(out)



def _u16_blob_to_raw(blob: bytes) -> tuple[list[int], int]:
    if not blob or len(blob) % 2:
        raise IRCodeError("Tuya timing blob has an invalid length")
    count = len(blob) // 2
    if count < 4 or count > MAX_TIMINGS:
        raise IRCodeError("Tuya timing count is invalid")
    values = list(struct.unpack("<" + "H" * count, blob))
    if len(values) % 2 == 0:
        values.pop()  # drop receiver-side trailing silence
    return _normalize_signed(values), DEFAULT_FREQUENCY



def tuya_b64_to_raw(code: str) -> tuple[list[int], int]:
    """Decode Tuya FastLZ Base64 IR data to timings."""
    cleaned = code.strip()
    if len(cleaned) < 8:
        raise IRCodeError("Tuya code is too short")
    if len(cleaned) % 4:
        cleaned += "=" * (-len(cleaned) % 4)
    try:
        packet = base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as err:
        raise IRCodeError("Invalid Tuya Base64") from err
    if packet and packet[0] in _BROADLINK_TYPES:
        raise IRCodeError("This is a Broadlink packet, not a Tuya container")
    blob = fastlz1_decompress(packet)
    if blob is None:
        raise IRCodeError("Base64 data is not a readable Tuya FastLZ IR container")
    return _u16_blob_to_raw(blob)



def plain_u16_b64_to_raw(code: str) -> tuple[list[int], int]:
    """Decode uncompressed Tuya little-endian uint16 Base64 timings."""
    cleaned = code.strip()
    if len(cleaned) % 4:
        cleaned += "=" * (-len(cleaned) % 4)
    try:
        blob = base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError) as err:
        raise IRCodeError("Invalid Base64") from err
    return _u16_blob_to_raw(blob)




def _heatshrink_decompress(blob: bytes) -> bytes:
    """Decode Xiaomi's heatshrink container using the pinned runtime library."""
    if heatshrink2 is None:
        raise IRCodeError(
            "Xiaomi Raw cần thư viện heatshrink2; hãy restart Home Assistant "
            "sau khi cài/nâng HanJoo IR"
        )
    try:
        fn = getattr(heatshrink2, "decompress", None) or getattr(heatshrink2, "decode")
        out = fn(blob)
    except Exception as err:
        raise IRCodeError("Không giải nén được Xiaomi Raw") from err
    if not isinstance(out, (bytes, bytearray)):
        raise IRCodeError("Xiaomi Raw giải nén ra dữ liệu không hợp lệ")
    if len(out) > 1_000_000:
        raise IRCodeError("Xiaomi Raw giải nén quá lớn")
    return bytes(out)


def _xiaomi_v1_signal_to_raw(payload: bytes) -> tuple[list[int], int]:
    """Parse a ChuangmiIrSignal (magic 0xA567) into signed timings."""
    if len(payload) < 68:
        raise IRCodeError("Xiaomi v1 signal quá ngắn")
    magic, edge_count = struct.unpack_from("<HH", payload, 0)
    if magic != 0xA567:
        raise IRCodeError("Xiaomi v1 signal sai magic")
    if edge_count < 3 or edge_count > MAX_TIMINGS:
        raise IRCodeError("Xiaomi v1 edge count không hợp lệ")
    times = list(struct.unpack_from("<16I", payload, 4))
    pair_count = (edge_count + 1) // 2
    if len(payload) < 68 + pair_count:
        raise IRCodeError("Xiaomi v1 signal bị cắt ngắn")
    raw: list[int] = []
    for idx in range(pair_count):
        packed = payload[68 + idx]
        gap_idx = (packed >> 4) & 0x0F
        pulse_idx = packed & 0x0F
        pulse = int(times[pulse_idx])
        gap = int(times[gap_idx])
        if pulse <= 0:
            raise IRCodeError("Xiaomi v1 chứa pulse 0")
        raw.append(pulse)
        if len(raw) < edge_count:
            if gap <= 0:
                raise IRCodeError("Xiaomi v1 chứa gap 0")
            raw.append(-gap)
    raw = raw[:edge_count]
    return _normalize_signed(raw), 38_000


def xiaomi_raw_to_raw(code: str) -> tuple[list[int], int]:
    """Decode Xiaomi/Chuangmi Raw strings used by SmartIR.

    Two deployed formats are accepted:
    - v1: heatshrink("learn" + base64(ChuangmiIrSignal))
    - v2: heatshrink("duration,duration,...\\0")

    The v2 conversion follows the Chuangmi/SmartIR converter convention:
    stored duration units are scaled by 38/36, so convert back by 36/38
    before storing controller-neutral microseconds.
    """
    cleaned = code.strip()
    if len(cleaned) < 8:
        raise IRCodeError("Xiaomi Raw quá ngắn")
    if len(cleaned) % 4:
        cleaned += "=" * (-len(cleaned) % 4)
    try:
        packed = base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError) as err:
        raise IRCodeError("Xiaomi Raw Base64 không hợp lệ") from err

    decoded = _heatshrink_decompress(packed)

    # v1 wrapper produced by older Chuangmi tools.
    if decoded.startswith(b"learn"):
        inner = decoded[5:].strip().rstrip(b"\x00")
        try:
            signal = base64.b64decode(inner, validate=False)
        except (binascii.Error, ValueError) as err:
            raise IRCodeError("Xiaomi v1 inner Base64 không hợp lệ") from err
        return _xiaomi_v1_signal_to_raw(signal)

    # v2 is a NUL-terminated ASCII duration list.
    try:
        text = decoded.decode("ascii").strip("\x00\r\n ")
    except UnicodeDecodeError as err:
        raise IRCodeError("Xiaomi Raw không phải v1/v2 đã biết") from err
    if not re.fullmatch(r"\d+(?:,\d+){3,}", text):
        raise IRCodeError("Xiaomi v2 timing list không hợp lệ")
    values = [int(v) for v in text.split(",")]
    timings = [
        max(1, round(value * 36_000 / 38_000)) * (1 if i % 2 == 0 else -1)
        for i, value in enumerate(values)
        if value > 0
    ]
    if len(timings) < 4:
        raise IRCodeError("Xiaomi v2 timing list quá ngắn")
    return _normalize_signed(timings), 38_000


def code_from_timings(timings: list[int], frequency: int = DEFAULT_FREQUENCY) -> dict[str, Any]:
    """Create the canonical stored code object."""
    return {
        "format": "raw",
        "frequency": int(frequency or DEFAULT_FREQUENCY),
        "timings": _normalize_signed(timings),
    }



def command_from_code(code: dict[str, Any], *, repeats: int = 1) -> RawIRCommand:
    """Build a runtime command from a canonical stored code."""
    if not isinstance(code, dict) or code.get("format") != "raw":
        raise IRCodeError("Unsupported stored IR code format")
    timings = code.get("timings")
    if not isinstance(timings, list):
        raise IRCodeError("Stored IR timings are missing")
    return RawIRCommand(
        timings,
        frequency=int(code.get("frequency") or DEFAULT_FREQUENCY),
        repeat_count=max(0, int(repeats) - 1),
    )



def decode_external_code(value: Any, encoding: str | None = None) -> dict[str, Any]:
    """Decode a third-party code value into HanJoo's canonical raw format.

    SmartIR labels are not always trustworthy (some files say ``Raw`` but
    contain Tuya Base64). Content-based Tuya detection therefore runs before
    the declared-encoding decoder.
    """
    if isinstance(value, dict) and value.get("format") == "raw":
        return code_from_timings(
            list(value.get("timings") or []),
            int(value.get("frequency") or DEFAULT_FREQUENCY),
        )
    if isinstance(value, list) and all(isinstance(v, (int, float)) for v in value):
        return code_from_timings([int(v) for v in value])
    if not isinstance(value, str):
        raise IRCodeError("IR code must be text or a timing list")
    if len(value.encode("utf-8", errors="ignore")) > MAX_IMPORT_BYTES:
        raise IRCodeError("IR code value is too large")

    text = value.strip()
    enc = (encoding or "").strip().lower()

    if text.upper().startswith("0000 "):
        timings, freq = pronto_to_raw(text)
        return code_from_timings(timings, freq)

    if enc in {"xiaomi_raw", "chuangmi_raw"}:
        timings, freq = xiaomi_raw_to_raw(text)
        return code_from_timings(timings, freq)

    # Content-based Tuya probe for ambiguous SmartIR Raw/Base64 values.
    if enc in {"", "raw", "base64", "tuya"}:
        try:
            timings, freq = tuya_b64_to_raw(text)
        except IRCodeError:
            pass
        else:
            return code_from_timings(timings, freq)

    if enc == "pronto":
        timings, freq = pronto_to_raw(text)
        return code_from_timings(timings, freq)
    if enc == "base64":
        timings, freq = broadlink_b64_to_raw(text)
        return code_from_timings(timings, freq)
    if enc == "hex":
        timings, freq = broadlink_hex_to_raw(text)
        return code_from_timings(timings, freq)
    if enc == "tuya":
        timings, freq = tuya_b64_to_raw(text)
        return code_from_timings(timings, freq)
    if enc in {"tuya_plain", "plain_base64"}:
        timings, freq = plain_u16_b64_to_raw(text)
        return code_from_timings(timings, freq)
    if enc == "raw" or (not enc and re.fullmatch(r"[\s,;:+\-\d]+", text)):
        values = [int(v) for v in re.findall(r"-?\d+", text)]
        if len(values) < 4:
            raise IRCodeError("Raw timing list is too short")
        return code_from_timings(values)

    # Last safe fallback: many exported Broadlink codes omit the encoding.
    if not enc:
        try:
            timings, freq = broadlink_b64_to_raw(text)
        except IRCodeError as err:
            raise IRCodeError("Unknown IR code encoding") from err
        return code_from_timings(timings, freq)

    raise IRCodeError(f"Unsupported IR encoding: {encoding!r}")



def code_to_pronto(code: dict[str, Any]) -> str:
    """Export canonical code as portable Pronto hex."""
    cmd = command_from_code(code)
    # Use stored timings rather than wire terminator to keep exported identity stable.
    return raw_to_pronto(
        list(code["timings"]), int(code.get("frequency") or DEFAULT_FREQUENCY)
    )
