# simple zarr3 reader, that do not user zarr packages
# and tries to maintain a cache of opened files

import os
import time
import math
import itertools
import json
from pathlib import Path
import argparse
import logging

import requests
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

def get_shard_chunk_index_from(coor, shard_sz, chunk_sz):
    s_idx = (coor[0] // shard_sz[0],
             coor[1] // shard_sz[1],
             coor[2] // shard_sz[2],
             coor[3] // shard_sz[3])
    c_idx = ((coor[0] % shard_sz[0]) // chunk_sz[0],
             (coor[1] % shard_sz[1]) // chunk_sz[1],
             (coor[2] % shard_sz[2]) // chunk_sz[2],
             (coor[3] % shard_sz[3]) // chunk_sz[3])
    resedual = (coor[0] % shard_sz[0] % chunk_sz[0],
                coor[1] % shard_sz[1] % chunk_sz[1],
                coor[2] % shard_sz[2] % chunk_sz[2],
                coor[3] % shard_sz[3] % chunk_sz[3])
    assert shard_sz[0]*s_idx[0] + chunk_sz[0]*c_idx[0] + resedual[0] == coor[0]
    assert shard_sz[1]*s_idx[1] + chunk_sz[1]*c_idx[1] + resedual[1] == coor[1]
    assert shard_sz[2]*s_idx[2] + chunk_sz[2]*c_idx[2] + resedual[2] == coor[2]
    assert shard_sz[3]*s_idx[3] + chunk_sz[3]*c_idx[3] + resedual[3] == coor[3]
    return s_idx, c_idx, resedual

def IndexFromStartSize(start, size):
    return tuple(slice(start[i], start[i]+size[i]) for i in range(len(start)))

class zarr3_reader:
    def __init__(self, zarr_path: str):
        self.zarr = zarr.open(zarr_path, mode="r")
        self.shape = self.zarr.shape
        self.chunk_shape = self.zarr.chunks
        self.dtype = self.zarr.dtype

def test_of_concept(zarr_path, res_lv, coor):
    zarr_path = Path(zarr_path)
    print(f"Testing zarr path {zarr_path}")
    
    if not zarr_path.exists():
        raise FileNotFoundError(f"Zarr path {zarr_path} does not exist.")
    if not (zarr_path / 'zarr.json').exists():
        raise FileNotFoundError(f"Zarr metadata file {zarr_path / 'zarr.json'} does not exist.")

    # read zarr configuration
    t1 = time.time()
    za_meta = json.load(open(zarr_path / res_lv / 'zarr.json'))
    t2 = time.time()
    logger.debug(f"  Zarr metadata read time: {t2 - t1:.3f} s")
    chunk_sz    = za_meta['codecs'][0]['configuration']['chunk_shape']
    shard_sz  = za_meta['chunk_grid']['configuration']['chunk_shape']
    shard_index_codecs  = za_meta['codecs'][0]['configuration']['index_codecs']
    chunk_codec_meta = za_meta['codecs'][0]['configuration']['codecs'][1]
    assert shard_index_codecs[0]["name"] == "bytes"
    assert shard_index_codecs[1]["name"] == "crc32c"
    assert chunk_codec_meta["name"] == "blosc"
    chunk_codec_meta['configuration']['shuffle'] = \
        getattr(Blosc, chunk_codec_meta['configuration']['shuffle'].upper())
    compressor = Blosc(**chunk_codec_meta['configuration'])
    dtype = np.dtype(za_meta['data_type'])

    # compute index for shard and chunk
    s_idx, c_idx, resedual = get_shard_chunk_index_from(coor, shard_sz, chunk_sz)

    # prepare reading index array
    index_array_shape = [shard_sz[i]//chunk_sz[i] for i in range(4)] + [2]
    index_array_bytes = 8 * np.prod(index_array_shape)  # uint64
    crc_n_bytes = 4
    #s_morton_idx = encode_morton(c_idx, chunk_sz)

    # shard file path
    f_shard_path = zarr_path / res_lv / 'c' / \
        f'{s_idx[0]}' / f'{s_idx[1]}' / f'{s_idx[2]}' / f'{s_idx[3]}'
    logger.debug(f"  Reading from shard file: {f_shard_path}")
    logger.debug(f"  inner index: {c_idx}, residual: {resedual};"
                 f"  indexing array nbytes: {index_array_bytes}")

    t3 = time.time()
    logger.debug(f"  metadata parse time: {t3 - t2:.3f} s")

    # the index array is stored at the end of shard data
    with open(f_shard_path, 'rb') as fd:
        fd.seek(-index_array_bytes-crc_n_bytes, os.SEEK_END)
        index_array = np.frombuffer(fd.read(index_array_bytes),
                                    dtype=np.uint64) \
                      .reshape(index_array_shape)
        logger.debug(f"  inner offset: {index_array[tuple(c_idx)][0]},"
                     f" nbytes: {index_array[tuple(c_idx)][1]}")
        t4 = time.time()
        logger.debug(f"  index array read time: {t4 - t3:.3f} s")
        offset, nbytes = index_array[tuple(c_idx)]
        if offset == UINT64_MAX and nbytes == UINT64_MAX:
            img = np.zeros(chunk_sz, dtype=dtype)
        # read the chunk
        fd.seek(offset, os.SEEK_SET)
        raw_data = fd.read(nbytes)
        img = np.frombuffer(compressor.decode(raw_data), dtype=dtype) \
            .reshape(chunk_sz)
        assert np.any(img)
    
    t5 = time.time()
    logger.debug(f"  chunk read time: {t5 - t4:.3f} s")

    # verify using zarr
    za = zarr.open(zarr_path, mode='r')[res_lv]
    img_zarr = za[IndexFromStartSize(coor, chunk_sz)]
    t6 = time.time()
    logger.debug(f"  Zarr read time: {t6 - t5:.3f} s")
    #print("  direct read: size =", img.shape, " dtype =", img.dtype)
    #print(img)
    #print("  zarr read  : size =", img_zarr.shape, " dtype =", img_zarr.dtype)
    #print(img_zarr)
    assert np.all(img == img_zarr)
    print("  read successfully and verified.")

if __name__ == "__main__":
    data_root = Path('./data')
    zarr_path = data_root / "macaque_brain/RM009/VISoR/RM009.vsr/visor_projn_images/xyy_xy_20251004.zarr"
    res_lv = 0
    c = 0
    zyx = (300*128//20, 60000//2//512*512, 70000//2//512*512)
    test_of_concept(zarr_path, str(res_lv), (c, *zyx))