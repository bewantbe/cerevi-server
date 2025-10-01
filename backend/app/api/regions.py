"""
API endpoints for brain regions
"""

import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Path
import logging

from ..models.region import (
    Region, RegionHierarchy, RegionPickResult, 
    RegionFilter, RegionResponse, RegionStatistics
)
from ..models.specimen import ViewType
from ..services.tile_service import TileService
from ..config import settings, get_specimen_config

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services
tile_service = TileService()

# Cache for region data
_region_cache = None

def load_region_hierarchy() -> RegionHierarchy:
    """Load region hierarchy from JSON file"""
    global _region_cache
    
    if _region_cache is None:
        regions_file = settings.get_regions_file()
        
        if not regions_file.exists():
            raise FileNotFoundError(f"Regions file not found: {regions_file}")
        
        try:
            with open(regions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Convert region data to Region objects
            regions = [Region(**region) for region in data['regions']]
            
            # Convert region_lookup values to Region objects
            region_lookup = {
                str(k): Region(**v) for k, v in data['region_lookup'].items()
            }
            
            _region_cache = RegionHierarchy(
                metadata=data['metadata'],
                regions=regions,
                hierarchy=data['hierarchy'],
                region_lookup=region_lookup
            )
            
            logger.info(f"Loaded {len(regions)} brain regions")
            
        except Exception as e:
            logger.error(f"Failed to load regions: {e}")
            raise
    
    return _region_cache

@router.get("/specimens/{specimen_id}/regions", response_model=RegionResponse)
async def get_regions(
    specimen_id: str = Path(..., description="Specimen ID"),
    level: Optional[int] = Query(None, ge=1, le=4, description="Hierarchy level (1-4)"),
    search: Optional[str] = Query(None, description="Search query for region names"),
    parent_id: Optional[int] = Query(None, description="Parent region ID"),
    max_results: int = Query(100, ge=1, le=1000, description="Maximum results")
):
    """Get brain regions with optional filtering"""
    
    # Verify specimen exists
    if not get_specimen_config(specimen_id):
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        hierarchy = load_region_hierarchy()
        
        # Apply filters
        filtered_regions = hierarchy.regions
        
        if search:
            filtered_regions = hierarchy.search_regions(search)
        
        if level:
            level_regions = hierarchy.get_regions_by_level(level)
            if search:
                # Intersect with search results
                level_ids = {r.id for r in level_regions}
                filtered_regions = [r for r in filtered_regions if r.id in level_ids]
            else:
                filtered_regions = level_regions
        
        if parent_id:
            # Filter by parent (this would need to be implemented based on hierarchy structure)
            pass
        
        # Limit results
        total_count = len(hierarchy.regions)
        filtered_count = len(filtered_regions)
        
        if len(filtered_regions) > max_results:
            filtered_regions = filtered_regions[:max_results]
        
        # Generate statistics
        stats = RegionStatistics(
            total_regions=total_count,
            regions_by_level={
                f"level_{i}": len(hierarchy.get_regions_by_level(i)) 
                for i in range(1, 5)
            },
            hierarchy_depth=4
        )
        
        return RegionResponse(
            regions=filtered_regions,
            total_count=total_count,
            filtered_count=filtered_count,
            statistics=stats
        )
        
    except Exception as e:
        logger.error(f"Failed to get regions: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve regions")

@router.get("/specimens/{specimen_id}/regions/{region_id}", response_model=Region)
async def get_region(
    specimen_id: str = Path(..., description="Specimen ID"),
    region_id: int = Path(..., description="Region ID")
):
    """Get details for a specific brain region"""
    
    # Verify specimen exists
    if not get_specimen_config(specimen_id):
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        hierarchy = load_region_hierarchy()
        region = hierarchy.get_region_by_id(region_id)
        
        if not region:
            raise HTTPException(status_code=404, detail=f"Region {region_id} not found")
        
        return region
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get region: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve region")

@router.get("/specimens/{specimen_id}/pick-region/{view}/{level}/{z}/{y}/{x}", response_model=RegionPickResult)
async def pick_region(
    specimen_id: str = Path(..., description="Specimen ID"),
    view: ViewType = Path(..., description="View type"),
    level: int = Path(..., ge=0, le=7, description="Resolution level"),
    z: int = Path(..., ge=0, description="Z coordinate"),
    y: int = Path(..., ge=0, description="Y coordinate"),
    x: int = Path(..., ge=0, description="X coordinate")
):
    """Pick brain region at specified coordinates"""
    
    # Verify specimen exists
    if not get_specimen_config(specimen_id):
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        # Get region value from atlas at coordinate
        region_value = tile_service.get_region_at_coordinate(
            specimen_id=specimen_id,
            view=view,
            x=x,
            y=y,
            z=z,
            level=level
        )
        
        # Look up region information
        hierarchy = load_region_hierarchy()
        region = hierarchy.get_region_by_value(region_value)
        
        result = RegionPickResult(
            specimen_id=specimen_id,
            coordinate={"x": x, "y": y, "z": z},
            region=region,
            region_value=region_value,
            confidence=1.0 if region else 0.0
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to pick region: {e}")
        raise HTTPException(status_code=500, detail="Failed to pick region")

@router.get("/specimens/{specimen_id}/regions-hierarchy")
async def get_region_hierarchy(
    specimen_id: str = Path(..., description="Specimen ID")
):
    """Get complete region hierarchy structure"""
    
    # Verify specimen exists
    if not get_specimen_config(specimen_id):
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        hierarchy = load_region_hierarchy()
        return {
            "metadata": hierarchy.metadata,
            "hierarchy": hierarchy.hierarchy,
            "statistics": {
                "total_regions": len(hierarchy.regions),
                "regions_by_level": {
                    f"level_{i}": len(hierarchy.get_regions_by_level(i)) 
                    for i in range(1, 5)
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get hierarchy: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve hierarchy")

@router.get("/specimens/{specimen_id}/regions/search")
async def search_regions(
    specimen_id: str = Path(..., description="Specimen ID"),
    q: str = Query(..., min_length=1, description="Search query"),
    max_results: int = Query(50, ge=1, le=200, description="Maximum results")
):
    """Search brain regions by name or abbreviation"""
    
    # Verify specimen exists
    if not get_specimen_config(specimen_id):
        raise HTTPException(status_code=404, detail=f"Specimen {specimen_id} not found")
    
    try:
        hierarchy = load_region_hierarchy()
        matching_regions = hierarchy.search_regions(q)
        
        # Limit results
        if len(matching_regions) > max_results:
            matching_regions = matching_regions[:max_results]
        
        return {
            "query": q,
            "results": matching_regions,
            "total_matches": len(matching_regions)
        }
        
    except Exception as e:
        logger.error(f"Failed to search regions: {e}")
        raise HTTPException(status_code=500, detail="Failed to search regions")
