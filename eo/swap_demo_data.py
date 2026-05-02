"""
Swap the demo's static anomaly data for the real Sentinel-2-derived
detections produced by batch_detect_corridor.py.

Reads:  eo/out/corridor_veg_loss.geojson   (Polygon features with rich props)
Writes: backend/data/full_scan_results.geojson   (Point features the frontend
                                                   expects: id, severity,
                                                   confidence, type, ...)
        backend/data/scan_metadata.json          (refreshed timestamps,
                                                   anomaly counts, etc.)

Behaviour:
  - Each detected polygon becomes a single Point at its centroid.
  - All real properties from detection are preserved (ndvi_drop_mean,
    distance_to_pipeline_m, before/after scene IDs, dates, etc.).
  - tile_id is computed as T01..T25 by snapping each centroid onto the
    pipeline centerline, taking distance-along-line, dividing into
    50 km buckets — matching the existing demo's 25-tile scheme.
  - scan_metadata.json gets refreshed with current timestamps and the
    real anomaly totals so the frontend's headline stats line up.

Usage:
    python swap_demo_data.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyproj
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = Path(__file__).resolve().parent / "out" / "corridor_veg_loss.geojson"
OUT_FEATURES = REPO_ROOT / "backend" / "data" / "full_scan_results.geojson"
OUT_METADATA = REPO_ROOT / "backend" / "data" / "scan_metadata.json"
PIPELINE_PATH = REPO_ROOT / "backend" / "data" / "pipeline.geojson"

TILE_LENGTH_KM = 50.0
N_TILES = 25  # T01..T25 like the existing demo


def load_pipeline_line() -> LineString:
    fc = json.loads(PIPELINE_PATH.read_text())
    geom = shape(fc["features"][0]["geometry"])
    if isinstance(geom, LineString):
        return geom
    # MultiLineString → unary_union into a single line if connected
    return geom


def centroid_lonlat(feat) -> tuple[float, float]:
    pt = shape(feat["geometry"]).centroid
    return float(pt.x), float(pt.y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print stats but don't overwrite backend/data files")
    args = ap.parse_args()

    if not INPUT_PATH.exists():
        sys.exit(f"Missing {INPUT_PATH} — run batch_detect_corridor.py first.")

    src = json.loads(INPUT_PATH.read_text())
    poly_features = src.get("features", [])
    print(f"Loaded {len(poly_features)} polygon detections from "
          f"{INPUT_PATH.relative_to(REPO_ROOT)}")

    if not poly_features:
        sys.exit("No detections — nothing to swap.")

    # Build a metric-CRS line for distance-along-line computation.
    # Web Mercator is fine here — we only need rough km offsets.
    pipe = load_pipeline_line()
    to_m = pyproj.Transformer.from_crs(
        "EPSG:4326", "EPSG:3857", always_xy=True
    ).transform
    pipe_m = shapely_transform(to_m, pipe)
    pipe_m_length_km = pipe_m.length / 1000.0
    print(f"Pipeline length (Web Mercator approximation): "
          f"{pipe_m_length_km:.1f} km")

    point_features = []
    sev_counts = {"high": 0, "medium": 0, "low": 0}
    type_counts: dict[str, int] = {}
    mgrs_tiles_seen: set[str] = set()
    most_recent_after = ""

    for i, feat in enumerate(poly_features):
        props = dict(feat["properties"])  # shallow copy
        lon, lat = centroid_lonlat(feat)

        # Distance along pipeline → T01..T25
        cent_m = shapely_transform(to_m, Point(lon, lat))
        dist_along_km = pipe_m.project(cent_m) / 1000.0
        tile_idx = min(N_TILES, max(1, int(dist_along_km // TILE_LENGTH_KM) + 1))
        props["tile_id"] = f"T{tile_idx:02d}"

        # Track the MGRS tile separately; useful for ops/debug
        mgrs = props.get("tile_id_mgrs") or props.pop("tile_id_mgrs", None)
        # The detector wrote MGRS to props["tile_id"]; we just overwrote it.
        # Recover it from the ID we synthesized in the merge step.
        if "_id_full" not in props:
            mgrs_from_id = None
            stable_id = props.get("id", "")
            # IDs look like "S2-VEG-43QDE-20260501-001"
            parts = stable_id.split("-")
            if len(parts) >= 3:
                mgrs_from_id = parts[2]
            if mgrs_from_id:
                props["mgrs_tile"] = mgrs_from_id
                mgrs_tiles_seen.add(mgrs_from_id)

        # Severity / type bookkeeping
        sev = props.get("severity", "low")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
        atype = props.get("type", "unknown")
        type_counts[atype] = type_counts.get(atype, 0) + 1

        # Track most-recent acquisition for "last_scan_at"
        after_iso = props.get("after_acquisition", "")
        if after_iso > most_recent_after:
            most_recent_after = after_iso

        # Round/normalize a few numeric props for display
        if isinstance(props.get("distance_to_pipeline_m"), (int, float)):
            props["distance_to_pipeline_m"] = round(
                float(props["distance_to_pipeline_m"])
            )

        # Final feature: Point geometry, retain all real props
        point_features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": props,
        })

    print(f"\nDetections by severity: {sev_counts}")
    print(f"Detections by type:     {type_counts}")
    print(f"MGRS tiles represented: {len(mgrs_tiles_seen)} "
          f"({sorted(mgrs_tiles_seen)})")
    print(f"Most recent S2 acquisition: {most_recent_after[:19]}Z")

    out_fc = {"type": "FeatureCollection", "features": point_features}

    # Build refreshed metadata (the FastAPI backend re-derives counts
    # from features at request time; we still update the scalars).
    now = datetime.now(timezone.utc)
    new_metadata = {
        "scan_id": f"S2-{now.strftime('%Y%m%d-%H%M%S')}",
        "scan_started_at": now.isoformat().replace("+00:00", "Z"),
        "scan_completed_at": now.isoformat().replace("+00:00", "Z"),
        "duration_seconds": 0.0,  # batch takes ~10 min; not relevant in UI
        "tiles_processed": len(mgrs_tiles_seen),
        "total_km_monitored": 1870,
        "total_anomalies": len(point_features),
        "anomalies_by_type": type_counts,
        "anomalies_by_severity": sev_counts,
        "sentinel_sources": {
            "sentinel-2_l2a": (
                "Real NDVI difference, Microsoft Planetary Computer, "
                "5-day revisit, latest cloud-free pair per MGRS tile"
            ),
        },
        "most_recent_acquisition": most_recent_after,
        # Existing tile_summaries are stale (T01..T25, demo only). Drop them
        # rather than fake them — the frontend's headline bar doesn't read
        # this array.
        "tile_summaries": [],
    }

    if args.dry_run:
        print("\n--dry-run: not writing files. Sample feature:")
        print(json.dumps(point_features[0], indent=2)[:1500])
        return

    OUT_FEATURES.write_text(json.dumps(out_fc))
    OUT_METADATA.write_text(json.dumps(new_metadata, indent=2))
    print(f"\nWrote {OUT_FEATURES.relative_to(REPO_ROOT)} "
          f"({OUT_FEATURES.stat().st_size:,} bytes)")
    print(f"Wrote {OUT_METADATA.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
