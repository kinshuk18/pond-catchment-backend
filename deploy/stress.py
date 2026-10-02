"""Threaded stress harness for the pond analysis API.

Usage:
    python deploy/stress.py [BASE_URL]

The script mirrors every printed line to docs/stress_results.txt.
"""

from __future__ import annotations

import json
import math
import socket
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from queue import Empty, Queue

TIMEOUT_SECONDS = 30
DEFAULT_BASE_URL = "http://10.1.75.51:3296"
BASE_BOX = {
    "min_lon": 81.30,
    "max_lon": 81.31,
    "min_lat": 21.16,
    "max_lat": 21.17,
}
SCENARIO_C_SHIFT_DEGREES = 0.0007


class Tee:
    def __init__(self, stream, file_handle):
        self.stream = stream
        self.file_handle = file_handle

    def write(self, text):
        self.stream.write(text)
        self.file_handle.write(text)

    def flush(self):
        self.stream.flush()
        self.file_handle.flush()


def emit(tee, text=""):
    print(text, file=tee)
    tee.flush()


def normalize_base_url(base_url):
    return base_url.rstrip("/")


def build_url(base_url, path):
    return f"{normalize_base_url(base_url)}{path}"


def json_body(payload):
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def classify_connection_error(exc):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    text = str(reason).lower()
    if "timed out" in text or "timeout" in text:
        return "timeout"
    return "connection_error"


def perform_request(method, url, payload):
    start = time.perf_counter()
    data = None if payload is None else json_body(payload)
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read()
            latency_ms = (time.perf_counter() - start) * 1000
            return {
                "status": response.status,
                "latency_ms": latency_ms,
                "x_cache": response.headers.get("X-Cache"),
                "error_kind": None,
            }
    except urllib.error.HTTPError as exc:
        try:
            exc.read()
        except Exception:
            pass
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": exc.code,
            "latency_ms": latency_ms,
            "x_cache": exc.headers.get("X-Cache") if exc.headers else None,
            "error_kind": None,
        }
    except urllib.error.URLError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": None,
            "latency_ms": latency_ms,
            "x_cache": None,
            "error_kind": classify_connection_error(exc),
        }
    except TimeoutError:
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": None,
            "latency_ms": latency_ms,
            "x_cache": None,
            "error_kind": "timeout",
        }


def run_requests(method, url, payloads, concurrency):
    queue = Queue()
    for payload in payloads:
        queue.put(payload)

    results = []
    results_lock = threading.Lock()

    def worker():
        while True:
            try:
                payload = queue.get_nowait()
            except Empty:
                return
            try:
                result = perform_request(method, url, payload)
            except Exception as exc:  # pragma: no cover - defensive reporting
                result = {
                    "status": None,
                    "latency_ms": 0.0,
                    "x_cache": None,
                    "error_kind": f"unexpected:{type(exc).__name__}",
                }
            with results_lock:
                results.append(result)
            queue.task_done()

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(concurrency)]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall_seconds = time.perf_counter() - started
    return results, wall_seconds


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    index = max(0, min(len(ordered) - 1,
                math.ceil((pct / 100.0) * len(ordered)) - 1))
    return round(ordered[index], 1)


def summarize(results):
    status_counts = Counter()
    error_counts = Counter()
    cache_counts = Counter()
    latencies = []

    for result in results:
        latencies.append(result["latency_ms"])
        if result["status"] is None:
            error_counts[result["error_kind"]] += 1
        else:
            status_counts[str(result["status"])] += 1
        if result["x_cache"]:
            cache_counts[result["x_cache"]] += 1

    error_summary = {
        "timeout": error_counts.get("timeout", 0),
        "connection_error": error_counts.get("connection_error", 0),
    }
    for name, count in error_counts.items():
        if name not in error_summary:
            error_summary[name] = count

    return {
        "status_counts": dict(sorted(status_counts.items(), key=lambda item: item[0])),
        "error_counts": error_summary,
        "cache_counts": dict(sorted(cache_counts.items(), key=lambda item: item[0])),
        "latency_p50_ms": round(statistics.median(latencies), 1) if latencies else 0.0,
        "latency_p95_ms": percentile(latencies, 95),
        "latency_max_ms": round(max(latencies), 1) if latencies else 0.0,
    }


def fetch_raw_json(base_url, path):
    last_exc = None
    for _attempt in range(5):
        request = urllib.request.Request(
            build_url(base_url, path), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            time.sleep(2)
    raise last_exc


def scenario_line(label, method, path, concurrency, results, wall_seconds):
    summary = summarize(results)
    request_count = len(results)
    req_per_s = request_count / wall_seconds if wall_seconds > 0 else 0.0
    return (
        f"{label} {method} {path} requests={request_count} concurrency={concurrency} "
        f"wall_seconds={wall_seconds:.3f} req_per_s={req_per_s:.2f} "
        f"status_counts={json.dumps(summary['status_counts'], sort_keys=True)} "
        f"error_counts={json.dumps(summary['error_counts'], sort_keys=True)} "
        f"latency_ms={{\"p50\":{summary['latency_p50_ms']:.1f},\"p95\":{summary['latency_p95_ms']:.1f},\"max\":{summary['latency_max_ms']:.1f}}} "
        f"x_cache_counts={json.dumps(summary['cache_counts'], sort_keys=True)}"
    )


def scenario_a_payloads(count):
    return [None] * count


def scenario_b_payloads(count):
    return [dict(BASE_BOX) for _ in range(count)]


def scenario_c_payloads(count):
    payloads = []
    for index in range(count):
        shift = round(index * SCENARIO_C_SHIFT_DEGREES, 4)
        payloads.append(
            {
                "min_lon": round(BASE_BOX["min_lon"] + shift, 4),
                "max_lon": round(BASE_BOX["max_lon"] + shift, 4),
                "min_lat": BASE_BOX["min_lat"],
                "max_lat": BASE_BOX["max_lat"],
            }
        )
    return payloads


def run_scenario(tee, base_url, label, method, path, payloads, concurrency):
    url = build_url(base_url, path)
    results, wall_seconds = run_requests(method, url, payloads, concurrency)
    line = scenario_line(label, method, path, concurrency,
                         results, wall_seconds)
    emit(tee, line)


def main(argv):
    base_url = normalize_base_url(
        argv[1] if len(argv) > 1 else DEFAULT_BASE_URL)
    docs_path = Path(__file__).resolve(
    ).parents[1] / "docs" / "stress_results.txt"
    docs_path.parent.mkdir(parents=True, exist_ok=True)

    with docs_path.open("w", encoding="utf-8") as log_file:
        tee = Tee(sys.stdout, log_file)
        emit(tee, f"base_url={base_url}")
        emit(tee, f"timeout_seconds={TIMEOUT_SECONDS}")
        emit(tee, f"bbox_exact={json.dumps(BASE_BOX, sort_keys=True)}")
        emit(tee, f"payload_exact={json.dumps(BASE_BOX, sort_keys=True)}")
        emit(tee, f"scenario_c_lon_shift_degrees={SCENARIO_C_SHIFT_DEGREES}")

        metrics_before = fetch_raw_json(base_url, "/metrics")
        emit(tee, f"metrics_before {metrics_before}")

        for concurrency in (1, 8, 32, 64):
            run_scenario(
                tee,
                base_url,
                "scenario_a",
                "GET",
                "/health",
                scenario_a_payloads(200),
                concurrency,
            )

        run_scenario(
            tee,
            base_url,
            "scenario_b",
            "POST",
            "/analyzeArea",
            scenario_b_payloads(100),
            8,
        )

        for concurrency in (1, 8, 16, 40):
            run_scenario(
                tee,
                base_url,
                "scenario_c",
                "POST",
                "/analyzeArea",
                scenario_c_payloads(60),
                concurrency,
            )

        metrics_after = fetch_raw_json(base_url, "/metrics")
        emit(tee, f"metrics_after {metrics_after}")


if __name__ == "__main__":
    main(sys.argv)
