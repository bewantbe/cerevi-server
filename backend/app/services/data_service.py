"""DataService implementing redesigned API contract.

Responsible for:
  - Loading specimen metadata from data/specimens (source of truth)
  - Serving region hierarchy JSON for a specimen
  - Resolving file paths for image (.ims), mask (.ims), mesh (.obj)
  - Extracting 2D tiles based on composite data_id format
  - Returning mesh bytes

data_id schema (See redesign spec):
  {specimen_id}:{image_type}:{resolution_level}:{channel}:{coords}

  image_type = {modality}{view_type}[-{encoding}]
    modality: img | msk | meh
    view_type: c | s | h | 3 (3 for volumetric / mesh)
    encoding (optional): raw | zstd_sqrt_v1 | textr | obj | ...

  resolution_level, channel may be omitted (empty) for mesh requests OR
  future volumetric fetches. We tolerate blank fields.

  coords forms:
    z,y,x  -> tile origin (required for img/msk 2D slice)
    region_name | region_name,z (NOT implemented yet – placeholder)

Limitations / Assumptions:
  - We pick the first available image / region_mask / mesh entry in metadata
    unless future query params specify otherwise.
  - Encoding flag is accepted but presently only .ims raw access is implemented;
    we ignore encoding when reading .ims (could dispatch different optimized
    zarr backends later).
  - For mask (msk*) we always PNG; for image (img*) JPEG.

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import json
import re
import logging

from ..models.specimen import ViewType
from .imaris_handler import ImarisHandler

logger = logging.getLogger(__name__)


@dataclass
class ParsedDataId:
    specimen_id: str
    modality: str  # img | msk | meh
    view_token: str  # c | s | h | 3
    encoding: Optional[str]
    resolution_level: Optional[int]
    channel: Optional[int]
    d_index: str

    def view_type(self) -> Optional[ViewType]:
        if self.view_token == 'c':
            return ViewType.CORONAL
        if self.view_token == 's':
            return ViewType.SAGITTAL
        if self.view_token == 'h':
            return ViewType.HORIZONTAL
        if self.view_token == '3':
            return ViewType.VOLUMETRIC
        return None  # unsupported

    def coords_tuple(self) -> Tuple[int, int, int]:
        parts = self.d_index.split(',') if self.d_index else []
        if len(parts) != 3:
            raise ValueError("coords must be z,y,x for img/msk requests")
        try:
            z, y, x = (int(p) for p in parts)
        except ValueError as e:
            raise ValueError("coords values must be integers") from e
        return z, y, x


class DataService:
    """Service for redesigned API interactions."""

    def __init__(self, data_root: Path | None = None):
        self.data_root = data_root or Path('data')
        self._specimens_cache: Optional[Dict[str, Any]] = None

    # -------------------- Metadata Loading --------------------
    def load_specimens_metadata(self, force: bool = False) -> Dict[str, Any]:
        if self._specimens_cache is None or force:
            specimens_file = self.data_root / 'specimens'
            if not specimens_file.exists():
                raise FileNotFoundError(f"Specimens metadata file not found: {specimens_file}")
            with open(specimens_file, 'r', encoding='utf-8') as f:
                self._specimens_cache = json.load(f)
            logger.info("Loaded specimens metadata: %d entries", len(self._specimens_cache))
        return self._specimens_cache

    def get_specimen_meta(self, specimen_id: str) -> Dict[str, Any]:
        meta = self.load_specimens_metadata().get(specimen_id)
        if not meta:
            raise KeyError(f"Specimen {specimen_id} not found in metadata")
        return meta

    def get_regions_metadata(self, specimen_id: str) -> Dict[str, Any]:
        # For now RM009 maps to CIVM atlas path; Use specimen atlas_reference/specimens field.
        specimen_meta = self.get_specimen_meta(specimen_id)
        atlas_ref = specimen_meta.get('atlas_reference', {}).get('specimens')
        # Hard-coded current path structure (data/macaque_brain/dMRI_atlas_CIVM/...)
        regions_path = self.data_root / 'macaque_brain' / 'dMRI_atlas_CIVM' / 'macaque_brain_regions.json'
        if not regions_path.exists():
            raise FileNotFoundError(f"Regions metadata file not found: {regions_path}")
        with open(regions_path, 'r', encoding='utf-8') as f:
            regions_json = json.load(f)
        # Potentially filter / adapt per specimen later.
        return regions_json

    # -------------------- data_id Parsing --------------------
    _IMAGE_TYPE_RE = re.compile(r'^(?P<mod>img|msk|meh)(?P<view>[csh3])(?:-(?P<enc>[A-Za-z0-9_]+))?$')

    def parse_data_id(self, data_id: str) -> ParsedDataId:
        parts = data_id.split(':')
        if len(parts) != 5:
            raise ValueError("data_id must have 5 colon-separated segments")
        specimen_id, image_type_token, rl_raw, ch_raw, coords = parts
        m = self._IMAGE_TYPE_RE.match(image_type_token)
        if not m:
            raise ValueError(f"Invalid image_type format: {image_type_token}")
        encoding = m.group('enc')
        modality = m.group('mod')
        view_token = m.group('view')
        resolution_level = int(rl_raw) if rl_raw.strip() != '' else None
        channel = int(ch_raw) if ch_raw.strip() != '' else None
        return ParsedDataId(
            specimen_id=specimen_id,
            modality=modality,
            view_token=view_token,
            encoding=encoding,
            resolution_level=resolution_level,
            channel=channel,
            d_index=coords
        )

    # -------------------- Tile / Mesh Serving --------------------
    def _resolve_ims_path(self, specimen_id: str, modality: str) -> Path:
        meta = self.get_specimen_meta(specimen_id)
        if modality == 'img':
            images = meta.get('image', {})
        elif modality == 'msk':
            # region_mask has nested mapping (like "V1": {...}) – pick first entry
            images = meta.get('region_mask', {})
        else:
            raise ValueError("_resolve_ims_path only supports img/msk")
        if not images:
            raise FileNotFoundError(f"No {'image' if modality=='img' else 'region_mask'} data for specimen {specimen_id}")
        first_entry = next(iter(images.values()))  # value is metadata dict
        rel_source = Path(first_entry['source'])
        ims_path = self.data_root / rel_source
        if not ims_path.exists():
            raise FileNotFoundError(f"File not found: {ims_path}")
        return ims_path

    def _get_tile_size(self, specimen_id: str, modality: str) -> int:
        meta = self.get_specimen_meta(specimen_id)
        if modality == 'img':
            images = meta.get('image', {})
        else:
            images = meta.get('region_mask', {})
        if not images:
            return 512
        first_entry = next(iter(images.values()))
        # Try tile_size_2d first element; fall back to 512
        ts = first_entry.get('tile_size_2d') or first_entry.get('tile_size_3d') or [512]
        if isinstance(ts, list):
            return int(ts[0])
        try:
            return int(ts)
        except Exception:
            return 512

    def _resolve_mesh_path(self, specimen_id: str) -> Path:
        meta = self.get_specimen_meta(specimen_id)
        meshes = meta.get('mesh', {})
        if not meshes:
            raise FileNotFoundError(f"No mesh data for specimen {specimen_id}")
        first_entry = next(iter(meshes.values()))
        rel_source = Path(first_entry['source'])
        mesh_path = self.data_root / rel_source
        if not mesh_path.exists():
            raise FileNotFoundError(f"Mesh file not found: {mesh_path}")
        return mesh_path

    def get_tile_bytes(self, parsed: ParsedDataId) -> bytes:
        if parsed.modality not in ('img', 'msk'):
            raise ValueError("get_tile_bytes only for img/msk modalities")
        view_type = parsed.view_type()
        if view_type is None:
            raise ValueError("View type required (c/s/h) for img/msk requests")
        if parsed.resolution_level is None:
            raise ValueError("resolution_level required for img/msk requests")
        if parsed.channel is None and parsed.modality == 'img':
            raise ValueError("channel required for img requests")
        z, y, x = parsed.coords_tuple()
        ims_path = self._resolve_ims_path(parsed.specimen_id, parsed.modality)
        channel = parsed.channel or 0
        tile_size = self._get_tile_size(parsed.specimen_id, parsed.modality)
        with ImarisHandler(ims_path) as h:
            tile = h.get_tile(view_type, parsed.resolution_level, channel, z, y, x, tile_size=tile_size)
        # Convert to image bytes (reuse TileService logic?) – implement lightweight here to avoid import cycle
        try:
            import numpy as np
            from PIL import Image
            import io
            arr = tile
            if arr.dtype != 'uint8':
                arr_max = arr.max() or 1
                arr = (arr.astype('float32') / arr_max * 255).astype('uint8')
            img = Image.fromarray(arr, mode='L')
            buf = io.BytesIO()
            if parsed.modality == 'img':
                img.save(buf, format='JPEG', quality=85, optimize=True)
            else:
                img.save(buf, format='PNG', optimize=True)
            return buf.getvalue()
        except Exception as e:
            logger.error("Failed to encode tile: %s", e)
            raise

    def get_mesh_bytes(self, parsed: ParsedDataId) -> bytes:
        mesh_path = self._resolve_mesh_path(parsed.specimen_id)
        return mesh_path.read_bytes()
