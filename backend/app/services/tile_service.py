"""
Service for generating image tiles
"""

import io
import numpy as np
from PIL import Image
from typing import Optional, Tuple, Union
import logging
from pathlib import Path

from .imaris_handler import ImarisHandler
from ..models.specimen import ViewType
from ..config import settings

logger = logging.getLogger(__name__)

class TileService:
    """Service for generating image tiles from Imaris data"""
    
    def __init__(self):
        self.default_tile_size = settings.default_tile_size
        
    def extract_image_tile(self, specimen_id: str, view: ViewType, level: int, 
                            channel: int, z: int, y: int, x: int, 
                            tile_size: Optional[int] = None) -> bytes:
        """Extract tile in JPEG from 3D image data, at origin (z,y,x), with specified tile size.
        
        Args:
            specimen_id: ID of the specimen
            view: View type (coronal, sagittal, horizontal)
            level: Resolution level (e.g. 0-7)
            channel: Channel index (e.g. 0-3)
            z: Z coordinate (pixel position)
            y: Y coordinate (pixel position)
            x: X coordinate (pixel position)
            tile_size: Size of extracted tile
            
        Returns:
            JPEG image bytes
        """
        
        if tile_size is None:
            tile_size = self.default_tile_size
            
        # Get image file path
        image_path = settings.get_image_path(specimen_id)
        
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found for specimen {specimen_id}")
        
        try:
            with ImarisHandler(image_path) as handler:
                # Get tile data
                tile_data = handler.get_tile(view, level, channel, z, y, x, tile_size)
                
                # Apply final vertical flip to match convention of image file
                tile_flipped = tile_data[::-1, :]
                
                # Convert to image
                image_bytes = self._array_to_image_bytes(tile_flipped, format='JPEG')
                
                logger.debug(f"Extracted image tile: {specimen_id}/{view}/{level}/{z}/{y}/{x}")
                return image_bytes
                
        except Exception as e:
            logger.error(f"Failed to extract image tile: {e}")
            raise
    
    def extract_atlas_tile(self, specimen_id: str, view: ViewType, level: int,
                            z: int, y: int, x: int, 
                            tile_size: Optional[int] = None) -> bytes:
        """Extract PNG tile from atlas mask (lossless)"""
        # TODO: may merge with extract_image_tile

        # Atlas typically has only one channel (channel 0)
        channel = 0

        if tile_size is None:
            tile_size = self.default_tile_size
            
        # Get atlas file path
        atlas_path = settings.get_atlas_path(specimen_id)
        
        if not atlas_path.exists():
            raise FileNotFoundError(f"Atlas file not found for specimen {specimen_id}")
        
        try:
            with ImarisHandler(atlas_path) as handler:
                tile_data = handler.get_tile(view, level, channel, z, y, x, tile_size)
                
                # Convert to PNG (lossless) for atlas data
                image_bytes = self._array_to_image_bytes(tile_data, format='PNG')
                
                logger.debug(f"Extracted atlas tile: {specimen_id}/{view}/{level}/{z}/{y}/{x}")
                return image_bytes
                
        except Exception as e:
            logger.error(f"Failed to extract atlas tile: {e}")
            raise
    
    def get_region_at_coordinate(self, specimen_id: str, view: ViewType, 
                                 x: int, y: int, z: int, level: int = 0) -> int:
        """Get region ID from atlas at specific coordinate"""
        
        # Get atlas file path
        atlas_path = settings.get_atlas_path(specimen_id)
        
        if not atlas_path.exists():
            raise FileNotFoundError(f"Atlas file not found for specimen {specimen_id}")
        
        try:
            with ImarisHandler(atlas_path) as handler:
                # Transform coordinates based on view type
                atlas_x, atlas_y, atlas_z = self._transform_coordinates_for_atlas(
                    view, x, y, z
                )
                
                # Get pixel value at coordinate (this is the region ID)
                region_value = handler.get_pixel_value_at_coordinate(
                    level, 0, atlas_x, atlas_y, atlas_z
                )
                
                return int(region_value)
                
        except Exception as e:
            logger.error(f"Failed to get region at coordinate: {e}")
            raise
    
    def get_image_info(self, specimen_id: str) -> dict:
        """Get image metadata information"""
        
        image_path = settings.get_image_path(specimen_id)
        
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found for specimen {specimen_id}")
        
        try:
            with ImarisHandler(image_path) as handler:
                metadata = handler.get_metadata()
                
                # Process metadata for API response
                info = {
                    "specimen_id": specimen_id,
                    "dimensions": metadata["shapes"].get(0, (0, 0, 0)),  # Level 0 shape
                    "channels": {str(i): settings.default_channels.get(str(i), f"Channel {i}") 
                               for i in metadata["channels"]},
                    "resolution_levels": metadata["resolution_levels"],
                    "tile_size": self.default_tile_size,
                    "pixel_size_um": (settings.image_resolution_um, 
                                     settings.image_resolution_um, 
                                     settings.image_resolution_um),
                    "data_type": metadata["data_type"],
                    "file_size": metadata["file_size"]
                }
                
                return info
                
        except Exception as e:
            logger.error(f"Failed to get image info: {e}")
            raise
    
    def get_atlas_info(self, specimen_id: str) -> dict:
        """Get atlas metadata information"""
        
        atlas_path = settings.get_atlas_path(specimen_id)
        
        if not atlas_path.exists():
            raise FileNotFoundError(f"Atlas file not found for specimen {specimen_id}")
        
        try:
            with ImarisHandler(atlas_path) as handler:
                metadata = handler.get_metadata()
                
                # Load region count from regions file
                regions_file = settings.get_regions_file()
                total_regions = 0
                if regions_file.exists():
                    import json
                    with open(regions_file, 'r') as f:
                        regions_data = json.load(f)
                        total_regions = regions_data.get('metadata', {}).get('total_regions', 0)
                
                # Process metadata for API response
                info = {
                    "specimen_id": specimen_id,
                    "dimensions": metadata["shapes"].get(0, (0, 0, 0)),  # Level 0 shape
                    "resolution_levels": metadata["resolution_levels"],
                    "tile_size": self.default_tile_size,
                    "pixel_size_um": (settings.image_resolution_um, 
                                     settings.image_resolution_um, 
                                     settings.image_resolution_um),
                    "data_type": metadata["data_type"],
                    "file_size": metadata["file_size"],
                    "total_regions": total_regions
                }
                
                return info
                
        except Exception as e:
            logger.error(f"Failed to get atlas info: {e}")
            raise
    
    def _array_to_image_bytes(self, array: np.ndarray, format: str = 'JPEG') -> bytes:
        """Convert numpy array to image bytes"""
        
        # Normalize array to 0-255 range
        if array.dtype != np.uint8:
            # Handle different data types
            if array.dtype in [np.uint16, np.uint32]:
                # For uint16/32, scale down to uint8
                array_max = np.max(array)
                if array_max > 0:
                    array = (array.astype(np.float32) / array_max * 255).astype(np.uint8)
                else:
                    array = array.astype(np.uint8)
            else:
                # For float types, assume 0-1 range
                array = (np.clip(array, 0, 1) * 255).astype(np.uint8)
        
        # Create PIL Image (grayscale)
        if len(array.shape) == 2:
            image = Image.fromarray(array, mode='L')
        else:
            raise ValueError("Only 2D arrays are supported for tile generation")
        
        # Convert to bytes
        buffer = io.BytesIO()
        
        if format == 'JPEG':
            # High quality JPEG for image data
            image.save(buffer, format='JPEG', quality=85, optimize=True)
        elif format == 'PNG':
            # Lossless PNG
            image.save(buffer, format='PNG', optimize=True)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        return buffer.getvalue()
    
    def _transform_coordinates_for_atlas(self, view: ViewType, x: int, y: int, z: int) -> Tuple[int, int, int]:
        """Transform display coordinates to atlas coordinates"""
        
        # For now, assume atlas coordinates match image coordinates
        # This may need adjustment based on actual atlas alignment
        
        if view == ViewType.SAGITTAL:
            # Display (x, y) maps to atlas (y, z), slice is x
            return x, y, z
        elif view == ViewType.CORONAL:
            # Display (x, y) maps to atlas (x, z), slice is y
            return x, y, z
        elif view == ViewType.HORIZONTAL:
            # Display (x, y) maps to atlas (x, y), slice is z
            return x, y, z
        else:
            raise ValueError(f"Unknown view type: {view}")
    
    def calculate_tile_grid(self, specimen_id: str, view: ViewType, level: int) -> dict:
        """Calculate tile grid information for a view and level"""
        
        image_path = settings.get_image_path(specimen_id)
        
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found for specimen {specimen_id}")
        
        try:
            with ImarisHandler(image_path) as handler:
                tiles_x, tiles_y = handler.calculate_tile_grid_size(view, level, self.default_tile_size)
                shape = handler.get_data_shape(level, 0)  # Get shape for channel 0
                
                return {
                    "view": view,
                    "level": level,
                    "tile_size": self.default_tile_size,
                    "tiles_x": tiles_x,
                    "tiles_y": tiles_y,
                    "image_shape": shape,
                    "total_tiles": tiles_x * tiles_y
                }
                
        except Exception as e:
            logger.error(f"Failed to calculate tile grid: {e}")
            raise
