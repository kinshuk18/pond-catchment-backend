#!/usr/bin/env python3
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000"

BBOXES = [
    (81.05, 81.09, 21.05, 21.09),
    (81.23, 81.27, 21.05, 21.09),
    (81.41, 81.45, 21.05, 21.09),
    (81.59, 81.63, 21.05, 21.09),
    (81.77, 81.81, 21.05, 21.09),
    (81.05, 81.09, 21.33, 21.37),
    (81.23, 81.27, 21.33, 21.37),
    (81.41, 81.45, 21.33, 21.37),
    (81.59, 81.63, 21.33, 21.37),
    (81.77, 81.81, 21.33, 21.37),
    (81.05, 81.09, 21.61, 21.65),
    (81.23, 81.27, 21.61, 21.65),
    (81.41, 81.45, 21.61, 21.65),
    (81.59, 81.63, 21.61, 21.65),
    (81.77, 81.81, 21.61, 21.65),
]

LAND_USES = [
    "forest_good_cover",
    "pasture_fair",
    "row_crop_contoured",
    "fallow_bare_soil",
]

COUNTS = {}
CACHE_HEADERS = {}
LATENCIES_MS = []
LOCK = threading.Lock()
BURST_THREADS = int(os.getenv("BURST_THREADS", "24"))


def send(req):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            headers = dict(response.headers.items())
            return response.status, body, headers, (time.perf_counter() - started) * 1000.0
    except urllib.error.HTTPError as exc:
        headers = dict(exc.headers.items()) if exc.headers is not None else {}
        return exc.code, exc.read().decode("utf-8", "replace"), headers, (time.perf_counter() - started) * 1000.0
    except Exception as exc:
        return 599, str(exc), {}, (time.perf_counter() - started) * 1000.0


def record_result(status, headers, latency_ms):
    with LOCK:
        COUNTS[str(status)] = COUNTS.get(str(status), 0) + 1
        LATENCIES_MS.append(latency_ms)
        cache_label = headers.get("X-Cache") or headers.get("x-cache")
        if cache_label in ("HIT", "MISS", "DEDUP"):
            CACHE_HEADERS[cache_label] = CACHE_HEADERS.get(cache_label, 0) + 1


def json_request(url, payload, method="POST"):
    data = json.dumps(payload).encode("utf-8")
    return urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method)


def multipart_request(url, field_name, filename, content_type, data):
    boundary = f"----pond-demo-{time.time_ns()}"
    body = b"".join([
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode(
            "utf-8"),
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
        data,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ])
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    return req


def run_demo(payload):
    url = BASE + "/analyzeArea"
    status, body, headers, latency_ms = send(json_request(url, payload))
    record_result(status, headers, latency_ms)
    return status, body


def burst_job(thread_id):
    for idx in range(40):
        seq = thread_id * 40 + idx
        payload = {
            "min_lon": 81.05 + (seq % 87) * 0.01,
            "max_lon": 81.09 + (seq % 87) * 0.01,
            "min_lat": 21.05 + ((seq // 87) % 87) * 0.01,
            "max_lat": 21.09 + ((seq // 87) % 87) * 0.01,
            "land_use": LAND_USES[seq % len(LAND_USES)],
        }
        run_demo(payload)


for n, bbox in enumerate(BBOXES):
    land_use = LAND_USES[n % len(LAND_USES)]
    payload = {"min_lon": bbox[0], "max_lon": bbox[1], "min_lat": bbox[2],
               "max_lat": bbox[3], "land_use": land_use}
    run_demo(payload)
    if n % 2 == 0:
        for _ in range(6):
            run_demo(payload)

for land_use in LAND_USES:
    payload = {"min_lon": 81.05, "max_lon": 81.09,
               "min_lat": 21.15, "max_lat": 21.19, "land_use": land_use}
    run_demo(payload)

run_demo({"min_lon": 81.05, "max_lon": 81.09,
         "min_lat": 21.15, "max_lat": 21.19, "land_use": "not_a_real_land_use"})
run_demo({"min_lon": 80.95, "max_lon": 81.09,
         "min_lat": 21.15, "max_lat": 21.19, "land_use": LAND_USES[0]})
run_demo({"min_lon": 81.0, "max_lon": 82.0,
         "min_lat": 21.0, "max_lat": 22.0, "land_use": LAND_USES[0]})

threads = []
for thread_id in range(BURST_THREADS):
    thread = threading.Thread(target=burst_job, args=(thread_id,))
    thread.start()
    threads.append(thread)
for thread in threads:
    thread.join()

status_url = BASE + "/health"
try:
    with urllib.request.urlopen(status_url, timeout=10) as response:
        status = response.status
        headers = dict(response.headers.items())
except Exception:
    status = 599
    headers = {}
record_result(status, headers, 0.0)

contour_path = "contours_1m.kml"
if os.path.exists(contour_path):
    with open(contour_path, "rb") as stream:
        contour_payload = stream.read()
    contour_req = multipart_request(
        BASE + "/analyzeContour",
        "contour_map",
        contour_path,
        "application/vnd.google-earth.kml+xml",
        contour_payload,
    )
    contour_status, contour_body, contour_headers, contour_latency_ms = send(
        contour_req)
    record_result(contour_status, contour_headers, contour_latency_ms)


def percentile(values, fraction):
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * fraction))
    return int(round(ordered[index]))


print("status_counts=" + json.dumps(dict(sorted(COUNTS.items())),
      separators=(",", ":"), sort_keys=True))
print("cache_headers=" + json.dumps(dict(sorted(CACHE_HEADERS.items())),
      separators=(",", ":"), sort_keys=True) +
      f" p50_ms={percentile(LATENCIES_MS, 0.5)} p95_ms={percentile(LATENCIES_MS, 0.95)}")
