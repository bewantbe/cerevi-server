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
        view_type: xy | yz | xz | 3d  (3d for volumetric / mesh)
            xy = return image data on xy plane (usually coronal)
            yz = return image data on yz plane (usually sagittal)
            xz = return image data on xz plane (usually horizontal)
            3d = return volumetric data or 3D mesh.
        encoding (optional): raw | zstd_sqrt_v1 | textr | obj | ...

  resolution_level, channel may be omitted (empty) for mesh requests.

  coords forms:
    z,y,x  -> tile origin (required for img/msk 2D slice)
    region_name -> return mesh for named region
    region_name,depth_idx ->  return 2D polygon for the region at depth_idx (NOT implemented yet)

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
from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class ParsedDataId:
    specimen_id: str
    modality:    str  # img | msk | meh
    view_token:  str  # xy | yz | xz | 3d
    encoding:    Optional[str]
    res_level:   Optional[int]
    channel:     Optional[int]
    pos_index:   str

    def view_type(self) -> Optional[ViewType]:
        # Map new tokens to ViewType enum
        if self.view_token == 'xz':
            return ViewType.HORIZONTAL
        if self.view_token == 'yz':
            return ViewType.SAGITTAL
        if self.view_token == 'xy':
            return ViewType.CORONAL
        if self.view_token == '3d':
            return ViewType.VOLUMETRIC
        return None  # unsupported

    def coords_tuple(self) -> Tuple[int, int, int]:
        parts = self.pos_index.split(',') if self.pos_index else []
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
        # Default to configured data root from settings if not provided
        self.data_root = data_root or settings.data_root_path
        self._specimens_cache: Optional[Dict[str, Any]] = None

    # -------------------- Metadata Loading --------------------
    def load_specimens_metadata(self) -> Dict[str, Any]:
        """Load specimens metadata and cache it.

        The cache is invalidated when the underlying `data_root/specimens` file's
        modification time changes.
        """
        specimens_file = self.data_root / 'specimens'
        if not specimens_file.exists():
            raise FileNotFoundError(f"Specimens metadata file not found: {specimens_file}")

        # Use file mtime to determine whether to reload cache
        try:
            mtime = specimens_file.stat().st_mtime
        except Exception:
            # If stat fails for some reason, fallback to reloading when cache is empty
            mtime = None

        if self._specimens_cache is None or getattr(self, '_specimens_mtime', None) != mtime:
            with open(specimens_file, 'r', encoding='utf-8') as f:
                self._specimens_cache = json.load(f)
            # Store mtime for future invalidation checks
            self._specimens_mtime = mtime
            logger.info("Loaded specimens metadata: %d entries (mtime=%s)", len(self._specimens_cache), mtime)

        return self._specimens_cache

    def get_specimen_meta(self, specimen_id: str) -> Dict[str, Any]:
        meta = self.load_specimens_metadata().get(specimen_id)
        if not meta:
            raise KeyError(f"Specimen {specimen_id} not found in metadata")
        return meta

    def get_regions_metadata(self, specimen_id: str) -> Dict[str, Any]:
        # For now RM009 maps to CIVM atlas path; Use specimen atlas_reference/specimens field.
        specimen_meta = self.get_specimen_meta(specimen_id)
        atlas_ref = specimen_meta.get('atlas_reference', {})
        regions_path = self.data_root / atlas_ref['dir_path'] / atlas_ref['source']['regions']
        if not regions_path.exists():
            raise FileNotFoundError(f"Regions metadata file not found: {regions_path}")
        with open(regions_path, 'r', encoding='utf-8') as f:
            regions_json = json.load(f)
        return regions_json

    # -------------------- data_id Parsing --------------------
    # Accept new multi-char view tokens (xy|yz|xz|3d). Keep legacy single char (c|s|h|3) for backward compatibility.
    _IMAGE_TYPE_RE = re.compile(r'^(?P<mod>img|msk|meh)(?P<view>xy|yz|xz|3d|c|s|h|3)(?:-(?P<enc>[A-Za-z0-9_]+))?$')

    def parse_data_id(self, data_id: str) -> ParsedDataId:
        parts = data_id.split(':')
        if len(parts) != 5:
            raise ValueError("data_id must have 5 colon-separated segments")
        specimen_id, image_type_token, rl_raw, ch_raw, pos_index = parts
        m = self._IMAGE_TYPE_RE.match(image_type_token)
        if not m:
            raise ValueError(f"Invalid image_type format: {image_type_token}")
        return ParsedDataId(
            specimen_id = specimen_id,
            modality    = m.group('mod'),
            view_token  = m.group('view'),
            encoding    = m.group('enc'),
            res_level   = int(rl_raw) if rl_raw.strip() != '' else None,
            channel     = int(ch_raw) if ch_raw.strip() != '' else None,
            pos_index   = pos_index
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

    def _resolve_mesh_path(self, specimen_id: str, region_id: str) -> Path:
        meta = self.get_specimen_meta(specimen_id)
        meshes = meta.get('mesh', {})
        if not meshes:
            raise FileNotFoundError(f"No mesh data for specimen {specimen_id}")
        first_entry = next(iter(meshes.values()))
        rel_source = self.data_root / first_entry['dir_path']
        mesh_path = rel_source / first_entry['source'].get(region_id, None)
        if not mesh_path:
            raise FileNotFoundError(f"No mesh source for region '{region_id}' in specimen {specimen_id}")
        if not mesh_path.exists():
            raise FileNotFoundError(f"Mesh file not found: {mesh_path}")
        return mesh_path

    def get_tile_bytes(self, parsed: ParsedDataId) -> bytes:
        if parsed.modality not in ('img', 'msk'):
            raise ValueError("get_tile_bytes only for img/msk modalities")
        view_type = parsed.view_type()
        if view_type is None:
            raise ValueError("View type required (xy|yz|xz) for img/msk requests")
        if parsed.res_level is None:
            raise ValueError("resolution_level required for img/msk requests")
        if parsed.channel is None and parsed.modality == 'img':
            raise ValueError("channel required for img requests")
        z, y, x = parsed.coords_tuple()
        ims_path = self._resolve_ims_path(parsed.specimen_id, parsed.modality)
        channel = parsed.channel or 0
        tile_size = self._get_tile_size(parsed.specimen_id, parsed.modality)
        with ImarisHandler(ims_path) as h:
            tile = h.get_tile(view_type, parsed.res_level, channel, z, y, x, tile_size=tile_size)
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
        mesh_path = self._resolve_mesh_path(parsed.specimen_id, parsed.pos_index)
        return mesh_path.read_bytes()
