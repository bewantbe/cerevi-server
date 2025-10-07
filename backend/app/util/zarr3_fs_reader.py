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
    s_idx = tuple(coor[i] // shard_sz[i] for i in range(len(coor)))
    c_idx = tuple((coor[i] % shard_sz[i]) // chunk_sz[i] for i in range(len(coor)))
    resedual = tuple(coor[i] % shard_sz[i] % chunk_sz[i] for i in range(len(coor)))
    #for i in range(len(coor)):
    #    assert shard_sz[i]*s_idx[i] + chunk_sz[i]*c_idx[i] + resedual[i] == coor[i]
    return s_idx, c_idx, resedual

def IndexFromStartSize(start, size):
    return tuple(slice(start[i], start[i]+size[i]) for i in range(len(start)))

class zarr3_reader:
    def __init__(self, zarr_path: str):
        self.zarr_path = Path(zarr_path)
        if not self.zarr_path.exists():
            raise FileNotFoundError(f"Zarr path {self.zarr_path} does not exist.")
        if not (self.zarr_path / 'zarr.json').exists():
            raise FileNotFoundError(f"Zarr metadata file {self.zarr_path / 'zarr.json'} does not exist.")

        # read zarr configuration
        self.za_meta = json.load(open(self.zarr_path / '0' / 'zarr.json'))
        self.shard_sz     = self.za_meta['chunk_grid']['configuration']['chunk_shape']
        self.chunk_sz     = self.za_meta['codecs'][0]['configuration']['chunk_shape']
        self.chunk_codec  = self.za_meta['codecs'][0]['configuration']['codecs'][1]
        self.index_codecs = self.za_meta['codecs'][0]['configuration']['index_codecs']
        self.dtype        = np.dtype(self.za_meta['data_type'])
        self.fill_value   = self.za_meta.get('fill_value', 0)

        # currently support only non-compressed index and blosc codec
        assert self.index_codecs[0]["name"] == "bytes"
        assert self.index_codecs[1]["name"] == "crc32c"
        assert self.chunk_codec["name"] == "blosc"
        self.chunk_codec['configuration']['shuffle'] = \
            getattr(Blosc, self.chunk_codec['configuration']['shuffle'].upper())
        self.compressor = Blosc(**self.chunk_codec['configuration'])

        self.index_array_shape = [self.shard_sz[i]//self.chunk_sz[i] for i in range(4)] + [2]
        self.index_array_bytes = 8 * np.prod(self.index_array_shape)  # uint64
        self.crc_nbytes = 4

        # cache of opened shard files
        # self.opened_files = {}

    #def get_za_meta(self, res_lv: str):

    def read_chunk(self, res_lv: str, coor: tuple, b_decode: bool = True):
        s_idx, c_idx, resedual = get_shard_chunk_index_from(coor, self.shard_sz, self.chunk_sz)
        assert all(r == 0 for r in resedual), "Only support reading full chunks."

        f_shard_path = self.zarr_path.joinpath(res_lv , 'c' , *map(str, s_idx))

        with open(f_shard_path, 'rb') as fd:
            fd.seek(-self.index_array_bytes-self.crc_nbytes, os.SEEK_END)
            index_array = np.frombuffer(fd.read(self.index_array_bytes),
                                        dtype=np.uint64) \
                          .reshape(self.index_array_shape)
            offset, nbytes = index_array[tuple(c_idx)]
            if offset == UINT64_MAX and nbytes == UINT64_MAX:
                if b_decode:
                    img = np.full(self.chunk_sz, self.fill_value, dtype=self.dtype)
                else:
                    img = None
            else:
                fd.seek(offset, os.SEEK_SET)
                raw_data = fd.read(nbytes)
                if b_decode:
                    img = np.frombuffer(self.compressor.decode(raw_data), dtype=self.dtype) \
                        .reshape(self.chunk_sz)
                else:
                    img = raw_data
        return img

def test_zarr3_reader(zarr_path, res_lv, coor):
    t1 = time.time()
    cz = zarr3_reader(zarr_path)
    img = cz.read_chunk(res_lv, coor)
    t2 = time.time()
    assert np.any(img)

    t3 = time.time()
    za = zarr.open(zarr_path, mode='r')[res_lv]
    img_zarr = za[IndexFromStartSize(coor, za.chunks)]
    t4 = time.time()
    assert np.any(img_zarr)

    assert np.all(img == img_zarr)

    print("  read successfully using zarr3_reader.")
    print(f"  zarr3_reader read time: {t2 - t1:.3f} s")
    print(f"  zarr read time: {t4 - t3:.3f} s")

if __name__ == "__main__":
    data_root = Path('./data')
    zarr_path = data_root / "macaque_brain/RM009/VISoR/RM009.vsr/visor_projn_images/xyy_xy_20251004.zarr"
    res_lv = 0
    c = 0
    zyx = (300*128//20, 60000//2//512*512, 70000//2//512*512)
    test_zarr3_reader(zarr_path, str(res_lv), (c, *zyx))