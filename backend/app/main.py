"""
Main FastAPI application for VISoR Platform
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .middleware.conditional_gzip import ConditionalGZipMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from .config import settings
from .api import new_api

# Configure logging
logging.basicConfig(
    level  = getattr(logging, settings.log_level),
    format = settings.log_format
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # FastAPI app startup
    logger.info(f"Starting {settings.app_name}, version {settings.app_version}")
    logger.info(f"Data path: {settings.data_root_path}")
    logger.info(f"Debug mode: {settings.debug}")
    
    yield
    
    # FastAPI app shutdown
    logger.info(f"Shutting down {settings.app_name} API")

# Create FastAPI application
app = FastAPI(
    title       = settings.app_name,
    version     = settings.app_version,
    description = settings.app_description,
    docs_url    = "/docs" if settings.debug else None,
    redoc_url   = "/redoc" if settings.debug else None,
    lifespan    = lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins     = settings.cors_origins,
    allow_credentials = True,
    allow_methods     = ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers     = ["*"],
)

# Enable automatic gzip compression for responses when the client supports it.
# Minimum size controls when compression is applied (in bytes).
app.add_middleware(ConditionalGZipMiddleware, minimum_size=1024)

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
        "data_root_path_exists": settings.data_root_path.exists()
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs" if settings.debug else "Documentation disabled in production"
    }

# Include redesigned unified endpoints (no /api prefix)
app.include_router(new_api.router, tags=[settings.app_api_version])

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host      = settings.host,
        port      = settings.port,
        reload    = settings.debug,
        log_level = settings.log_level.lower()
    )
