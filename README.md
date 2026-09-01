# AI-Driven Pond Catchment Analysis Backend

**Author:** Kinshuk Gupta (12341190) | IIT Bhilai - CSL559

## Overview
This repository contains a high-performance, asynchronous FastAPI backend designed to process geospatial contour maps (KML/KMZ) and dynamically identify the optimal geographical coordinates for rainwater harvesting ponds.

## SOTA Hydrological Innovation
Standard GIS algorithms frequently succumb to the "Macro-Valley Trap"—placing ponds in the absolute lowest point of a map, which is invariably an active river channel or flood plain.

To solve this, this engine implements:
1. **Spatial Multi-Criteria Evaluation (MCE):** We calculate the 30th percentile of elevation to map the macro-drainage network, then apply Euclidean Distance Transforms to create a strict spatial buffer. Ponds are mathematically forbidden from being placed within this flood-risk radius.
2. **Spatial Non-Maximum Suppression (NMS):** The engine evaluates all viable upland topological sinks, ranks them by upstream flow accumulation, and utilizes NMS to return the **Top 3 geographically distinct** locations, ensuring diverse, safe options.

## Core Stack
* **Gateway:** FastAPI, Uvicorn
* **Compute:** NumPy, SciPy (Cubic Spline Interpolation, Euclidean Distance Transforms, Gaussian/Minimum Filtering)
* **Parsing:** BeautifulSoup4, lxml (Namespace-agnostic regex parsing)

## API Usage
**Endpoint:** `POST /analyzeContour`
**Form-Data Key:** `contour_map` (Attach KML/KMZ file)

\`\`\`bash
curl -X POST -F "contour_map=@contours_1m.kml" http://10.1.75.51:3293/analyzeContour
\`\`\`

Returns a JSON payload containing an array of the `recommended_ponds` with corresponding catchment areas, bounding boxes, and system metadata.
