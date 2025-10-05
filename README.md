# Cerevi Backend

## Web API

This backend now implements a unified, minimal API surface:

Endpoints:

* `GET /health` – Health probe.
* `GET /metadata?type=specimens` – Returns specification (metadata) of images for each specimen. In backend it is the raw contents of `data/specimens`.
* `GET /metadata?type=regions&specimen={specimen_id}` – Returns region hierarchy JSON for the specimen. Currently CIVM atlas JSON.
* `GET /data/{data_id}` – Fetch imagery / mask tiles / mesh using composite identifier. Return image size is described in `/metadata?type=specimens`.

`data_id` format:
```
{specimen_id}:{image_type}:{resolution_level}:{channel}:{index}

specimen_id = RM009 | ...
    Obtained from `/metadata?type=specimens`

image_type = {modality}{view_type}[-{encoding}]
    * modality: img | msk | meh
        Query `/metadata?type=specimens` for availability, img = "image", msk = "region_mask", meh = "mesh"
    * view_type: c | s | h | 3
        c,s,h,3 = coronal, sagittal, horizontal, 3D
    * encoding: optional (raw | zstd_sqrt_v1 | textr | obj | ...)
        Query `/metadata?type=specimens` for availability, "encoding_2d_list", "encoding_3d_list", "encoding_list".
        If omitted, defaults to "raw" for img and msk, "obj" for meh.

resolution_level = 0, 1, 2, ...
    usually 0 = highest resolution, see `resolution_um_list` in `/metadata?type=specimens`

channel = 0, 1, 2, ...
    See 'channels' in `/metadata?type=specimens`.

index = {z},{y},{x} | {region_name} | {region_name},{z} ...
    For 2D tiles and 3D blocks: z,y,x (voxel position).
    For meshes: region_name (e.g. "brain_shell", "v1"), or {region_name},{z} (2D region at specific z-plane).
```

Examples:
```
GET /data/RM009:imgc:0:0:43200,512,1536   # Coronal image tile (RAW)
GET /data/RM009:mskc:0:0:43200,512,1536   # Coronal mask tile (RAW)
GET /data/RM009:meh3:::v1                 # Mesh (OBJ text)
```

Legacy `/api/*` endpoints (specimens, tiles, regions, metadata) were removed in favor of this contract.

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
curl -s 'http://localhost:8000/metadata?type=specimens' | jq
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

## Local (Without Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir backend
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
| `DATA_PATH` | Path inside container to data assets | `/app/data` |
| `REDIS_URL` | Redis connection string (empty disables) | `redis://redis:6379` |

## Data Directory Layout

```
data/
└── macaque_brain
    ├── RM009.vsr                                 # RM009 specimen data (entity-based organization)
    │   ├── visor_recon_images                    # 
    │   │       └── yzj_brain_10x_20250904.zarr   # Multi-resolution image data, master tape
    │   ├── visor_textr_images                    # 
    │   │       ├── coronal.zarr     # optimized for coronal-section access
    │   │       ├── sagittal.zarr                 # optimized for sagittal-section access
    │   │       ├── horizontal.zarr               # optimized for horizontal-section access
    │   │       └── 3d.zarr                       # optimized for volumetric access, e.g. codec ktx2
    │   ├── visor_h265_images                     # 
    │   │       └── 3d.zarr                       # optimized for volumetric access, e.g. codec ktx2
    │   ├── visor_ims_images                      # 
    │   │       └── image.ims                     # Multi-resolution image data, lower resolution
    │   ├── visor_atlas_images                    # 
    │   │       └── atlas.ims                     # Brain region masks (brain area ID as pixel)
    │   ├── visor_mesh_images                     # 
    │   │       └── brain_shell.obj               # 3D brain surface model
    │   ├── info.json                             # Basic information about the specimen
    │   ├── metadata.json                         # custom metadata
    │   └── copyright                             # Attribution and copyright information
    └── dMRI_atlas_CIVM/    # CIVM atlas data
        ├── macaque_brain_regions.json    # Hierarchical region structure (names as json)
        ├── macaque_brain_regions.xlsx    # Source atlas data (names as Excel, for generating json only)
        ├── atlas.ims   (not yet)            # Brain region masks (brain area ID as pixel)
        └── copyright                     # Attribution and copyright information
```


## Migration Notes

The refactor removed legacy routers; only `/health`, `/metadata`, and `/data/{data_id}` remain. Client applications must construct `data_id` strings per the schema above. Tile size derives from each entry's `tile_size_2d` in `data/specimens`.

## Next Steps (Optional Enhancements)
- Provide mock data fixtures for fully offline test runs
- Introduce OpenAPI tags documentation enhancements

## License
GPL-3.0 License. See `LICENSE` file for details.
