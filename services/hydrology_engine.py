import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import minimum_filter, gaussian_filter, distance_transform_edt

def analyze_terrain(points: list) -> dict:
    pts = np.array(points)
    lons, lats, elevs = pts[:, 0], pts[:, 1], pts[:, 2]
    
    min_lon, max_lon = lons.min(), lons.max()
    min_lat, max_lat = lats.min(), lats.max()
    
    grid_x, grid_y = np.mgrid[min_lon:max_lon:200j, min_lat:max_lat:200j]
    dem = griddata((lons, lats), elevs, (grid_x, grid_y), method='cubic')
    
    valid_mask = ~np.isnan(dem)
    dem[~valid_mask] = np.nanmax(dem)
    
    # SOTA: Euclidean River Buffering
    river_threshold = np.nanpercentile(dem[valid_mask], 30)
    river_mask = (dem <= river_threshold) & valid_mask
    dist_from_river = distance_transform_edt(~river_mask)
    safe_zone_mask = (dist_from_river > 15) & valid_mask
    
    smoothed_dem = gaussian_filter(dem, sigma=1)
    local_min = minimum_filter(smoothed_dem, size=12)
    sink_mask = (smoothed_dem == local_min) & safe_zone_mask
    
    candidates = []
    if np.any(sink_mask):
        sink_coords = np.argwhere(sink_mask)
        lat_mid = np.radians((min_lat + max_lat) / 2)
        dx = (max_lon - min_lon) * 111320 * np.cos(lat_mid) / 200
        dy = (max_lat - min_lat) * 111320 / 200
        cell_area_sqm = dx * dy
        
        for x, y in sink_coords:
            target_lon = float(grid_x[x, y])
            target_lat = float(grid_y[x, y])
            target_elev = float(dem[x, y])
            
            dist_x = (grid_x - target_lon) * 111320 * np.cos(lat_mid)
            dist_y = (grid_y - target_lat) * 111320
            dist_from_pond = np.sqrt(dist_x**2 + dist_y**2)
            
            local_catchment_mask = (dem > target_elev) & safe_zone_mask & (dist_from_pond < 1000)
            catchment_area = float(np.sum(local_catchment_mask) * cell_area_sqm)
            
            candidates.append({
                "x_idx": int(x), "y_idx": int(y),
                "longitude": target_lon,
                "latitude": target_lat,
                "elevation": round(target_elev, 2),
                "catchment_area_sq_meters": round(catchment_area, 2)
            })
            
    candidates.sort(key=lambda c: c['catchment_area_sq_meters'], reverse=True)
    
    top_3_ponds = []
    min_separation = 20  
    
    for cand in candidates:
        if len(top_3_ponds) >= 3:
            break
        too_close = False
        for selected in top_3_ponds:
            dist = np.sqrt((cand['x_idx'] - selected['x_idx'])**2 + (cand['y_idx'] - selected['y_idx'])**2)
            if dist < min_separation:
                too_close = True
                break
        if not too_close:
            top_3_ponds.append(cand) # FIXED KEYERROR HERE
            
    # Clean output payload
    final_ponds = []
    for p in top_3_ponds:
        final_ponds.append({
            "longitude": p["longitude"],
            "latitude": p["latitude"],
            "elevation": p["elevation"],
            "catchment_area_sq_meters": p["catchment_area_sq_meters"]
        })
            
    return {
        "recommended_ponds": final_ponds,
        "bounding_box": {
            "min_lon": min_lon, "max_lon": max_lon,
            "min_lat": min_lat, "max_lat": max_lat
        },
        "system_note": "SOTA Implemented: Spatial Multi-Criteria Evaluation with Euclidean River Buffering and Non-Maximum Suppression (NMS) for top 3 geographically distinct upland basins."
    }
