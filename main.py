import logging

import httpx
from fastapi import FastAPI, Request, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from services.kml_parser import parse_kml
from services.hydrology_engine import analyze_terrain
from services.elevation_client import fetch_elevation_grid
from services.rainfall_engine import estimate_water_volume, CURVE_NUMBERS, DEFAULT_LAND_USE

app = FastAPI(title="AI Village Pond Planning API", version="1.1")

logger = logging.getLogger("pond_planner")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
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
        raise HTTPException(status_code=400, detail="Only .kml or .kmz formats are supported.")
    
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
async def analyze_area(req: AreaRequest):
    """Map-drawn-rectangle entry point for Phase 3 — no file upload needed."""
    if req.land_use not in CURVE_NUMBERS:
        raise HTTPException(status_code=400, detail=f"land_use must be one of {list(CURVE_NUMBERS)}")
    try:
        points = await fetch_elevation_grid(req.min_lon, req.max_lon, req.min_lat, req.max_lat)
        analysis = analyze_terrain(points)

        for pond in analysis["recommended_ponds"]:
            pond["expected_water_volume"] = await estimate_water_volume(
                pond["longitude"], pond["latitude"],
                pond["catchment_area_sq_meters"], req.land_use
            )

        return JSONResponse(content={"status": "success", "data": analysis})
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream data source failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))