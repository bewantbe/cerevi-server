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
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(ch)

def sanity_check(url):
    r1 = requests.get(url)
    img1 = np.frombuffer(r1.content, dtype=np.float16).reshape((512,512))
    sp = url.split(",")
    url2 = ",".join(sp[:-1] + [str(int(sp[-1]) + 256)])
    r2 = requests.get(url2)
    img2 = np.frombuffer(r2.content, dtype=np.float16).reshape((512,512))
    logger.debug("Sanity check for two adjacent tiles...")
    logger.debug("   %s", url)
    logger.debug("   %s", url2)
    assert np.any(img1)
    assert np.all(img1[:,256:] == img2[:,:256])
    print("Sanity check passed.")

# from https://github.com/zarr-developers/zarr-python/blob/main/src/zarr/core/indexing.py
def decode_morton(z: int, chunk_shape: tuple[int, ...]) -> tuple[int, ...]:
    # Inspired by compressed morton code as implemented in Neuroglancer
    # https://github.com/google/neuroglancer/blob/master/src/neuroglancer/datasource/precomputed/volume.md#compressed-morton-code
    bits = tuple(math.ceil(math.log2(c)) for c in chunk_shape)
    max_coords_bits = max(bits)
    input_bit = 0
    input_value = z
    out = [0] * len(chunk_shape)

    for coord_bit in range(max_coords_bits):
        for dim in range(len(chunk_shape)):
            if coord_bit < bits[dim]:
                bit = (input_value >> input_bit) & 1
                out[dim] |= bit << coord_bit
                input_bit += 1
    return tuple(out)

# from AI
def encode_morton(coords: tuple[int, ...], chunk_shape: tuple[int, ...]) -> int:
    """
    Inverse of decode_morton: interleave the bits of coords (LSB-first per coordinate)
    in the same order decode_morton reads them, producing an integer z.
    """
    if len(coords) != len(chunk_shape):
        raise ValueError("coords and chunk_shape must have same length")
    bits = tuple(math.ceil(math.log2(c)) if c > 1 else 1 for c in chunk_shape)
    max_coords_bits = max(bits)
    z = 0
    out_bit = 0
    for coord_bit in range(max_coords_bits):
        for dim in range(len(coords)):
            if coord_bit < bits[dim]:
                bit = (coords[dim] >> coord_bit) & 1
                z |= (bit << out_bit)
                out_bit += 1
    return z

def test_morton_indexing():
    shape = (15, 256,256)
    for coords in itertools.product(*(range(s) for s in shape)):
        z = encode_morton(coords, shape)
        assert decode_morton(z, shape) == coords

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

def fs_extreme_throughput_benchmark(zarr_path, res_lv, coor, n_req):
    zarr_path = Path(zarr_path)
    # for zarr 3 with group
    print(f"Throughput benchmark: {n_req} requests to {zarr_path}")
    
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
        data_size = 0
        for i in range(n_req):
            offset, nbytes = index_array[tuple(c_idx)]
            if offset == UINT64_MAX and nbytes == UINT64_MAX:
                img = np.zeros(chunk_sz, dtype=dtype)
            # read the chunk
            fd.seek(offset, os.SEEK_SET)
            raw_data = fd.read(nbytes)
            img = np.frombuffer(compressor.decode(raw_data), dtype=dtype) \
                .reshape(chunk_sz)
            assert np.any(img)
            data_size += img.nbytes / (1024 * 1024)  # in MB
            if (i + 1) % 10 == 0:
                print(f"   Completed {i + 1} requests...")
    
    t5 = time.time()
    logger.debug(f"  chunk read time: {t5 - t4:.3f} s")
    dt = t5 - t3
    print(f"Speed: {data_size / dt:.3f} MiB/s, {n_req / dt:.2f} req/s")

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

    """
    data_size = 0
    t0 = time.time()
    for i in range(n_req):
        raw_data = f_shard_path.read_bytes()
        data_size += len(raw_data) / (1024 * 1024)  # in MB
        if (i + 1) % 10 == 0:
            print(f"   Completed {i + 1} requests...")
    t1 = time.time()
    dt = t1 - t0
    print(f"Speed: {data_size / dt:.3f} MiB/s, {n_req / dt:.2f} req/s")
    """

def local_throughtput_benchmark(zarr_path, res_lv, coor, n_req):
    print(f"Throughput benchmark: {n_req} requests to {zarr_path}")
    img_sz = (512, 512)
    za = zarr.open(zarr_path, mode='r')[res_lv]
    data_size = 0
    t0 = time.time()
    for i in range(n_req):
        img = za[coor[0], coor[1], coor[2]:coor[2]+img_sz[0], coor[3]:coor[3]+img_sz[1]]
        data_size += img.nbytes / (1024 * 1024)  # in MB
        if (i + 1) % 10 == 0:
            print(f"   Completed {i + 1} requests...")
    t1 = time.time()
    dt = t1 - t0
    print(f"Speed: {data_size / dt:.3f} MiB/s, {n_req / dt:.2f} req/s")

def net_throughtput_benchmark(url, n_req):
    print(f"Throughput benchmark: {n_req} requests to {url}")
    data_size = 0
    t0 = time.time()
    for i in range(n_req):
        r = requests.get(url)
        r.raise_for_status()
        data_size += len(r.content) / (1024 * 1024)  # in MB
        if (i + 1) % 10 == 0:
            print(f"   Completed {i + 1} requests...")
    t1 = time.time()
    dt = t1 - t0
    print(f"Speed: {data_size / dt:.3f} MiB/s, {n_req / dt:.2f} req/s")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark zarr and network for cerevi project")
    parser.add_argument("--base-url", default="http://localhost:8000/data/",
                        help="Base URL for network requests (default: http://localhost:8000/data/)")
    parser.add_argument("--data-root", default="./data",
                        help="Path to local data root (default: ./data)")
    parser.add_argument("--n-req", type=int, default=10,
                        help="Number of requests to perform for each benchmark (default: 100)")
    args = parser.parse_args()

    base_url = args.base_url
    res_lv = 0
    c = 0
    zyx = (300*128//20, 60000//2//512*512, 70000//2//512*512)
    url = f"{base_url}RM009:imgxy:{res_lv}:{c}:{zyx[0]},{zyx[1]},{zyx[2]}"
    sanity_check(url)
    net_throughtput_benchmark(url, args.n_req)

    data_root = Path(args.data_root)
    zarr_path = data_root / "macaque_brain/RM009/VISoR/RM009.vsr/visor_projn_images/xyy_xy_20251004.zarr"
    local_throughtput_benchmark(zarr_path, str(res_lv), (c, *zyx), args.n_req)

    fs_extreme_throughput_benchmark(zarr_path, str(res_lv), (c, *zyx), args.n_req)