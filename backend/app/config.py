"""
Configuration settings for the VISoR Platform backend
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings"""
    
    # Application info
    app_name: str = "VISoR Platform API"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    
    # CORS settings
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",  # Added for frontend development
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]
    
    # Data paths
    data_path: Path = Field(default_factory=lambda: Path(os.getenv("DATA_PATH", "data")))
    # Atlas path for region data
    atlas_civm_path: Path = Field(default_factory=lambda: Path(os.getenv("DATA_PATH", "data")) / "macaque_brain_dMRI_atlas_CIVM")
    
    # Redis settings
    redis_url: str = "redis://redis:6379"
    redis_db: int = 0
    redis_max_connections: int = 10
    
    # Cache settings
    cache_ttl_tiles: int = 3600  # 1 hour
    cache_ttl_metadata: int = 86400  # 24 hours
    cache_ttl_regions: int = 86400  # 24 hours
    
    # Image processing settings
    default_tile_size: int = 512
    max_resolution_level: int = 7
    supported_formats: List[str] = ["png", "jpg", "jpeg"]
    
    # Coordinate system settings
    coordinate_system: str = "right_handed"
    axes_order: str = "zyx"  # Image array order
    
    # Channel settings
    default_channels: Dict[str, str] = {
        "0": "405nm",
        "1": "488nm", 
        "2": "561nm",
        "3": "640nm"
    }
    
    # 3D model settings
    mesh_scale_factor: float = 10.0  # Mesh units are in 10um
    image_resolution_um: float = 10.0  # Image resolution at level 0
    
    # Performance settings
    max_concurrent_requests: int = 100
    request_timeout: int = 30
    
    # Logging settings
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Pydantic v2 configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Ignore extra environment variables
    )
        
    def get_specimen_path(self, specimen_id: str) -> Path:
        """Get the path to a specific specimen directory"""
        return self.data_path / specimen_id
    
    def get_image_path(self, specimen_id: str) -> Path:
        """Get the path to the image file for a specimen"""
        return self.get_specimen_path(specimen_id) / "image.ims"
    
    def get_atlas_path(self, specimen_id: str) -> Path:
        """Get the path to the atlas file for a specimen"""
        return self.get_specimen_path(specimen_id) / "atlas.ims"
    
    def get_model_path(self, specimen_id: str) -> Path:
        """Get the path to the 3D model file for a specimen"""
        return self.get_specimen_path(specimen_id) / "brain_shell.obj"
    
    def get_regions_file(self) -> Path:
        """Get the path to the regions JSON file"""
        return self.atlas_civm_path / "macaque_brain_regions.json"


# Global settings instance
settings = Settings()


# Specimen configuration
SPECIMENS_CONFIG = {
    "macaque_brain_RM009": {
        "id": "macaque_brain_RM009",
        "name": "Macaque Brain RM009",
        "species": "Macaca mulatta",
        "description": "High-resolution macaque brain imaging with VISoR technology",
        "has_image": True,
        "has_atlas": True,
        "has_model": True,
        "channels": settings.default_channels,
        "resolution_um": settings.image_resolution_um,
        "coordinate_system": settings.coordinate_system,
        "axes_order": settings.axes_order,
    }
}


def get_specimen_config(specimen_id: str) -> Optional[Dict]:
    """Get configuration for a specific specimen"""
    return SPECIMENS_CONFIG.get(specimen_id)


def get_all_specimens() -> List[Dict]:
    """Get configuration for all available specimens"""
    return list(SPECIMENS_CONFIG.values())
