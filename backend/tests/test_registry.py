"""Tests for the cleaned registry models and loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models.registry import AtlasEntry, ImageVariant, SpecimenEntry
from app.services.registry import (
    get_specimen,
    get_variant,
    load_registry,
    resolve_atlas_for_specimen,
)


REPO_REGISTRY = Path(__file__).resolve().parents[2] / "metadata" / "specimens.json"


def test_real_registry_validates() -> None:
    """The shipped metadata/specimens.json must validate against the schema."""
    reg = load_registry(REPO_REGISTRY)
    assert "RM009" in reg
    assert "CM005" in reg
    assert "dMRI_CIVM" in reg
    assert "MW001" in reg
    assert "BB001" in reg


def test_specimen_vs_atlas_discrimination() -> None:
    reg = load_registry(REPO_REGISTRY)
    assert isinstance(reg["RM009"], SpecimenEntry)
    assert isinstance(reg["dMRI_CIVM"], AtlasEntry)


def test_rm009_image_variant() -> None:
    reg = load_registry(REPO_REGISTRY)
    spec = get_specimen(reg, "RM009")
    assert "recon-20251109" in spec.image
    v = spec.image["recon-20251109"]
    assert isinstance(v, ImageVariant)
    assert len(v.files) == 4
    # Routing rows preserved verbatim
    assert v.modes.three_d == [
        (0, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [0, 1, 2, 3]),
    ]
    assert v.modes.xy == [(1, [0, 1, 2, 3, 4, 5, 6, 7], [0, 1, 2, 3])]


def test_cm005_and_bb001_image_variants_match_generated_metadata() -> None:
    reg = load_registry(REPO_REGISTRY)
    cm005 = get_specimen(reg, "CM005").image["recon-20260513"]
    bb001 = get_specimen(reg, "BB001").image["recon-20260616"]

    assert cm005.modes.three_d == [(0, list(range(10)), [0, 3])]
    assert cm005.modes.xy == [(1, list(range(8)), [0, 3])]

    assert bb001.files[0].endswith("visor_recon_images/yzj_half_brain_20260616.zarr")
    assert bb001.files[1].endswith("visor_projn_images/yzj_xy_20260616.zarr")
    assert bb001.modes.three_d == [(0, list(range(11)), [0, 1])]
    assert bb001.modes.xy == [(1, list(range(9)), [0, 1])]


def test_rm009_region_mask() -> None:
    reg = load_registry(REPO_REGISTRY)
    spec = get_specimen(reg, "RM009")
    rm = spec.region_mask["V1"]
    assert rm.region_id_map["1"] == "V1-l1"
    assert len(rm.region_id_map) == 7


def test_rm009_mesh_routing_uses_region_names() -> None:
    reg = load_registry(REPO_REGISTRY)
    spec = get_specimen(reg, "RM009")
    mesh = spec.mesh["v20260130"]
    assert mesh.downsample_factor == 10
    assert mesh.modes.three_d == [(0, [0], ["brain_shell"])]
    # xy/xz/yz are empty for mesh
    assert mesh.modes.xy == []


def test_new_mesh_variants_use_file_stem_region_names() -> None:
    reg = load_registry(REPO_REGISTRY)
    cm005 = get_specimen(reg, "CM005")
    bb001 = get_specimen(reg, "BB001")
    assert cm005.mesh["v20260602"].downsample_factor == 160
    assert cm005.mesh["v20260602"].modes.three_d == [
        (0, [0], ["brain_shell"]),
    ]
    assert bb001.mesh["v20260602"].downsample_factor == 10
    assert bb001.mesh["v20260602"].modes.three_d == [(0, [0], ["brain"])]


def test_atlas_reference_resolution() -> None:
    reg = load_registry(REPO_REGISTRY)
    atlas = resolve_atlas_for_specimen(reg, "RM009")
    assert atlas.id == "dMRI_CIVM"
    assert "published" in atlas.regions
    blobs = atlas.regions["published"].blobs
    assert blobs["region_list"] == [(0,)]


def test_no_atlas_reference_raises_404() -> None:
    reg = load_registry(REPO_REGISTRY)
    with pytest.raises(HTTPException) as exc:
        resolve_atlas_for_specimen(reg, "MW001")
    assert exc.value.status_code == 404


def test_unknown_specimen_raises_404() -> None:
    reg = load_registry(REPO_REGISTRY)
    with pytest.raises(HTTPException) as exc:
        get_specimen(reg, "DOES_NOT_EXIST")
    assert exc.value.status_code == 404


def test_atlas_id_used_as_specimen_raises_404() -> None:
    reg = load_registry(REPO_REGISTRY)
    with pytest.raises(HTTPException) as exc:
        get_specimen(reg, "dMRI_CIVM")
    assert exc.value.status_code == 404


def test_get_variant_unknown_kind_raises_404() -> None:
    reg = load_registry(REPO_REGISTRY)
    with pytest.raises(HTTPException) as exc:
        get_variant(reg, "RM009", "bogus", "x")
    assert exc.value.status_code == 404


def test_invalid_registry_fails_fast(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"X": {"id": "X"}}))  # missing required fields
    with pytest.raises(Exception):
        load_registry(bad)
