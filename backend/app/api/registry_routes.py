"""Slim registry/atlas/mesh routes for cerevi-server."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..config import settings
from ..models.registry import AtlasEntry, MeshVariant, SpecimenEntry
from ..services.gateway import upstream_zarr_url
from ..services.proxy import proxy_stream
from ..services.registry import (
    get_atlas,
    get_specimen,
    get_variant,
    resolve_atlas_for_specimen,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_IMAGE_METADATA_FIELDS = {
    "pixel_format",
    "physical_size_um",
    "origin_um",
    "channels",
    "resolutions_um_2d",
    "axes_order",
    "tile_size_2d",
    "tile_step_2d",
    "tile_thickness_2d",
    "tile_size_3d",
}


def _registry(request: Request):
    return request.app.state.registry


def _mesh_regions(entry: SpecimenEntry) -> dict[str, list[str]]:
    regions: dict[str, list[str]] = {}
    for variant_name, variant in entry.mesh.items():
        names: list[str] = []
        for _file_idx, _levels, row_names in variant.modes.three_d:
            names.extend(name for name in row_names if isinstance(name, str))
        regions[variant_name] = names
    return regions


def _mesh_downsample_factors(entry: SpecimenEntry) -> dict[str, float]:
    return {
        variant_name: variant.downsample_factor
        for variant_name, variant in entry.mesh.items()
    }


def _image_metadata(entry: SpecimenEntry) -> dict[str, dict[str, Any]]:
    return {
        variant_name: variant.model_dump(
            include=_IMAGE_METADATA_FIELDS,
            mode="json",
            exclude_none=True,
        )
        for variant_name, variant in entry.image.items()
    }


def _slim_specimen(entry: SpecimenEntry | AtlasEntry) -> dict[str, Any]:
    if isinstance(entry, AtlasEntry):
        return {
            "id": entry.id,
            "kind": "atlas",
            "name": entry.name,
            "species": entry.species,
            "description": entry.description,
        }
    return {
        "id": entry.id,
        "kind": "specimen",
        "name": entry.name,
        "species": entry.species,
        "description": entry.description,
        "atlasReference": entry.atlas_reference,
        "imageVariants": list(entry.image.keys()),
        "imageMetadata": _image_metadata(entry),
        "regionMaskVariants": list(entry.region_mask.keys()),
        "meshVariants": list(entry.mesh.keys()),
        "meshRegions": _mesh_regions(entry),
        "meshDownsampleFactors": _mesh_downsample_factors(entry),
    }


@router.get("/registry/specimens")
def list_specimens(request: Request) -> JSONResponse:
    reg = _registry(request)
    return JSONResponse([_slim_specimen(e) for _, e in reg.items()])


@router.get("/registry/specimens/{specimen_id}")
def get_specimen_detail(request: Request, specimen_id: str) -> JSONResponse:
    reg = _registry(request)
    entry = reg.get(specimen_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown id: {specimen_id}")
    return JSONResponse(_slim_specimen(entry))


@router.get("/atlas/{atlas_id}/regions.json")
async def get_atlas_regions(request: Request, atlas_id: str) -> Response:
    """Proxy the atlas region-list blob from dc-helper.

    Atlas entries declare a `regions.{name}.files[]` with a corresponding
    `blobs.region_list = [[file_idx]]` pointer.
    """
    if not settings.dc_helper_url:
        raise HTTPException(status_code=503, detail="DC_HELPER_URL not configured")
    reg = _registry(request)
    atlas = get_atlas(reg, atlas_id)
    if "published" not in atlas.regions:
        raise HTTPException(status_code=404, detail="No 'published' regions for atlas")
    pub = atlas.regions["published"]
    region_list_ptr = pub.blobs.get("region_list")
    if not region_list_ptr or not region_list_ptr[0]:
        raise HTTPException(status_code=404, detail="region_list pointer missing")
    file_idx = region_list_ptr[0][0]
    if file_idx >= len(pub.files):
        raise HTTPException(status_code=502, detail="region_list file_idx out of range")
    upstream = upstream_zarr_url(settings.dc_helper_url, pub.files[file_idx])
    return await proxy_stream(request, upstream)


@router.get("/specimens/{specimen_id}/atlas")
def specimen_atlas_redirect(request: Request, specimen_id: str) -> JSONResponse:
    """Resolve a specimen's atlas reference and return the atlas summary + URL."""
    reg = _registry(request)
    atlas = resolve_atlas_for_specimen(reg, specimen_id)
    return JSONResponse({
        **_slim_specimen(atlas),
        "regionsUrl": f"/atlas/{atlas.id}/regions.json",
    })


@router.get("/meshes/{specimen_id}/{variant}/{region}.obj")
async def get_mesh(
    request: Request, specimen_id: str, variant: str, region: str
) -> Response:
    """Proxy a mesh `.obj` from dc-helper, resolved via the mesh routing table."""
    if not settings.dc_helper_url:
        raise HTTPException(status_code=503, detail="DC_HELPER_URL not configured")
    reg = _registry(request)
    v = get_variant(reg, specimen_id, "mesh", variant)
    if not isinstance(v, MeshVariant):
        raise HTTPException(status_code=500, detail="Variant not a mesh")
    if "/" in region or ".." in region:
        raise HTTPException(status_code=400, detail="Invalid region name")
    # 3d routing rows: [file_idx, [global_level], [region_name, ...]]
    for file_idx, _levels, names in v.modes.three_d:
        if region in names:
            if file_idx >= len(v.files):
                raise HTTPException(status_code=502, detail="file_idx out of range")
            upstream = upstream_zarr_url(settings.dc_helper_url, v.files[file_idx])
            return await proxy_stream(request, upstream)
    raise HTTPException(status_code=404, detail=f"Region not in mesh: {region}")
