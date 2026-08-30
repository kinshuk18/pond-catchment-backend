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
    local_min = minimum_filter(dem, size=5)
    sink_mask = (dem == local_min) & valid_mask
    
    if np.any(sink_mask):
        sink_coords = np.where(sink_mask)
        deepest_idx = np.argmin(dem[sink_coords])
        optimal_x = sink_coords[0][deepest_idx]
        optimal_y = sink_coords[1][deepest_idx]
    else:
        optimal_x, optimal_y = np.unravel_index(np.nanargmin(dem), dem.shape)
        
    target_lon = float(grid_x[optimal_x, optimal_y])
    target_lat = float(grid_y[optimal_x, optimal_y])
    target_elev = float(dem[optimal_x, optimal_y])
    
    # 3. Cell Area Math (Spherical approximation)
    lat_mid = np.radians((min_lat + max_lat) / 2)
    dx = (max_lon - min_lon) * 111320 * np.cos(lat_mid) / 100
    dy = (max_lat - min_lat) * 111320 / 100
    cell_area_sqm = dx * dy
    
    # 4. Topological Watershed Trace (BFS Algorithm)
    # Replaces the flawed global threshold with a rigorous connected-component trace
    visited = np.zeros_like(dem, dtype=bool)
    queue = [(optimal_x, optimal_y)]
    visited[optimal_x, optimal_y] = True
    catchment_cells = 0
    
    # D8 connectivity directions
    directions = [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]
    
    while queue:
        cx, cy = queue.pop(0)
        catchment_cells += 1
        current_elev = dem[cx, cy]
        
        for dx_step, dy_step in directions:
            nx, ny = cx + dx_step, cy + dy_step
            # Check grid bounds
            if 0 <= nx < dem.shape[0] and 0 <= ny < dem.shape[1]:
                if not visited[nx, ny] and valid_mask[nx, ny]:
                    # Uphill trace: neighbor must be higher or equal to flow down to current cell
                    if dem[nx, ny] >= current_elev:
                        visited[nx, ny] = True
                        queue.append((nx, ny))
                        
    catchment_area_sqm = float(catchment_cells * cell_area_sqm)
    
    return {
        "pond_location": {
            "longitude": target_lon,
            "latitude": target_lat,
            "elevation": round(target_elev, 2)
        },
        "catchment_area_sq_meters": round(catchment_area_sqm, 2),
        "bounding_box": {
            "min_lon": min_lon, "max_lon": max_lon,
            "min_lat": min_lat, "max_lat": max_lat
        },
        "system_note": "Identified enclosed morphological sink. Catchment derived via topological BFS trace."
    }
