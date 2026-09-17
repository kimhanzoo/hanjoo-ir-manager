"""Native A/C recognition bridge for HanJoo Brain.

The public codec sidecar (:8101) already runs the pinned IRremoteESP8266 and
irtxrx decoders.  Historically that evidence was available for diagnostics but
was not always forwarded into Brain (:8102), so Brain could fall back to a
weaker timing-family guess.  This module patches the thin Core client once at
integration import time and injects conservative, cross-capture A/C candidates
into the existing Brain fusion request.

No user/device state is stored here.  The bridge is local-only and only affects
recognition evidence.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .core_client import HanJooCoreClient

_PATCH_FLAG = "_hanjoo_native_ac_bridge_v2"
_ORIGINAL_FUSE = HanJooCoreClient.fuse_identification


def _canonical_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    state = dict(value)

    # IRremoteESP8266 stdAc uses ``degrees`` and numeric enum values.  Normalize
    # only for semantic checking; the original protocol identity is preserved.
    if state.get("temp") is None:
        for key in ("temperature", "degrees"):
            if state.get(key) is not None:
                state["temp"] = state.get(key)
                break

    mode = state.get("mode")
    if isinstance(mode, (int, float)):
        state["mode"] = {
            -1: "off",
            0: "auto",
            1: "cool",
            2: "heat",
            3: "dry",
            4: "fan_only",
        }.get(int(mode), mode)

    if state.get("fan") is None:
        fan = state.get("fanspeed")
        if isinstance(fan, (int, float)):
            state["fan"] = {
                0: "auto",
                1: "min",
                2: "low",
                3: "medium",
                4: "high",
                5: "max",
                6: "medium_high",
            }.get(int(fan), fan)
        elif fan is not None:
            state["fan"] = fan

    return state


def _agreement(decoded: dict[str, Any], expected: dict[str, Any]) -> float:
    keys = [
        key
        for key, value in expected.items()
        if value is not None and key in {"power", "mode", "temp", "fan", "swing"}
    ]
    if not keys:
        return 1.0

    score = 0.0
    for key in keys:
        actual = decoded.get(key)
        wanted = expected.get(key)
        if key == "temp":
            try:
                score += 1.0 if abs(float(actual) - float(wanted)) <= 0.51 else 0.0
            except (TypeError, ValueError):
                pass
        elif key == "power":
            if actual is None and str(decoded.get("mode") or "").lower() == "off":
                actual = False
            score += 1.0 if bool(actual) is bool(wanted) else 0.0
        else:
            score += 1.0 if str(actual).lower() == str(wanted).lower() else 0.0
    return score / len(keys)


def _state_signature(state: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(state.get(key) for key in ("power", "mode", "temp", "fan", "swing"))


def _match_quality(match: dict[str, Any], expected: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    canonical = _canonical_state(match.get("canonical") or match.get("hvac_state"))
    semantic = _agreement(canonical, expected) if canonical else 0.0
    quality = (
        (3000 if match.get("native_decoder") and str(match.get("type") or "").lower() == "ac" else 0)
        + (1200 if str(match.get("type") or "").lower() == "ac" or match.get("ac_state") else 0)
        + (500 if match.get("structured") or canonical else 0)
        + int(match.get("variant_hits") or 0) * 20
        + semantic * 400
        + min(int(match.get("richness") or 0), 20) * 5
    )
    return quality, canonical


def _fallback_matches(result: dict[str, Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(result.get("matches"), list):
        matches.extend(row for row in result["matches"] if isinstance(row, dict))
        return matches

    irtxrx = result.get("irtxrx") if isinstance(result.get("irtxrx"), dict) else {}
    matches.extend(row for row in irtxrx.get("matches") or [] if isinstance(row, dict))

    native = result.get("irremoteesp8266") if isinstance(result.get("irremoteesp8266"), dict) else {}
    native_rows = native.get("candidates") if isinstance(native.get("candidates"), list) else []
    if not native_rows and isinstance(native.get("match"), dict):
        native_rows = [native["match"]]
    for row in native_rows:
        if not isinstance(row, dict) or not row.get("protocol"):
            continue
        matches.append(
            {
                "protocol": row.get("protocol"),
                "brand": row.get("brand"),
                "type": "ac" if row.get("ac_state") else "remote",
                "structured": bool(row.get("ac_state")),
                "can_encode": False,
                "canonical": row.get("hvac_state") if isinstance(row.get("hvac_state"), dict) else {},
                "hvac_state": row.get("hvac_state"),
                "native_decoder": True,
                "ac_state": bool(row.get("ac_state")),
                "variant_hits": row.get("variant_hits") or 1,
                "richness": 8 if row.get("ac_state") else 1,
                "source": "irremoteesp8266",
            }
        )
    return matches


async def _native_ac_candidates(
    client: HanJooCoreClient,
    captures: list[dict[str, Any]],
    kind_hint: str,
) -> list[dict[str, Any]]:
    if len(captures) < 2:
        return []

    guided_ac = kind_hint in {"air_conditioner", "climate"} or any(
        any(key in (capture.get("expected") or {}) for key in ("temp", "mode"))
        for capture in captures
    )
    if not guided_ac:
        return []

    probed = await asyncio.gather(
        *(client.probe_all(list(capture.get("timings") or [])) for capture in captures),
        return_exceptions=True,
    )

    groups: dict[str, dict[str, Any]] = {}
    for capture, result in zip(captures, probed):
        if isinstance(result, Exception) or not isinstance(result, dict):
            continue
        expected = dict(capture.get("expected") or {})

        # Keep at most the best evidence for one protocol from one physical
        # button press, otherwise frame variants could inflate matched_captures.
        per_capture: dict[str, tuple[float, dict[str, Any], dict[str, Any]]] = {}
        for match in _fallback_matches(result):
            protocol = str(match.get("protocol") or "").strip()
            if not protocol:
                continue
            is_ac = bool(match.get("ac_state")) or str(match.get("type") or "").lower() == "ac"
            if not is_ac:
                continue
            quality, canonical = _match_quality(match, expected)
            key = protocol.lower().replace(" ", "_")
            old = per_capture.get(key)
            if old is None or quality > old[0]:
                per_capture[key] = (quality, match, canonical)

        for key, (_quality, match, canonical) in per_capture.items():
            row = groups.setdefault(
                key,
                {
                    "protocol": str(match.get("protocol") or ""),
                    "brand": match.get("brand"),
                    "sources": set(),
                    "states": [],
                    "agreements": [],
                    "can_encode": False,
                    "native": False,
                    "structured": False,
                },
            )
            row["brand"] = row.get("brand") or match.get("brand")
            row["sources"].add(str(match.get("source") or ("irremoteesp8266" if match.get("native_decoder") else "codec")))
            row["states"].append(canonical)
            row["agreements"].append(_agreement(canonical, expected) if canonical else 0.0)
            row["can_encode"] = row["can_encode"] or bool(match.get("can_encode"))
            row["native"] = row["native"] or bool(match.get("native_decoder"))
            row["structured"] = row["structured"] or bool(match.get("structured") or canonical)

    total = len(captures)
    output: list[dict[str, Any]] = []
    for key, row in groups.items():
        matched = len(row["states"])
        if matched < 2:
            continue
        valid_ratio = matched / total if total else 0.0
        semantic = sum(row["agreements"]) / len(row["agreements"]) if row["agreements"] else 0.0
        distinct = len({_state_signature(state) for state in row["states"] if state})

        confidence = round(
            52 * valid_ratio
            + 31 * semantic
            + (8 if row["structured"] else 0)
            + (6 if row["native"] else 0)
            + (3 if distinct >= 2 else 0)
        )
        confidence = max(0, min(100, confidence))

        # A/C auto recommendation is deliberately strict: all three guided
        # captures must decode as the same protocol and follow 24/25/26 C.
        safe = (
            total >= 3
            and matched >= 3
            and valid_ratio >= 0.99
            and semantic >= 0.84
            and distinct >= 2
            and confidence >= 90
        )

        protocol = row["protocol"]
        source_engine = "irremoteesp8266" if row["native"] else "irtxrx"
        output.append(
            {
                "candidate": {
                    "id": f"codec:{key}",
                    "brand": row.get("brand"),
                    "model": protocol,
                    "kind": "air_conditioner",
                    "source": "protocol_engine",
                    "engine": source_engine,
                    "variant": protocol,
                    "protocol": protocol,
                    "recognition_only": not bool(row["can_encode"]),
                },
                "group_id": f"protocol:{key}",
                "confidence": confidence,
                "matched_captures": matched,
                "capture_count": total,
                "semantic_ratio": round(semantic, 4),
                "distinct_matches": distinct,
                "decoded_states": row["states"][:4],
                "evidence_sources": sorted(row["sources"]),
                "evidence": "native_ac_decode",
                "_core_recommended": safe,
            }
        )

    output.sort(
        key=lambda item: (
            -int(bool(item.get("_core_recommended"))),
            -int(item.get("confidence") or 0),
            -int(item.get("matched_captures") or 0),
        )
    )
    return output[:24]


def _merge_candidates(existing: list[dict[str, Any]], native: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in [*native, *existing]:
        if not isinstance(row, dict):
            continue
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        cid = str(candidate.get("id") or row.get("group_id") or "")
        if not cid:
            continue
        old = merged.get(cid)
        if old is None or int(row.get("confidence") or 0) > int(old.get("confidence") or 0):
            merged[cid] = row
    return list(merged.values())


async def _fuse_with_native_ac(
    self: HanJooCoreClient,
    captures: list[dict[str, Any]],
    *,
    kind_hint: str = "auto",
    candidates: list[dict[str, Any]] | None = None,
    profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    native_rows: list[dict[str, Any]] = []
    try:
        native_rows = await _native_ac_candidates(self, captures, str(kind_hint or "auto").lower())
    except Exception:
        # Recognition must remain usable even if the public sidecar probe fails.
        native_rows = []

    result = await _ORIGINAL_FUSE(
        self,
        captures,
        kind_hint=kind_hint,
        candidates=_merge_candidates(list(candidates or []), native_rows),
        profiles=profiles,
    )
    if isinstance(result, dict):
        result.setdefault("native_ac_bridge_candidates", len(native_rows))
    return result


if not getattr(HanJooCoreClient, _PATCH_FLAG, False):
    HanJooCoreClient.fuse_identification = _fuse_with_native_ac
    setattr(HanJooCoreClient, _PATCH_FLAG, True)
