"""Registry loader and lookup helpers for cerevi-server."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import HTTPException

from ..models.registry import (
    AtlasEntry,
    ImageVariant,
    MeshVariant,
    RegionMaskVariant,
    Registry,
    SpecimenEntry,
)

logger = logging.getLogger(__name__)


def load_registry(path: Path) -> Registry:
    """Load and validate the registry JSON. Fail-fast on schema errors."""
    if not path.is_file():
        raise FileNotFoundError(f"Registry not found: {path}")
    raw = json.loads(path.read_text())
    return Registry.parse(raw)


def get_specimen(registry: Registry, specimen_id: str) -> SpecimenEntry:
    entry = registry.get(specimen_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown specimen: {specimen_id}")
    if not isinstance(entry, SpecimenEntry):
        raise HTTPException(
            status_code=404, detail=f"{specimen_id} is not a specimen (it's an atlas)"
        )
    return entry


def get_atlas(registry: Registry, atlas_id: str) -> AtlasEntry:
    entry = registry.get(atlas_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown atlas: {atlas_id}")
    if not isinstance(entry, AtlasEntry):
        raise HTTPException(
            status_code=404, detail=f"{atlas_id} is not an atlas (it's a specimen)"
        )
    return entry


def resolve_atlas_for_specimen(registry: Registry, specimen_id: str) -> AtlasEntry:
    spec = get_specimen(registry, specimen_id)
    if not spec.atlas_reference:
        raise HTTPException(status_code=404, detail=f"No atlas for specimen: {specimen_id}")
    return get_atlas(registry, spec.atlas_reference)


_VariantUnion = ImageVariant | RegionMaskVariant | MeshVariant


def get_variant(
    registry: Registry,
    specimen_id: str,
    kind: str,
    variant: str,
) -> _VariantUnion:
    spec = get_specimen(registry, specimen_id)
    bag: dict[str, _VariantUnion]
    if kind == "image":
        bag = spec.image  # type: ignore[assignment]
    elif kind == "region_mask":
        bag = spec.region_mask  # type: ignore[assignment]
    elif kind == "mesh":
        bag = spec.mesh  # type: ignore[assignment]
    else:
        raise HTTPException(status_code=404, detail=f"Unknown kind: {kind}")
    v = bag.get(variant)
    if v is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown variant: {specimen_id}/{kind}/{variant}"
        )
    return v
