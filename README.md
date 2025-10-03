# Cerevi Backend – Redesigned API

This backend now implements a unified, minimal API surface:

Endpoints:

* `GET /health` – Health probe.
* `GET /metadata?type=specimens` – Returns the raw contents of `data/specimens` (source of truth for specimen + data asset metadata).
* `GET /metadata?type=regions&specimen=RM009` – Returns region hierarchy JSON for the specimen (currently CIVM atlas JSON).
* `GET /data/{data_id}` – Fetch imagery / mask tiles / mesh using composite identifier.

`data_id` format:
```
{specimen_id}:{image_type}:{resolution_level}:{channel}:{coords}

image_type = {modality}{view_type}[-{encoding}]
	modality: img | msk | meh
	view_type: c | s | h | 3
	encoding: optional (raw | zstd_sqrt_v1 | textr | obj | ...)

coords for 2D tiles: z,y,x (origin voxel)
```

Examples:
```
GET /data/RM009:imgc:0:0:43200,512,1536   # Coronal image tile (JPEG)
GET /data/RM009:mskc:0:0:43200,512,1536   # Coronal mask tile (PNG)
GET /data/RM009:meh3:::v1                 # Mesh (OBJ text) – resolution/channel omitted
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
curl -s 'localhost:8000/metadata?type=specimens' | jq
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

Or locally:
```
cd backend
pytest -v
```
```

Some tests may skip if large data files aren't present.

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DEBUG` | Enable docs & reload | `false` |
| `DATA_PATH` | Path inside container to data assets | `/app/data` |
| `REDIS_URL` | Redis connection string (empty disables) | `redis://redis:6379` |

## Data Directory

A placeholder `backend/data/.gitkeep` is included. Mount or populate actual data externally for real tile serving.

## Migration Notes

The refactor removed legacy routers; only `/health`, `/metadata`, and `/data/{data_id}` remain. Client applications must construct `data_id` strings per the schema above. Tile size derives from each entry's `tile_size_2d` in `data/specimens`.

## Next Steps (Optional Enhancements)
- Add CI workflow (pytest + lint)
- Add pre-commit hooks for formatting
- Provide mock data fixtures for fully offline test runs
- Introduce OpenAPI tags documentation enhancements

## License
Refer to original project licensing (not modified here).
