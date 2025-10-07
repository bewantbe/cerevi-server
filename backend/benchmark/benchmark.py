import time
import numpy as np
import requests

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

def throughtput_benchmark(url, n_req):
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
    base_url = "http://localhost:8000/data/"
    res_lv = 0
    c = 0
    zyx = (300*128//20, 60000//2//512*512, 70000//2//512*512)
    url = f"{base_url}RM009:imgxy:{res_lv}:{c}:{zyx[0]},{zyx[1]},{zyx[2]}"
    sanity_check(url)
    throughtput_benchmark(url, 100)