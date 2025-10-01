"""
Integration tests for VISoR Platform backend

Converted from scripts/test_backend.py to proper pytest format.
Tests the core functionality including imports, data access, 
region loading, and image metadata extraction.
"""

import sys
import os
import json
import pytest

# Add backend to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

class TestBackendIntegration:
    """Integration tests for backend components"""

    def test_imports(self):
        """Test that all backend modules can be imported"""
        
        # Test configuration import
        from app.config import settings
        assert settings is not None
        assert hasattr(settings, 'app_name')
        assert hasattr(settings, 'data_path')
        assert hasattr(settings, 'default_tile_size')
        
        # Test specimen models
        from app.models.specimen import SpecimenMetadata, ViewType
        assert SpecimenMetadata is not None
        assert ViewType is not None
        
        # Test region models  
        from app.models.region import Region, RegionHierarchy
        assert Region is not None
        assert RegionHierarchy is not None
        
        # Test services
        from app.services.imaris_handler import ImarisHandler
        assert ImarisHandler is not None
        
        from app.services.tile_service import TileService
        assert TileService is not None
        
        # Test FastAPI app
        from app.main import app
        assert app is not None

    def test_data_access(self):
        """Test access to data files and directories"""
        from app.config import settings
        
        # Check if data directories exist
        assert settings.data_path.exists(), f"Data path does not exist: {settings.data_path}"
        macaque_path = settings.get_specimen_path("macaque_brain_RM009")
        assert macaque_path.exists(), f"Macaque RM009 path does not exist: {macaque_path}"
        assert settings.atlas_civm_path.exists(), f"Atlas CIVM path does not exist: {settings.atlas_civm_path}"
        
        # Check specimen data
        specimen_id = "macaque_brain_RM009"
        image_path = settings.get_image_path(specimen_id)
        atlas_path = settings.get_atlas_path(specimen_id)
        model_path = settings.get_model_path(specimen_id)
        regions_file = settings.get_regions_file()
        
        # Verify paths are configured (they may not exist in test environment)
        assert image_path is not None, "Image path should be configured"
        assert atlas_path is not None, "Atlas path should be configured"
        assert model_path is not None, "Model path should be configured"
        assert regions_file is not None, "Regions file path should be configured"

    def test_region_loading(self):
        """Test loading region hierarchy from JSON file"""
        from app.config import settings
        
        regions_file = settings.get_regions_file()
        assert regions_file is not None, "Regions file path should be configured"
        
        if regions_file.exists():
            with open(regions_file, 'r') as f:
                data = json.load(f)
            
            # Verify JSON structure
            assert 'metadata' in data, "Regions file should have metadata section"
            assert 'regions' in data, "Regions file should have regions section"
            assert 'total_regions' in data['metadata'], "Metadata should include total_regions"
            
            # Verify regions data
            regions = data['regions']
            assert len(regions) > 0, "Should have at least one region"
            
            # Check sample region structure
            sample_region = regions[0]
            assert 'name' in sample_region, "Region should have name field"
            assert 'abbreviation' in sample_region, "Region should have abbreviation field"
        else:
            pytest.skip(f"Regions file not found: {regions_file}")

    def test_image_metadata_extraction(self):
        """Test image metadata extraction from Imaris files"""
        from app.config import settings
        from app.services.imaris_handler import ImarisHandler
        
        specimen_id = "macaque_brain_RM009"
        image_path = settings.get_image_path(specimen_id)
        
        if image_path and image_path.exists():
            with ImarisHandler(image_path) as handler:
                metadata = handler.get_metadata()
                
                # Verify metadata structure
                assert metadata is not None, "Should return metadata"
                assert 'file_size' in metadata, "Metadata should include file_size"
                assert 'resolution_levels' in metadata, "Metadata should include resolution_levels"
                assert 'channels' in metadata, "Metadata should include channels"
                assert 'data_type' in metadata, "Metadata should include data_type"
                assert 'shapes' in metadata, "Metadata should include shapes"
                
                # Verify data types
                assert isinstance(metadata['file_size'], (int, float)), "File size should be numeric"
                assert isinstance(metadata['resolution_levels'], list), "Resolution levels should be list"
                assert isinstance(metadata['channels'], list), "Channels should be list"
                assert isinstance(metadata['shapes'], dict), "Shapes should be dictionary"
                
                # Verify reasonable values
                assert metadata['file_size'] > 0, "File size should be positive"
                assert len(metadata['resolution_levels']) > 0, "Should have at least one resolution level"
                assert len(metadata['channels']) > 0, "Should have at least one channel"
        else:
            pytest.skip(f"Image file not found: {image_path}")


def test_backend_integration_suite():
    """Run all integration tests as a suite"""
    # This can be used to run all tests programmatically if needed
    import pytest
    
    # Run tests in this module
    pytest.main([__file__, "-v"])


if __name__ == "__main__":
    # Allow running this file directly with python
    test_backend_integration_suite()
