# simple zarr3 reader, that do not user zarr packages
# and tries to maintain a cache of opened files

import os
import time
import json
import math
from pathlib import Path
import logging
from dataclasses import dataclass
from typing import Literal, Tuple, Any
from collections import OrderedDict
import threading
import argparse

import numpy as np
import zarr
from numcodecs import Blosc

UINT64_MAX = np.int64(-1).astype(np.uint64)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(ch)

def coor_to_shard_chunk_index(coor, shard_sz, chunk_sz):
    s_idx = tuple(coor[i] // shard_sz[i] for i in range(len(coor)))
    c_idx = tuple((coor[i] % shard_sz[i]) // chunk_sz[i] for i in range(len(coor)))
    residual = tuple(coor[i] % shard_sz[i] % chunk_sz[i] for i in range(len(coor)))
    return s_idx, c_idx, residual

def IndexFromStartSize(start, size):
    return tuple(slice(start[i], start[i]+size[i]) for i in range(len(start)))

@dataclass(frozen=True)
class ZarrMeta:
    shape: Tuple[int, ...]
    shard_sz: Tuple[int, ...]
    chunk_sz: Tuple[int, ...]
    compressor: Any
    index_array_shape: Tuple[int, ...]
    index_array_bytes: int
    crc_nbytes: int
    dtype: Any
    fill_value: Any

class zarr3_reader:
    def __init__(self, zarr_path: str, max_cache_items: int = 10000):
        self.zarr_path = Path(zarr_path)
        if not self.zarr_path.exists():
            raise FileNotFoundError(f"Zarr path {self.zarr_path} does not exist.")
        if not (self.zarr_path / 'zarr.json').exists():
            raise FileNotFoundError(f"Zarr metadata file {self.zarr_path / 'zarr.json'} does not exist.")
        
        # cache index array, map shard index to index_array
        self._index_array_cache = OrderedDict()
        self._max_cache_items = max_cache_items

        # cache meta, map res_lv to meta
        self._meta_cache = {}
        
        # lock for cache access
        self._lock = threading.RLock()

    def get_zarr_group_meta(self, res_lv: str) -> ZarrMeta:
        # read zarr configuration
        za_meta = json.load(open(self.zarr_path / res_lv / 'zarr.json'))
        dshape       = tuple(za_meta['shape'])
        shard_sz     = tuple(za_meta['chunk_grid']['configuration']['chunk_shape'])
        chunk_sz     = tuple(za_meta['codecs'][0]['configuration']['chunk_shape'])
        chunk_codec  = za_meta['codecs'][0]['configuration']['codecs'][1]
        index_codecs = za_meta['codecs'][0]['configuration']['index_codecs']
        dtype        = np.dtype(za_meta['data_type'])
        fill_value   = za_meta.get('fill_value', 0)

        # currently support only non-compressed index and blosc codec
        if index_codecs[0]["name"] != "bytes":
            raise NotImplementedError(f"Only bytes index codec is supported, got {index_codecs[0]['name']}.")
        if index_codecs[1]["name"] != "crc32c":
            raise NotImplementedError(f"Only crc32c index codec is supported, got {index_codecs[1]['name']}.")
        if chunk_codec["name"] != "blosc":
            raise NotImplementedError(f"Only blosc codec is supported, got {chunk_codec['name']}.")
        chunk_codec['configuration']['shuffle'] = \
            getattr(Blosc, chunk_codec['configuration']['shuffle'].upper())
        compressor = Blosc(**chunk_codec['configuration'])

        index_array_shape = tuple(shard_sz[i]//chunk_sz[i]
                                  for i in range(len(shard_sz))) + (2,)
        index_array_bytes = 8 * int(np.prod(index_array_shape))  # uint64
        crc_nbytes = 4

        return ZarrMeta(
            shape      = dshape,
            shard_sz   = shard_sz,
            chunk_sz   = chunk_sz,
            compressor = compressor,
            index_array_shape = index_array_shape,
            index_array_bytes = index_array_bytes,
            crc_nbytes = crc_nbytes,
            dtype      = dtype,
            fill_value = fill_value,
        )

    def clear_cache(self):
        with self._lock:
            self._index_array_cache.clear()
            self._meta_cache.clear()

    def _get_meta(self, res_lv: str) -> ZarrMeta:
        with self._lock:
            meta = self._meta_cache.get(res_lv)
            if meta is None:
                meta = self.get_zarr_group_meta(res_lv)
                self._meta_cache[res_lv] = meta
            return meta

    def _read_index_array(self, meta, shard_fd):
        # intentionally skip checking file size and crc32c check for performance consideration
        shard_fd.seek(-meta.index_array_bytes-meta.crc_nbytes, os.SEEK_END)
        index_array = np.frombuffer(shard_fd.read(meta.index_array_bytes),
                                    dtype=np.uint64) \
                        .reshape(meta.index_array_shape)
        return index_array

    def _get_index_array(self, meta, shard_fd, shard_key):
        with self._lock:
            index_array = self._index_array_cache.get(shard_key)
            if index_array is not None:
                self._index_array_cache.move_to_end(shard_key)  # mark as recently used
                return index_array
        index_array = self._read_index_array(meta, shard_fd)
        with self._lock:
            self._index_array_cache[shard_key] = index_array
            if len(self._index_array_cache) > self._max_cache_items:
                self._index_array_cache.popitem(last=False)  # remove least recently used item
        return index_array

    def read_chunk(self, res_lv: str, coor: tuple, b_decode: bool = True):
        meta = self._get_meta(res_lv)
        if len(coor) != len(meta.shard_sz):
            raise ValueError(f"Coordinate dimension {len(coor)} does not match data dimension {len(meta.shard_sz)}.")

        s_idx, c_idx, residual = coor_to_shard_chunk_index(coor, meta.shard_sz, meta.chunk_sz)
        if any(r != 0 for r in residual):
            raise NotImplementedError("Reading partial chunks is not supported.")

        shard_path = self.zarr_path.joinpath(res_lv , 'c' , *map(str, s_idx))
        if not shard_path.exists():
            if b_decode:
                return np.full(meta.chunk_sz, meta.fill_value, dtype=meta.dtype)
            return None

        shard_key = (res_lv, s_idx)
        with open(shard_path, 'rb') as shard_fd:
            index_array = self._get_index_array(meta, shard_fd, shard_key)

            offset, nbytes = index_array[tuple(c_idx)]
            if offset == UINT64_MAX and nbytes == UINT64_MAX:
                if b_decode:
                    img = np.full(meta.chunk_sz, meta.fill_value, dtype=meta.dtype)
                else:
                    img = None
            else:
                # intentionally skip checking offset and nbytes for performance consideration
                shard_fd.seek(int(offset), os.SEEK_SET)
                raw_data = shard_fd.read(int(nbytes))
                if b_decode:
                    img = np.frombuffer(meta.compressor.decode(raw_data), dtype=meta.dtype) \
                          .reshape(meta.chunk_sz)
                    # TODO: tolerate_corruption
                else:
                    img = raw_data
        return img

    # TODO: consider batch reading

    def exists_chunk(self, res_lv: str, coor: tuple) -> bool:
        meta = self._get_meta(res_lv)
        if len(coor) != len(meta.shard_sz):
            raise ValueError(f"Coordinate dimension {len(coor)} does not match data dimension {len(meta.shard_sz)}.")

        s_idx, c_idx, residual = coor_to_shard_chunk_index(coor, meta.shard_sz, meta.chunk_sz)
        if any(r != 0 for r in residual):
            raise NotImplementedError("Reading partial chunks is not supported.")

        shard_path = self.zarr_path.joinpath(res_lv , 'c' , *map(str, s_idx))
        if not shard_path.exists():
            return False

        shard_key = (res_lv, s_idx)
        with open(shard_path, 'rb') as shard_fd:
            index_array = self._get_index_array(meta, shard_fd, shard_key)

            offset, nbytes = index_array[tuple(c_idx)]
            if offset == UINT64_MAX and nbytes == UINT64_MAX:
                return False
            else:
                return True

    def validate(self, mode: Literal['full_read', 'size']):
        # validate through transversing all chunks
        for res_lv in self.zarr_path.iterdir():
            if not res_lv.is_dir():
                continue
            meta = self._get_meta(res_lv.name)
            shard_grid = tuple(math.ceil(meta.shape[i]/meta.shard_sz[i])
                            for i in range(len(meta.shard_sz)))
            for s_idx in np.ndindex(shard_grid):
                shard_path = res_lv / 'c' / '/'.join(map(str, s_idx))
                print(f"Validating shard {s_idx}", end='')
                if not shard_path.exists():
                    print(", shard file does not exist, skip.")
                    continue
                t1 = time.time()
                with open(shard_path, 'rb') as shard_fd:
                    index_array = self._get_index_array(meta, shard_fd, (res_lv.name, s_idx))
                    cnt_chunks = 0
                    data_sz = 0
                    for c_idx in np.ndindex(index_array.shape[:-1]):
                        offset, nbytes = index_array[c_idx]
                        if offset == UINT64_MAX and nbytes == UINT64_MAX:
                            continue
                        cnt_chunks += 1
                        if mode == 'size':
                            continue
                        try:
                            shard_fd.seek(int(offset), os.SEEK_SET)
                            raw_data = shard_fd.read(int(nbytes))
                            img = np.frombuffer(meta.compressor.decode(raw_data), dtype=meta.dtype)
                            img = img.reshape(meta.chunk_sz)
                            data_sz += len(raw_data)
                        except Exception as e:
                            logger.error(f"Error reading chunk at shard {s_idx}, chunk {c_idx} in res_lv {res_lv.name}: {e}")
                t2 = time.time()
                if cnt_chunks > 0:
                    print(f", {cnt_chunks} chunks validated in {t2 - t1:.3f} s, total data read {data_sz / (1024*1024):.3f} MB.")
                else:
                    print(f", no chunks to validate.")

def test_zarr3_reader(zarr_path, res_lv, coor):
    t3 = time.time()
    za = zarr.open(zarr_path, mode='r')[res_lv]
    img_zarr = za[IndexFromStartSize(coor, za.chunks)]
    t4 = time.time()
    if not np.any(img_zarr):
        logger.warning("the chunk read by zarr is empty.")

    t1 = time.time()
    cz = zarr3_reader(zarr_path)
    img = cz.read_chunk(res_lv, coor)
    t2 = time.time()

    assert np.all(img == img_zarr)

    print("  read successfully using zarr3_reader.")
    print(f"  zarr3_reader read time: {t2 - t1:.3f} s")
    print(f"  zarr read time: {t4 - t3:.3f} s")

def read_whole_test(zarr_path):
    cz = zarr3_reader(zarr_path)
    cz.validate(mode='full_read')

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Utility for reading/testing custom Zarr v3 filesystem layout"
    )
    parser.add_argument("--data-root", type=Path, default=Path("./data"),
                        help="Root directory that contains the dataset (default: ./data)")
    parser.add_argument("--zarr-rel", type=str,
                        default="macaque_brain/RM009/VISoR/RM009.vsr/visor_projn_images/xyy_xy_20251004.zarr",
                        help="Relative path (from data-root) to the target .zarr directory")
    parser.add_argument("--mode", choices=["whole", "test"], default="test",
                        help="Operation mode: 'whole' = traverse & validate all chunks, 'test' = read a single chunk (default: whole)")
    parser.add_argument("--res-lv", type=int, default=0, help="Resolution level to read for test mode (default: 0)")
    parser.add_argument("--channel", type=int, default=0, help="Channel index for test mode (default: 0)")
    parser.add_argument("--coord", nargs=3, type=int, metavar=("Z", "Y", "X"),
                        help="Starting voxel coordinate (Z Y X) for the chunk in test mode. If omitted, uses (0,0,0)")
    parser.add_argument("--fallback-demo", action="store_true",
                        help="If --coord not provided, use the previous demo coordinate heuristic instead of (0,0,0)")
    return parser.parse_args()


def main():
    args = _parse_args()
    data_root = args.data_root
    zarr_path = data_root / args.zarr_rel

    if args.mode == "whole":
        logger.info(f"Running whole-dataset validation on {zarr_path}")
        read_whole_test(zarr_path)
        return

    # test mode
    res_lv = args.res_lv
    c = args.channel
    if args.coord is not None:
        zyx = tuple(args.coord)
    else:
        if args.fallback_demo:
            # retain previous demo heuristic (dataset specific) but guarded behind flag
            zyx = (
                300 * 128 // 20,
                60000 // 2 // 512 * 512,
                70000 // 2 // 512 * 512,
            )
        else:
            zyx = (0, 0, 0)

    logger.info(f"Testing single chunk at (channel={c}, z={zyx[0]}, y={zyx[1]}, x={zyx[2]}) in res_lv={res_lv}")
    test_zarr3_reader(zarr_path, str(res_lv), (c, *zyx))


if __name__ == "__main__":
    main()