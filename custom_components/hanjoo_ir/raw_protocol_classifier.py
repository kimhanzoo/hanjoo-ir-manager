"""Conservative raw-timing protocol-family classifier.

This module is intentionally independent of the protected Core add-on.  It does
not try to identify a specific appliance from one raw frame.  Its job is to
recognise common wire-format families from robust timing features so Fusion can
use that evidence to search the richer profile libraries.
"""
from __future__ import annotations

from statistics import median
from typing import Any


def _close(value: float, target: float, rel: float) -> float:
    if target <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(float(value) - target) / (target * rel))


def _count_close(value: int, target: int, tolerance: int = 1) -> float:
    delta = abs(int(value) - int(target))
    if delta <= tolerance:
        return 1.0
    if delta <= tolerance + 2:
        return 0.55
    return 0.0


def _cluster_spaces(values: list[int]) -> tuple[float, float] | None:
    """Return robust short/long space centres for pulse-distance protocols."""
    xs = sorted(int(abs(x)) for x in values if int(abs(x)) > 0)
    if len(xs) < 6:
        return None

    # Remove one obvious trailing idle gap if the receiver included it in-body.
    if len(xs) >= 3 and xs[-1] > max(5000, xs[-2] * 2.5):
        xs = xs[:-1]
    if len(xs) < 6:
        return None

    lo = float(xs[len(xs) // 4])
    hi = float(xs[(3 * len(xs)) // 4])
    if hi <= lo * 1.35:
        return None

    for _ in range(8):
        a = [x for x in xs if abs(x - lo) <= abs(x - hi)]
        b = [x for x in xs if abs(x - lo) > abs(x - hi)]
        if not a or not b:
            return None
        nlo = float(median(a))
        nhi = float(median(b))
        if abs(nlo - lo) < 1 and abs(nhi - hi) < 1:
            break
        lo, hi = nlo, nhi
    if hi < lo:
        lo, hi = hi, lo
    if hi <= lo * 1.6:
        return None
    return lo, hi


def timing_features(timings: list[Any]) -> dict[str, Any] | None:
    vals: list[int] = []
    for index, raw in enumerate(timings):
        try:
            value = abs(int(raw))
        except (TypeError, ValueError):
            return None
        if value <= 0:
            continue
        vals.append(value if index % 2 == 0 else -value)

    if len(vals) < 12:
        return None

    # A long negative tail is normally receiver idle time, not protocol data.
    if vals[-1] < 0 and abs(vals[-1]) > 2500:
        vals = vals[:-1]
    if len(vals) < 12:
        return None

    header_mark = abs(vals[0])
    header_space = abs(vals[1])
    body_marks = [abs(x) for x in vals[2::2]]
    body_spaces = [abs(x) for x in vals[3::2]]
    if len(body_marks) < 4 or len(body_spaces) < 4:
        return None

    clusters = _cluster_spaces(body_spaces)
    if clusters is None:
        return {
            "header_mark": header_mark,
            "header_space": header_space,
            "bit_count": min(len(body_marks), len(body_spaces)),
            "mark_median": float(median(body_marks)),
            "short_space": None,
            "long_space": None,
            "space_ratio": None,
        }

    short_space, long_space = clusters
    return {
        "header_mark": header_mark,
        "header_space": header_space,
        "bit_count": min(len(body_marks), len(body_spaces)),
        "mark_median": float(median(body_marks)),
        "short_space": short_space,
        "long_space": long_space,
        "space_ratio": long_space / short_space if short_space else None,
    }


_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "id": "lg",
        "protocol": "LG/LG2",
        "brand": "LG",
        "bits": 28,
        "header_mark": 8500,
        "header_space": 4250,
        "mark": 560,
        "short": 560,
        "long": 1690,
    },
    {
        "id": "nec",
        "protocol": "NEC/NECext",
        "brand": None,
        "bits": 32,
        "header_mark": 9000,
        "header_space": 4500,
        "mark": 560,
        "short": 560,
        "long": 1690,
    },
    {
        "id": "samsung32",
        "protocol": "Samsung32",
        "brand": "Samsung",
        "bits": 32,
        "header_mark": 4500,
        "header_space": 4500,
        "mark": 560,
        "short": 560,
        "long": 1690,
    },
    {
        "id": "jvc",
        "protocol": "JVC",
        "brand": "JVC",
        "bits": 16,
        "header_mark": 8400,
        "header_space": 4200,
        "mark": 525,
        "short": 525,
        "long": 1575,
    },
    {
        "id": "panasonic48",
        "protocol": "Panasonic/Kaseikyo",
        "brand": "Panasonic",
        "bits": 48,
        "header_mark": 3500,
        "header_space": 1750,
        "mark": 430,
        "short": 430,
        "long": 1290,
    },
)


def _family_score(features: dict[str, Any], family: dict[str, Any]) -> float:
    short = features.get("short_space")
    long = features.get("long_space")
    ratio = features.get("space_ratio")
    if short is None or long is None or ratio is None or ratio < 1.65:
        return 0.0

    score = (
        0.23 * _close(features["header_mark"], family["header_mark"], 0.28)
        + 0.19 * _close(features["header_space"], family["header_space"], 0.32)
        + 0.20 * _count_close(features["bit_count"], family["bits"], 1)
        + 0.12 * _close(features["mark_median"], family["mark"], 0.45)
        + 0.11 * _close(short, family["short"], 0.55)
        + 0.11 * _close(long, family["long"], 0.45)
        + 0.04 * min(1.0, max(0.0, (ratio - 1.65) / 1.2))
    )
    return max(0.0, min(1.0, score))


def classify_capture(timings: list[Any]) -> list[dict[str, Any]]:
    features = timing_features(timings)
    if not features:
        return []
    rows = []
    for family in _FAMILIES:
        score = _family_score(features, family)
        if score < 0.68:
            continue
        rows.append({"family": family, "score": score, "features": features})
    rows.sort(key=lambda row: row["score"], reverse=True)
    # A timing frame should contribute only its strongest family evidence.
    return rows[:1]


def raw_protocol_candidates(captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate common-family timing evidence across multiple captures.

    These rows are *hints*, not safe device recommendations.  Fusion still
    requires a Core-safe decode or a strong raw-profile match before it can
    recommend/install a concrete device profile automatically.
    """
    grouped: dict[str, dict[str, Any]] = {}
    total = len(captures)
    for capture in captures:
        matches = classify_capture(list(capture.get("timings") or []))
        if not matches:
            continue
        match = matches[0]
        family = match["family"]
        gid = str(family["id"])
        row = grouped.setdefault(
            gid,
            {"family": family, "scores": [], "features": []},
        )
        row["scores"].append(float(match["score"]))
        row["features"].append(dict(match["features"]))

    out: list[dict[str, Any]] = []
    for gid, row in grouped.items():
        matched = len(row["scores"])
        if matched < 2:
            continue
        family = row["family"]
        avg = sum(row["scores"]) / matched
        consistency = matched / total if total else 0.0
        bit_counts = [int(x.get("bit_count") or 0) for x in row["features"]]
        stable_bits = len(set(bit_counts)) <= 1
        confidence = round(68 * avg + 24 * consistency + (8 if stable_bits else 0))
        diagnostics = row["features"][0]
        out.append(
            {
                "candidate": {
                    "id": f"heuristic:{gid}",
                    "brand": family.get("brand"),
                    "model": f"{family['protocol']} family",
                    "kind": "custom",
                    "source": "raw_timing_heuristic",
                    "protocol": family["protocol"],
                    "variant": family["protocol"],
                    "recognition_only": True,
                },
                "group_id": f"protocol:{gid}",
                "confidence": max(0, min(96, confidence)),
                "matched_captures": matched,
                "capture_count": total,
                "semantic_ratio": 1.0,
                "distinct_matches": matched,
                "evidence_sources": ["raw_timing_heuristic"],
                "evidence": "raw_timing_family",
                "timing_diagnostics": {
                    "header_mark": diagnostics.get("header_mark"),
                    "header_space": diagnostics.get("header_space"),
                    "bit_count": diagnostics.get("bit_count"),
                    "mark_median": round(float(diagnostics.get("mark_median") or 0), 1),
                    "short_space": round(float(diagnostics.get("short_space") or 0), 1),
                    "long_space": round(float(diagnostics.get("long_space") or 0), 1),
                },
                "_core_recommended": False,
            }
        )
    out.sort(key=lambda x: (-int(x.get("confidence") or 0), -int(x.get("matched_captures") or 0)))
    return out
