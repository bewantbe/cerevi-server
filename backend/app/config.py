"""Minimal configuration used by the current redesigned API.

All unused settings and legacy helpers were removed to reduce surface area.
Only fields referenced in application code (main app setup & logging) remain.
"""

import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Application info
    app_name: str = "VISoR Platform API"
    app_version: str = "1.0.0"
    app_description: str = "API for VISoR (Volumetric Imaging with Synchronized on-the-fly-scan and Readout) Platform"
    app_api_version: str = "v2"
    debug: bool = False

    # Server / network
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]

    # Data root (specimens metadata + assets)
    data_root_path: Path = Field(default_factory=
        lambda: Path(os.getenv("DATA_ROOT_PATH", "data")))

    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

