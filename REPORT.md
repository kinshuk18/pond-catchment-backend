# Assignment 1 - Phase 2: Pond Catchment Analysis Backend

**Name:** Kinshuk Gupta  
**Roll No:** 12341190  
**Branch:** Data Science and Artificial Intelligence (2027 Batch)  
**Course:** CSL559 - Computer Systems Design  

---

## 1. System Deployment & Endpoints
* **Target Server:** `stu24_sys1` (10.1.75.51)
* **Allocated Port:** `3293`
* **Working API URL:** `http://10.1.75.51:3293/analyzeContour` (Method: `POST`)
* **GitHub Repository:** https://github.com/kinshuk18/pond-catchment-backend.git

## 2. The "River Issue" Solution: SOTA Upland Catchment Isolation
A common flaw in basic topographical algorithms is identifying the absolute lowest point (the river channel) as the optimal pond location. Placing a rainwater harvesting structure in a floodplain is geomorphologically incorrect. To definitively solve the **"River Issue"**, this backend implements an advanced spatial isolation algorithm:

1.  **Floodplain Exclusion via Elevation Percentiles:** The uploaded vector data is interpolated into a high-resolution 200x200 DEM raster. The algorithm dynamically calculates the 20th percentile of all elevations. Any pixel falling below this threshold is mathematically classified as macro-drainage (river/floodplain) and permanently excluded from the candidate pool.
2.  **Topographic Position Index (TPI) & Upland Sink Detection:** Using a spatial minimum filter and Gaussian smoothing, the engine isolates topological bowls strictly within the remaining upland mask. This guarantees the pond is placed in a natural micro-catchment where it can safely intercept runoff before it reaches the river.
3.  **Radial Catchment Estimation:** The upstream contributing area ($A_c$) is derived by aggregating uphill gradients within a localized 1km radius of the identified sink to prevent false accumulation from neighboring macro-watersheds.

## 3. Code Reusability & Generalization
*   **Zero Hardcoding:** Bounding boxes, exclusion thresholds, and geographic coordinates are calculated entirely dynamically.
*   **Namespace-Agnostic Parser:** The parser utilizes robust regex to handle custom `lxml` objectify namespaces (e.g., `<name py:pytype="str">277.0</name>`).

## 4. Demonstration Results
Testing the engine with the provided `contours_1m.kml` yields the following JSON payload, correctly identifying an optimal localized sink safely in the uplands at an elevation of 279.76m.

```json
{
  "status": "success",
  "data": {
    "pond_location": {
      "longitude": 81.29317925803028,
      "latitude": 21.25677553354567,
      "elevation": 279.76
    },
    "catchment_area_sq_meters": 2094529.35,
    "bounding_box": {
      "min_lon": 81.2814044952393,
      "max_lon": 81.3126468658447,
      "min_lat": 21.2398224433387,
      "max_lat": 21.2635806472203
    },
    "system_note": "SOTA Upland Isolation Applied: Floodplain masked (bottom 20%). Identified upland micro-catchment away from main river."
  }
}
```

## 5. Execution Instructions for Evaluators
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 3293
```
Note: Send a POST request with multipart/form-data attaching the contour file under the key `file`.

**AI Acknowledgment:** Generative AI tools were utilized for syntax formatting, debugging, and structuring FastAPI boilerplate. Core algorithmic hydrology logic (Percentile Floodplain Exclusion and Upland Sink Detection) was mathematically modeled by the student to solve the SOTA river-avoidance constraint.
