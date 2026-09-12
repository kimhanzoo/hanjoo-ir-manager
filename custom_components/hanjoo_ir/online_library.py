"""Built-in online IR library providers for HanJoo IR."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .catalog import parse_smartir_catalog
from .const import MAX_IMPORT_BYTES
from .flipper_irdb import (
    FLIPPER_LICENSE,
    FLIPPER_REF,
    FLIPPER_REPO,
    parse_flipper_profile,
    parse_github_tree,
)
from .importers import ImportResult, import_profile_text
from .manager import HanJooIRManager

_LOGGER = logging.getLogger(__name__)

SMARTIR_REPO = "smartHomeHub/SmartIR"
SMARTIR_REF = "master"
SMARTIR_LICENSE = "MIT"
SMARTIR_DOCS = {
    "climate": "CLIMATE.md",
    "fan": "FAN.md",
    "media_player": "MEDIA_PLAYER.md",
}
SMARTIR_RAW_BASE = (
    "https://raw.githubusercontent.com/"
    f"{SMARTIR_REPO}/{SMARTIR_REF}"
)

FLIPPER_TREE_URL = (
    "https://api.github.com/repos/"
    f"{FLIPPER_REPO}/git/trees/{FLIPPER_REF}?recursive=1"
)
FLIPPER_RAW_BASE = (
    "https://raw.githubusercontent.com/"
    f"{FLIPPER_REPO}/{FLIPPER_REF}"
)

CATALOG_TTL_SECONDS = 6 * 60 * 60
_REQUEST_TIMEOUT = ClientTimeout(total=25)
_SMARTIR_ID_RE = re.compile(r"^smartir:(climate|fan|media_player):(\d+)$")


class OnlineLibraryError(ValueError):
    """Network/provider/catalog error safe to show in the admin panel."""


class OnlineLibrary:
    """Aggregate enabled public IR sources behind one searchable catalog."""

    def __init__(self, hass: HomeAssistant, manager: HanJooIRManager) -> None:
        self.hass = hass
        self.manager = manager
        self._catalogs: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._profile_cache: dict[str, tuple[float, ImportResult]] = {}
        self._locks: dict[str, asyncio.Lock] = {
            "smartir": asyncio.Lock(),
            "flipper_irdb": asyncio.Lock(),
        }
        self._source_errors: dict[str, str] = {}

    def sources(self) -> list[dict[str, Any]]:
        """Return only sources that are genuinely implemented."""
        enabled = self.manager.get_online_source_settings()
        descriptors = [
            {
                "id": "smartir",
                "name": "SmartIR Community Codes",
                "enabled": enabled.get("smartir", True),
                "can_toggle": True,
                "license": SMARTIR_LICENSE,
                "repository": SMARTIR_REPO,
                "kinds": ["air_conditioner", "fan", "tv"],
                "mode": "online_on_demand",
                "note_vi": (
                    "Điều hòa, TV/media và quạt. Profile được tải theo nhu cầu; "
                    "HanJoo chuẩn hóa Broadlink, Xiaomi Raw, ESPHome và SmartIR."
                ),
                "note_en": (
                    "Air conditioners, TV/media devices, and fans. Profiles are fetched on demand; "
                    "HanJoo normalizes Broadlink, Xiaomi Raw, ESPHome, and SmartIR formats."
                ),
            },
            {
                "id": "flipper_irdb",
                "name": "Flipper-IRDB Community",
                "enabled": enabled.get("flipper_irdb", False),
                "can_toggle": True,
                "license": FLIPPER_LICENSE,
                "repository": FLIPPER_REPO,
                "kinds": [
                    "tv", "projector", "soundbar", "receiver", "fan",
                    "air_conditioner", "light", "camera", "console",
                    "air_purifier", "custom",
                ],
                "mode": "online_on_demand",
                "note_vi": (
                    "CSDL CC0 rất lớn theo loại → hãng → model. Hỗ trợ trực tiếp "
                    "RAW và các parsed protocol phổ biến: NEC/NECext, Samsung32, "
                    "Sony SIRC và RC5/RC5X."
                ),
                "note_en": (
                    "Large CC0 database organized by type → brand → model. Direct support for "
                    "RAW and common parsed protocols: NEC/NECext, Samsung32, Sony SIRC, and RC5/RC5X."
                ),
            },
        ]

        for row in descriptors:
            cache = self._catalogs.get(row["id"])
            row["catalog_count"] = len(cache[1]) if cache else None
            row["last_error"] = self._source_errors.get(row["id"])
        return descriptors

    async def async_set_source_enabled(
        self, source_id: str, enabled: bool
    ) -> dict[str, Any]:
        if source_id not in {"smartir", "flipper_irdb"}:
            raise OnlineLibraryError("Nguồn này chưa có provider thật trong HanJoo")
        await self.manager.set_online_source_enabled(source_id, enabled)
        if enabled:
            # Verify immediately so the UI reports a real working/error state.
            try:
                rows = await self._async_source_catalog(source_id, force=True)
                self._source_errors.pop(source_id, None)
                count = len(rows)
            except Exception as err:
                self._source_errors[source_id] = str(err)
                count = 0
                raise
        else:
            count = len(self._catalogs.get(source_id, (0, []))[1])
        return {
            "source_id": source_id,
            "enabled": enabled,
            "catalog_count": count,
        }

    async def async_refresh_source(self, source_id: str) -> dict[str, Any]:
        if source_id not in {"smartir", "flipper_irdb"}:
            raise OnlineLibraryError("Nguồn không hợp lệ")
        try:
            rows = await self._async_source_catalog(source_id, force=True)
        except Exception as err:
            self._source_errors[source_id] = str(err)
            raise
        self._source_errors.pop(source_id, None)
        return {"source_id": source_id, "catalog_count": len(rows)}

    async def async_catalog(self, *, force: bool = False) -> list[dict[str, Any]]:
        settings = self.manager.get_online_source_settings()
        enabled_ids = [
            source_id
            for source_id in ("smartir", "flipper_irdb")
            if settings.get(source_id, False)
        ]
        if not enabled_ids:
            return []

        results = await asyncio.gather(
            *(
                self._async_source_catalog(source_id, force=force)
                for source_id in enabled_ids
            ),
            return_exceptions=True,
        )
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for source_id, result in zip(enabled_ids, results):
            if isinstance(result, Exception):
                self._source_errors[source_id] = str(result)
                errors.append(f"{source_id}: {result}")
                continue
            self._source_errors.pop(source_id, None)
            rows.extend(result)

        if not rows and errors:
            raise OnlineLibraryError(
                "Không tải được nguồn thư viện đang bật: " + "; ".join(errors)
            )
        return rows

    async def _async_source_catalog(
        self, source_id: str, *, force: bool = False
    ) -> list[dict[str, Any]]:
        now = time.monotonic()
        cached = self._catalogs.get(source_id)
        if (
            not force
            and cached is not None
            and now - cached[0] < CATALOG_TTL_SECONDS
        ):
            return list(cached[1])

        lock = self._locks[source_id]
        async with lock:
            now = time.monotonic()
            cached = self._catalogs.get(source_id)
            if (
                not force
                and cached is not None
                and now - cached[0] < CATALOG_TTL_SECONDS
            ):
                return list(cached[1])

            if source_id == "smartir":
                rows = await self._load_smartir_catalog()
            elif source_id == "flipper_irdb":
                rows = await self._load_flipper_catalog()
            else:
                raise OnlineLibraryError("Nguồn không hỗ trợ")

            self._catalogs[source_id] = (time.monotonic(), rows)
            return list(rows)

    async def _load_smartir_catalog(self) -> list[dict[str, Any]]:
        results = await asyncio.gather(
            *(
                self._async_fetch_smartir_doc(kind, filename)
                for kind, filename in SMARTIR_DOCS.items()
            ),
            return_exceptions=True,
        )
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for (kind, _filename), result in zip(SMARTIR_DOCS.items(), results):
            if isinstance(result, Exception):
                errors.append(f"{kind}: {result}")
                continue
            try:
                parsed = parse_smartir_catalog(result, kind)
                for row in parsed:
                    row["source"] = "smartir"
                    row["semantic_type"] = row.get("kind")
                    row["kind"] = {
                        "climate": "air_conditioner",
                        "fan": "fan",
                        "media_player": "tv",
                    }.get(kind, kind)
                    row["semantic_type"] = kind
                rows.extend(parsed)
            except (ValueError, TypeError) as err:
                errors.append(f"{kind}: {err}")

        if not rows:
            raise OnlineLibraryError(
                "Không tải được danh mục SmartIR. "
                + ("; ".join(errors) if errors else "Không có dữ liệu.")
            )
        merged = {row["id"]: row for row in rows}
        return sorted(
            merged.values(),
            key=lambda item: (
                str(item.get("kind")),
                str(item.get("brand", "")).lower(),
                str(item.get("model", "")).lower(),
            ),
        )

    async def _load_flipper_catalog(self) -> list[dict[str, Any]]:
        text = await self._async_get_text(
            FLIPPER_TREE_URL,
            max_bytes=12_000_000,
            accept="application/vnd.github+json",
        )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as err:
            raise OnlineLibraryError("GitHub trả catalog Flipper không hợp lệ") from err
        try:
            rows = parse_github_tree(payload)
        except ValueError as err:
            raise OnlineLibraryError(str(err)) from err
        if not rows:
            raise OnlineLibraryError("Flipper-IRDB không trả về profile .ir nào")
        return rows

    async def async_search(
        self,
        query: str = "",
        kind: str | None = None,
        *,
        limit: int = 100,
        force: bool = False,
    ) -> dict[str, Any]:
        rows = await self.async_catalog(force=force)
        query_l = " ".join(query.lower().split())

        filtered = [
            row
            for row in rows
            if (
                not kind
                or row.get("kind") == kind
                or row.get("semantic_type") == kind
            )
            and (not query_l or query_l in row.get("search", ""))
        ]

        if query_l:
            tokens = [token for token in re.split(r"[^a-z0-9]+", query_l) if token]

            def score(row: dict[str, Any]) -> tuple[int, str, str, str]:
                brand = str(row.get("brand") or "").lower()
                model = str(row.get("model") or "").lower()
                search = str(row.get("search") or "")
                points = 0
                if query_l == model:
                    points += 100
                if query_l == brand:
                    points += 80
                if model.startswith(query_l):
                    points += 50
                if brand.startswith(query_l):
                    points += 40
                points += sum(8 for token in tokens if token in model)
                points += sum(5 for token in tokens if token in brand)
                points += sum(1 for token in tokens if token in search)
                return (
                    -points,
                    str(row.get("source")),
                    brand,
                    model,
                )

            filtered.sort(key=score)
        else:
            filtered.sort(
                key=lambda row: (
                    str(row.get("kind")),
                    str(row.get("brand", "")).lower(),
                    str(row.get("model", "")).lower(),
                )
            )

        limit = max(1, min(int(limit), 250))
        return {
            "items": filtered[:limit],
            "total": len(filtered),
            "catalog_total": len(rows),
            "sources": self.sources(),
            "cached": bool(self._catalogs),
        }

    def cached_profiles(self) -> list[tuple[str, ImportResult]]:
        """Return cached online profiles without causing network I/O."""
        now = time.monotonic()
        out: list[tuple[str, ImportResult]] = []
        for catalog_id, (stamp, result) in list(self._profile_cache.items()):
            if now - stamp < CATALOG_TTL_SECONDS:
                out.append((catalog_id, deepcopy(result)))
        return out

    async def async_fetch_profile(self, catalog_id: str) -> ImportResult:
        now = time.monotonic()
        cached = self._profile_cache.get(catalog_id)
        if cached and now - cached[0] < CATALOG_TTL_SECONDS:
            return deepcopy(cached[1])

        if catalog_id.startswith("smartir:"):
            result = await self._fetch_smartir_profile(catalog_id)
        elif catalog_id.startswith("flipper:"):
            result = await self._fetch_flipper_profile(catalog_id)
        else:
            raise OnlineLibraryError("Online profile ID không hợp lệ")

        self._profile_cache[catalog_id] = (time.monotonic(), deepcopy(result))
        return result

    async def _fetch_smartir_profile(self, catalog_id: str) -> ImportResult:
        match = _SMARTIR_ID_RE.fullmatch(catalog_id)
        if not match:
            raise OnlineLibraryError("SmartIR profile ID không hợp lệ")
        kind, code = match.groups()
        url = f"{SMARTIR_RAW_BASE}/codes/{kind}/{code}.json"
        text = await self._async_get_text(url, max_bytes=MAX_IMPORT_BYTES)
        result = import_profile_text(text, f"smartir-{kind}-{code}.json")
        result.profile["source"] = "smartir_online"
        result.profile["source_ref"] = {
            "provider": "smartir",
            "repository": SMARTIR_REPO,
            "ref": SMARTIR_REF,
            "kind": kind,
            "code": code,
            "license": SMARTIR_LICENSE,
        }
        return result

    async def _fetch_flipper_profile(self, catalog_id: str) -> ImportResult:
        path = catalog_id.removeprefix("flipper:")
        if not path or ".." in path or not path.lower().endswith(".ir"):
            raise OnlineLibraryError("Flipper profile path không hợp lệ")
        rows = await self._async_source_catalog("flipper_irdb")
        row = next((item for item in rows if item.get("id") == catalog_id), None)
        if row is None:
            raise OnlineLibraryError("Profile Flipper không còn trong catalog")
        url = f"{FLIPPER_RAW_BASE}/{quote(path, safe='/')}"
        text = await self._async_get_text(url, max_bytes=MAX_IMPORT_BYTES)
        try:
            return parse_flipper_profile(text, path=path, catalog_row=row)
        except ValueError as err:
            raise OnlineLibraryError(str(err)) from err

    async def _async_fetch_smartir_doc(self, kind: str, filename: str) -> str:
        url = f"{SMARTIR_RAW_BASE}/docs/{filename}"
        return await self._async_get_text(url, max_bytes=2_000_000)

    async def _async_get_text(
        self,
        url: str,
        *,
        max_bytes: int,
        accept: str | None = None,
    ) -> str:
        session = async_get_clientsession(self.hass)
        headers = {
            "User-Agent": "HanJoo-IR-Home-Assistant",
        }
        if accept:
            headers["Accept"] = accept
        try:
            async with session.get(
                url, timeout=_REQUEST_TIMEOUT, headers=headers
            ) as response:
                if response.status != 200:
                    rate = response.headers.get("X-RateLimit-Remaining")
                    suffix = f" · GitHub rate remaining: {rate}" if rate else ""
                    raise OnlineLibraryError(
                        f"Nguồn thư viện trả HTTP {response.status}{suffix}"
                    )
                length = response.content_length
                if length is not None and length > max_bytes:
                    raise OnlineLibraryError("File thư viện online quá lớn")
                raw = await response.read()
        except (ClientError, TimeoutError) as err:
            raise OnlineLibraryError(
                f"Lỗi kết nối thư viện online: {err}"
            ) from err
        if len(raw) > max_bytes:
            raise OnlineLibraryError("File thư viện online quá lớn")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as err:
            raise OnlineLibraryError("Nguồn thư viện không phải UTF-8") from err
