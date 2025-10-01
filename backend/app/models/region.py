"""
Data models for brain regions
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class Region(BaseModel):
    """Brain region model"""
    id: int
    name: str
    abbreviation: str
    level1: str
    level2: str
    level3: str
    level4: str
    value: int  # Region ID value in atlas mask
    parent_id: Optional[int] = None
    children: List[int] = Field(default_factory=list)
    color: Optional[str] = None  # Hex color for visualization

class RegionHierarchy(BaseModel):
    """Hierarchical structure of brain regions"""
    metadata: Dict[str, Any]
    regions: List[Region]
    hierarchy: Dict[str, Any]
    region_lookup: Dict[str, Region]
    
    def get_region_by_id(self, region_id: int) -> Optional[Region]:
        """Get region by ID"""
        return self.region_lookup.get(str(region_id))
    
    def get_region_by_value(self, value: int) -> Optional[Region]:
        """Get region by atlas mask value"""
        for region in self.regions:
            if region.value == value:
                return region
        return None
    
    def search_regions(self, query: str) -> List[Region]:
        """Search regions by name or abbreviation"""
        query_lower = query.lower()
        matching_regions = []
        
        for region in self.regions:
            if (query_lower in region.name.lower() or 
                query_lower in region.abbreviation.lower()):
                matching_regions.append(region)
        
        return matching_regions
    
    def get_regions_by_level(self, level: int) -> List[Region]:
        """Get regions by hierarchy level (1-4)"""
        if level < 1 or level > 4:
            return []
        
        level_attr = f"level{level}"
        unique_levels = set()
        regions = []
        
        for region in self.regions:
            level_value = getattr(region, level_attr)
            if level_value and level_value not in unique_levels:
                unique_levels.add(level_value)
                regions.append(region)
        
        return regions

class RegionPickResult(BaseModel):
    """Result of region picking at a coordinate"""
    specimen_id: str
    coordinate: Dict[str, int]  # x, y, z coordinates
    region: Optional[Region] = None
    region_value: int = 0
    confidence: float = 1.0
    
class RegionStatistics(BaseModel):
    """Statistics about brain regions"""
    total_regions: int
    regions_by_level: Dict[str, int]
    hierarchy_depth: int
    coverage_stats: Optional[Dict[str, Any]] = None

class RegionFilter(BaseModel):
    """Filter for region queries"""
    level: Optional[int] = Field(None, ge=1, le=4)
    search_query: Optional[str] = None
    parent_id: Optional[int] = None
    include_children: bool = True
    max_results: int = Field(default=100, ge=1, le=1000)

class RegionResponse(BaseModel):
    """Response model for region queries"""
    regions: List[Region]
    total_count: int
    filtered_count: int
    statistics: Optional[RegionStatistics] = None
