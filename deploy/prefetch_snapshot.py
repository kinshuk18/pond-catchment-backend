"""Prefetch rainfall snapshot: Open-Meteo archive, 0.25-degree cells over lon 81-82, lat 21-22. Run locally."""
import json
import os
import time
from datetime import date

import httpx

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rainfall_snapshot.json")
LAT0, LON0, STEP, N = 21.0, 81.0, 0.25, 5
URL = "https://archive-api.open-meteo.com/v1/archive"


def save(data):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, OUT)


def fetch(client, lat, lon, start, end):
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "precipitation_sum", "timezone": "auto",
    }
    for attempt in range(6):
        try:
            r = client.get(URL, params=params, timeout=60)
            if r.status_code == 429:
                print("429, sleeping 60s", flush=True)
                time.sleep(60)
                continue
            r.raise_for_status()
            vals = r.json()["daily"]["precipitation_sum"]
            while vals and vals[-1] is None:
                vals.pop()
            if not vals or any(v is None for v in vals):
                raise ValueError("missing values")
            return [float(v) for v in vals]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            print(f"attempt {attempt + 1} failed: {exc}", flush=True)
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"giving up on {lat},{lon}; rerun to resume")


def main():
    end = date.today()
    start = end.replace(year=end.year - 5)
    data = {"start": start.isoformat(), "end": end.isoformat(), "lat0": LAT0, "lon0": LON0,
            "step": STEP, "n": N, "cells": {}}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("start") == data["start"] and old.get("end") == data["end"]:
            data = old
    with httpx.Client() as client:
        for i in range(N):
            for j in range(N):
                lat, lon = LAT0 + i * STEP, LON0 + j * STEP
                key = f"{lat:.2f},{lon:.2f}"
                if key in data["cells"]:
                    continue
                data["cells"][key] = fetch(client, lat, lon, start, end)
                save(data)
                print(f"{key} ok ({len(data['cells'])}/{N * N})", flush=True)
                time.sleep(1)
    print("done", OUT)


main()