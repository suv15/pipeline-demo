"""
Full-Corridor Scan Script (Offline, One-Time)
----------------------------------------------
Simulates a complete Sentinel-1/Sentinel-2 analysis across all tiles
and produces cached results for the live demo backend.

Outputs (into ./data/):
  - full_scan_results.geojson  : ~45 anomalies distributed across tiles
  - scan_metadata.json         : timestamps, stats, tile-level summary

Run once:
  python run_full_scan.py

To swap in REAL Sentinel processing later, replace the body of
`analyze_tile()` with actual Copernicus STAC calls + change detection.
The rest of the pipeline stays identical.
"""

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

from shapely.geometry import shape, Point

DATA_DIR = Path("./data")

# ---- Anomaly generation config ----
ANOMALY_TEMPLATES = [
    {
        "type": "encroachment",
        "source": "sentinel-2_classification",
        "descriptions": [
            "New permanent structure detected within RoW",
            "Unauthorized construction adjacent to pipeline",
            "New road alignment crossing RoW",
            "Informal settlement expansion within buffer zone",
        ],
        "severity_weights": {"high": 0.5, "medium": 0.35, "low": 0.15},
        "confidence_range": (0.72, 0.94),
    },
    {
        "type": "vegetation_loss",
        "source": "sentinel-2_ndvi",
        "descriptions": [
            "NDVI drop >0.3 over contiguous 2+ hectare area",
            "Vegetation clearing detected along RoW corridor",
            "Significant canopy loss, possible right-of-way violation",
            "Seasonal NDVI variation within expected range",
        ],
        "severity_weights": {"high": 0.2, "medium": 0.45, "low": 0.35},
        "confidence_range": (0.65, 0.90),
    },
    {
        "type": "excavation",
        "source": "sentinel-1_coherence",
        "descriptions": [
            "SAR coherence loss indicating recent earthworks",
            "Deep tilling or excavation within 100m of RoW",
            "Construction-scale ground disturbance detected",
            "Agricultural deep-plowing near pipeline centerline",
        ],
        "severity_weights": {"high": 0.45, "medium": 0.4, "low": 0.15},
        "confidence_range": (0.68, 0.92),
    },
    {
        "type": "thermal_anomaly",
        "source": "viirs_thermal",
        "descriptions": [
            "Persistent thermal signature, investigate for leak",
            "Localized thermal anomaly, possible equipment issue",
            "Industrial heat source, likely adjacent facility",
        ],
        "severity_weights": {"high": 0.6, "medium": 0.3, "low": 0.1},
        "confidence_range": (0.55, 0.85),
    },
    {
        "type": "water_pooling",
        "source": "sentinel-1_backscatter",
        "descriptions": [
            "Unusual water accumulation near RoW, possible subsidence",
            "Seasonal water body expansion within buffer",
        ],
        "severity_weights": {"high": 0.3, "medium": 0.5, "low": 0.2},
        "confidence_range": (0.6, 0.82),
    },
]


def weighted_choice(weights_dict):
    items = list(weights_dict.keys())
    weights = list(weights_dict.values())
    return random.choices(items, weights=weights, k=1)[0]


def random_point_in_polygon(poly, max_attempts=100):
    """Generate a random point inside a polygon (rejection sampling)."""
    minx, miny, maxx, maxy = poly.bounds
    for _ in range(max_attempts):
        pt = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))
        if poly.contains(pt):
            return pt
    # Fallback: centroid
    return poly.centroid


def analyze_tile(tile_feature, scan_time):
    """
    Simulate analysis of one tile. Returns 0-4 anomalies.

    REPLACE THIS FUNCTION with real Copernicus STAC queries + SAR/optical
    change detection when wiring up live data. Signature stays the same.
    """
    tile_geom = shape(tile_feature["geometry"])
    tile_id = tile_feature["properties"]["tile_id"]

    # Distribution: most tiles have 1-2 anomalies, some have 0, a few have 3-4
    n_anomalies = random.choices([0, 1, 2, 3, 4], weights=[0.15, 0.35, 0.3, 0.15, 0.05], k=1)[0]

    # Weighted template selection — encroachment and vegetation loss are most common
    # in real pipeline monitoring, thermal and water less so
    template_weights = [0.30, 0.30, 0.20, 0.10, 0.10]

    anomalies = []
    for i in range(n_anomalies):
        template = random.choices(ANOMALY_TEMPLATES, weights=template_weights, k=1)[0]
        severity = weighted_choice(template["severity_weights"])
        description = random.choice(template["descriptions"])
        confidence = round(random.uniform(*template["confidence_range"]), 2)

        pt = random_point_in_polygon(tile_geom)

        # Detection time: within the last 7 days, skewed toward more recent
        hours_ago = int(random.triangular(1, 168, 24))
        detected_at = scan_time - timedelta(hours=hours_ago)

        # Area affected (hectares) — varies by type
        area_ha = {
            "encroachment": random.uniform(0.1, 2.5),
            "vegetation_loss": random.uniform(1.0, 12.0),
            "excavation": random.uniform(0.3, 4.0),
            "thermal_anomaly": random.uniform(0.05, 0.5),
            "water_pooling": random.uniform(0.5, 6.0),
        }[template["type"]]

        anomalies.append({
            "type": "Feature",
            "properties": {
                "id": f"ANM-{tile_id}-{i+1:02d}",
                "tile_id": tile_id,
                "type": template["type"],
                "severity": severity,
                "description": description,
                "detected_at": detected_at.isoformat() + "Z",
                "confidence": confidence,
                "source": template["source"],
                "area_hectares": round(area_ha, 2),
                "status": "unreviewed",
                "distance_to_pipeline_m": random.randint(15, 850),
            },
            "geometry": {
                "type": "Point",
                "coordinates": [round(pt.x, 6), round(pt.y, 6)],
            },
        })

    return anomalies


def main():
    random.seed(2026)
    print("Running full-corridor scan (simulated)...\n")

    tiles_path = DATA_DIR / "aoi_tiles.geojson"
    if not tiles_path.exists():
        print(f"ERROR: {tiles_path} not found. Run prep_pipeline_data.py first.")
        return

    tiles_fc = json.loads(tiles_path.read_text())
    tiles = tiles_fc["features"]

    scan_start = datetime.utcnow()
    all_anomalies = []
    tile_summaries = []

    for i, tile in enumerate(tiles):
        tile_id = tile["properties"]["tile_id"]
        # Simulate processing time (visible in the metadata, not in demo)
        time.sleep(0.02)

        anomalies = analyze_tile(tile, scan_start)
        all_anomalies.extend(anomalies)

        severity_counts = {"high": 0, "medium": 0, "low": 0}
        for a in anomalies:
            severity_counts[a["properties"]["severity"]] += 1

        tile_summaries.append({
            "tile_id": tile_id,
            "start_km": tile["properties"]["start_km"],
            "end_km": tile["properties"]["end_km"],
            "anomaly_count": len(anomalies),
            "severity_counts": severity_counts,
            "last_scanned": scan_start.isoformat() + "Z",
        })

        print(f"  [{i+1:2d}/{len(tiles)}] {tile_id} "
              f"({tile['properties']['start_km']:.0f}-{tile['properties']['end_km']:.0f} km): "
              f"{len(anomalies)} anomalies")

    scan_end = datetime.utcnow()
    duration_sec = (scan_end - scan_start).total_seconds()

    # Write full_scan_results.geojson
    results_fc = {
        "type": "FeatureCollection",
        "features": all_anomalies,
    }
    (DATA_DIR / "full_scan_results.geojson").write_text(json.dumps(results_fc, indent=2))

    # Aggregate stats
    type_counts = {}
    severity_totals = {"high": 0, "medium": 0, "low": 0}
    for a in all_anomalies:
        t = a["properties"]["type"]
        s = a["properties"]["severity"]
        type_counts[t] = type_counts.get(t, 0) + 1
        severity_totals[s] += 1

    # Write metadata
    metadata = {
        "scan_id": f"SCAN-{scan_start.strftime('%Y%m%d-%H%M%S')}",
        "scan_started_at": scan_start.isoformat() + "Z",
        "scan_completed_at": scan_end.isoformat() + "Z",
        "duration_seconds": round(duration_sec, 2),
        "tiles_processed": len(tiles),
        "total_km_monitored": 1870,
        "total_anomalies": len(all_anomalies),
        "anomalies_by_type": type_counts,
        "anomalies_by_severity": severity_totals,
        "sentinel_sources": {
            "sentinel-1_grd": "latest IW scenes, 12-day revisit",
            "sentinel-2_l2a": "latest cloud-free, 5-day revisit",
            "viirs_thermal": "daily composite",
        },
        "tile_summaries": tile_summaries,
    }
    (DATA_DIR / "scan_metadata.json").write_text(json.dumps(metadata, indent=2))

    print(f"\n✓ Full scan complete in {duration_sec:.1f}s")
    print(f"✓ Total anomalies: {len(all_anomalies)}")
    print(f"  - High severity:   {severity_totals['high']}")
    print(f"  - Medium severity: {severity_totals['medium']}")
    print(f"  - Low severity:    {severity_totals['low']}")
    print(f"✓ By type: {type_counts}")
    print(f"\n✓ Files: {DATA_DIR / 'full_scan_results.geojson'}")
    print(f"         {DATA_DIR / 'scan_metadata.json'}")


if __name__ == "__main__":
    main()
