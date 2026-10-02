"""
Converts a recommended pond\x27s catchment area into an expected harvestable
water volume using the SCS Curve Number (SCS-CN) method. Daily rainfall is
obtained primarily from NASA POWER\x27s Agroclimatology community and, if that
source is unavailable or malformed, from Open-Meteo\x27s archive API.
"""
import asyncio
import logging
import random
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

NASA_POWER_DAILY_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

logger = logging.getLogger(__name__)

# Nearby candidate ponds share the rainfall providers\x27 gridded source cell.
# Cache both the daily values and provenance so cache hits remain auditable.
_RAINFALL_CACHE: dict[tuple[float, float, str, str], tuple[list[float], str]] = {}

# AMC-II Curve Numbers, Hydrologic Soil Group C (SCS NEH-4 Table 9.1).
CURVE_NUMBERS = {
    "forest_good_cover": 70,
    "pasture_fair": 79,
    "row_crop_contoured": 82,
    "fallow_bare_soil": 91,
}
DEFAULT_LAND_USE = "row_crop_contoured"


class RainfallDataSourceError(httpx.HTTPError):
    """Both external rainfall providers were unable to supply valid data."""


def _validated_daily_values(values: object, source: str) -> list[float]:
    """Validate provider values and normalize them to daily precipitation mm."""
    if not isinstance(values, dict) or not values:
        raise ValueError(f"{source} returned no daily precipitation series.")

    daily_values: list[float | None] = []
    for day, value in sorted(values.items()):
        if not isinstance(day, str):
            raise ValueError(f"{source} returned an invalid date key.")
        try:
            rainfall_mm = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{source} returned a non-numeric precipitation value.") from exc
        # NASA POWER uses -999 for days not yet published. Those trailing
        # placeholders are excluded; an interior gap remains a hard failure.
        daily_values.append(None if rainfall_mm < 0 else rainfall_mm)

    trailing_missing = 0
    while daily_values and daily_values[-1] is None:
        daily_values.pop()
        trailing_missing += 1
    if not daily_values or any(value is None for value in daily_values):
        raise ValueError(f"{source} returned a missing or negative precipitation value.")
    if trailing_missing:
        logger.warning(
            "%s omitted %d trailing day(s) marked unavailable by the provider.",
            source,
            trailing_missing,
        )
    return [float(value) for value in daily_values]


async def fetch_nasa_power_daily(
    latitude: float, longitude: float, start: date, end: date
) -> list[float]:
    """Fetch NASA POWER AG PRECTOTCORR (bias-corrected daily precipitation)."""
    params = {
        "parameters": "PRECTOTCORR",
        "community": "AG",
        "longitude": longitude,
        "latitude": latitude,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(NASA_POWER_DAILY_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    try:
        values = payload["properties"]["parameter"]["PRECTOTCORR"]
    except (KeyError, TypeError) as exc:
        raise ValueError("NASA POWER response did not contain PRECTOTCORR daily data.") from exc
    return _validated_daily_values(values, "NASA POWER")


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, IndexError):
            return None


async def fetch_open_meteo_daily(
    latitude: float, longitude: float, start: date, end: date
) -> list[float]:
    """Fetch the fallback archive series with two retries and polite backoff."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "precipitation_sum",
        "timezone": "auto",
    }
    retry_delays = (1.0, 3.0)
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(3):
            try:
                response = await client.get(OPEN_METEO_ARCHIVE_URL, params=params)
                if response.status_code >= 400:
                    response.raise_for_status()
                payload = response.json()
                daily = payload["daily"]
                values = daily.get("precipitation_sum") if isinstance(daily, dict) else None
                if not isinstance(values, list) or not values:
                    raise ValueError("Open-Meteo returned no daily precipitation records.")
                normalized = []
                for value in values:
                    rainfall_mm = float(value)
                    if rainfall_mm < 0:
                        raise ValueError("Open-Meteo returned negative precipitation.")
                    normalized.append(rainfall_mm)
                return normalized
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt == len(retry_delays):
                    break
                retry_after = (
                    _retry_after_seconds(response)
                    if "response" in locals() and response.status_code == 429
                    else None
                )
                base_delay = retry_after if retry_after is not None else retry_delays[attempt]
                delay = base_delay + random.uniform(0.0, 0.5)
                logger.warning(
                    "Open-Meteo fallback attempt %d failed (%s); retrying in %.1fs",
                    attempt + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

    raise RainfallDataSourceError(
        f"Open-Meteo fallback failed after 3 attempts: {last_error}"
    ) from last_error


def _scs_runoff_mm(rainfall_mm: float, cn: int) -> float:
    """SCS-CN direct runoff depth Q (mm) for one day\x27s rainfall P (mm)."""
    if rainfall_mm <= 0:
        return 0.0
    s = (25400.0 / cn) - 254.0
    ia = 0.2 * s
    if rainfall_mm <= ia:
        return 0.0
    return ((rainfall_mm - ia) ** 2) / (rainfall_mm - ia + s)


async def estimate_water_volume(
    centroid_lon: float,
    centroid_lat: float,
    catchment_area_sq_m: float,
    land_use: str = DEFAULT_LAND_USE,
    years_back: int = 5,
) -> dict:
    """Estimate annual runoff volume without changing the SCS-CN calculation."""
    cn = CURVE_NUMBERS.get(land_use, CURVE_NUMBERS[DEFAULT_LAND_USE])
    end = date.today()
    start = end.replace(year=end.year - years_back)

    # NASA POWER and ERA5-Land are gridded products; a 0.1-degree cache key
    # prevents repeated requests for neighbouring sites in the same selection.
    source_lat, source_lon = round(centroid_lat, 1), round(centroid_lon, 1)
    cache_key = (source_lat, source_lon, start.isoformat(), end.isoformat())
    cached = _RAINFALL_CACHE.get(cache_key)

    if cached is None:
        try:
            daily_rain = await fetch_nasa_power_daily(source_lat, source_lon, start, end)
            source = "NASA POWER"
        except Exception as nasa_error:
            logger.warning("NASA POWER rainfall request failed; using Open-Meteo fallback: %s", nasa_error)
            try:
                daily_rain = await fetch_open_meteo_daily(source_lat, source_lon, start, end)
                source = "Open-Meteo fallback"
            except Exception as open_meteo_error:
                raise RainfallDataSourceError(
                    "NASA POWER primary and Open-Meteo fallback both failed. "
                    f"NASA POWER: {nasa_error}; Open-Meteo: {open_meteo_error}"
                ) from open_meteo_error
        _RAINFALL_CACHE[cache_key] = (daily_rain, source)
        cache_hit = False
    else:
        daily_rain, source = cached
        cache_hit = True

    logger.info(
        "Rainfall source=%s cache_hit=%s grid_cell=(%.1f, %.1f)",
        source,
        cache_hit,
        source_lat,
        source_lon,
    )

    total_runoff_mm = sum(_scs_runoff_mm(rainfall_mm, cn) for rainfall_mm in daily_rain)
    n_years = max(years_back, 1)
    avg_annual_runoff_mm = total_runoff_mm / n_years
    volume_cubic_m = avg_annual_runoff_mm * catchment_area_sq_m / 1000.0

    return {
        "land_use_assumed": land_use,
        "curve_number": cn,
        "years_of_record": n_years,
        "avg_annual_rainfall_mm": round(sum(daily_rain) / n_years, 1),
        "avg_annual_runoff_mm": round(avg_annual_runoff_mm, 1),
        "expected_water_volume_cubic_m": round(volume_cubic_m, 1),
        "method": "SCS Curve Number (NEH-4), applied per-day to NASA POWER AG PRECTOTCORR rainfall (Open-Meteo archive fallback)",
    }
