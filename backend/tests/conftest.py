"""
Pytest configuration for VISoR Platform backend tests
"""
import sys
import os
import pytest

# Add backend to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

@pytest.fixture(scope="session")
def backend_path():
    """Get the backend directory path"""
    return os.path.join(os.path.dirname(__file__), '..')

@pytest.fixture(scope="session") 
def data_path():
    """Get the data directory path"""
    backend_dir = os.path.join(os.path.dirname(__file__), '..')
    return os.path.join(backend_dir, '..', 'data')
