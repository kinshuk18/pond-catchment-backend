from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from services.kml_parser import parse_kml
from services.hydrology_engine import analyze_terrain

app = FastAPI(title="AI Village Pond Planning API", version="1.0")

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
