"""OME-Zarr v0.5 gateway: synthesize per-mode multiscale groups from the
composition described by the registry's routing tables.

For `(specimen, kind, variant, mode)`:
- The group `zarr.json` is synthesized: one dataset per global level, scale
  copied from the upstream contributing source's multiscales.
- The array `zarr.json` and chunks are proxied unchanged from the upstream
  file at the resolved internal level.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request

from ..models.registry import (
    ImageVariant,
    Modes,
    RegionMaskVariant,
    Registry,
)
from .proxy import JsonCache
from .registry import get_specimen, get_variant

logger = logging.getLogger(__name__)


_MODE_ATTRS = {"3d": "three_d", "xy": "xy", "xz": "xz", "yz": "yz"}


def _rows_for_mode(modes: Modes, mode: str) -> list[tuple[int, list[int], list[int | str]]]:
    attr = _MODE_ATTRS.get(mode)
    if attr is None:
        raise HTTPException(status_code=404, detail=f"Unknown mode: {mode}")
    rows: list = getattr(modes, attr)
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"No data for mode '{mode}' on this variant"
        )
    return rows


def enumerate_global_levels(rows: list) -> list[int]:
    levels: set[int] = set()
    for _file_idx, level_indices, _ch in rows:
        for gl in level_indices:
            if isinstance(gl, int) and gl >= 0:
                levels.add(gl)
    return sorted(levels)


def resolve_level(rows: list, global_level: int) -> tuple[int, int]:
    """Return (file_idx, internal_level) that serves `global_level`."""
    for file_idx, level_indices, _ch in rows:
        for internal_idx, gl in enumerate(level_indices):
            if gl == global_level:
                return file_idx, internal_idx
    raise HTTPException(
        status_code=404, detail=f"Level {global_level} not in routing table"
    )


def upstream_zarr_url(dc_helper_url: str, file_path: str, *suffix: str) -> str:
    base = dc_helper_url.rstrip("/")
    parts = [base, file_path.strip("/")]
    parts.extend(p.strip("/") for p in suffix if p)
    return "/".join(parts)


def _imageish(variant: object) -> ImageVariant | RegionMaskVariant:
    if not isinstance(variant, (ImageVariant, RegionMaskVariant)):
        raise HTTPException(
            status_code=404,
            detail="Mesh variants do not expose OME-Zarr; use /meshes routes",
        )
    return variant


async def build_group_zarr_json(
    request: Request,
    registry: Registry,
    cache: JsonCache,
    dc_helper_url: str,
    specimen_id: str,
    kind: str,
    variant_name: str,
    mode: str,
) -> dict[str, Any]:
    """Synthesize the group `zarr.json` for one access mode."""
    get_specimen(registry, specimen_id)  # 404 if unknown
    variant = _imageish(get_variant(registry, specimen_id, kind, variant_name))
    rows = _rows_for_mode(variant.modes, mode)
    global_levels = enumerate_global_levels(rows)
    if not global_levels:
        raise HTTPException(status_code=404, detail="Empty pyramid")

    client = request.app.state.http_client

    # Fetch upstream group zarr.json for each contributing file.
    needed_files = sorted({fi for fi, _, _ in rows})
    upstream_groups: dict[int, dict[str, Any]] = {}
    for fi in needed_files:
        url = upstream_zarr_url(dc_helper_url, variant.files[fi], "zarr.json")
        upstream_groups[fi] = await cache.get(client, url)

    # Canonical source = first file in first row (carries omero/visor + axes).
    canonical_fi = rows[0][0]
    canonical = upstream_groups[canonical_fi]
    canonical_ome = canonical.get("attributes", {}).get("ome", {})
    canonical_ms = (canonical_ome.get("multiscales") or [{}])[0]
    axes = canonical_ms.get("axes", [])

    datasets: list[dict[str, Any]] = []
    for global_level in global_levels:
        file_idx, internal_idx = resolve_level(rows, global_level)
        ms_list = (
            upstream_groups[file_idx]
            .get("attributes", {})
            .get("ome", {})
            .get("multiscales", [{}])
        )
        upstream_datasets = ms_list[0].get("datasets", [])
        if internal_idx >= len(upstream_datasets):
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Upstream {variant.files[file_idx]} has no internal level "
                    f"{internal_idx} (referenced by global level {global_level})"
                ),
            )
        ct = upstream_datasets[internal_idx].get("coordinateTransformations", [])
        datasets.append({"path": str(global_level), "coordinateTransformations": ct})

    out_attrs: dict[str, Any] = {
        "ome": {
            "version": "0.5",
            "multiscales": [
                {
                    "name": f"{specimen_id}/{kind}/{variant_name}/{mode}",
                    "axes": axes,
                    "datasets": datasets,
                }
            ],
        }
    }
    if "omero" in canonical_ome:
        out_attrs["ome"]["omero"] = canonical_ome["omero"]
    if "visor" in canonical.get("attributes", {}):
        out_attrs["visor"] = canonical["attributes"]["visor"]

    return {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": out_attrs,
    }


def resolve_upstream_for_level(
    registry: Registry,
    dc_helper_url: str,
    specimen_id: str,
    kind: str,
    variant_name: str,
    mode: str,
    global_level: int,
    *suffix: str,
) -> str:
    """Return the upstream URL for an array's `zarr.json` or chunk."""
    variant = _imageish(get_variant(registry, specimen_id, kind, variant_name))
    rows = _rows_for_mode(variant.modes, mode)
    file_idx, internal_idx = resolve_level(rows, global_level)
    return upstream_zarr_url(
        dc_helper_url, variant.files[file_idx], str(internal_idx), *suffix
    )
