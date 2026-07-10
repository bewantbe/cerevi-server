# Cerevi Backend

## Web API

This backend now implements a unified, minimal API surface:

CM005 is the default specimen. CM005, RM009, and BB001 are the reviewed imaging entries; MW001 and dMRI_CIVM remain placeholders for now.

Endpoints:

* `GET /health` – Health probe.
* `GET /registry/specimens` – Lists specimens and atlas placeholders. CM005 is the default first specimen.
* `GET /registry/specimens/{specimen_id}` – Returns one specimen or atlas summary.
* `GET /ome-zarr/{specimen_id}/{kind}/{variant}/{mode}/...` – Serves virtual OME-Zarr groups, arrays, and chunks.
* `GET /meshes/{specimen_id}/{variant}/{region}.obj` – Serves OBJ meshes declared in `metadata/specimens.json`.
* `GET /specimens/{specimen_id}/atlas` and `GET /atlas/{atlas_id}/regions.json` – Resolve and proxy atlas regions when a specimen has an atlas reference.

Examples:
```
GET /registry/specimens
GET /ome-zarr/CM005/image/recon-20260513/3d/zarr.json
GET /ome-zarr/CM005/image/recon-20260513/xz/0/zarr.json
GET /meshes/CM005/v20260602/brain_shell.obj
```

Legacy `/api/*` endpoints (specimens, tiles, regions, metadata) were removed in favor of this contract.

Specimen registry responses include `imageMetadata`, keyed by image variant name. Each value mirrors the image metadata attached in `metadata/specimens.json`, including channels, physical size, voxel/tile settings, axes order, and declared encodings.

## Contents

- `backend/` – FastAPI application (copied without code changes from `old_cerevi/backend`)
- `docker-compose.yml` – Backend + Redis stack
- `docker-compose.dev-backend.yml` – Development overlay (hot reload, no Redis)
- `.env.example` – Example environment variables

## Quick Start (Docker)

```bash
cp .env.example .env
# Development (hot reload, no Redis dependency)
docker-compose -f docker-compose.yml -f docker-compose.dev-backend.yml up --build -d backend
# Or full stack with Redis cache
docker-compose up --build -d

# Check health
curl http://localhost:8000/health | jq

# Specimens metadata
curl -s 'http://localhost:8000/registry/specimens' | jq
```

To rebuild cleanly:
```bash
docker-compose build --no-cache backend
```

View logs:
```bash
docker-compose logs -f backend
```

Tear down:
```bash
docker-compose down -v
```

If use of SSHFS is desired
```bash
sudo sshfs autocv172:/mnt/share_read_only/cerevi ~/code/cerevi-server/metadata -o allow_other
# then docker-compose up backend
# otherwise you get mkdir file exists error
```

## Local (Without Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
PYTHONPATH=backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir backend
pytest backend/tests/test_new_api.py -v
```

(Ensure `DATA_PATH` points to valid specimen and atlas data if you need non-404 responses for image/atlas endpoints.)

## Tests

```bash
docker-compose exec backend pytest tests -v
```

Or locally:
```
cd backend
pytest -v
```

Some tests may skip if large data files aren't present.

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DEBUG` | Enable docs & reload | `false` |
| `DATA_PATH` | Path inside container to data assets | `/app/metadata` |
| `REDIS_URL` | Redis connection string (empty disables) | `redis://redis:6379` |

## Data Directory Layout

```
cerevi/
├── specimens                                            # contract between backend and frontend
└── macaque_brain
     ├── ATLAS
     │    └── dMRI_CIVM/                                 # CIVM atlas data
     │         ├── macaque_brain_regions.json            # Hierarchical region structure (names as json)
     │         ├── macaque_brain_regions.xlsx            # Source atlas data (names as Excel, for generating json only)
     │         ├── atlas.ims   (not yet)                 # Brain region masks (brain area ID as pixel)
     │         └── copyright                             # Attribution and copyright information
    └── CM005
         ├── MRI
         │    └── ...
         ├── VISoR-tif
         │    └── ... 
         └── VISoR
            └── CM005.vsr                             # default CM005 specimen data
                ├── visor_recon_images
                │    └── lzc_whole_brain_20260513.zarr
                ├── visor_projn_images
                │    ├── yzj_xy_20260527.zarr
                │    ├── yzj_xz_20260527.zarr
                │    └── yzj_yz_20260527.zarr
                └── visor_mesh
                    └── brain_shell.obj      # 3D brain surface model
```

## Remote Data Filename Update Checklist

Use `metadata/specimens.json` as the source of truth. On the remote data root served by `cerevi-dc-helper`, every `files[]` path must exist exactly, including case and dates.

```bash
DATA_ROOT=/path/to/cerevi-data
cd "$DATA_ROOT"

# Rename only when the existing file is the same asset under an old name.
[[ -f macaque_brain/CM005/VISoR/CM005.vsr/visor_mesh/brain.obj \
    && ! -f macaque_brain/CM005/VISoR/CM005.vsr/visor_mesh/brain_shell.obj ]] \
    && mv macaque_brain/CM005/VISoR/CM005.vsr/visor_mesh/brain.obj \
        macaque_brain/CM005/VISoR/CM005.vsr/visor_mesh/brain_shell.obj
[[ -f macaque_brain/RM009/VISoR/RM009.vsr/visor_mesh/brain_shell.obj \
    && ! -f macaque_brain/RM009/VISoR/RM009.vsr/visor_mesh/brain_xyy_20260130.obj ]] \
    && mv macaque_brain/RM009/VISoR/RM009.vsr/visor_mesh/brain_shell.obj \
        macaque_brain/RM009/VISoR/RM009.vsr/visor_mesh/brain_xyy_20260130.obj

# Mesh filenames expected by the current registry.
test -f macaque_brain/CM005/VISoR/CM005.vsr/visor_mesh/brain_shell.obj
test -f macaque_brain/RM009/VISoR/RM009.vsr/visor_mesh/brain_xyy_20260130.obj
test -f human_brain/BB001/VISoR/BB001.vsr/visor_mesh/brain.obj

# Image directories expected by the current registry.
test -d macaque_brain/CM005/VISoR/CM005.vsr/visor_recon_images/lzc_whole_brain_20260513.zarr
test -d macaque_brain/CM005/VISoR/CM005.vsr/visor_projn_images/yzj_xy_20260527.zarr
test -d macaque_brain/CM005/VISoR/CM005.vsr/visor_projn_images/yzj_xz_20260527.zarr
test -d macaque_brain/CM005/VISoR/CM005.vsr/visor_projn_images/yzj_yz_20260527.zarr
test -d macaque_brain/RM009/VISoR/RM009.vsr/visor_recon_images/ycy_whole_brain_20251109.zarr
test -d macaque_brain/RM009/VISoR/RM009.vsr/visor_projn_images/xyy_xy_20251208.zarr
test -d macaque_brain/RM009/VISoR/RM009.vsr/visor_projn_images/xyy_xz_20251209.zarr
test -d macaque_brain/RM009/VISoR/RM009.vsr/visor_projn_images/xyy_yz_20251209.zarr
test -d human_brain/BB001/VISoR/BB001.vsr/visor_recon_images/yzj_half_brain_20260616.zarr
test -d human_brain/BB001/VISoR/BB001.vsr/visor_projn_images/yzj_xy_20260616.zarr
test -d human_brain/BB001/VISoR/BB001.vsr/visor_projn_images/yzj_xz_20260616.zarr
test -d human_brain/BB001/VISoR/BB001.vsr/visor_projn_images/yzj_yz_20260616zarr
```

After renaming or syncing assets, restart `cerevi-dc-helper` and `cerevi-server`, then smoke-test the paths through the API:

```bash
curl -f http://localhost:8000/registry/specimens
curl -f http://localhost:8000/meshes/CM005/v20260602/brain_shell.obj >/dev/null
curl -f http://localhost:8000/ome-zarr/CM005/image/recon-20260513/3d/zarr.json >/dev/null
curl -f http://localhost:8000/ome-zarr/BB001/image/recon-20260527/xy/zarr.json >/dev/null
```


## Migration Notes

The refactor removed legacy `/api/*`, `/metadata`, and `/data/{data_id}` routers. Client applications should use `/registry/*` for availability, `/ome-zarr/*` for image and mask arrays, `/meshes/*` for OBJ surfaces, and atlas routes only for specimens that declare an atlas reference.

## Next Steps (Optional Enhancements)
- Provide mock data fixtures for fully offline test runs
- Introduce OpenAPI tags documentation enhancements

## License
GPL-3.0 License. See `LICENSE` file for details.
