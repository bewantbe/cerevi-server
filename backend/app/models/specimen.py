"""Minimal specimen model definitions used by the redesigned API.

Historically this module contained numerous Pydantic models for rich metadata
and coordinate transforms. The current API only needs the ``ViewType`` enum to
map human-readable view tokens to internal orientation handling in
``DataService``. The removed models can be restored from git history if future
features require them again.
"""

from enum import Enum


class ViewType(str, Enum):
    """Image view types used for orientation mapping."""
    SAGITTAL = "sagittal"     # YZ plane (perpendicular to X-axis)
    CORONAL = "coronal"       # XZ plane (perpendicular to Y-axis)
    HORIZONTAL = "horizontal" # XY plane (perpendicular to Z-axis)
    VOLUMETRIC = "3d"         # 3D volume

__all__ = ["ViewType"]
