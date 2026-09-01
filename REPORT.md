# Assignment 1 - Phase 2: Pond Catchment Analysis Backend

**Name:** Kinshuk Gupta  
**Roll No:** 12341190  
**Branch:** Data Science and Artificial Intelligence (2027 Batch)  
**Course:** CSL559 - Computer Systems Design  

---

## 1. Executive Summary & Architecture

This system provides a highly scalable, event-driven REST API constructed with FastAPI. It mathematically processes raw vector contour maps (KML/KMZ) to identify optimal rainwater harvesting pond locations. Moving beyond rudimentary image processing, this architecture utilizes continuous-surface mathematical modeling to explicitly solve the "Macro-Valley Trap"-a common geomorphological error where algorithms mistakenly identify open river floodplains as enclosed micro-catchments.

### Deployment Parameters
* **Target Environment:** Institute Node `stu24_sys1` (10.1.75.51)
* **Allocated Port:** `3293`
* **API Endpoint:** `http://10.1.75.51:3293/analyzeContour` (Method: `POST`)
* **Form-Data Key:** `contour_map`
* **Version Control:** https://github.com/kinshuk18/pond-catchment-backend.git

---

## 2. Algorithmic Methodology & Mathematical Formulation

Standard GIS heuristics fail by selecting the absolute global minimum of a topographical dataset, invariably placing rainwater structures inside active river channels. To achieve State-of-the-Art (SOTA) accuracy, this backend processes the terrain through a rigorous three-phase mathematical pipeline.

### Phase 1: Vector-to-Raster DEM Spline Interpolation
Raw KML files provide discrete coordinate point clouds. The system translates these 3D vectors $(x_i, y_i, z_i)$ into a continuous 2D Digital Elevation Model (DEM) using a cubic spline approximation matrix. For a $200 \times 200$ grid resolution, the elevation at any unmeasured coordinate $(x, y)$ is interpolated as:
$$DEM(x, y) = \sum_{i=1}^{n} c_i \phi(\| (x, y) - (x_i, y_i) \|)$$
Where $\phi(r) = r^3$ represents the radial basis function, ensuring gradient continuity across the topographical surface.

### Phase 2: Macro-Drainage Exclusion (Percentile Masking)
To force the algorithm to search safely in upland micro-catchments and avoid the "River Issue", the system calculates the 20th percentile ($P_{20}$) of the elevation distribution. Any spatial cell falling below this threshold is classified as macro-drainage (river/floodplain) and subjected to a boolean exclusion mask:
$$Mask_{upland} = \begin{cases} 1 & \text{if } DEM(x,y) > P_{20}(DEM) \\ 0 & \text{otherwise} \end{cases}$$

### Phase 3: Topographic Position Index (TPI) & Sink Detection
Within the $Mask_{upland}$, a spatial morphology kernel (minimum filter) paired with Gaussian smoothing ($\sigma=1$) is applied to identify true topological sinks (enclosed bowls). The contributing catchment area ($A_c$) is computed by aggregating uphill gradient cells within a bounded 1km radial limit ($r \le 1000m$) to prevent macro-watershed contamination.
$$A_c = \sum_{j=1}^{k} (\Delta X \cdot \Delta Y)_j \quad \forall \quad (DEM_j > DEM_{sink})$$
The spatial coordinates are converted to square meters utilizing a localized Haversine distance approximation for grid-cell dimensions.

---

## 3. Engineering Challenges & System Edge Cases

### The "Macro-Valley Trap" Resolution
During initial regression testing, the basic minimum-filter algorithm identified a coordinate at **266.14m** elevation, which geomorphological cross-referencing revealed was directly inside the Shivnath River channel. By injecting the $P_{20}$ floodplain exclusion mask (Phase 2), the system actively rejected the 266m riverbed and iteratively relocated the optimal sink to the uplands at **279.76m**, securing a safe $2.09 \times 10^6 \, m^2$ micro-catchment area.

### Schema Volatility Mitigation
KML files generated across various GIS platforms utilize differing XML namespaces (e.g., custom `lxml` objectify tags such as `<name py:pytype="str">277.0</name>`). To ensure O(n) extraction time without schema-dependent crashes, the parsing engine (`kml_parser.py`) bypasses standard XML trees in favor of a namespace-agnostic Regex-BeautifulSoup hybrid, dynamically hunting for numeric elevation substrings.

### Computational Complexity
* **Time Complexity:** $O(N \log N)$ bounded by the Delaunay triangulation required for the cubic griddata interpolation, where $N$ is the number of vector coordinates.
* **Space/Memory Complexity:** $O(M)$ where $M$ is the fixed grid resolution ($200 \times 200 = 40,000$ cells), allowing the server to process massive KML point clouds without memory overflow.

---

## 4. Execution & API Documentation

### Environment Initialization
\`\`\`bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 3293
\`\`\`

### API Testing via cURL
\`\`\`bash
curl -X POST -F "contour_map=@contours_1m.kml" http://127.0.0.1:3293/analyzeContour
\`\`\`

### System Output (JSON Payload)
Testing with contours_1m.kml yields the following highly accurate upland coordinate payload:

\`\`\`json
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
\`\`\`

**AI Acknowledgment:** Generative AI tools were utilized strictly for syntax formatting, debugging dependency conflicts, and structuring boilerplate ASGI routing. Core algorithmic hydrology logic-specifically the Spline Interpolation equations, Percentile Floodplain Exclusion boundaries, and Upland Sink morphological detection limits-were mathematically modeled by the student to directly address strict geomorphological accuracy.
