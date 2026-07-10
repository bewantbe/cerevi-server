"""Application settings.

All configuration comes from environment variables (with defaults).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_root() -> Path:
    configured = os.getenv("METADATA_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data"


class Settings(BaseSettings):
    app_name: str = "VISoR Platform API"
    app_version: str = "2.0.0"
    debug: bool = False

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
    ]

    # Local data dir for registry, atlases, and meshes. Default to the
    # canonical repo-level cerevi-server/metadata directory for local dev.
    data_root: Path = Field(default_factory=_default_data_root)

    # Upstream data center URL (cerevi-dc-helper). Required for /zarr proxy.
    dc_helper_url: str = Field(default_factory=lambda: os.getenv("DC_HELPER_URL", ""))

    proxy_timeout: float = 30.0
    proxy_max_connections: int = 64

    # TTL for the in-memory upstream-zarr.json cache used by the OME-Zarr gateway.
    zarr_metadata_cache_ttl: float = 60.0

    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()

