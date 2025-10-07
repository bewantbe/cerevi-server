import time
import numpy as np
import requests
import zarr
from pathlib import Path
import argparse

def sanity_check(url):
    r1 = requests.get(url)
    img1 = np.frombuffer(r1.content, dtype=np.float16).reshape((512,512))
    sp = url.split(",")
    url2 = ",".join(sp[:-1] + [str(int(sp[-1]) + 256)])
    r2 = requests.get(url2)
    img2 = np.frombuffer(r2.content, dtype=np.float16).reshape((512,512))
    print("Sanity check for two adjacent tiles...")
    print("   ", url)
    print("   ", url2)
    assert np.any(img1)
    assert np.all(img1[:,256:] == img2[:,:256])
    print("Sanity check passed.")

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