"""
Main FastAPI application for VISoR Platform
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from .config import settings
from .api import (
    new_api,          # redesigned endpoints
    specimens,        # legacy specimen endpoints (kept during migration)
    metadata as legacy_metadata,
    tiles as legacy_tiles,
    regions as legacy_regions,
)


# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format=settings.log_format
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting VISoR Platform API")
    logger.info(f"Data path: {settings.data_path}")
    logger.info(f"Debug mode: {settings.debug}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down VISoR Platform API")

# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="API for VISoR (Volumetric Imaging with Synchronized on-the-fly-scan and Readout) Platform",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "data_path_exists": settings.data_path.exists()
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "VISoR Platform API",
        "version": settings.app_version,
        "docs": "/docs" if settings.debug else "Documentation disabled in production"
    }

# Include legacy /api endpoints for backward compatibility (migration phase)
app.include_router(specimens.router, prefix="/api", tags=["specimens (legacy)"])
app.include_router(legacy_metadata.router, prefix="/api", tags=["metadata (legacy)"])
app.include_router(legacy_tiles.router, prefix="/api", tags=["tiles (legacy)"])
app.include_router(legacy_regions.router, prefix="/api", tags=["regions (legacy)"])

# Include redesigned unified endpoints (no /api prefix)
app.include_router(new_api.router, tags=["v2"])

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
