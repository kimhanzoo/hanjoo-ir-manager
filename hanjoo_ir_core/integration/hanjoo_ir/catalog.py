"""Catalog parsers for built-in online IR library sources.

This module is pure Python on purpose: catalog parsing can be regression-tested
without booting Home Assistant or making network requests.
"""
from __future__ import annotations

import html
import re
from typing import Any

_SMARTIR_LINK_RE = re.compile(
    r"\[(?P<label>\d+)\]\(\.\./codes/(?P<kind>climate|fan|media_player)/(?P<code>\d+)\.json\)",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _clean_md_cell(value: str) -> str:
    value = _BR_RE.sub(" / ", value)
    value = re.sub(r"\*\*|__|`", "", value)
    value = _TAG_RE.sub("", value)
    value = html.unescape(value)
    return " ".join(value.split()).strip(" |")


def _split_models(raw: str) -> list[str]:
    # SmartIR documentation uses <br> heavily and sometimes commas/slashes
    # inside a model designation. Split only on explicit line breaks so model
    # names are not accidentally damaged.
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    out: list[str] = []
    for part in raw.splitlines():
        item = _clean_md_cell(part)
        if item and item not in out:
            out.append(item)
    return out or ["Unknown model"]


def parse_smartir_catalog(text: str, expected_kind: str) -> list[dict[str, Any]]:
    """Parse SmartIR's human-maintained Markdown device table.

    The docs are intentionally accepted loosely: some rows have leading pipes,
    some do not, and a handful contain extra Notes columns. The link itself is
    the source of truth for kind/profile code; headings provide the brand.
    Duplicate links are merged so documentation aliases become one candidate.
    """
    if expected_kind not in {"climate", "fan", "media_player"}:
        raise ValueError(f"Unsupported SmartIR kind: {expected_kind}")

    brand = ""
    by_id: dict[str, dict[str, Any]] = {}

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#### "):
            brand = _clean_md_cell(stripped[5:])
            continue

        match = _SMARTIR_LINK_RE.search(stripped)
        if not match or match.group("kind").lower() != expected_kind:
            continue

        code = match.group("code")
        catalog_id = f"smartir:{expected_kind}:{code}"

        # The cell immediately after the code link is Supported Models.
        after = stripped[match.end():].lstrip()
        if after.startswith("|"):
            after = after[1:]
        model_cell = after.split("|", 1)[0].strip()
        models = _split_models(model_cell)

        # Controller is normally the last useful cell, even when a Notes
        # column exists. Ignore table decorations and empty trailing cells.
        cells = [_clean_md_cell(x) for x in stripped.strip("|").split("|")]
        cells = [x for x in cells if x]
        controller = cells[-1] if len(cells) >= 3 else ""

        row = by_id.setdefault(
            catalog_id,
            {
                "id": catalog_id,
                "source": "smartir",
                "kind": expected_kind,
                "code": code,
                "brand": brand or "Unknown",
                "models": [],
                "controller": controller,
            },
        )
        if row["brand"] == "Unknown" and brand:
            row["brand"] = brand
        if controller and not row.get("controller"):
            row["controller"] = controller
        for model in models:
            if model not in row["models"]:
                row["models"].append(model)

    rows = list(by_id.values())
    for row in rows:
        row["model"] = " / ".join(row["models"])
        row["name"] = f"{row['brand']} · {row['model']}"
        row["search"] = (
            f"{row['brand']} {row['model']} {row['kind']} {row['code']} "
            f"{row.get('controller', '')}"
        ).lower()
    rows.sort(key=lambda item: (str(item["brand"]).lower(), str(item["model"]).lower()))
    return rows
