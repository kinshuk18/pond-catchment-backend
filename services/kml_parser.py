from bs4 import BeautifulSoup
import re
from services.telemetry import get_tracer, record_span_error

TRACER = get_tracer("services.kml_parser")

def parse_kml(file_content: bytes) -> list:
    """Extracts X, Y, Z coordinates dynamically from any generalized KML/KMZ contour map."""
    with TRACER.start_as_current_span("kml.parse") as span:
        span.set_attribute("kml.file_bytes", len(file_content))
        try:
            soup = BeautifulSoup(file_content, "xml")
            points = []
            
            for placemark in soup.find_all("Placemark"):
                name_tag = placemark.find("name")
                elevation = 0.0
                if name_tag and name_tag.text:
                    try:
                        # Extract numeric elevation dynamically
                        elevation = float(re.findall(r"[-+]?(?:\d*\.\d+|\d+)", name_tag.text)[0])
                    except IndexError:
                        continue

                line_string = placemark.find("LineString")
                if line_string:
                    coords_text = line_string.find("coordinates").text.strip()
                    coord_pairs = coords_text.split()
                    for pair in coord_pairs:
                        parts = pair.split(',')
                        if len(parts) >= 2:
                            lon, lat = float(parts[0]), float(parts[1])
                            points.append([lon, lat, elevation])
                            
            if not points:
                exc = ValueError("No valid contour geometry found in the KML.")
                record_span_error(span, exc, 400)
                raise exc
                
            span.set_attribute("kml.point_count", len(points))
            return points
        except Exception as exc:
            record_span_error(span, exc)
            raise
