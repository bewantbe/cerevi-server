"""HTTP proxy + JSON cache helpers for talking to cerevi-dc-helper.

The helper serves whole zarr chunks as plain 200 responses (no Range, no
ETag). The proxy here is correspondingly simple: GET-only, full-body
stream-through.
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

_FWD_RES_HEADERS = ("content-type", "content-length")

# We don't honor Range. Tell zarrita-style clients explicitly so they don't
# probe with Range/suffix requests on the sharding-codec path.
_NO_RANGE_HEADERS = {"accept-ranges": "none"}


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def proxy_stream(request: Request, upstream_url: str) -> StreamingResponse:
    """GET `upstream_url` and stream the body back to the client.

    The original request method may be HEAD; in that case we still issue a
    GET upstream (helper supports HEAD too, but this keeps the proxy path
    uniform) and drop the body via Starlette's HEAD handling.
    """
    client = _client(request)
    method = "HEAD" if request.method == "HEAD" else "GET"
    upstream_req = client.build_request(method, upstream_url)
    try:
        upstream_resp = await client.send(upstream_req, stream=True)
    except httpx.RequestError as exc:
        logger.warning("Upstream error %s: %s", upstream_url, exc)
        raise HTTPException(status_code=502, detail="Upstream unreachable") from exc

    res_headers = {
        h: upstream_resp.headers[h]
        for h in _FWD_RES_HEADERS
        if h in upstream_resp.headers
    }
    res_headers.update(_NO_RANGE_HEADERS)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()

    return StreamingResponse(
        body(),
        status_code=upstream_resp.status_code,
        headers=res_headers,
    )


# --- TTL JSON cache for upstream zarr.json ---------------------------------

class JsonCache:
    """Tiny in-memory TTL cache for upstream JSON documents."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    async def get(self, client: httpx.AsyncClient, url: str) -> Any:
        now = time.monotonic()
        hit = self._store.get(url)
        if hit is not None and (now - hit[0]) < self._ttl:
            return hit[1]
        try:
            r = await client.get(url)
        except httpx.RequestError as exc:
            logger.warning("Upstream JSON fetch failed %s: %s", url, exc)
            raise HTTPException(status_code=502, detail="Upstream unreachable") from exc
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Upstream not found: {url}")
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Upstream {r.status_code}")
        data = r.json()
        self._store[url] = (now, data)
        return data

    def clear(self) -> None:
        self._store.clear()
