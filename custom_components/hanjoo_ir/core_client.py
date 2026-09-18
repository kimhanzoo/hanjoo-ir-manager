"""Thin local RPC client for the compiled HanJoo IR Core add-on.

The protocol catalog, encoders and decoders intentionally live in the compiled
Core process. This module contains only transport/validation glue and therefore
can safely remain visible inside a Home Assistant custom integration.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CORE_API_VERSION, CORE_BASE_URL, CORE_REQUEST_TIMEOUT




def _probe_timings(values: list[int]) -> list[int]:
    """Preserve signed mark/space timings for the recognition sidecar.

    Positive values are marks and negative values are spaces. Keeping polarity
    lets the sidecar reject a leading idle-space and preserve the native decoder
    phase instead of inferring mark/space solely from array index parity.
    """
    out: list[int] = []
    for value in values:
        try:
            usec = int(value)
        except (TypeError, ValueError):
            continue
        if usec == 0:
            continue
        out.append(usec)
    return out


def _codec_timings(values: list[int]) -> list[int]:
    """Convert Home Assistant signed mark/space timings to codec durations.

    HA/infrared-protocols represents marks as positive values and spaces as
    negative values. irtxrx decoders expect an alternating list of positive
    microsecond durations. Keeping the sign caused every real receiver capture
    to miss even though generated/ideal test vectors decoded correctly.
    """
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
        self.base_url = CORE_BASE_URL.rstrip("/")
        self._resolved_base_url: str | None = None

    async def _supervisor_core_base_url(self) -> str | None:
        """Resolve the add-on hostname from Supervisor instead of assuming local-* DNS.

        Repository-installed add-ons receive a Supervisor-generated slug/hostname
        (for example ``<repo>_hanjoo_ir_core``), while a local add-on normally uses
        ``local_hanjoo_ir_core``.  Hard-coding one form makes the other form
        unreachable even though the container itself is healthy.
        """
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            return None
        session = async_get_clientsession(self.hass)
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with asyncio.timeout(3.0):
                async with session.get("http://supervisor/addons", headers=headers) as response:
                    payload = await response.json(content_type=None)
                    if response.status >= 400 or not isinstance(payload, dict):
                        return None
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            addons = data.get("addons") if isinstance(data, dict) else None
            if not isinstance(addons, list):
                return None

            addon_slug = None
            for addon in addons:
                if not isinstance(addon, dict):
                    continue
                slug = str(addon.get("slug") or addon.get("addon") or "").strip()
                name = str(addon.get("name") or "").strip().lower()
                normalized = slug.lower().replace("-", "_")
                if normalized.endswith("hanjoo_ir_core") or name == "hanjoo ir core":
                    addon_slug = slug
                    break
            if not addon_slug:
                return None

            hostname = addon_slug
            try:
                async with asyncio.timeout(3.0):
                    async with session.get(
                        f"http://supervisor/addons/{quote(addon_slug, safe='')}/info",
                        headers=headers,
                    ) as response:
                        info_payload = await response.json(content_type=None)
                        if response.status < 400 and isinstance(info_payload, dict):
                            info = info_payload.get("data")
                            if isinstance(info, dict):
                                hostname = str(info.get("hostname") or hostname).strip() or hostname
            except (TimeoutError, OSError, ValueError):
                # The add-on slug itself is a valid internal DNS name on Supervisor
                # installations, so info lookup failure is not fatal.
                pass
            return f"http://{hostname}:8099"
        except (TimeoutError, OSError, ValueError):
            return None

    async def _candidate_base_urls(self) -> list[str]:
        urls: list[str] = []
        if self._resolved_base_url:
            urls.append(self._resolved_base_url.rstrip("/"))
        supervisor_url = await self._supervisor_core_base_url()
        if supervisor_url:
            urls.append(supervisor_url.rstrip("/"))
        # Compatibility fallbacks for local/manual installs and older packages.
        urls.extend([
            self.base_url.rstrip("/"),
            "http://local_hanjoo_ir_core:8099",
            "http://local-hanjoo-ir-core:8099",
            "http://hanjoo_ir_core:8099",
            "http://hanjoo-ir-core:8099",
        ])
        return list(dict.fromkeys(urls))

    async def _json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        session = async_get_clientsession(self.hass)
        last_error: Exception | None = None
        for base_url in await self._candidate_base_urls():
            url = f"{base_url}{path}"
            try:
                async with asyncio.timeout(timeout or CORE_REQUEST_TIMEOUT):
                    async with session.request(method, url, json=payload) as response:
                        data = await response.json(content_type=None)
                        if response.status >= 400:
                            message = data.get("error") if isinstance(data, dict) else str(data)
                            raise HanJooCoreError(f"HanJoo IR Core error {response.status}: {message}")
                        self._resolved_base_url = base_url
                        return data
            except HanJooCoreError:
                raise
            except (TimeoutError, OSError, ValueError) as err:
                last_error = err
                continue
        raise HanJooCoreError(
            "Cannot connect to HanJoo IR Core add-on. "
            "Supervisor could not resolve/reach the Core service on port 8099. "
            f"Last transport error: {last_error}"
        ) from last_error

    async def _active_host(self) -> str:
        if not self._resolved_base_url:
            # /health also validates the API and caches the working base URL.
            await self.health()
        base = (self._resolved_base_url or self.base_url).split("://", 1)[-1]
        return base.split(":", 1)[0]

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
        # Same add-on hostname, dedicated internal sidecar port.
        host = await self._active_host()
        url = f"http://{host}:8101/v1/probe"
        try:
            async with asyncio.timeout(8.0):
                async with session.post(url, json={"timings": _probe_timings(timings)}) as response:
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
        host = await self._active_host()
        try:
            async with asyncio.timeout(10.0):
                async with session.post(f"http://{host}:8101/v1/probe-all", json={"timings": _probe_timings(timings)}) as response:
                    data = await response.json(content_type=None)
                    if response.status >= 400: raise HanJooCoreError(f"HanJoo codec probe error {response.status}: {data}")
                    if not isinstance(data, dict): raise HanJooCoreError("HanJoo codec probe returned an invalid response")
                    return data
        except HanJooCoreError:
            raise
        except (TimeoutError, OSError, ValueError) as err:
            raise HanJooCoreError("HanJoo codec probe is unavailable") from err

    async def probe_health(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        host = await self._active_host()
        try:
            async with asyncio.timeout(4.0):
                async with session.get(f"http://{host}:8101/health") as response:
                    data = await response.json(content_type=None)
                    return data if isinstance(data, dict) else {}
        except Exception:
            return {}


    async def brain_health(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        host = await self._active_host()
        try:
            async with asyncio.timeout(4.0):
                async with session.get(f"http://{host}:8102/health") as response:
                    data = await response.json(content_type=None)
                    return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def classify_timings(self, timings: list[int]) -> list[dict[str, Any]]:
        """Ask the protected Core Brain for conservative wire-family hints."""
        session = async_get_clientsession(self.hass)
        host = await self._active_host()
        try:
            async with asyncio.timeout(6.0):
                async with session.post(
                    f"http://{host}:8102/v1/classify",
                    json={"timings": timings},
                ) as response:
                    data = await response.json(content_type=None)
                    if response.status >= 400:
                        raise HanJooCoreError(
                            f"HanJoo Brain classify error {response.status}: "
                            f"{data.get('error') if isinstance(data, dict) else data}"
                        )
                    rows = data.get("matches") if isinstance(data, dict) else None
                    return [dict(row) for row in rows or [] if isinstance(row, dict)]
        except HanJooCoreError:
            raise
        except (TimeoutError, OSError, ValueError) as err:
            raise HanJooCoreError("HanJoo Brain classifier is unavailable") from err

    async def fuse_identification(
        self,
        captures: list[dict[str, Any]],
        *,
        kind_hint: str = "auto",
        candidates: list[dict[str, Any]] | None = None,
        profiles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Delegate protocol-family inference, profile scoring and safety policy to Core Brain."""
        session = async_get_clientsession(self.hass)
        host = await self._active_host()
        payload = {
            "captures": captures[:6],
            "kind_hint": kind_hint,
            "candidates": candidates or [],
            "profiles": profiles or [],
        }
        try:
            async with asyncio.timeout(20.0):
                async with session.post(f"http://{host}:8102/v1/fuse", json=payload) as response:
                    data = await response.json(content_type=None)
                    if response.status >= 400:
                        raise HanJooCoreError(
                            f"HanJoo Brain error {response.status}: "
                            f"{data.get('error') if isinstance(data, dict) else data}"
                        )
                    if not isinstance(data, dict):
                        raise HanJooCoreError("HanJoo Brain returned an invalid response")
                    return data
        except HanJooCoreError:
            raise
        except (TimeoutError, OSError, ValueError) as err:
            raise HanJooCoreError("HanJoo Brain service is unavailable") from err

    async def source_descriptor(self, enabled: bool = True) -> dict[str, Any]:
        last_error: str | None = None
        try:
            # Check health first so "container is Running" is not confused with
            # "protocol service is healthy". A running add-on may still have a
            # broken/missing codec dependency.
            health = await self.health()
            data = await self._json("GET", f"/v1/source?enabled={'1' if enabled else '0'}")
            if isinstance(data, dict):
                data["core_available"] = True
                data["core_health"] = "healthy"
                data["core_version"] = health.get("version")
                # The protected gateway ABI remains 0.3.0 internally; the add-on
                # package version tracks packaging/runtime fixes independently.
                data["core_package_version"] = health.get("package_version") or health.get("version")
                probe_health = await self.probe_health()
                brain_health = await self.brain_health()
                data["recognition_protocol_count"] = int(probe_health.get("recognition_coverage") or 0)
                data["irtxrx_protocol_count"] = int(probe_health.get("irtxrx_protocols") or 0)
                data["irremoteesp8266_protocol_count"] = int(probe_health.get("irremoteesp8266_protocols") or 0)
                data["brain_available"] = bool(brain_health.get("ok"))
                data["brain_version"] = brain_health.get("version")
                data["note_vi"] = (
                    "Core và Brain đang hoạt động; nhận diện, chấm điểm và chính sách khuyến nghị chạy trong add-on."
                    if brain_health.get("ok") else
                    "Core đang chạy nhưng Brain nhận diện chưa sẵn sàng."
                )
                data["note_en"] = (
                    "Core and Brain are healthy; recognition, scoring and recommendation policy run in the add-on."
                    if brain_health.get("ok") else
                    "Core is running but the recognition Brain is not ready."
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

    async def search(self, query: str = "", kind: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        q = quote(str(query), safe="")
        k = quote(str(kind or ""), safe="")
        data = await self._json("GET", f"/v1/search?query={q}&kind={k}&limit={max(1, min(int(limit), 250))}")
        if not isinstance(data, list):
            raise HanJooCoreError("Core returned an invalid catalog")
        return [dict(item) for item in data if isinstance(item, dict)]

    async def profile(self, candidate_id: str) -> dict[str, Any]:
        data = await self._json("GET", f"/v1/profile?id={quote(candidate_id, safe='')}")
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

    async def decode(self, protocol: dict[str, Any], timings: list[int]) -> dict[str, Any] | None:
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
