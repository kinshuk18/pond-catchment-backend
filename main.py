import asyncio
import hashlib
import logging
import math
import os
import time
import uuid
from collections import OrderedDict, deque

import httpx
from fastapi import FastAPI, Request, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
except ImportError:
    trace = None
    Status = None
    StatusCode = None

from services import snapshot, telemetry as telemetry_module
from services.kml_parser import parse_kml
from services.hydrology_engine import analyze_terrain
from services.elevation_client import fetch_elevation_grid_ex
from services.rainfall_engine import estimate_water_volume, CURVE_NUMBERS, DEFAULT_LAND_USE


class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, *args, **kwargs):
        return self

    def record_exception(self, *args, **kwargs):
        return self

    def set_status(self, *args, **kwargs):
        return self


class _NoopTracer:
    def start_as_current_span(self, *args, **kwargs):
        return _NoopSpan()


def _otel_error(span, status_code, exc):
    if span is None or Status is None or StatusCode is None:
        return
    span.set_attribute("http.status_code", status_code)
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR))


app = FastAPI(title="AI Village Pond Planning API", version="1.1")
TRACER = trace.get_tracer(
    "pond-catchment-backend") if trace is not None else _NoopTracer()
TRACER, INSTRUMENTS, shutdown_telemetry = telemetry_module.init_telemetry(app)
if TRACER is None:
    TRACER = trace.get_tracer(
        "pond-catchment-backend") if trace is not None else _NoopTracer()
INSTRUMENTS = INSTRUMENTS or {}
app.add_event_handler("shutdown", shutdown_telemetry)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pond_planner")

if snapshot.DATA_MODE == "snapshot" and not snapshot.available():
    raise RuntimeError(
        f"DATA_MODE=snapshot needs {snapshot.HGT_PATH} and {snapshot.RAIN_PATH}")
logger.info("DATA_MODE=%s", snapshot.DATA_MODE)

MAX_AREA_KM2 = float(os.getenv("MAX_AREA_KM2", "25"))
MAX_INFLIGHT = int(os.getenv("MAX_INFLIGHT", "8"))
CACHE_TTL_S = int(os.getenv("CACHE_TTL_S", "1800"))
CACHE_MAX = int(os.getenv("CACHE_MAX", "128"))
START_TS = time.time()
_cache = OrderedDict()   # key -> (expiry, payload)
_inflight_keys = {}      # key -> Future, dedupes identical in-flight requests
_inflight = 0
_stats = {"requests": 0, "errors": 0, "cache_hits": 0,
          "cache_misses": 0, "rejected_503": 0}
_lat = deque(maxlen=1000)


@app.middleware("http")
async def metrics_mw(request: Request, call_next):
    rid = uuid.uuid4().hex[:8]
    request.state.request_id = rid
    t0 = time.perf_counter()
    cache_label = "unknown"
    try:
        response = await call_next(request)
    except Exception:
        _stats["errors"] += 1
        raise
    dt = (time.perf_counter() - t0) * 1000
    _stats["requests"] += 1
    if getattr(response, "status_code", 200) >= 500:
        _stats["errors"] += 1
    _lat.append(dt)
    cache_label = response.headers.get("X-Cache", "unknown")
    response.headers["X-Request-ID"] = rid
    logger.info("rid=%s %s %s %d %.0fms", rid, request.method,
                request.url.path, response.status_code, dt)
    if INSTRUMENTS:
        INSTRUMENTS["requests_total"].add(1, {
            "endpoint": request.url.path,
            "status": str(response.status_code),
            "cache": cache_label,
        })
        INSTRUMENTS["request_duration_seconds"].record(dt / 1000.0, {
            "endpoint": request.url.path,
            "status": str(response.status_code),
            "cache": cache_label,
        })
    return response


def _pct(p):
    if not _lat:
        return 0.0
    s = sorted(_lat)
    return round(s[min(len(s) - 1, int(p / 100 * len(s)))], 1)


@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version, "uptime_s": round(time.time() - START_TS, 1),
            "pid": os.getpid(), "cache_entries": len(_cache), "data_mode": snapshot.DATA_MODE}


@app.get("/metrics")
async def metrics():
    h, m = _stats["cache_hits"], _stats["cache_misses"]
    return {**_stats, "in_flight": _inflight, "latency_ms_p50": _pct(50), "latency_ms_p95": _pct(95),
            "cache_hit_rate": round(h / (h + m), 3) if h + m else 0.0, "pid": os.getpid()}

# CORS disabled: frontend is served from the same origin as the API.
# from fastapi.middleware.cors import CORSMiddleware
# app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# TODO: tighten allow_origins before final deploy — "*" is fine for local testing only


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Keep unexpected failures JSON-shaped and avoid exposing tracebacks."""
    logger.exception("Unhandled error while serving %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "Internal server error"},
    )


class AreaRequest(BaseModel):
    min_lon: float
    max_lon: float
    min_lat: float
    max_lat: float
    land_use: str = DEFAULT_LAND_USE


@app.post("/analyzeContour")
async def analyze_contour(contour_map: UploadFile):
    if not contour_map.filename.endswith(('.kml', '.kmz')):
        raise HTTPException(
            status_code=400, detail="Only .kml or .kmz formats are supported.")

    try:
        content = await contour_map.read()
        points = parse_kml(content)
        analysis = analyze_terrain(points)

        return JSONResponse(content={
            "status": "success",
            "data": analysis
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyzeArea")
async def analyze_area(request: Request, req: AreaRequest):
    """Map-drawn-rectangle entry point for Phase 3 — no file upload needed."""
    global _inflight
    rid = getattr(request.state, "request_id", uuid.uuid4().hex[:8])
    with TRACER.start_as_current_span("pond.analyze_area") as span:
        span.set_attribute("pond.request_id", rid)
        if req.land_use not in CURVE_NUMBERS:
            exc = HTTPException(
                status_code=400, detail=f"land_use must be one of {list(CURVE_NUMBERS)}")
            _otel_error(span, 400, exc)
            raise exc
        if not (-90 <= req.min_lat < req.max_lat <= 90 and -180 <= req.min_lon < req.max_lon <= 180):
            exc = HTTPException(
                status_code=422, detail="Invalid bounding box coordinates")
            _otel_error(span, 422, exc)
            raise exc
        mid_lat = (req.min_lat + req.max_lat) / 2
        area_km2 = ((req.max_lat - req.min_lat) * 111.32) * ((req.max_lon -
                                                              req.min_lon) * 111.32 * math.cos(math.radians(mid_lat)))
        if area_km2 > MAX_AREA_KM2:
            exc = HTTPException(
                status_code=422, detail=f"Area {area_km2:.1f} km2 exceeds limit of {MAX_AREA_KM2} km2")
            _otel_error(span, 422, exc)
            raise exc
        if snapshot.DATA_MODE == "snapshot" and not snapshot.covers(req.min_lon, req.max_lon, req.min_lat, req.max_lat):
            exc = HTTPException(
                status_code=422,
                detail="Selection is outside the supported region (Raipur-Durg-Bhilai: lon 81-82, lat 21-22)",
            )
            _otel_error(span, 422, exc)
            raise exc

        key = hashlib.sha1(
            f"{req.min_lon:.4f}|{req.max_lon:.4f}|{req.min_lat:.4f}|{req.max_lat:.4f}|{req.land_use}".encode()
        ).hexdigest()
        hit = _cache.get(key)
        cache_result = "MISS"
        if hit and hit[0] > time.time():
            cache_result = "HIT"
            with TRACER.start_as_current_span("cache.lookup") as cache_span:
                cache_span.set_attribute("pond.request_id", rid)
                cache_span.set_attribute("pond.cache", cache_result)
                _cache.move_to_end(key)
                _stats["cache_hits"] += 1
                if INSTRUMENTS:
                    INSTRUMENTS["cache_events_total"].add(1, {"result": "HIT"})
            logger.info("analyze.done", extra={
                "request_id": rid, "land_use": req.land_use, "bbox_area_km2": area_km2,
                "cache": "HIT", "duration_ms": 0,
            })
            return JSONResponse(content=hit[1], headers={"X-Cache": "HIT"})
        pending = _inflight_keys.get(key)
        if pending is not None:
            cache_result = "DEDUP"
            with TRACER.start_as_current_span("cache.lookup") as cache_span:
                cache_span.set_attribute("pond.request_id", rid)
                cache_span.set_attribute("pond.cache", cache_result)
                _stats["cache_hits"] += 1
                if INSTRUMENTS:
                    INSTRUMENTS["cache_events_total"].add(
                        1, {"result": "DEDUP"})
            try:
                response_payload = await asyncio.shield(pending)
                logger.info("analyze.done", extra={
                    "request_id": rid, "land_use": req.land_use, "bbox_area_km2": area_km2,
                    "cache": "DEDUP", "duration_ms": 0,
                })
                return JSONResponse(content=response_payload, headers={"X-Cache": "DEDUP"})
            except Exception as e:
                _otel_error(span, 502, e)
                raise HTTPException(
                    status_code=502, detail="Shared analysis failed; retry")
        if _inflight >= MAX_INFLIGHT:
            _stats["rejected_503"] += 1
            if INSTRUMENTS:
                INSTRUMENTS["backpressure_rejections_total"].add(1)
            exc = HTTPException(status_code=503, detail="Server busy, retry shortly", headers={
                                "Retry-After": "2"})
            _otel_error(span, 503, exc)
            logger.info("analyze.rejected", extra={
                "request_id": rid, "land_use": req.land_use, "bbox_area_km2": area_km2,
                "cache": "MISS", "duration_ms": 0,
            })
            raise exc

        _stats["cache_misses"] += 1
        cache_result = "MISS"
        with TRACER.start_as_current_span("cache.lookup") as cache_span:
            cache_span.set_attribute("pond.request_id", rid)
            cache_span.set_attribute("pond.cache", cache_result)
            if INSTRUMENTS:
                INSTRUMENTS["cache_events_total"].add(1, {"result": "MISS"})
        logger.info("analyze.start", extra={
            "request_id": rid, "land_use": req.land_use, "bbox_area_km2": area_km2,
            "cache": "MISS", "duration_ms": 0,
        })
        fut = asyncio.get_running_loop().create_future()
        _inflight_keys[key] = fut
        _inflight += 1
        if INSTRUMENTS:
            INSTRUMENTS["inflight_requests"].add(1)
        try:
            with TRACER.start_as_current_span("elevation.fetch") as elev_span:
                elev_span.set_attribute("pond.request_id", rid)
                elev_t0 = time.perf_counter()
                points, elevation_source = await fetch_elevation_grid_ex(
                    req.min_lon, req.max_lon, req.min_lat, req.max_lat
                )
                elev_duration = time.perf_counter() - elev_t0
                elev_span.set_attribute(
                    "pond.elevation.source", elevation_source)
                elev_span.set_attribute("pond.grid_points", len(points))
                if INSTRUMENTS and "dem_load_duration_seconds" in INSTRUMENTS:
                    INSTRUMENTS["dem_load_duration_seconds"].record(
                        elev_duration, {"source": elevation_source})
            with TRACER.start_as_current_span("terrain.analyze") as terrain_span:
                terrain_span.set_attribute("pond.request_id", rid)
                terrain_t0 = time.perf_counter()
                analysis = await asyncio.to_thread(analyze_terrain, points)
                terrain_duration = time.perf_counter() - terrain_t0
                terrain_span.set_attribute(
                    "pond.terrain_duration_s", terrain_duration)
                terrain_span.set_attribute("pond.ponds_found", len(
                    analysis.get("recommended_ponds", [])))
                best = max(analysis.get("recommended_ponds", []), key=lambda item: item.get(
                    "catchment_area_sq_meters", 0), default={})
                if best:
                    terrain_span.set_attribute("pond.catchment_m2", float(
                        best.get("catchment_area_sq_meters", 0)))
                if INSTRUMENTS:
                    INSTRUMENTS["terrain_duration_seconds"].record(
                        terrain_duration, {})
                    INSTRUMENTS["ponds_found"].record(
                        float(len(analysis.get("recommended_ponds", []))), {})
            rainfall_source = "n/a"
            for pond in analysis["recommended_ponds"]:
                with TRACER.start_as_current_span("rainfall.fetch") as rain_span:
                    rain_span.set_attribute("pond.request_id", rid)
                    rain_span.set_attribute("pond.latitude", pond["latitude"])
                    rain_span.set_attribute(
                        "pond.longitude", pond["longitude"])
                    pond["expected_water_volume"] = await estimate_water_volume(
                        pond["longitude"], pond["latitude"],
                        pond["catchment_area_sq_meters"], req.land_use
                    )
                    rainfall_source = pond["expected_water_volume"]["rainfall_source"]
                    rain_span.set_attribute(
                        "pond.rainfall.source", rainfall_source)
                    if INSTRUMENTS:
                        INSTRUMENTS["runoff_volume_m3"].record(float(
                            pond["expected_water_volume"].get("expected_water_volume_cubic_m", 0.0)), {})
                with TRACER.start_as_current_span("runoff.scs") as runoff_span:
                    runoff_span.set_attribute("pond.request_id", rid)
                    runoff_span.set_attribute("pond.land_use", req.land_use)
                    runoff_span.set_attribute(
                        "pond.cn", pond["expected_water_volume"].get("curve_number", 0))
                    runoff_span.set_attribute("pond.volume_m3_yr", float(
                        pond["expected_water_volume"].get("expected_water_volume_cubic_m", 0.0)))
            payload = {
                "status": "success",
                "data": analysis,
                "data_source": {"elevation": elevation_source, "rainfall": rainfall_source, "mode": snapshot.DATA_MODE},
            }
            _cache[key] = (time.time() + CACHE_TTL_S, payload)
            while len(_cache) > CACHE_MAX:
                _cache.popitem(last=False)
            fut.set_result(payload)
            if INSTRUMENTS and "analyses_total" in INSTRUMENTS:
                INSTRUMENTS["analyses_total"].add(1, {"land_use": req.land_use})
            logger.info("analyze.done", extra={
                "request_id": rid, "land_use": req.land_use, "bbox_area_km2": area_km2,
                "cache": "MISS", "duration_ms": 0,
            })
            return JSONResponse(content=payload, headers={"X-Cache": "MISS"})
        except httpx.HTTPError as e:
            fut.set_exception(e)
            fut.exception()
            _otel_error(span, 502, e)
            if INSTRUMENTS:
                INSTRUMENTS["upstream_errors_total"].add(
                    1, {"upstream": "httpx"})
                if "rainfall_fetch_failures_total" in INSTRUMENTS:
                    INSTRUMENTS["rainfall_fetch_failures_total"].add(1, {"source": "upstream_httpx"})
            raise HTTPException(
                status_code=502, detail=f"Upstream data source failed: {e}")
        except Exception as e:
            fut.set_exception(e)
            fut.exception()
            _otel_error(span, 500, e)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            _inflight -= 1
            if INSTRUMENTS:
                INSTRUMENTS["inflight_requests"].add(-1)
            _inflight_keys.pop(key, None)


# Single-origin frontend. Must stay LAST so API routes match first.
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "frontend"), html=True), name="frontend")
