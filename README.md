# Cerevi Backend (Extracted)

This repository contains the extracted backend portion of the original `old_cerevi` project. It provides a FastAPI-based API for serving specimen metadata, brain region hierarchy, image/atlas tiles, and related model information.

## Contents

- `backend/` – FastAPI application (copied without code changes from `old_cerevi/backend`)
- `docker-compose.yml` – Backend + Redis stack
- `docker-compose.dev-backend.yml` – Development overlay (hot reload, no Redis)
- `.env.example` – Example environment variables
- `old_cerevi/` – Original project kept for reference (not used by the new stack)

## Quick Start (Docker)

```bash
cp .env.example .env
# Development (hot reload, no Redis dependency)
docker-compose -f docker-compose.yml -f docker-compose.dev-backend.yml up --build -d backend
# Or full stack with Redis cache
docker-compose up --build -d

# Check health
curl http://localhost:8000/health | jq
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
# Run in container
docker-compose exec backend pytest tests -v
# Or locally
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

## Data Directory

A placeholder `backend/data/.gitkeep` is included. Mount or populate actual data externally for real tile serving.

## No Code Changes Assurance
Files in `backend/` are direct copies of the original backend logic (only relocation). Any future refactor should be explicitly tracked via PR.

## Next Steps (Optional Enhancements)
- Add CI workflow (pytest + lint)
- Add pre-commit hooks for formatting
- Provide mock data fixtures for fully offline test runs
- Introduce OpenAPI tags documentation enhancements

## License
Refer to original project licensing (not modified here).
