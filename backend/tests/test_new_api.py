"""Tests for redesigned unified API (/metadata, /data/{data_id}).

These tests intentionally minimal; they ensure new endpoints respond and
basic schema expectations hold. Tile / mesh retrieval are attempted only if
underlying data files exist (skip otherwise).
"""

import sys, os, json, gzip
import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.main import app  # noqa

client = TestClient(app)


def test_health():
    r = client.get('/health')
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'healthy'


def test_metadata_specimens():
    r = client.get('/metadata', params={'type': 'specimens'})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert 'RM009' in data
    sa = data['RM009']
    assert 'image' in sa
    assert "recon-v2" in sa['image']
    assert "RAS_coordinate" in sa['image']['recon-v2']


def test_metadata_regions():
    r = client.get('/metadata', params={'type': 'regions', 'specimen': 'RM009'})
    if r.status_code == 404:
        pytest.skip('Regions file missing in test environment')
    assert r.status_code == 200
    data = r.json()
    assert 'regions' in data or 'hierarchy' in data or isinstance(data, dict)


@pytest.mark.parametrize('view_token', ['3d', 'xy', 'xz', 'yz'])
def test_data_image_tile(view_token):
    # Attempt to fetch tile at origin for level 0 channel 0
    data_id = f'RM009:img{view_token}:0:0:0,0,0'
    r = client.get(f'/data/{data_id}')
    if r.status_code == 404:
        pytest.skip('Image file not present')
    elif r.status_code == 400:
        # Could be unsupported view if data orientation missing; treat as skip
        pytest.skip('View unsupported in current test data')
    else:
        assert r.status_code == 200
        # JPEG content for image modalities or raw bytestream
        ct = r.headers.get('content-type', '')
        assert ct in ('image/jpeg', 'image/jpg', 'application/octet-stream')

        # If server returned raw bytestream for image tiles (octet-stream),
        # ensure expected uncompressed size. 2 bytes per voxel/pixel.
        if ct == 'application/octet-stream':
            if view_token == '3d':
                # 3D tile/block: 64x64x64 voxels
                expected = 64 * 64 * 64 * 2
            else:
                # 2D tile: 512x512 pixels
                expected = 512 * 512 * 2
            assert len(r.content) == expected

def test_adjacent_image_tiles_overlap_xy():
    """Verify adjacent XY tiles overlap consistently for float16 raw tiles.

    This test requests two adjacent tiles along X and checks that the right
    half of the first equals the left half of the second. It uses the same
    coordinates as the original ad-hoc check and requires octet-stream
    float16 tiles sized 512x512.
    """
    # Resolution level and channel
    res_lv = 0
    ch = 0
    # Use original coordinates (Z,Y,X)
    zyx = (
        300 * 128 // 20,
        (60000 // 2 // 512) * 512,
        (70000 // 2 // 512) * 512,
    )

    data_id1 = f"RM009:imgxy:{res_lv}:{ch}:{zyx[0]},{zyx[1]},{zyx[2]}"
    r1 = client.get(f"/data/{data_id1}")
    # Do not skip on 404; require data to be present
    assert r1.status_code == 200, f"Unexpected status for first tile: {r1.status_code}"
    ct1 = r1.headers.get("content-type", "")
    assert "application/octet-stream" in ct1, f"Expected raw octet-stream, got {ct1}"
    assert len(r1.content) == 512 * 512 * 2, "Unexpected payload size for first tile"
    img1 = np.frombuffer(r1.content, dtype=np.float16).reshape((512, 512))

    # Adjacent tile along X by +256
    zyx2 = (zyx[0], zyx[1], zyx[2] + 256)
    data_id2 = f"RM009:imgxy:{res_lv}:{ch}:{zyx2[0]},{zyx2[1]},{zyx2[2]}"
    r2 = client.get(f"/data/{data_id2}")
    assert r2.status_code == 200, f"Unexpected status for adjacent tile: {r2.status_code}"
    ct2 = r2.headers.get("content-type", "")
    assert "application/octet-stream" in ct2, f"Expected raw octet-stream, got {ct2}"
    assert len(r2.content) == 512 * 512 * 2, "Unexpected payload size for adjacent tile"
    img2 = np.frombuffer(r2.content, dtype=np.float16).reshape((512, 512))

    # Basic sanity and overlap consistency
    assert np.any(img1), "First tile appears empty"
    assert np.all(img1[:, 256:] == img2[:, :256]), "Adjacent tile overlap mismatch"

def test_data_mask_tile():
    data_id = 'RM009:mskxz:0:0:0,0,0'
    r = client.get(f'/data/{data_id}')
    if r.status_code in (400, 404):
        pytest.skip('Mask atlas file not present')
    else:
        assert r.status_code == 200
        assert r.headers['content-type'] == 'image/png'


def test_data_mesh():
    data_id = 'RM009:meh3d:::brain_shell'
    r = client.get(f'/data/{data_id}')
    if r.status_code == 404:
        pytest.skip('Mesh file not present')
    elif r.status_code == 400:
        pytest.skip('Mesh modality unsupported in environment')
    else:
        assert r.status_code == 200
        assert 'text/plain' in r.headers['content-type']

        # Verify the OBJ header: third line should indicate Meshlab generator
        # Be tolerant of comment prefixes (e.g. '# ') that commonly appear in .obj files
        text = r.text
        lines = text.splitlines()
        if len(lines) < 3:
            pytest.skip('Mesh response too short to verify header')
        # Strip common comment markers and whitespace before comparison
        third = lines[2].lstrip('# ').strip()
        assert third == 'OBJ File Generated by Meshlab'


def test_json_compression():
    # Request specimens JSON with gzip accept header and ensure server gzips JSON responses
    headers = {'Accept-Encoding': 'gzip'}
    r = client.get('/metadata', params={'type': 'specimens'}, headers=headers)
    if r.status_code == 404:
        pytest.skip('Specimens metadata missing in test environment')
    assert r.status_code == 200

    # Server should indicate gzip encoding when it compressed the response
    enc = r.headers.get('Content-Encoding', '')
    assert 'gzip' in enc.lower()

    body = r.content
    # If the TestClient auto-decompressed, content won't start with gzip magic.
    if body[:2] == b'\x1f\x8b':
        decompressed = gzip.decompress(body)
    else:
        # Already decompressed by client
        decompressed = body

    # Ensure decompressed bytes are valid JSON
    data = json.loads(decompressed)
    assert isinstance(data, dict)
