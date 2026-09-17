"""Bridge strong native A/C decoder evidence into HanJoo Brain fusion."""
from __future__ import annotations

from typing import Any

from .core_client import HanJooCoreClient

_PATCH_FLAG = "_hanjoo_native_ac_bridge_v4"
_ORIGINAL_FUSE = HanJooCoreClient.fuse_identification

_MODE = {-1: "off", 0: "auto", 1: "cool", 2: "heat", 3: "dry", 4: "fan_only"}
_FAN = {0: "auto", 1: "min", 2: "low", 3: "medium", 4: "high", 5: "max", 6: "medium_high"}


def _canonical(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out = dict(value)
    if out.get("temp") is None:
        out["temp"] = out.get("temperature", out.get("degrees"))
    mode = out.get("mode")
    if isinstance(mode, (int, float)):
        out["mode"] = _MODE.get(int(mode), mode)
    if out.get("fan") is None:
        fan = out.get("fanspeed")
        out["fan"] = _FAN.get(int(fan), fan) if isinstance(fan, (int, float)) else fan
    return out


def _agreement(state: dict[str, Any], expected: dict[str, Any]) -> float:
    keys = [k for k in ("power", "mode", "temp") if expected.get(k) is not None]
    if not keys:
        return 1.0
    good = 0.0
    for key in keys:
        actual, wanted = state.get(key), expected.get(key)
        if key == "temp":
            try:
                good += 1.0 if abs(float(actual) - float(wanted)) <= 0.51 else 0.0
            except (TypeError, ValueError):
                pass
        elif key == "power":
            if actual is None and str(state.get("mode") or "").lower() == "off":
                actual = False
            good += 1.0 if bool(actual) is bool(wanted) else 0.0
        else:
            good += 1.0 if str(actual).lower() == str(wanted).lower() else 0.0
    return good / len(keys)


def _matches(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("matches"), list):
        return [dict(x) for x in result["matches"] if isinstance(x, dict)]
    rows: list[dict[str, Any]] = []
    irtxrx = result.get("irtxrx") if isinstance(result.get("irtxrx"), dict) else {}
    rows.extend(dict(x) for x in irtxrx.get("matches") or [] if isinstance(x, dict))
    native = result.get("irremoteesp8266") if isinstance(result.get("irremoteesp8266"), dict) else {}
    native_rows = native.get("candidates") if isinstance(native.get("candidates"), list) else []
    if not native_rows and isinstance(native.get("match"), dict):
        native_rows = [native["match"]]
    for x in native_rows:
        if not isinstance(x, dict) or not x.get("protocol"):
            continue
        rows.append({
            "protocol": x.get("protocol"), "brand": x.get("brand"),
            "type": "ac" if x.get("ac_state") else "remote",
            "structured": bool(x.get("ac_state")), "can_encode": False,
            "canonical": x.get("hvac_state") if isinstance(x.get("hvac_state"), dict) else {},
            "native_decoder": True, "ac_state": bool(x.get("ac_state")),
            "variant_hits": x.get("variant_hits") or 1, "source": "irremoteesp8266",
        })
    return rows


async def _native_rows(client: HanJooCoreClient, captures: list[dict[str, Any]], kind_hint: str) -> list[dict[str, Any]]:
    guided_ac = kind_hint in {"air_conditioner", "climate"} or any(
        any(k in (c.get("expected") or {}) for k in ("temp", "mode")) for c in captures
    )
    if not guided_ac or len(captures) < 2:
        return []

    probed: list[dict[str, Any] | Exception] = []
    for capture in captures:
        try:
            result = await client.probe_all(list(capture.get("timings") or []))
            probed.append(result if isinstance(result, dict) else {})
        except Exception as err:
            probed.append(err)

    groups: dict[str, dict[str, Any]] = {}
    for index, (capture, result) in enumerate(zip(captures, probed)):
        if isinstance(result, Exception) or not isinstance(result, dict):
            continue
        expected = dict(capture.get("expected") or {})
        per_press: dict[str, tuple[float, dict[str, Any], dict[str, Any]]] = {}
        for match in _matches(result):
            protocol = str(match.get("protocol") or "").strip()
            is_ac = bool(match.get("ac_state")) or str(match.get("type") or "").lower() == "ac"
            if not protocol or not is_ac:
                continue
            state = _canonical(match.get("canonical") or match.get("hvac_state"))
            semantic = _agreement(state, expected) if state else 0.0
            quality = (
                (3000 if match.get("native_decoder") else 0)
                + (700 if state or match.get("structured") else 0)
                + int(match.get("variant_hits") or 0) * 20
                + semantic * 500
            )
            key = protocol.lower().replace(" ", "_")
            if key not in per_press or quality > per_press[key][0]:
                per_press[key] = (quality, match, state)

        for key, (_quality, match, state) in per_press.items():
            row = groups.setdefault(key, {
                "protocol": str(match.get("protocol") or ""), "brand": match.get("brand"),
                "hits": {}, "can_encode": False, "native": False, "sources": set(),
            })
            row["brand"] = row.get("brand") or match.get("brand")
            row["hits"][index] = (state, expected)
            row["can_encode"] = row["can_encode"] or bool(match.get("can_encode"))
            row["native"] = row["native"] or bool(match.get("native_decoder"))
            row["sources"].add(str(match.get("source") or ("irremoteesp8266" if match.get("native_decoder") else "irtxrx")))

    total = len(captures)
    out: list[dict[str, Any]] = []
    for key, row in groups.items():
        hits = list(row["hits"].values())
        matched = len(hits)
        if matched < 2:
            continue
        states = [state for state, _ in hits]
        agreements = [_agreement(state, expected) if state else 0.0 for state, expected in hits]
        semantic = sum(agreements) / len(agreements) if agreements else 0.0
        distinct = len({(s.get("power"), s.get("mode"), s.get("temp")) for s in states if s})
        ratio = matched / total if total else 0.0
        confidence = max(0, min(100, round(
            52 * ratio + 31 * semantic + (8 if any(states) else 0)
            + (6 if row["native"] else 0) + (3 if distinct >= 2 else 0)
        )))
        safe = total >= 3 and matched >= 3 and ratio >= 0.99 and semantic >= 0.84 and distinct >= 2 and confidence >= 90
        protocol = row["protocol"]
        out.append({
            "candidate": {
                "id": f"codec:{key}", "brand": row.get("brand"), "model": protocol,
                "kind": "air_conditioner", "source": "protocol_engine",
                "engine": "irremoteesp8266" if row["native"] else "irtxrx",
                "variant": protocol, "protocol": protocol,
                "recognition_only": not bool(row["can_encode"]),
            },
            "group_id": f"protocol:{key}", "confidence": confidence,
            "matched_captures": matched, "capture_count": total,
            "semantic_ratio": round(semantic, 4), "distinct_matches": distinct,
            "decoded_states": states[:3], "evidence_sources": sorted(row["sources"]),
            "evidence": "native_ac_decode", "_core_recommended": safe,
        })
    out.sort(key=lambda x: (-int(bool(x.get("_core_recommended"))), -int(x.get("confidence") or 0), -int(x.get("matched_captures") or 0)))
    return out[:24]


def _merge(existing: list[dict[str, Any]], native: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in [*native, *existing]:
        if not isinstance(row, dict):
            continue
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        key = str(candidate.get("id") or row.get("group_id") or "")
        if not key:
            continue
        old = rows.get(key)
        if old is None or int(row.get("confidence") or 0) > int(old.get("confidence") or 0):
            rows[key] = row
    return list(rows.values())


def _base_result(native: list[dict[str, Any]], *, brain_unavailable: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "recommended": False,
        "recommended_id": None,
        "equivalent_candidate_ids": [],
        "candidates": list(native),
        "brand_hints": [],
        "native_ac_bridge_candidates": len(native),
    }
    if brain_unavailable:
        result["brain_degraded"] = True
        result["message_en"] = "Brain service restarted during analysis; native protocol evidence is shown without automatic recommendation."
        result["message_vi"] = "Brain đã khởi động lại trong lúc phân tích; HanJoo vẫn hiển thị bằng chứng protocol native nhưng không tự khuyến nghị."
        result["message"] = result["message_en"]
    return result


def _postprocess(result: dict[str, Any], native: list[dict[str, Any]], captures: list[dict[str, Any]], kind_hint: str) -> dict[str, Any]:
    result["native_ac_bridge_candidates"] = len(native)
    if not native:
        if kind_hint in {"air_conditioner", "climate"}:
            kept = []
            for row in list(result.get("candidates") or []):
                confidence = int(row.get("confidence") or 0)
                matched = int(row.get("matched_captures") or 0)
                if confidence >= 60 or matched >= 3:
                    kept.append(row)
            result["candidates"] = kept
            valid_ids = {str((r.get("candidate") or {}).get("id") or "") for r in kept}
            if str(result.get("recommended_id") or "") not in valid_ids:
                result["recommended"] = False
                result["recommended_id"] = None
        return result

    result["candidates"] = _merge(list(result.get("candidates") or []), native)
    result["candidates"].sort(key=lambda x: (-int(bool(x.get("_core_recommended"))), -int(x.get("confidence") or 0)))
    best = native[0]
    brand = (best.get("candidate") or {}).get("brand")
    if brand:
        hints = [str(x) for x in list(result.get("brand_hints") or []) if x]
        if brand.lower() not in {x.lower() for x in hints}:
            hints.insert(0, brand)
        result["brand_hints"] = hints[:8]
    if best.get("_core_recommended"):
        cid = str((best.get("candidate") or {}).get("id") or "")
        protocol = str((best.get("candidate") or {}).get("model") or "A/C")
        result["recommended"] = True
        result["recommended_id"] = cid
        result["equivalent_candidate_ids"] = [cid]
        result["message_en"] = f"Native A/C decoding confirmed {protocol} across {best['matched_captures']}/{best['capture_count']} captures."
        result["message_vi"] = f"Bộ giải mã A/C native đã xác nhận {protocol} trên {best['matched_captures']}/{best['capture_count']} mẫu."
        result["message"] = result["message_en"]
    return result


async def _fuse_with_native_ac(self: HanJooCoreClient, captures: list[dict[str, Any]], *, kind_hint: str = "auto", candidates=None, profiles=None) -> dict[str, Any]:
    hint = str(kind_hint or "auto").lower()
    try:
        native = await _native_rows(self, captures, hint)
    except Exception:
        native = []

    try:
        result = await _ORIGINAL_FUSE(
            self, captures, kind_hint=kind_hint,
            candidates=_merge(list(candidates or []), native), profiles=profiles,
        )
    except Exception:
        return _postprocess(_base_result(native, brain_unavailable=True), native, captures, hint)

    return _postprocess(result if isinstance(result, dict) else {}, native, captures, hint)


if not getattr(HanJooCoreClient, _PATCH_FLAG, False):
    HanJooCoreClient.fuse_identification = _fuse_with_native_ac
    setattr(HanJooCoreClient, _PATCH_FLAG, True)
