"""In-process smoke test, no server. Run: env DATA_MODE=snapshot PYTHONPATH=. python deploy/smoke_test.py"""
import time

from fastapi.testclient import TestClient

import main

c = TestClient(main.app)
BOX = {"min_lon": 81.30, "max_lon": 81.31, "min_lat": 21.16, "max_lat": 21.17}
OUT = {"min_lon": 77.20, "max_lon": 77.21, "min_lat": 28.60, "max_lat": 28.61}

for name, body in (("inside#1", BOX), ("inside#2", BOX), ("outside", OUT)):
    t = time.perf_counter()
    r = c.post("/analyzeArea", json=body)
    ms = (time.perf_counter() - t) * 1000
    j = r.json()
    print(name, r.status_code, r.headers.get("x-cache"),
          f"{ms:.0f}ms", j.get("data_source") or j.get("detail"))
    if r.status_code == 200:
        ponds = j["data"]["recommended_ponds"]
        print("  ponds:", len(ponds))
        if ponds:
            print("  first:", ponds[0])
print("health", c.get("/health").json())
print("metrics", c.get("/metrics").json())
