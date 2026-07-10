"""FastAPI entrypoint for cerevi-server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import registry_routes, zarr_gateway
from .config import settings
from .services.proxy import JsonCache
from .services.registry import load_registry

logging.basicConfig(level=getattr(logging, settings.log_level), format=settings.log_format)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info(
        "DC_HELPER_URL=%s data_root=%s",
        settings.dc_helper_url or "<unset>",
        settings.data_root,
    )

    # Registry is required to start.
    registry_path = settings.data_root / "specimens.json"
    app.state.registry = load_registry(registry_path)
    logger.info("Loaded registry: %d entries", len(app.state.registry.root))

    app.state.zarr_meta_cache = JsonCache(ttl_seconds=settings.zarr_metadata_cache_ttl)

    limits = httpx.Limits(max_connections=settings.proxy_max_connections)
    app.state.http_client = httpx.AsyncClient(timeout=settings.proxy_timeout, limits=limits)
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        logger.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _on_unhandled(request, exc):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "healthy",
        "version": settings.app_version,
        "dc_helper_configured": bool(settings.dc_helper_url),
    }


app.include_router(registry_routes.router)
app.include_router(zarr_gateway.router)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
