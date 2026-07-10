"""Tests for the cerevi-server OME-Zarr gateway and auxiliary routes.

Uses respx to stub upstream cerevi-dc-helper responses backed by the real
fixture trees produced by `cerevi-dc-helper/tests/fixtures/build.py`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

DC_HELPER_FIXTURES_BUILD = (
    Path(__file__).resolve().parents[3]
    / "cerevi-dc-helper"
    / "tests"
    / "fixtures"
    / "build.py"
)


def _load_fixture_builder():
    spec = importlib.util.spec_from_file_location(
        "_dc_fixtures_build", DC_HELPER_FIXTURES_BUILD
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mount_fixture_routes(fixtures_root: Path, base_url: str = "http://dc.test") -> None:
    """Register a respx route for each file under `fixtures_root`."""

    def handler(request):
        # Strip leading "http://dc.test/"
        rel = str(request.url).split(base_url + "/", 1)[1]
        target = fixtures_root / rel
        if not target.is_file():
            return Response(404)
        data = target.read_bytes()
        if target.name == "zarr.json":
            return Response(200, json=json.loads(data))
        return Response(200, content=data)

    # Catch-all under base_url
    respx.route(url__regex=rf"^{base_url}/.+").mock(side_effect=handler)


@pytest.fixture()
def fixtures_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    builder = _load_fixture_builder()
    return builder.build_all(tmp_path_factory.mktemp("dc_fixtures"))


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    repo_data = Path(__file__).resolve().parents[2] / "data"
    monkeypatch.setenv("METADATA_ROOT", str(repo_data))
    monkeypatch.setenv("DC_HELPER_URL", "http://dc.test")

    import importlib

    import app.config as cfg
    import app.api.registry_routes as rr
    import app.api.zarr_gateway as zg
    import app.services.gateway as g
    import app.services.proxy as p
    import app.services.registry as r
    import app.main as main_mod

    importlib.reload(cfg)
    importlib.reload(p)
    importlib.reload(r)
    importlib.reload(g)
    importlib.reload(rr)
    importlib.reload(zg)
    importlib.reload(main_mod)

    with TestClient(main_mod.app) as c:
        yield c


# ---------------------------------------------------------------------------
# Registry routes
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["dc_helper_configured"] is True


def test_registry_specimens_lists_all(client: TestClient) -> None:
    r = client.get("/registry/specimens")
    assert r.status_code == 200
    rows = r.json()
    ids = {row["id"]: row for row in rows}
    assert rows[0]["id"] == "CM005"
    assert {"CM005", "RM009", "dMRI_CIVM", "MW001", "BB001"} <= set(ids)
    assert ids["CM005"]["imageVariants"] == ["recon-20260513"]
    assert ids["CM005"]["meshVariants"] == ["v20260602"]
    assert ids["CM005"]["meshRegions"] == {"v20260602": ["brain_shell"]}
    assert ids["CM005"]["meshDownsampleFactors"] == {"v20260602": 160.0}
    assert ids["RM009"]["kind"] == "specimen"
    assert ids["RM009"]["imageVariants"] == ["recon-20251109"]
    assert ids["RM009"]["regionMaskVariants"] == ["V1"]
    assert ids["RM009"]["meshVariants"] == ["v20260130"]
    assert ids["RM009"]["meshRegions"] == {"v20260130": ["brain_shell"]}
    assert ids["RM009"]["meshDownsampleFactors"] == {"v20260130": 10.0}
    assert ids["BB001"]["imageVariants"] == ["recon-20260616"]
    assert ids["BB001"]["meshVariants"] == ["v20260602"]
    assert ids["BB001"]["meshRegions"] == {"v20260602": ["brain"]}
    assert ids["BB001"]["meshDownsampleFactors"] == {"v20260602": 10.0}
    assert ids["dMRI_CIVM"]["kind"] == "atlas"


def test_registry_specimen_detail_includes_image_metadata(client: TestClient) -> None:
    r = client.get("/registry/specimens/CM005")
    assert r.status_code == 200
    metadata = r.json()["imageMetadata"]["recon-20260513"]
    assert metadata["pixel_format"] == "uint16"
    assert metadata["physical_size_um"] == [67200.0, 50000.0, 60000.0]
    assert metadata["origin_um"] == [0.0, 0.0, 0.0]
    assert metadata["channels"] == [
        {"wavelength": "405", "marker": "DAPI"},
        {"wavelength": "640", "marker": "Nissl"},
    ]
    assert metadata["resolutions_um_2d"] == [
        [20.0, 1.0],
        [20.0, 2.0],
        [20.0, 4.0],
        [20.0, 8.0],
        [20.0, 16.0],
        [20.0, 32.0],
        [20.0, 64.0],
        [20.0, 128.0],
    ]
    assert metadata["axes_order"] == "ZYX"
    assert metadata["tile_size_2d"] == [512, 512]
    assert metadata["tile_step_2d"] == 20.0
    assert metadata["tile_thickness_2d"] == 20.0
    assert metadata["tile_size_3d"] == [64, 64, 64]


def test_registry_specimen_detail(client: TestClient) -> None:
    r = client.get("/registry/specimens/RM009")
    assert r.status_code == 200
    body = r.json()
    assert body["atlasReference"] == "dMRI_CIVM"
    rm009_metadata = body["imageMetadata"]["recon-20251109"]
    assert rm009_metadata["channels"][1] == {
        "wavelength": "488",
        "marker": "AAV-eGFP",
    }
    assert rm009_metadata["tile_size_3d"] == [64, 64, 64]


def test_registry_unknown_specimen(client: TestClient) -> None:
    r = client.get("/registry/specimens/NOPE")
    assert r.status_code == 404


def test_specimen_atlas_redirect(client: TestClient) -> None:
    r = client.get("/specimens/RM009/atlas")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "dMRI_CIVM"
    assert body["regionsUrl"] == "/atlas/dMRI_CIVM/regions.json"


def test_specimen_atlas_redirect_no_atlas(client: TestClient) -> None:
    r = client.get("/specimens/MW001/atlas")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Atlas regions proxy (uses fixture-tree-shaped paths)
# ---------------------------------------------------------------------------


@respx.mock
def test_atlas_regions_proxy(client: TestClient, fixtures_root: Path) -> None:
    # Add the atlas region file to fixtures (not built by the standard fixtures).
    atlas_path = (
        fixtures_root / "macaque_brain" / "ATLAS" / "dMRI_CIVM" / "macaque_brain_regions.json"
    )
    atlas_path.parent.mkdir(parents=True, exist_ok=True)
    atlas_path.write_text(json.dumps({"hierarchy": [{"id": 1}]}))
    _mount_fixture_routes(fixtures_root)

    r = client.get("/atlas/dMRI_CIVM/regions.json")
    assert r.status_code == 200
    assert r.json() == {"hierarchy": [{"id": 1}]}


# ---------------------------------------------------------------------------
# Mesh proxy
# ---------------------------------------------------------------------------


@respx.mock
def test_mesh_proxy(client: TestClient, fixtures_root: Path) -> None:
    mesh_path = (
        fixtures_root
        / "macaque_brain"
        / "RM009"
        / "VISoR"
        / "RM009.vsr"
        / "visor_mesh"
        / "brain_shell.obj"
    )
    mesh_path.parent.mkdir(parents=True, exist_ok=True)
    mesh_path.write_text("# OBJ\nv 0 0 0\n")
    _mount_fixture_routes(fixtures_root)

    r = client.get("/meshes/RM009/v20260130/brain_shell.obj")
    assert r.status_code == 200
    assert r.text.startswith("# OBJ")


def test_mesh_traversal_blocked(client: TestClient) -> None:
    r = client.get("/meshes/RM009/v20260130/..%2Fevil.obj")
    assert r.status_code in (400, 404)


def test_mesh_unknown_region(client: TestClient) -> None:
    r = client.get("/meshes/RM009/v20260130/nonexistent.obj")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# OME-Zarr gateway — group synthesis
# ---------------------------------------------------------------------------


@respx.mock
def test_gateway_group_3d_cm005_default(client: TestClient, fixtures_root: Path) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/CM005/image/recon-20260513/3d/zarr.json")
    assert r.status_code == 200, r.text
    body = r.json()
    ms = body["attributes"]["ome"]["multiscales"][0]
    assert [d["path"] for d in ms["datasets"]] == [str(i) for i in range(10)]
    scales = [d["coordinateTransformations"][0]["scale"] for d in ms["datasets"]]
    assert scales[0] == [1.0, 1.0, 1.0, 1.0]
    assert scales[9] == [1.0, 512.0, 512.0, 512.0]
    assert len(body["attributes"]["ome"]["omero"]["channels"]) == 2


@respx.mock
def test_gateway_group_xz_cm005_uses_axis_specific_scale(
    client: TestClient, fixtures_root: Path
) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/CM005/image/recon-20260513/xz/zarr.json")
    assert r.status_code == 200, r.text
    ms = r.json()["attributes"]["ome"]["multiscales"][0]
    assert [d["path"] for d in ms["datasets"]] == [str(i) for i in range(8)]
    assert ms["datasets"][0]["coordinateTransformations"][0]["scale"] == [
        1.0,
        1.0,
        20.0,
        1.0,
    ]


@respx.mock
def test_gateway_group_3d_rm009(client: TestClient, fixtures_root: Path) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/3d/zarr.json")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["zarr_format"] == 3
    assert body["node_type"] == "group"
    ms = body["attributes"]["ome"]["multiscales"][0]
    assert [a["name"] for a in ms["axes"]] == ["c", "z", "y", "x"]
    # 3d is served by the whole-brain recon over global levels 0..9.
    paths = [d["path"] for d in ms["datasets"]]
    assert paths == [str(i) for i in range(10)]
    # Whole-brain scales double each level from 1 um up to 512 um.
    scales = [d["coordinateTransformations"][0]["scale"] for d in ms["datasets"]]
    assert scales[0] == [1.0, 1.0, 1.0, 1.0]
    assert scales[1] == [1.0, 2.0, 2.0, 2.0]
    assert scales[9] == [1.0, 512.0, 512.0, 512.0]
    # Forwarded omero + custom visor block
    assert len(body["attributes"]["ome"]["omero"]["channels"]) == 4
    assert body["attributes"]["visor"]["channels"][0]["wavelength"] == "405"


@respx.mock
def test_gateway_group_xy_rm009_uses_projection_levels(
    client: TestClient, fixtures_root: Path
) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/xy/zarr.json")
    assert r.status_code == 200, r.text
    ms = r.json()["attributes"]["ome"]["multiscales"][0]
    assert [d["path"] for d in ms["datasets"]] == [str(i) for i in range(8)]
    # Level 0 (projn): slice axis = 20, plane = 1
    assert ms["datasets"][0]["coordinateTransformations"][0]["scale"] == [
        1.0,
        20.0,
        1.0,
        1.0,
    ]
    assert ms["datasets"][7]["coordinateTransformations"][0]["scale"] == [
        1.0,
        20.0,
        128.0,
        128.0,
    ]


@respx.mock
def test_gateway_group_unknown_specimen(client: TestClient, fixtures_root: Path) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/NOPE/image/recon-20251109/3d/zarr.json")
    assert r.status_code == 404


@respx.mock
def test_gateway_group_unknown_mode(client: TestClient, fixtures_root: Path) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/bogus/zarr.json")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# OME-Zarr gateway — array zarr.json + chunks
# ---------------------------------------------------------------------------


@respx.mock
def test_gateway_array_zarr_json_3d_level0(client: TestClient, fixtures_root: Path) -> None:
    """Global 3D level 0 routes to the whole-brain recon internal level 0."""
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/3d/0/zarr.json")
    assert r.status_code == 200
    body = r.json()
    assert body["node_type"] == "array"
    assert body["shape"] == [4, 64, 64, 64]
    assert body["dimension_names"] == ["c", "z", "y", "x"]


@respx.mock
def test_gateway_array_zarr_json_3d_level1_routes_to_whole_brain(
    client: TestClient, fixtures_root: Path
) -> None:
    """Global 3D level 1 routes to the whole-brain recon internal level 1 (32^3)."""
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/3d/1/zarr.json")
    assert r.status_code == 200
    assert r.json()["shape"] == [4, 32, 32, 32]


@respx.mock
def test_gateway_array_xy_level7_routes_to_projection(
    client: TestClient, fixtures_root: Path
) -> None:
    """xy global level 7 routes to the projection pyramid's internal level 7."""
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/xy/7/zarr.json")
    assert r.status_code == 200
    assert r.json()["shape"] == [4, 4, 1, 1]


@respx.mock
def test_gateway_chunk_fetch(client: TestClient, fixtures_root: Path) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/3d/1/c/0/0/0/0")
    assert r.status_code == 200
    # whole-brain internal level 1: chunk_shape (1,4,4,4) uint16 = 128 bytes
    assert len(r.content) == 128


@respx.mock
def test_gateway_chunk_traversal_blocked(client: TestClient, fixtures_root: Path) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/3d/0/c/..%2Fevil")
    assert r.status_code in (400, 404)


@respx.mock
def test_gateway_unknown_level(client: TestClient, fixtures_root: Path) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/3d/99/zarr.json")
    assert r.status_code == 404


@respx.mock
def test_gateway_chunk_head(client: TestClient, fixtures_root: Path) -> None:
    """HEAD on chunk URL returns 200 (zarrita probes existence with HEAD)."""
    _mount_fixture_routes(fixtures_root)
    r = client.head("/ome-zarr/RM009/image/recon-20251109/3d/1/c/0/0/0/0")
    assert r.status_code == 200
    assert r.content == b""
    assert r.headers.get("accept-ranges") == "none"


@respx.mock
def test_gateway_group_zarr_json_head(client: TestClient, fixtures_root: Path) -> None:
    _mount_fixture_routes(fixtures_root)
    r = client.head("/ome-zarr/RM009/image/recon-20251109/3d/zarr.json")
    assert r.status_code == 200
    assert r.content == b""
    assert r.headers.get("accept-ranges") == "none"


@respx.mock
def test_gateway_chunk_no_range(client: TestClient, fixtures_root: Path) -> None:
    """Server advertises accept-ranges: none on chunk responses."""
    _mount_fixture_routes(fixtures_root)
    r = client.get("/ome-zarr/RM009/image/recon-20251109/3d/1/c/0/0/0/0")
    assert r.status_code == 200
    assert r.headers.get("accept-ranges") == "none"
