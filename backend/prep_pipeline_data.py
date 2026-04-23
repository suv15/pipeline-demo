"""
Pipeline Data Prep Script
--------------------------
Generates GeoJSON for the IOCL Salaya-Mathura crude pipeline corridor demo.

Outputs:
  - pipeline.geojson         : approximate alignment (LineString)
  - buffer_1km.geojson       : 1 km Right-of-Way buffer (Polygon)
  - buffer_5km.geojson       : 5 km monitoring buffer (Polygon)
  - sample_anomalies.geojson : 8 seeded demo anomalies along the route
  - aoi_tiles.geojson        : 10 km analysis tiles covering the corridor

Run:
  pip install shapely pyproj geojson
  python prep_pipeline_data.py

Note: Alignment is a PUBLIC APPROXIMATION based on published route maps
(Salaya -> Viramgam -> Koyali -> Ratlam -> Mathura). For a real deployment,
replace with surveyed KML/SHP from the operator.
"""

import json
import random
from pathlib import Path

from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform
from pyproj import Transformer

OUT_DIR = Path("./data")
OUT_DIR.mkdir(exist_ok=True)

# Approximate route waypoints (lon, lat) — IOCL Salaya-Mathura crude pipeline
# Source: publicly documented route, approximated for demo purposes only
ROUTE_POINTS = [
    (69.2510, 22.4620),  # Salaya, Gujarat (origin)
    (69.7800, 22.4200),  # Jamnagar area
    (70.5600, 22.4600),  # Rajkot outskirts
    (71.6500, 22.7800),  # Surendranagar
    (72.0400, 22.7700),  # Viramgam
    (72.6800, 22.3500),  # Koyali refinery (IOCL)
    (73.2000, 22.3100),  # Vadodara region
    (74.1500, 22.5800),  # Dahod
    (74.7500, 23.1800),  # Ratlam
    (75.8800, 23.1800),  # Ujjain area
    (76.8000, 24.1500),  # Kota region
    (77.4200, 25.4500),  # Sawai Madhopur area
    (77.6700, 27.4900),  # Mathura (terminus)
]


def build_pipeline_geojson():
    line = LineString(ROUTE_POINTS)
    feature = {
        "type": "Feature",
        "properties": {
            "name": "IOCL Salaya-Mathura Crude Pipeline",
            "operator": "Indian Oil Corporation Limited",
            "type": "crude_oil",
            "diameter_inch": 28,
            "length_km_approx": 1870,
            "commissioned": 1996,
            "status": "operational",
        },
        "geometry": mapping(line),
    }
    fc = {"type": "FeatureCollection", "features": [feature]}
    (OUT_DIR / "pipeline.geojson").write_text(json.dumps(fc, indent=2))
    print(f"✓ pipeline.geojson ({line.length:.2f} deg length)")
    return line


def build_buffers(line):
    # Project to metric CRS (EPSG:7755 — India-specific LCC) for accurate buffering
    to_metric = Transformer.from_crs("EPSG:4326", "EPSG:7755", always_xy=True).transform
    to_wgs = Transformer.from_crs("EPSG:7755", "EPSG:4326", always_xy=True).transform

    line_m = transform(to_metric, line)

    for km, fname in [(1, "buffer_1km.geojson"), (5, "buffer_5km.geojson")]:
        buf_m = line_m.buffer(km * 1000, cap_style=2, join_style=2)
        buf_wgs = transform(to_wgs, buf_m)
        feature = {
            "type": "Feature",
            "properties": {"buffer_km": km, "purpose": "RoW" if km == 1 else "monitoring"},
            "geometry": mapping(buf_wgs),
        }
        fc = {"type": "FeatureCollection", "features": [feature]}
        (OUT_DIR / fname).write_text(json.dumps(fc, indent=2))
        print(f"✓ {fname}")

    return line_m, to_wgs


def build_aoi_tiles(line_m, to_wgs, tile_km=50):
    """Divide the corridor into analysis tiles so users can refresh a single segment."""
    total_len = line_m.length
    n_tiles = int(total_len // (tile_km * 1000)) + 1

    features = []
    for i in range(n_tiles):
        start = i * tile_km * 1000
        end = min((i + 1) * tile_km * 1000, total_len)
        if end - start < 1000:
            continue
        # Sample points along segment and buffer
        segment_pts = [line_m.interpolate(start + j * (end - start) / 20) for j in range(21)]
        segment = LineString([(p.x, p.y) for p in segment_pts])
        tile = segment.buffer(5000, cap_style=2, join_style=2)
        tile_wgs = transform(to_wgs, tile)
        features.append({
            "type": "Feature",
            "properties": {
                "tile_id": f"T{i+1:02d}",
                "start_km": round(start / 1000, 1),
                "end_km": round(end / 1000, 1),
                "last_scan": None,
                "anomaly_count": 0,
            },
            "geometry": mapping(tile_wgs),
        })

    fc = {"type": "FeatureCollection", "features": features}
    (OUT_DIR / "aoi_tiles.geojson").write_text(json.dumps(fc, indent=2))
    print(f"✓ aoi_tiles.geojson ({len(features)} tiles)")


def build_sample_anomalies(line):
    """Seed a few plausible anomalies for the baseline view."""
    random.seed(42)
    anomaly_types = [
        ("encroachment", "high", "New structure detected within 50m of RoW"),
        ("vegetation_loss", "medium", "NDVI drop >0.3 over 2 hectares"),
        ("excavation", "high", "Earthworks detected adjacent to pipeline"),
        ("vegetation_loss", "low", "Seasonal NDVI variation, likely benign"),
        ("encroachment", "medium", "Unauthorized road crossing RoW"),
        ("thermal_anomaly", "high", "Persistent thermal signature, possible leak"),
        ("excavation", "medium", "Agricultural deep-tilling near RoW"),
        ("encroachment", "low", "Small structure, pre-existing per archive"),
    ]

    features = []
    total_len = line.length
    for i, (atype, severity, desc) in enumerate(anomaly_types):
        # Place along route at varied positions
        frac = (i + 1) / (len(anomaly_types) + 1) + random.uniform(-0.03, 0.03)
        pt_on_line = line.interpolate(frac, normalized=True)
        # Offset slightly off the centerline
        offset_lon = pt_on_line.x + random.uniform(-0.01, 0.01)
        offset_lat = pt_on_line.y + random.uniform(-0.01, 0.01)

        features.append({
            "type": "Feature",
            "properties": {
                "id": f"ANM-{i+1:03d}",
                "type": atype,
                "severity": severity,
                "description": desc,
                "detected_at": "2026-04-15T10:30:00Z",
                "confidence": round(random.uniform(0.62, 0.94), 2),
                "source": "sentinel-1_change" if atype == "excavation" else "sentinel-2_ndvi",
                "status": "unreviewed",
            },
            "geometry": {"type": "Point", "coordinates": [offset_lon, offset_lat]},
        })

    fc = {"type": "FeatureCollection", "features": features}
    (OUT_DIR / "sample_anomalies.geojson").write_text(json.dumps(fc, indent=2))
    print(f"✓ sample_anomalies.geojson ({len(features)} anomalies)")


def main():
    print("Building pipeline corridor data...\n")
    line = build_pipeline_geojson()
    line_m, to_wgs = build_buffers(line)
    build_aoi_tiles(line_m, to_wgs)
    build_sample_anomalies(line)
    print(f"\n✓ All files written to {OUT_DIR.absolute()}")
    print("\nNext: copy the ./data folder into your backend project.")


if __name__ == "__main__":
    main()
