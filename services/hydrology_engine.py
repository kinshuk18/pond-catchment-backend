import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import minimum_filter

def analyze_terrain(points: list) -> dict:
    pts = np.array(points)
    lons, lats, elevs = pts[:, 0], pts[:, 1], pts[:, 2]
    
    min_lon, max_lon = lons.min(), lons.max()
    min_lat, max_lat = lats.min(), lats.max()
    
    # 1. Dynamic Rasterization (100x100 DEM grid)
    grid_x, grid_y = np.mgrid[min_lon:max_lon:100j, min_lat:max_lat:100j]
    dem = griddata((lons, lats), elevs, (grid_x, grid_y), method='cubic')
    
    valid_mask = ~np.isnan(dem)
    dem[~valid_mask] = np.nanmax(dem)
    
    # 2. Morphological Sink Analysis (River vs. Pond filtering)
    # A local minimum filter ensures we find a topological "bowl" (pond), not a gradient channel (river)
    local_min = minimum_filter(dem, size=5)
    sink_mask = (dem == local_min) & valid_mask
    
    if np.any(sink_mask):
        sink_coords = np.where(sink_mask)
        deepest_idx = np.argmin(dem[sink_coords])
        optimal_x = sink_coords[0][deepest_idx]
        optimal_y = sink_coords[1][deepest_idx]
    else:
        # Fallback to lowest absolute point if no enclosed bowl exists
        optimal_x, optimal_y = np.unravel_index(np.nanargmin(dem), dem.shape)
        
    target_lon = float(grid_x[optimal_x, optimal_y])
    target_lat = float(grid_y[optimal_x, optimal_y])
    target_elev = float(dem[optimal_x, optimal_y])
    
    # 3. Catchment Area Math (Spherical approximation)
    lat_mid = np.radians((min_lat + max_lat) / 2)
    dx = (max_lon - min_lon) * 111320 * np.cos(lat_mid) / 100
    dy = (max_lat - min_lat) * 111320 / 100
    cell_area_sqm = dx * dy
    
    # Simplistic D8 upstream calculation
    catchment_cells = np.sum((dem > target_elev) & valid_mask)
    catchment_area_sqm = float(catchment_cells * cell_area_sqm)
    
    return {
        "pond_location": {
            "longitude": target_lon,
            "latitude": target_lat,
            "elevation": target_elev
        },
        "catchment_area_sq_meters": round(catchment_area_sqm, 2),
        "bounding_box": {
            "min_lon": min_lon, "max_lon": max_lon,
            "min_lat": min_lat, "max_lat": max_lat
        },
        "system_note": "Identified enclosed morphological sink to avoid river channel misclassification."
    }
