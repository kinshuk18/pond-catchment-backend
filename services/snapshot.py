"""Offline data snapshot (local SRTM tile + prefetched rainfall) so the service does not depend on flaky public APIs."""
import json
import logging
import math
import os
from functools import lru_cache

import numpy as np
from scipy.ndimage import distance_transform_edt, map_coordinates

logger = logging.getLogger(__name__)

DATA_MODE = os.getenv("DATA_MODE", "auto").lower()  # live | snapshot | auto
if DATA_MODE not in ("live", "snapshot", "auto"):
    raise ValueError("DATA_MODE must be live, snapshot or auto")

DATA_DIR = os.getenv(
    "DATA_DIR", os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), "data")
)
HGT_PATH = os.path.join(DATA_DIR, "N21E081.hgt")
RAIN_PATH = os.path.join(DATA_DIR, "rainfall_snapshot.json")
LAT0, LON0 = 21.0, 81.0  # SRTM tile N21E081: lat 21-22, lon 81-82
COVER = (81.0, 82.0, 21.0, 22.0)  # min_lon, max_lon, min_lat, max_lat


@lru_cache(maxsize=1)
def available() -> bool:
    return os.path.exists(HGT_PATH) and os.path.exists(RAIN_PATH)


def covers(min_lon: float, max_lon: float, min_lat: float, max_lat: float) -> bool:
    return (
        available()
        and COVER[0] <= min_lon
        and max_lon <= COVER[1]
        and COVER[2] <= min_lat
        and max_lat <= COVER[3]
    )


@lru_cache(maxsize=1)
def _tile() -> np.ndarray:
    raw = np.fromfile(HGT_PATH, dtype=">i2")
    n = math.isqrt(raw.size)
    if n * n != raw.size or n not in (1201, 3601):
        raise ValueError(
            f"{HGT_PATH}: unexpected {raw.size} samples (need 1201x1201 or 3601x3601)")
    arr = raw.reshape(n, n).astype(np.float32)
    void = arr == -32768
    if void.any():
        idx = distance_transform_edt(
            void, return_distances=False, return_indices=True)
        arr = arr[tuple(idx)]
        logger.warning(
            "SRTM tile: filled %d void cells from nearest valid cell", int(void.sum()))
    return arr


def elevation_label() -> str:
    res = "1 arc-sec, ~30 m" if _tile(
    ).shape[0] == 3601 else "3 arc-sec, ~90 m"
    return f"SRTM {res} snapshot (N21E081)"


def sample_elevations(coords: list[tuple[float, float]]) -> list[float]:
    """coords: [(lon, lat)] -> elevation in metres, bilinear on the local SRTM tile."""
    arr = _tile()
    n = arr.shape[0]
    lon = np.array([c[0] for c in coords], dtype=np.float64)
    lat = np.array([c[1] for c in coords], dtype=np.float64)
    rows = (LAT0 + 1.0 - lat) * (n - 1)  # row 0 = northern edge
    cols = (lon - LON0) * (n - 1)
    return map_coordinates(arr, [rows, cols], order=1, mode="nearest").tolist()


@lru_cache(maxsize=1)
def _rain() -> dict:
    with open(RAIN_PATH, encoding="utf-8") as f:
        return json.load(f)


def rainfall_series(lat: float, lon: float) -> tuple[list[float], str]:
    """Nearest prefetched rainfall cell -> (daily mm, provenance string)."""
    data = _rain()
    step, n = data["step"], data["n"]
    i = min(max(round((lat - data["lat0"]) / step), 0), n - 1)
    j = min(max(round((lon - data["lon0"]) / step), 0), n - 1)
    key = f"{data['lat0'] + i * step:.2f},{data['lon0'] + j * step:.2f}"
    return data["cells"][key], f"Open-Meteo snapshot ({data['start']} to {data['end']}, cell {key})"
