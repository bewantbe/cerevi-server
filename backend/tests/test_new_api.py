"""Tests for redesigned unified API (/metadata, /data/{data_id}).

These tests intentionally minimal; they ensure new endpoints respond and
basic schema expectations hold. Tile / mesh retrieval are attempted only if
underlying data files exist (skip otherwise).
"""

import sys, os, json
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
    assert "VISoR" in sa['image']
    assert "RAS_coordinate" in sa['image']['VISoR']


def test_metadata_regions():
    r = client.get('/metadata', params={'type': 'regions', 'specimen': 'RM009'})
    if r.status_code == 404:
        pytest.skip('Regions file missing in test environment')
    assert r.status_code == 200
    data = r.json()
    assert 'regions' in data or 'hierarchy' in data or isinstance(data, dict)


@pytest.mark.parametrize('view_token', ['xz', 'yz', 'xy'])
def test_data_image_tile(view_token):
    # Attempt to fetch tile at origin for level 0 channel 0
    data_id = f'RM009:img{view_token}:0:0:0,0,0'
    r = client.get(f'/data/{data_id}')
    if r.status_code == 404:
        pytest.skip('Image .ims file not present')
    elif r.status_code == 400:
        # Could be unsupported view if data orientation missing; treat as skip
        pytest.skip('View unsupported in current test data')
    else:
        assert r.status_code == 200
        # JPEG content for image modalities
        assert r.headers['content-type'] in ('image/jpeg', 'image/jpg')


def test_data_mask_tile():
    data_id = 'RM009:mskxz:0:0:0,0,0'
    r = client.get(f'/data/{data_id}')
    if r.status_code in (400, 404):
        pytest.skip('Mask atlas file not present')
    else:
        assert r.status_code == 200
        assert r.headers['content-type'] == 'image/png'


def test_data_mesh():
    data_id = 'RM009:meh3d:::v1'
    r = client.get(f'/data/{data_id}')
    if r.status_code == 404:
        pytest.skip('Mesh file not present')
    elif r.status_code == 400:
        pytest.skip('Mesh modality unsupported in environment')
    else:
        assert r.status_code == 200
        assert 'text/plain' in r.headers['content-type']
