"""Thin local RPC client for the compiled HanJoo IR Core add-on.

The protocol catalog, encoders and decoders intentionally live in the compiled
Core process. This module contains only transport/validation glue and therefore
can safely remain visible inside a Home Assistant custom integration.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CORE_API_VERSION, CORE_BASE_URLS, CORE_REQUEST_TIMEOUT



def _codec_timings(values: list[int]) -> list[int]:
    """Convert Home Assistant signed mark/space timings to codec durations."""
    out: list[int] = []
    for value in values:
        try:
            usec = abs(int(value))
        except (TypeError, ValueError):
            continue
        if usec <= 0:
            continue
        out.append(usec)
    return out


class HanJooCoreError(HomeAssistantError):
    """HanJoo Core is unavailable or returned an invalid response."""


class HanJooCoreClient:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._base_urls = tuple(url.rstrip("/") for url in CORE_BASE_URLS)
        self.base_url = self._base_urls[0]

    async def _json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Call Core using the public-repository DNS name with local fallback."""
        session = async_get_clientsession(self.hass)
        last_err: Exception | None = None
        urls = [self.base_url, *[url for url in self._base_urls if url != self.base_url]]

        for base_url in urls:
            url = f"{base_url}{path}"
            try:
                async with asyncio.timeout(timeout or CORE_REQUEST_TIMEOUT):
                    async with session.request(method, url, json=payload) as response:
                        data = await response.json(content_type=None)
                        if response.status >= 400:
                            message = data.get("error") if isinstance(data, dict) else str(data)
                            raise HanJooCoreError(
                                f"HanJoo IR Core error {response.status}: {message}"
                            )
                        self.base_url = base_url
                        return data
            except HanJooCoreError:
                raise
            except (TimeoutError, OSError, ValueError) as err:
                last_err = err
                continue

        raise HanJooCoreError(
            "Cannot connect to HanJoo IR Core add-on. "
            "Check that the add-on is installed, running, and healthy."
        ) from last_err

    async def health(self) -> dict[str, Any]:
        data = await self._json("GET", "/health")
        if not isinstance(data, dict) or not data.get("ok"):
            raise HanJooCoreError("HanJoo IR Core returned an invalid health response")
        if int(data.get("api") or 0) != CORE_API_VERSION:
            raise HanJooCoreError(
                f"Incompatible Core API: expected {CORE_API_VERSION}, got {data.get('api')}"
            )
        return data

    async def _json_probe(self, timings: list[int]) -> dict[str, Any]:
        """Probe every protocol registered by the public codec sidecar."""
        session = async_get_clientsession(self.hass)
        host = self.base_url.split("://", 1)[-1].split(":", 1)[0]
        url = f"http://{host}:8101/v1/probe"
        try:
            async with asyncio.timeout(8.0):
                async with session.post(url, json={"timings": _codec_timings(timings)}) as response:
                    data = await response.json(content_type=None)
                    if response.status >= 400:
                        raise HanJooCoreError(
                            f"HanJoo codec probe error {response.status}: "
                            f"{data.get('error') if isinstance(data, dict) else data}"
                        )
                    if not isinstance(data, dict):
                        raise HanJooCoreError("HanJoo codec probe returned an invalid response")
                    return data
        except HanJooCoreError:
            raise
        except (TimeoutError, OSError, ValueError) as err:
            raise HanJooCoreError("HanJoo codec probe is unavailable") from err

    async def probe(self, timings: list[int]) -> dict[str, Any]:
        return await self._json_probe(timings)

    async def probe_all(self, timings: list[int]) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        host = self.base_url.split("://", 1)[-1].split(":", 1)[0]
        try:
            async with asyncio.timeout(10.0):
                async with session.post(
                    f"http://{host}:8101/v1/probe-all",
                    json={"timings": _codec_timings(timings)},
                ) as response:
                    data = await response.json(content_type=None)
                    if response.status >= 400:
                        raise HanJooCoreError(f"HanJoo codec probe error {response.status}: {data}")
                    if not isinstance(data, dict):
                        raise HanJooCoreError("HanJoo codec probe returned an invalid response")
                    return data
        except HanJooCoreError:
            raise
        except (TimeoutError, OSError, ValueError) as err:
            raise HanJooCoreError("HanJoo codec probe is unavailable") from err

    async def probe_health(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        host = self.base_url.split("://", 1)[-1].split(":", 1)[0]
        try:
            async with asyncio.timeout(4.0):
                async with session.get(f"http://{host}:8101/health") as response:
                    data = await response.json(content_type=None)
                    return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def source_descriptor(self, enabled: bool = True) -> dict[str, Any]:
        last_error: str | None = None
        try:
            health = await self.health()
            data = await self._json("GET", f"/v1/source?enabled={'1' if enabled else '0'}")
            if isinstance(data, dict):
                data["core_available"] = True
                data["core_health"] = "healthy"
                data["core_version"] = health.get("version")
                data["core_package_version"] = "0.5.2"
                probe_health = await self.probe_health()
                data["recognition_protocol_count"] = int(
                    probe_health.get("recognition_coverage") or 0
                )
                data["irtxrx_protocol_count"] = int(
                    probe_health.get("irtxrx_protocols") or 0
                )
                data["irremoteesp8266_protocol_count"] = int(
                    probe_health.get("irremoteesp8266_protocols") or 0
                )
                data["note_vi"] = (
                    "Core đang hoạt động và có thể tạo/giải mã các protocol IR được hỗ trợ."
                )
                data["note_en"] = (
                    "Core is healthy and can generate/decode supported IR protocols."
                )
                return data
        except HanJooCoreError as err:
            last_error = str(err)

        return {
            "id": "protocol_engine",
            "name": "HanJoo Protocol Engine (Core)",
            "enabled": bool(enabled),
            "can_toggle": True,
            "local": True,
            "protected_core": True,
            "core_available": False,
            "core_health": "unhealthy_or_unreachable",
            "catalog_count": 0,
            "protocol_count": 0,
            "brand_count": 0,
            "kinds": ["air_conditioner"],
            "note_vi": (
                "Add-on có thể đang chạy nhưng dịch vụ Core chưa sẵn sàng hoặc Home Assistant chưa kết nối được."
            ),
            "note_en": (
                "The add-on may be running, but the Core service is not ready or Home Assistant cannot reach it."
            ),
            "last_error": last_error,
        }

    async def search(
        self, query: str = "", kind: str | None = None, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        q = quote(str(query), safe="")
        k = quote(str(kind or ""), safe="")
        data = await self._json(
            "GET",
            f"/v1/search?query={q}&kind={k}&limit={max(1, min(int(limit), 250))}",
        )
        if not isinstance(data, list):
            raise HanJooCoreError("Core returned an invalid catalog")
        return [dict(item) for item in data if isinstance(item, dict)]

    async def profile(self, candidate_id: str) -> dict[str, Any]:
        data = await self._json(
            "GET", f"/v1/profile?id={quote(candidate_id, safe='')}"
        )
        if not isinstance(data, dict):
            raise HanJooCoreError("Core returned an invalid profile")
        return data

    async def generate(
        self,
        protocol: dict[str, Any],
        *,
        mode: str | None,
        temp: float | None,
        fan: str | None,
    ) -> dict[str, Any]:
        data = await self._json(
            "POST",
            "/v1/generate",
            payload={"protocol": protocol, "mode": mode, "temp": temp, "fan": fan},
        )
        if not isinstance(data, dict) or not data.get("codes"):
            raise HanJooCoreError("Core could not generate an IR code")
        return data

    async def identify(self, captures: list[dict[str, Any]]) -> dict[str, Any]:
        """Identify an A/C protocol from multiple guided physical-remote captures."""
        normalized: list[dict[str, Any]] = []
        for capture in captures:
            item = dict(capture)
            item["timings"] = _codec_timings(list(capture.get("timings") or []))
            normalized.append(item)
        data = await self._json(
            "POST",
            "/v1/identify",
            payload={"captures": normalized},
            timeout=15.0,
        )
        if not isinstance(data, dict) or not isinstance(data.get("candidates", []), list):
            raise HanJooCoreError("Core returned an invalid identification result")
        return data

    async def decode(
        self, protocol: dict[str, Any], timings: list[int]
    ) -> dict[str, Any] | None:
        data = await self._json(
            "POST",
            "/v1/decode",
            payload={"protocol": protocol, "timings": _codec_timings(timings)},
        )
        if data is None:
            return None
        if not isinstance(data, dict):
            raise HanJooCoreError("Core returned an invalid decode result")
        return data
