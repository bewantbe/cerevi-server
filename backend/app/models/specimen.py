"""
Data models for specimens
"""

from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from enum import Enum

class CoordinateSystem(str, Enum):
    """Coordinate system types"""
    RIGHT_HANDED = "right_handed"
    LEFT_HANDED = "left_handed"

class ViewType(str, Enum):
    """Image view types"""
    SAGITTAL = "sagittal"    # YZ plane (perpendicular to X-axis)
    CORONAL = "coronal"      # XZ plane (perpendicular to Y-axis)
    HORIZONTAL = "horizontal" # XY plane (perpendicular to Z-axis)

class SpecimenMetadata(BaseModel):
    """Specimen metadata model"""
    id: str
    name: str
    species: str
    description: str
    has_image: bool = False
    has_atlas: bool = False
    has_model: bool = False
    channels: Dict[str, str] = Field(default_factory=dict)
    resolution_um: float = 10.0
    coordinate_system: CoordinateSystem = CoordinateSystem.RIGHT_HANDED
    axes_order: str = "zyx"
    
class ImageInfo(BaseModel):
    """Image information model"""
    specimen_id: str
    dimensions: Tuple[int, int, int]  # (z, y, x)
    channels: Dict[str, str]
    resolution_levels: List[int]
    tile_size: int
    pixel_size_um: Tuple[float, float, float]  # (z, y, x) in micrometers
    data_type: str
    file_size: int
    
class AtlasInfo(BaseModel):
    """Atlas mask information model"""
    specimen_id: str
    dimensions: Tuple[int, int, int]  # (z, y, x)
    resolution_levels: List[int]
    tile_size: int
    pixel_size_um: Tuple[float, float, float]  # (z, y, x) in micrometers
    data_type: str
    file_size: int
    total_regions: int

class ModelInfo(BaseModel):
    """3D model information model"""
    specimen_id: str
    file_path: str
    scale_factor: float = 10.0  # Units in 10um
    coordinate_mapping: Dict[str, str] = Field(default_factory=lambda: {
        "x": "x",
        "y": "-y",  # Y becomes -Y in model
        "z": "z"
    })
    vertex_count: int = 0
    face_count: int = 0
    file_size: int = 0

class TileRequest(BaseModel):
    """Tile request model"""
    specimen_id: str
    view: ViewType
    level: int = Field(ge=0, le=7)
    z: int = Field(ge=0)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    channel: Optional[int] = Field(default=0, ge=0, le=3)
    tile_size: Optional[int] = Field(default=512, ge=64, le=2048)


class CoordinateTransform(BaseModel):
    """Coordinate transformation model"""
    view: ViewType
    array_axes: Tuple[int, int]  # Which axes from (z,y,x) array
    display_axes: Tuple[str, str]  # Display axis names
    slice_axis: int  # Which axis is the slice index

# Coordinate transformation mappings
COORDINATE_TRANSFORMS = {
    ViewType.SAGITTAL: CoordinateTransform(
        view=ViewType.SAGITTAL,
        array_axes=(0, 1),  # z, y from (z,y,x)
        display_axes=("anterior-posterior", "superior-inferior"),
        slice_axis=2  # X axis
    ),
    ViewType.CORONAL: CoordinateTransform(
        view=ViewType.CORONAL,
        array_axes=(0, 2),  # z, x from (z,y,x)
        display_axes=("anterior-posterior", "left-right"),
        slice_axis=1  # Y axis
    ),
    ViewType.HORIZONTAL: CoordinateTransform(
        view=ViewType.HORIZONTAL,
        array_axes=(1, 2),  # y, x from (z,y,x)
        display_axes=("superior-inferior", "left-right"),
        slice_axis=0  # Z axis
    )
}
