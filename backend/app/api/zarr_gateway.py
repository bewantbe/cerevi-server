"""OME-Zarr v0.5 gateway routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..config import settings
from ..services.gateway import (
    build_group_zarr_json,
    resolve_upstream_for_level,
)
from ..services.proxy import proxy_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ome-zarr")


def _registry(request: Request):
    return request.app.state.registry


def _cache(request: Request):
    return request.app.state.zarr_meta_cache


def _check_dc():
    if not settings.dc_helper_url:
        raise HTTPException(status_code=503, detail="DC_HELPER_URL not configured")


@router.api_route(
    "/{specimen_id}/{kind}/{variant}/{mode}/zarr.json", methods=["GET", "HEAD"]
)
async def group_zarr_json(
    request: Request,
    specimen_id: str,
    kind: str,
    variant: str,
    mode: str,
) -> Response:
    _check_dc()
    body = await build_group_zarr_json(
        request,
        _registry(request),
        _cache(request),
        settings.dc_helper_url,
        specimen_id,
        kind,
        variant,
        mode,
    )
    if request.method == "HEAD":
        import json as _json

        encoded = _json.dumps(body).encode()
        return Response(
            content=b"",
            media_type="application/json",
            headers={"content-length": str(len(encoded)), "accept-ranges": "none"},
        )
    return JSONResponse(body, headers={"accept-ranges": "none"})


@router.api_route(
    "/{specimen_id}/{kind}/{variant}/{mode}/{level}/zarr.json",
    methods=["GET", "HEAD"],
)
async def array_zarr_json(
    request: Request,
    specimen_id: str,
    kind: str,
    variant: str,
    mode: str,
    level: int,
) -> Response:
    _check_dc()
    upstream = resolve_upstream_for_level(
        _registry(request),
        settings.dc_helper_url,
        specimen_id,
        kind,
        variant,
        mode,
        level,
        "zarr.json",
    )
    return await proxy_stream(request, upstream)


@router.api_route(
    "/{specimen_id}/{kind}/{variant}/{mode}/{level}/c/{coords:path}",
    methods=["GET", "HEAD"],
)
async def chunk(
    request: Request,
    specimen_id: str,
    kind: str,
    variant: str,
    mode: str,
    level: int,
    coords: str,
) -> Response:
    _check_dc()
    if ".." in coords:
        raise HTTPException(status_code=400, detail="Invalid chunk path")
    upstream = resolve_upstream_for_level(
        _registry(request),
        settings.dc_helper_url,
        specimen_id,
        kind,
        variant,
        mode,
        level,
        "c",
        coords,
    )
    return await proxy_stream(request, upstream)
