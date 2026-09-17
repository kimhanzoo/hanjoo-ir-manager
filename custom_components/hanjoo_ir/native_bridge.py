"""Bridge IRremoteESP8266 native A/C evidence into the protected Brain.

The public sidecar is the protocol decoder; the Brain remains responsible for
ranking/recommendation. This module translates only strong, repeated native A/C
decodes into the Manager candidate/result shape.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from .core_client import HanJooCoreClient

_ORIGINAL_FUSE = HanJooCoreClient.fuse_identification
_MODE = {-1: "off", 0: "auto", 1: "cool", 2: "heat", 3: "dry", 4: "fan_only"}
_FAN = {0: "auto", 1: "min", 2: "low", 3: "medium", 4: "high", 5: "max", 6: "medium_high"}
_SWING_V = {-1: "off", 0: "auto", 1: "highest", 2: "high", 3: "middle", 4: "low", 5: "lowest", 6: "upper_middle"}
_SWING_H = {-1: "off", 0: "auto", 1: "left_max", 2: "left", 3: "middle", 4: "right", 5: "right_max", 6: "wide"}


def _brand(protocol: str) -> str | None:
    p = protocol.upper()
    for token, brand in (("DAIKIN", "Daikin"), ("PANASONIC", "Panasonic"), ("MITSUBISHI", "Mitsubishi"), ("FUJITSU", "Fujitsu"), ("HITACHI", "Hitachi"), ("SAMSUNG", "Samsung"), ("TOSHIBA", "Toshiba"), ("GREE", "Gree"), ("MIDEA", "Midea"), ("HAIER", "Haier"), ("SHARP", "Sharp"), ("SANYO", "Sanyo"), ("KELVINATOR", "Kelvinator"), ("WHIRLPOOL", "Whirlpool"), ("AIRWELL", "Airwell"), ("VESTEL", "Vestel"), ("ELECTRA", "Electra")):
        if token in p:
            return brand
    return None


def _canonical(match: dict[str, Any]) -> dict[str, Any]:
    raw = match.get("hvac_state") if isinstance(match.get("hvac_state"), dict) else {}
    state = {
        "power": raw.get("power"),
        "mode": _MODE.get(raw.get("mode"), raw.get("mode")),
        "temp": raw.get("degrees"),
        "temperature": raw.get("degrees"),
        "fan": _FAN.get(raw.get("fanspeed"), raw.get("fanspeed")),
        "swingV": _SWING_V.get(raw.get("swingv"), raw.get("swingv")),
        "swingH": _SWING_H.get(raw.get("swingh"), raw.get("swingh")),
        "model": raw.get("model"),
    }
    return {k: v for k, v in state.items() if v is not None}


def _agreement(state: dict[str, Any], expected: dict[str, Any]) -> float:
    keys = [k for k in ("power", "mode", "temp") if expected.get(k) is not None]
    if not keys:
        return 1.0
    score = 0.0
    for key in keys:
        wanted, actual = expected.get(key), state.get(key)
        if key == "temp":
            try:
                score += 1.0 if abs(float(actual) - float(wanted)) <= 0.51 else 0.0
            except (TypeError, ValueError):
                pass
        elif key == "power":
            score += 1.0 if bool(actual) is bool(wanted) else 0.0
        else:
            score += 1.0 if str(actual).lower() == str(wanted).lower() else 0.0
    return score / len(keys)


async def _native_rows(client: HanJooCoreClient, captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(captures) < 3:
        return []
    results = await asyncio.gather(*(client.probe_all(list(cap.get("timings") or [])) for cap in captures), return_exceptions=True)
    grouped: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for index, (cap, result) in enumerate(zip(captures, results)):
        if isinstance(result, Exception) or not isinstance(result, dict):
            continue
        native = result.get("irremoteesp8266") if isinstance(result.get("irremoteesp8266"), dict) else {}
        matches = list(native.get("candidates") or [])
        if not matches and isinstance(native.get("match"), dict):
            matches = [native["match"]]
        for match in matches:
            if isinstance(match, dict) and match.get("ac_state") and match.get("protocol"):
                grouped[str(match["protocol"]).upper()].append((index, match, dict(cap.get("expected") or {})))

    rows: list[dict[str, Any]] = []
    total = len(captures)
    for protocol, hits in grouped.items():
        by_press: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
        for index, match, expected in hits:
            old = by_press.get(index)
            if old is None or bool(match.get("full_capture_match")):
                by_press[index] = (match, expected)
        if len(by_press) < 3:
            continue
        states = [_canonical(match) for match, _ in by_press.values()]
        agreements = [_agreement(_canonical(match), expected) for match, expected in by_press.values()]
        semantic = sum(agreements) / len(agreements) if agreements else 0.0
        distinct = len({(s.get("power"), s.get("mode"), s.get("temp")) for s in states})
        guided = any(bool(expected) for _, expected in by_press.values())
        if guided and semantic < 0.80:
            continue
        if not guided and distinct < 2:
            continue
        valid = len(by_press)
        confidence = min(99, round(72 + 18 * (valid / total) + 8 * semantic + (2 if distinct >= 2 else 0)))
        first = next(iter(by_press.values()))[0]
        brand = first.get("brand") or _brand(protocol)
        candidate_id = f"native_ac:{protocol.lower()}"
        candidate = {"id": candidate_id, "brand": brand, "model": protocol, "kind": "air_conditioner", "source": "protocol_engine", "engine": "irremoteesp8266", "variant": protocol, "protocol": protocol, "recognition_only": True, "native_decoder": True}
        rows.append({"candidate": candidate, "group_id": f"protocol:irremoteesp8266:{protocol.lower()}", "confidence": confidence, "matched_captures": valid, "capture_count": total, "semantic_ratio": round(semantic, 4), "distinct_matches": distinct, "decoded_states": states, "evidence_sources": ["irremoteesp8266_native_ac"], "evidence": "native_ac_decode", "_core_recommended": valid >= 3 and (semantic >= 0.80 if guided else distinct >= 2)})
    rows.sort(key=lambda row: (-int(row.get("confidence") or 0), -int(row.get("matched_captures") or 0)))
    return rows


async def _fuse_with_native(self: HanJooCoreClient, captures: list[dict[str, Any]], *, kind_hint: str = "auto", candidates=None, profiles=None):
    result = await _ORIGINAL_FUSE(self, captures, kind_hint=kind_hint, candidates=candidates, profiles=profiles)
    if str(kind_hint or "auto").lower() not in {"auto", "air_conditioner", "climate"}:
        return result
    native = await _native_rows(self, captures)
    if not native:
        if str(kind_hint).lower() in {"air_conditioner", "climate"}:
            kept = []
            for row in list(result.get("candidates") or []):
                confidence = int(row.get("confidence") or 0)
                matched = int(row.get("matched_captures") or 0)
                total = int(row.get("capture_count") or len(captures) or 0)
                if confidence < 60 and matched < max(3, total):
                    continue
                kept.append(row)
            result["candidates"] = kept
        return result
    existing = list(result.get("candidates") or [])
    native_ids = {row["candidate"]["id"] for row in native}
    result["candidates"] = native + [row for row in existing if str((row.get("candidate") or {}).get("id") or "") not in native_ids]
    best = native[0]
    if bool(best.get("_core_recommended")):
        result["recommended"] = True
        result["recommended_id"] = best["candidate"]["id"]
        result["equivalent_candidate_ids"] = [best["candidate"]["id"]]
        brand = best["candidate"].get("brand")
        hints = [str(x) for x in list(result.get("brand_hints") or []) if x]
        if brand and brand.lower() not in {x.lower() for x in hints}:
            hints.insert(0, brand)
        result["brand_hints"] = hints[:8]
        result["message_en"] = f"Native AC decoder confirmed {best['candidate']['model']} across {best['matched_captures']}/{best['capture_count']} captures."
        result["message_vi"] = f"Native AC decoder đã xác nhận {best['candidate']['model']} trên {best['matched_captures']}/{best['capture_count']} mẫu."
        result["message"] = result["message_en"]
    return result


if HanJooCoreClient.fuse_identification is not _fuse_with_native:
    HanJooCoreClient.fuse_identification = _fuse_with_native
