"""
API endpoints for metadata
"""

from fastapi import APIRouter, HTTPException, Path
import logging

from ..models.specimen import ImageInfo, AtlasInfo, ModelInfo
from ..services.tile_service import TileService
from ..config import settings, get_specimen_config

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
tile_service = TileService()

@router.get("/specimens/{specimen_id}/image-info", response_model=ImageInfo)
async def get_image_info(
    specimen_id: str = Path(..., description="Specimen ID")
):
    """Get image metadata information"""
    
    # Verify specimen exists
    if not get_specimen_config(specimen_id):
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        info = tile_service.get_image_info(specimen_id)
        return ImageInfo(**info)
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get image info: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve image information")

@router.get("/specimens/{specimen_id}/atlas-info", response_model=AtlasInfo)
async def get_atlas_info(
    specimen_id: str = Path(..., description="Specimen ID")
):
    """Get atlas metadata information"""
    
    # Verify specimen exists
    if not get_specimen_config(specimen_id):
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        info = tile_service.get_atlas_info(specimen_id)
        return AtlasInfo(**info)
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get atlas info: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve atlas information")

@router.get("/specimens/{specimen_id}/model-info", response_model=ModelInfo)
async def get_model_info(
    specimen_id: str = Path(..., description="Specimen ID")
):
    """Get 3D model metadata information"""
    
    # Verify specimen exists
    specimen_config = get_specimen_config(specimen_id)
    if not specimen_config:
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        model_path = settings.get_model_path(specimen_id)
        
        if not model_path.exists():
            raise HTTPException(status_code=404, detail=f"3D model not found for specimen {specimen_id}")
        
        # Get basic file info
        file_size = model_path.stat().st_size
        
        # For now, return basic info
        # In a full implementation, you would parse the OBJ file to get vertex/face counts
        info = ModelInfo(
            specimen_id=specimen_id,
            file_path=str(model_path),
            scale_factor=settings.mesh_scale_factor,
            vertex_count=0,  # Would need OBJ parser
            face_count=0,    # Would need OBJ parser
            file_size=file_size
        )
        
        return info
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get model info: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve model information")

@router.get("/specimens/{specimen_id}/metadata")
async def get_complete_metadata(
    specimen_id: str = Path(..., description="Specimen ID")
):
    """Get complete metadata for a specimen"""
    
    # Verify specimen exists
    specimen_config = get_specimen_config(specimen_id)
    if not specimen_config:
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        metadata = {
            "specimen": specimen_config,
            "image": None,
            "atlas": None,
            "model": None
        }
        
        # Get image info if available
        if specimen_config.get("has_image", False):
            try:
                image_info = tile_service.get_image_info(specimen_id)
                metadata["image"] = image_info
            except Exception as e:
                logger.warning(f"Could not get image info: {e}")
        
        # Get atlas info if available
        if specimen_config.get("has_atlas", False):
            try:
                atlas_info = tile_service.get_atlas_info(specimen_id)
                metadata["atlas"] = atlas_info
            except Exception as e:
                logger.warning(f"Could not get atlas info: {e}")
        
        # Get model info if available
        if specimen_config.get("has_model", False):
            try:
                model_path = settings.get_model_path(specimen_id)
                if model_path.exists():
                    file_size = model_path.stat().st_size
                    metadata["model"] = {
                        "specimen_id": specimen_id,
                        "file_path": str(model_path),
                        "scale_factor": settings.mesh_scale_factor,
                        "file_size": file_size
                    }
            except Exception as e:
                logger.warning(f"Could not get model info: {e}")
        
        return metadata
        
    except Exception as e:
        logger.error(f"Failed to get complete metadata: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metadata")

@router.get("/specimens/{specimen_id}/config-info")
async def get_config_info(
    specimen_id: str = Path(..., description="Specimen ID")
):
    """Get configuration and capabilities for a specimen"""
    
    # Verify specimen exists
    specimen_config = get_specimen_config(specimen_id)
    if not specimen_config:
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        # Get tile size suggestion
        suggested_tile_size = settings.default_tile_size
        
        config_info = {
            "specimen_id": specimen_id,
            "suggested_tile_size": suggested_tile_size,
            "max_resolution_level": settings.max_resolution_level,
            "supported_views": ["sagittal", "coronal", "horizontal"],
            "coordinate_system": settings.coordinate_system,
            "axes_order": settings.axes_order,
            "capabilities": {
                "has_image": specimen_config.get("has_image", False),
                "has_atlas": specimen_config.get("has_atlas", False),
                "has_model": specimen_config.get("has_model", False),
                "multi_channel": True,
                "multi_resolution": True,
                "region_picking": specimen_config.get("has_atlas", False)
            },
            "channels": specimen_config.get("channels", {}),
            "resolution_um": specimen_config.get("resolution_um", settings.image_resolution_um)
        }
        
        return config_info
        
    except Exception as e:
        logger.error(f"Failed to get config info: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve configuration")
