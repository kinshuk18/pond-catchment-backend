# Assignment 1 - Phase 2: Pond Catchment Analysis Backend

**Name:** Kinshuk Gupta  
**Roll No:** 12341190  
**Branch:** Data Science and Artificial Intelligence (2027 Batch)  
**Course:** CSL559 - Computer Systems Design  

---

## 1. System Deployment & Endpoints
The backend is currently deployed and running via an asynchronous FastAPI gateway on the allotted institute server network.

* **Target Server:** `stu24_sys1` (10.1.75.51)
* **Allocated Port:** `3293`
* **Working API URL:** `http://10.1.75.51:3293/analyzeContour` (Method: `POST`)
* **GitHub Repository:** https://github.com/kinshuk18/pond-catchment-backend.git

## 2. Catchment Analysis & Hydrological Methodology
To ensure high accuracy and explicitly avoid the misclassification of open river channels as localized pond basins, the backend bypasses basic flat-geometry processing in favor of dynamic continuous-surface modeling.

1.  **Vector-to-Raster DEM Interpolation:** The uploaded KML vector coordinates (X, Y, Z) are mathematically interpolated into a 2D Digital Elevation Model (DEM) grid using a cubic spline algorithm (`scipy.interpolate.griddata`).
2.  **Morphological Basin Detection:** To satisfy the strict constraint of isolating a pond rather than a river gradient, the algorithm applies a spatial minimum filter (`scipy.ndimage.minimum_filter`). This isolates enclosed topological bowls (true sinks) rather than merely finding the absolute lowest elevation point on the map, which often traces flowing water.
3.  **Catchment Area Estimation:** The upstream contributing area ($A_c$) is calculated by aggregating the uphill gradients leading directly into the localized sink. We map spherical distances to grid cells to approximate the area in square meters.

## 3. Code Reusability & Generalization
The codebase strictly adheres to the generalization mandate for Phase 3. 
*   **Zero Hardcoding:** Bounding boxes, matrix dimensions, and geographic coordinates are calculated entirely dynamically based on the uploaded file's geometry footprint.
*   **Namespace-Agnostic Parser:** The `kml_parser.py` module utilizes robust regex extraction and `BeautifulSoup` to parse custom `lxml` objectify namespaces (e.g., `<name py:pytype="str">277.0</name>`), preventing crashes on varying XML schemas.

## 4. Demonstration Results
Testing the engine with the provided `contours_1m.kml` yields the following JSON payload, correctly identifying an optimal localized sink.

```json
{
  "status": "success",
  "data": {
    "pond_location": {
      "longitude": 81.28298239274463,
      "latitude": 21.26334066536291,
      "elevation": 266.13509630147934
    },
    "catchment_area_sq_meters": 8178373.08,
    "bounding_box": {
      "min_lon": 81.2814044952393,
      "max_lon": 81.3126468658447,
      "min_lat": 21.2398224433387,
      "max_lat": 21.2635806472203
    },
    "system_note": "Identified enclosed morphological sink to avoid river channel misclassification."
  }
}
```

## 5. Execution Instructions for Evaluators
To run the analysis engine locally:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 3293
```

Note: Send a `POST` request with `multipart/form-data` attaching the contour file under the key `file`.

**AI Acknowledgment:** Generative AI tools were utilized strictly for syntax formatting, debugging dependency conflicts, and structuring boilerplate FastAPI routing. Core algorithmic logic (DEM interpolation and morphological sink analysis) was mathematically modeled by the student.
