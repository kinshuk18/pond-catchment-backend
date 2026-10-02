"""Fetch a terrain elevation lattice from resilient public elevation providers."""
import asyncio
import logging

import httpx

OPEN_TOPO_URL = "https://api.opentopodata.org/v1/srtm90m"
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
BATCH_SIZE = 100
REQUEST_DELAY_S = 1.0

logger = logging.getLogger(__name__)


class ElevationDataSourceError(httpx.HTTPError):
    """Neither elevation provider returned a complete, valid grid."""


def _build_coordinates(
    min_lon: float, max_lon: float, min_lat: float, max_lat: float, grid_size: int
) -> list[tuple[float, float]]:
    if grid_size < 2:
        raise ValueError("grid_size must be >= 2")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError("Bounding box minimums must be smaller than maximums.")

    lons = [min_lon + i * (max_lon - min_lon) / (grid_size - 1) for i in range(grid_size)]
    lats = [min_lat + j * (max_lat - min_lat) / (grid_size - 1) for j in range(grid_size)]
    return [(lon, lat) for lat in lats for lon in lons]


def _validated_elevations(values: list[object], source: str, expected: int) -> list[float]:
    if len(values) != expected:
        raise ValueError(f"{source} returned {len(values)} elevations; expected {expected}.")
    elevations: list[float] = []
    for value in values:
        if value is None:
            raise ValueError(f"{source} returned a null elevation.")
        try:
            elevations.append(float(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{source} returned a non-numeric elevation.") from exc
    return elevations


async def _fetch_open_topo_data(coords: list[tuple[float, float]]) -> list[float]:
    """Use SRTM90m in 100-point batches, retrying one failed batch once."""
    elevations: list[float] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for start in range(0, len(coords), BATCH_SIZE):
            batch = coords[start : start + BATCH_SIZE]
            locations = "|".join(f"{lat:.6f},{lon:.6f}" for lon, lat in batch)
            last_error: Exception | None = None

            for attempt in range(2):
                try:
                    response = await client.get(OPEN_TOPO_URL, params={"locations": locations})
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("status") != "OK":
                        raise ValueError(
                            f"OpenTopoData API error: {payload.get('error', 'unknown')}"
                        )
                    results = payload["results"]
                    values = [result["elevation"] for result in results]
                    elevations.extend(_validated_elevations(values, "OpenTopoData", len(batch)))
                    break
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    last_error = exc
                    if attempt == 1:
                        raise ElevationDataSourceError(
                            f"OpenTopoData batch starting at point {start} failed after one retry: {exc}"
                        ) from exc
                    logger.warning(
                        "OpenTopoData batch starting at point %d failed (%s); retrying once.",
                        start,
                        exc,
                    )
                    await asyncio.sleep(0.5)
            else:
                raise ElevationDataSourceError(str(last_error))

            if start + BATCH_SIZE < len(coords):
                await asyncio.sleep(REQUEST_DELAY_S)

    return elevations


async def _fetch_open_elevation(coords: list[tuple[float, float]]) -> list[float]:
    """Request the complete grid in Open-Elevation's POST lookup format."""
    locations = [{"latitude": lat, "longitude": lon} for lon, lat in coords]
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(OPEN_ELEVATION_URL, json={"locations": locations})
        response.raise_for_status()
        payload = response.json()

    try:
        results = payload["results"]
        values = [result["elevation"] for result in results]
    except (KeyError, TypeError) as exc:
        raise ValueError("Open-Elevation response did not contain ordered elevation results.") from exc
    return _validated_elevations(values, "Open-Elevation", len(coords))


async def fetch_elevation_grid(
    min_lon: float,
    max_lon: float,
    min_lat: float,
    max_lat: float,
    grid_size: int = 25,
) -> list[list[float]]:
    """
    Sample a grid_size x grid_size lattice and return [lon, lat, elevation].
    OpenTopoData SRTM90m is primary; Open-Elevation is a full-grid fallback.
    """
    coords = _build_coordinates(min_lon, max_lon, min_lat, max_lat, grid_size)

    try:
        elevations = await _fetch_open_topo_data(coords)
        source = "OpenTopoData"
    except Exception as topo_error:
        logger.warning(
            "OpenTopoData elevation request failed; using Open-Elevation fallback: %s",
            topo_error,
        )
        try:
            elevations = await _fetch_open_elevation(coords)
            source = "Open-Elevation fallback"
        except Exception as open_elevation_error:
            raise ElevationDataSourceError(
                "OpenTopoData primary and Open-Elevation fallback both failed. "
                f"OpenTopoData: {topo_error}; Open-Elevation: {open_elevation_error}"
            ) from open_elevation_error

    logger.info("Elevation source=%s grid_points=%d", source, len(coords))
    return [[lon, lat, elevation] for (lon, lat), elevation in zip(coords, elevations)]
