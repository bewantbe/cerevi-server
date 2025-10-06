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
import numpy as np

import PIL.Image
from io import BytesIO
import h5py
import zarr

from ..models.specimen import ViewType
from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class ParsedDataId:
    specimen_id: str
    modality:    str  # img | msk | meh
    view_type:   str  # xy | yz | xz | 3d
    encoding:    Optional[str]
    res_level:   Optional[int]
    channel:     Optional[int]
    pos_index:   str

    def view_explain(self) -> Optional[ViewType]:
        # Map new tokens to ViewType enum
        if self.view_type == 'xz':
            return ViewType.HORIZONTAL
        if self.view_type == 'yz':
            return ViewType.SAGITTAL
        if self.view_type == 'xy':
            return ViewType.CORONAL
        if self.view_type == '3d':
            return ViewType.VOLUMETRIC
        return None  # unsupported

    def index_tuple(self) -> Tuple[int, int, int]:
        parts = self.pos_index.split(',') if self.pos_index else []
        if len(parts) != 3:
            raise ValueError("coords must be z,y,x for img/msk requests")
        try:
            z, y, x = (int(p) for p in parts)
        except ValueError as e:
            raise ValueError("coords values must be integers") from e
        return z, y, x

def FirstValue(d: Dict[str, Any]) -> Any:
    """Helper to get the first value from a dict, or None if empty."""
    if not d:
        return None
    return next(iter(d.values()))

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
        atlas_ref = specimen_meta.get('atlas_reference')
        if atlas_ref is None:
            raise ValueError(f"Specimen {specimen_id} has no valid atlas reference")
        atlas_meta = self.get_specimen_meta(atlas_ref)
        data_provider = FirstValue(atlas_meta['regions'])["data_provider"]
        regions_path = self.data_root / data_provider["pathes"][data_provider['region_list'][0][0]]
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
        modality    = m.group('mod')
        encoding    = m.group('enc')
        if encoding is None:
            if modality == 'img':
                encoding = 'raw'  # default for img
            elif modality == 'msk':
                encoding = 'png'  # default for msk
            elif modality == 'meh':
                encoding = 'obj'  # default for meh
        return ParsedDataId(
            specimen_id = specimen_id,
            modality    = modality,
            view_type   = m.group('view'),
            encoding    = encoding,
            res_level   = int(rl_raw) if rl_raw.strip() != '' else None,
            channel     = int(ch_raw) if ch_raw.strip() != '' else None,
            pos_index   = pos_index
        )

    # -------------------- Tile / Mesh Serving --------------------
    def _resolve_image_path(self, specimen_id: str, modality: str, view_type: str,
                            res_level: int, channel: int) -> Path:
        meta = self.get_specimen_meta(specimen_id)
        if modality == 'img':
            images = meta.get('image', {})
        elif modality == 'msk':
            images = meta.get('region_mask', {})
        else:
            raise ValueError("_resolve_ims_path only supports img/msk")
        if not images:
            raise FileNotFoundError(f"No {'image' if modality=='img' else 'region_mask'} data for specimen {specimen_id}")
        first_entry = FirstValue(images)
        data_provider = first_entry.get('data_provider')
        pathes = data_provider.get('pathes', [])
        ok = False
        # find which file provides the requested view_type, res_level, channel
        for fidx, res_lv_list, ch_list in data_provider.get(view_type, []):
            if (res_level in res_lv_list) and (channel in ch_list):
                ok = True
                break
        if not ok:
            raise FileNotFoundError(f"No matching {modality} data for view '{view_type}' at level {res_level} channel {channel} in specimen {specimen_id}")
        img_path = self.data_root / pathes[fidx]
        if not img_path.exists():
            raise FileNotFoundError(f"File not found: {img_path}")
        res_lv_idx = res_lv_list.index(res_level)
        if img_path.suffix == '.zarr':
            param = (str(res_lv_idx), channel)
        elif img_path.suffix == '.ims':
            param = ('DataSet', f'ResolutionLevel {res_lv_idx}', 'TimePoint 0', f'Channel {channel}', 'Data')
        else:
            raise ValueError(f"Unsupported image file format: {img_path.suffix}")
        return img_path, param

    def _get_tile_size(self, specimen_id: str, modality: str, view_type: str) -> int:
        meta = self.get_specimen_meta(specimen_id)
        if modality == 'img':
            images = meta.get('image', {})
        else:
            images = meta.get('region_mask', {})
        if not images:
            raise FileNotFoundError(f"No {'image' if modality=='img' else 'region_mask'} data for specimen {specimen_id}")
        first_entry = FirstValue(images)
        # Try tile_size_2d first element; fall back to 512
        if view_type == '3d':
            return first_entry.get('tile_size_3d')
        elif view_type in ('xy', 'yz', 'xz'):
            return first_entry.get('tile_size_2d')
        else:
            raise ValueError("Invalid view_type for tile size")

    def _read_tile(self, img_path: Path, view_type: str, param: Tuple) -> np.ndarray:
        zyx = param[-2]
        tile_size_0 = param[-1]
        if view_type == "xy":
            tile_size = (1, tile_size_0[0], tile_size_0[1])
            roi = [slice(zyx[i], zyx[i] + tile_size[i]) for i in range(3)]
            roi[0] = zyx[0]
        elif view_type == "yz":
            tile_size = (tile_size_0[0], tile_size_0[1], 1)
            roi = [slice(zyx[i], zyx[i] + tile_size[i]) for i in range(3)]
            roi[2] = zyx[2]
        elif view_type == "xz":
            tile_size = (tile_size_0[0], 1, tile_size_0[1])
            roi = [slice(zyx[i], zyx[i] + tile_size[i]) for i in range(3)]
            roi[1] = zyx[1]
        elif view_type == "3d":
            tile_size = tile_size_0
            roi = [slice(zyx[i], zyx[i] + tile_size[i]) for i in range(3)]
        else:
            raise ValueError(f"Unsupported view_type: {view_type}")
        #print(f"Reading tile from {img_path} at {roi} for view {view_type}")
        if img_path.suffix == '.ims':
            with h5py.File(img_path, 'r') as h5f:
                harray = h5f[param[0]][param[1]][param[2]][param[3]][param[4]]
                tile = harray[tuple(roi)]
        elif img_path.suffix == '.zarr':
            zf = zarr.open(img_path, mode='r')
            za = zf[param[0]]
            tile = za[param[1], *roi]
        else:
            raise ValueError(f"Unsupported image file format: {img_path.suffix}")
        return tile

    def get_tile_bytes(self, parsed: ParsedDataId) -> bytes:
        if parsed.modality not in ('img', 'msk'):
            raise ValueError("get_tile_bytes only for img/msk modalities")
        view_type = parsed.view_explain()
        if view_type is None:
            raise ValueError("View type required (xy|yz|xz) for img/msk requests")
        if parsed.res_level is None:
            raise ValueError("resolution_level required for img/msk requests")
        if parsed.channel is None and parsed.modality == 'img':
            raise ValueError("channel required for img requests")
        channel = parsed.channel
        z, y, x = parsed.index_tuple()
        tile_size = self._get_tile_size(parsed.specimen_id, parsed.modality, parsed.view_type)
        img_path, param = self._resolve_image_path(parsed.specimen_id, parsed.modality,
                                                   parsed.view_type, parsed.res_level, channel)
        tile = self._read_tile(img_path, parsed.view_type, param + ((z,y,x), tile_size))
        if parsed.modality == 'img':
            if not parsed.encoding == 'raw':
                raise ValueError("Only raw encoding supported for img")
            img = np.clip(tile - 100, 0, 65500)          # remove background
            img_fp32 = img.astype(np.float32)
            img_fp16 = img_fp32.astype(np.float16)
            return img_fp16.tobytes()
        elif parsed.modality == 'msk':
            if not parsed.encoding == 'png':
                raise ValueError("Only PNG encoding supported for msk")
            # For mask, we assume PNG encoding; tile is uint16 labels
            # Convert to uint8 for PNG (may lose some labels if >255)
            assert tile.dtype == np.uint8
            msk_uint8 = tile
            img_pil = PIL.Image.fromarray(msk_uint8, mode='P')
            with BytesIO() as output:
                img_pil.save(output, format="PNG")
                return output.getvalue()
        else:
            raise ValueError("Unsupported modality in get_tile_bytes")

    def _resolve_mesh_path(self, specimen_id: str, region_id: str) -> Path:
        meta = self.get_specimen_meta(specimen_id)
        meshes = meta.get('mesh', {})
        if not meshes:
            raise FileNotFoundError(f"No mesh data for specimen {specimen_id}")
        first_entry = FirstValue(meshes)
        data_provider = first_entry.get('data_provider')
        mesh_pathes = data_provider.get('pathes', [])
        view_types = '3d'
        ok = False
        for fidx, res_lv, region_list in data_provider.get(view_types, []):
            if region_id in region_list:
                ok = True
                break
        if not ok:
            raise FileNotFoundError(f"Region '{region_id}' not found in mesh data for specimen {specimen_id}")
        mesh_path = self.data_root / mesh_pathes[fidx]
        if not mesh_path:
            raise FileNotFoundError(f"No mesh source for region '{region_id}' in specimen {specimen_id}")
        if not mesh_path.exists():
            raise FileNotFoundError(f"Mesh file not found: {mesh_path}")
        return mesh_path

    def get_mesh_bytes(self, parsed: ParsedDataId) -> bytes:
        mesh_path = self._resolve_mesh_path(parsed.specimen_id, parsed.pos_index)
        return mesh_path.read_bytes()
