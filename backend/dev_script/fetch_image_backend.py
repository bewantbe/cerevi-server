#!/usr/bin/env python3
# Copied from old_cerevi/backend/dev_script (no logic changes)

import sys
from pathlib import Path
import time
import numpy as np

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.tile_service import TileService  # noqa: E402
from app.models.specimen import ViewType  # noqa: E402
from app.services.imaris_handler import ImarisHandler  # noqa: E402
from app.config import settings  # noqa: E402


def read_save_ims_backend(specimen_id, view, level, channel, z, y, x, tile_size):
    print(f"Fetching image tile using backend TileService...")
    print(f"Parameters: specimen={specimen_id}, view={view}, level={level}, channel={channel}, z={z}, y={y}, x={x}")
    try:
        tile_service = TileService()
        image_path = settings.get_image_path(specimen_id)
        with ImarisHandler(image_path) as handler:
            raw_tile_data = handler.get_tile(view, level, channel, z, y, x, tile_size)
            tile_flipped = raw_tile_data[::-1, :]
        print("\nRaw Tile Pixel Statistics (before JPEG conversion):")
        print(f"  Mean: {np.mean(tile_flipped):.2f}")
        print(f"  Std:  {np.std(tile_flipped):.2f}")
        print(f"  Min:  {np.min(tile_flipped):.2f}")
        print(f"  Max:  {np.max(tile_flipped):.2f}")
        print(f"  Shape: {tile_flipped.shape}")
        print(f"  Dtype: {tile_flipped.dtype}")
        start_time = time.time()
        image_bytes = tile_service.extract_image_tile(
            specimen_id=specimen_id,
            view=view,
            level=level,
            channel=channel,
            z=z,
            y=y,
            x=x,
            tile_size=tile_size
        )
        elapsed_time = time.time() - start_time
        print(f"  Tile extraction time: {elapsed_time:.3f} seconds")
        out_dir = backend_dir / "tmp"
        out_dir.mkdir(exist_ok=True)
        output_path = out_dir / f"image_backend_{specimen_id}_{view}_l{level}_c{channel}_z{z}_y{y}_x{x}.jpg"
        with open(output_path, 'wb') as f:
            f.write(image_bytes)
        print(f"✓ Image saved successfully: {output_path}")
        print(f"  Image size: {len(image_bytes)} bytes")
        image_info = tile_service.get_image_info(specimen_id)
        print("tile_service.get_image_info(specimen_id)")
        print(f"  Image dimensions: {image_info['dimensions']}")
        print(f"  Available channels: {list(image_info['channels'].keys())}")
        print(f"  Resolution levels: {image_info['resolution_levels']}")
    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
        return 1
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return 1
    return 0


def main():
    params = [
        {"specimen_id": "macaque_brain_rm009", "view": ViewType.CORONAL, "level": 4, "z": 256, "y": 0, "x": 0, "channel": 0, "tile_size": 512},
        {"specimen_id": "macaque_brain_rm009", "view": ViewType.SAGITTAL, "level": 4, "z": 0, "y": 0, "x": 224, "channel": 0, "tile_size": 512},
        {"specimen_id": "macaque_brain_rm009", "view": ViewType.HORIZONTAL, "level": 4, "z": 0, "y": 192, "x": 0, "channel": 0, "tile_size": 512},
        {"specimen_id": "macaque_brain_rm009", "view": ViewType.CORONAL, "level": 0, "z": 3200, "y": 3200, "x": 3200, "channel": 0, "tile_size": 512},
    ]
    for pm in params:
        if read_save_ims_backend(**pm) != 0:
            return 1
        print("\n" + "=" * 50 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
