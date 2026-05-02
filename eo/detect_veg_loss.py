"""
Detect vegetation loss from a pair of Sentinel-2 L2A scenes.

For a given MGRS tile that intersects the IOCL Salaya-Mathura corridor:
  1. Find the two most recent cloud-free scenes (newer + ~10-20 days prior)
  2. Read Red (B04) + NIR (B08), windowed to the corridor 5 km buffer
  3. Compute NDVI for each, then NDVI difference (after - before)
  4. Threshold: pixels where NDVI dropped by >= --ndvi-drop are flagged
  5. Vectorize contiguous regions, filter by minimum area
  6. Write GeoJSON in EPSG:4326 with attribution to source scenes

Output: eo/out/veg_loss_<tile>_<beforeDate>_to_<afterDate>.geojson

Usage:
    python detect_veg_loss.py --tile 43QDE
    python detect_veg_loss.py --tile 42QYL --ndvi-drop 0.15 --min-area-ha 0.3
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from rasterio.features import shapes
from rasterio.warp import transform_bounds, transform_geom
from rasterio.windows import from_bounds as window_from_bounds
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).resolve().parent.parent
BUFFER_5KM_PATH = REPO_ROOT / "backend" / "data" / "buffer_5km.geojson"
PIPELINE_PATH = REPO_ROOT / "backend" / "data" / "pipeline.geojson"
STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
OUT_DIR = Path(__file__).resolve().parent / "out"


def load_aoi():
    fc = json.loads(BUFFER_5KM_PATH.read_text())
    geoms = [shape(f["geometry"]) for f in fc["features"]]
    return unary_union(geoms) if len(geoms) > 1 else geoms[0]


def load_pipeline():
    """Load the pipeline centerline as a single shapely geometry (WGS84)."""
    fc = json.loads(PIPELINE_PATH.read_text())
    geoms = [shape(f["geometry"]) for f in fc["features"]]
    return unary_union(geoms) if len(geoms) > 1 else geoms[0]


def find_scene_pair(catalog, aoi, tile_id, max_cloud, min_gap_days, lookback_days=180):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    # NOTE: When restricting by s2:mgrs_tile, do NOT pass intersects= — the tile
    # id alone gives a tight geographic filter, and the corridor polygon
    # combined with a long lookback will time out Planetary Computer's STAC API.
    search = catalog.search(
        collections=[COLLECTION],
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={
            "eo:cloud_cover": {"lt": max_cloud},
            "s2:mgrs_tile": {"eq": tile_id},
        },
    )
    items = sorted(search.items(), key=lambda i: i.datetime, reverse=True)
    if len(items) < 2:
        sys.exit(f"Only {len(items)} cloud-free scenes for tile {tile_id} — need 2.")
    after = items[0]
    before = next(
        (i for i in items[1:] if (after.datetime - i.datetime).days >= min_gap_days),
        items[-1],
    )
    return before, after


def read_band_window(item, band_name, aoi_geom_4326):
    """Read a Sentinel-2 band, windowed to the AOI bbox (in image CRS)."""
    asset = item.assets[band_name]
    with rasterio.open(asset.href) as src:
        # AOI bbox in image CRS
        aoi_bounds = transform_bounds("EPSG:4326", src.crs, *aoi_geom_4326.bounds)
        window = window_from_bounds(*aoi_bounds, transform=src.transform)
        # Round window to integer pixel boundaries, intersect with image
        window = window.round_offsets().round_lengths().intersection(
            rasterio.windows.Window(0, 0, src.width, src.height)
        )
        data = src.read(1, window=window).astype("float32")
        win_transform = src.window_transform(window)
        return data, win_transform, src.crs


def ndvi(red, nir):
    denom = nir + red
    out = np.zeros_like(denom, dtype="float32")
    np.divide(nir - red, denom, out=out, where=denom > 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tile", default="43QDE",
                    help="MGRS tile id (e.g. 43QDE, 42QYL)")
    ap.add_argument("--max-cloud", type=float, default=10,
                    help="Max cloud cover percent for scene selection")
    ap.add_argument("--min-gap-days", type=int, default=10,
                    help="Minimum days between before/after scenes")
    ap.add_argument("--ndvi-drop", type=float, default=0.20,
                    help="Minimum NDVI drop to flag as veg loss")
    ap.add_argument("--min-area-ha", type=float, default=0.5,
                    help="Minimum contiguous area (hectares) to flag")
    ap.add_argument("--lookback-days", type=int, default=180,
                    help="How far back to search the STAC catalog")
    ap.add_argument("--max-pipeline-dist-m", type=float, default=1500,
                    help="Max distance from pipeline centerline to keep a "
                         "detection (m). 1000m = within RoW; 1500m default "
                         "gives a small margin. Set 5000 to keep all in buffer.")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    aoi = load_aoi()
    pipeline = load_pipeline()

    print(f"[1/6] Searching Planetary Computer for tile {args.tile} ...")
    catalog = pystac_client.Client.open(STAC_API, modifier=planetary_computer.sign_inplace)
    before, after = find_scene_pair(catalog, aoi, args.tile, args.max_cloud, args.min_gap_days, args.lookback_days)
    gap = (after.datetime - before.datetime).days
    print(f"      before: {before.datetime.date()}  cloud={before.properties['eo:cloud_cover']:>5.1f}%  {before.id}")
    print(f"      after : {after.datetime.date()}  cloud={after.properties['eo:cloud_cover']:>5.1f}%  {after.id}")
    print(f"      gap   : {gap} days")

    # Clip AOI to tile footprint to skip pixels outside the tile
    tile_geom = shape(after.geometry)
    clipped = aoi.intersection(tile_geom)
    if clipped.is_empty:
        sys.exit("Corridor 5 km buffer doesn't intersect this tile.")
    print(f"[2/6] AOI ∩ tile bbox: {clipped.bounds}")

    print(f"[3/6] Reading Red (B04) + NIR (B08) windowed to corridor ...")
    red_b, win_t, win_crs = read_band_window(before, "B04", clipped)
    nir_b, _, _ = read_band_window(before, "B08", clipped)
    red_a, _, _ = read_band_window(after, "B04", clipped)
    nir_a, _, _ = read_band_window(after, "B08", clipped)
    print(f"      array shape: {red_b.shape}  dtype: {red_b.dtype}")

    print("[4/6] Computing NDVI difference ...")
    ndvi_b = ndvi(red_b, nir_b)
    ndvi_a = ndvi(red_a, nir_a)
    diff = ndvi_a - ndvi_b
    valid = (red_b > 0) & (red_a > 0)
    diff_valid = diff[valid]
    print(f"      NDVI before: mean={ndvi_b[valid].mean():+.3f}  std={ndvi_b[valid].std():.3f}")
    print(f"      NDVI after : mean={ndvi_a[valid].mean():+.3f}  std={ndvi_a[valid].std():.3f}")
    print(f"      NDVI diff  : min={diff_valid.min():+.3f}  max={diff_valid.max():+.3f}  mean={diff_valid.mean():+.3f}")

    # Build loss mask (only within valid area)
    loss = (diff <= -args.ndvi_drop) & valid
    print(f"      pixels with NDVI drop ≥ {args.ndvi_drop}: {int(loss.sum()):,} / {loss.size:,} "
          f"({100 * loss.sum() / loss.size:.3f}%)")

    print("[5/6] Vectorizing detections ...")
    px_w = abs(win_t.a)
    px_h = abs(win_t.e)
    pixel_area_m2 = px_w * px_h
    min_pixels = max(1, int(args.min_area_ha * 10_000 / pixel_area_m2))
    print(f"      pixel size: {px_w:.1f}m × {px_h:.1f}m   min pixels for {args.min_area_ha} ha: {min_pixels}")

    # Reproject the pipeline centerline to the tile's UTM CRS once,
    # so we can do polygon→pipeline distance checks in metres.
    pipe_utm = shape(transform_geom("EPSG:4326", win_crs, mapping(pipeline)))
    print(f"      pipeline length within tile bbox: {pipe_utm.length:.0f} m")

    mask_u8 = loss.astype("uint8")
    detections = []
    skipped_far = 0
    for geom, _val in shapes(mask_u8, mask=(mask_u8 == 1), transform=win_t):
        poly_utm = shape(geom)
        area_m2 = poly_utm.area
        if area_m2 < args.min_area_ha * 10_000:
            continue
        # Distance from this polygon to the pipeline centerline (UTM, metres).
        # This is THE single most important filter — without it, the detector
        # flags every harvested farm field for tens of km around. Pipeline
        # monitoring only cares about anomalies near the pipe.
        dist_m = poly_utm.distance(pipe_utm)
        if dist_m > args.max_pipeline_dist_m:
            skipped_far += 1
            continue
        # Compute NDVI stats inside the polygon to drive confidence/severity
        # (cheap approximation via the polygon's bbox window of the diff array)
        geom_4326 = transform_geom(win_crs, "EPSG:4326", geom)

        # Mean NDVI drop inside this polygon (rough, full-poly average)
        # We approximate by sampling the loss area inside the bbox of the polygon.
        minx, miny, maxx, maxy = poly_utm.bounds
        col_min = int((minx - win_t.c) / win_t.a)
        row_min = int((miny - win_t.f) / win_t.e)
        col_max = int((maxx - win_t.c) / win_t.a)
        row_max = int((maxy - win_t.f) / win_t.e)
        r0, r1 = sorted((max(0, row_min), min(diff.shape[0], row_max)))
        c0, c1 = sorted((max(0, col_min), min(diff.shape[1], col_max)))
        ndvi_drop_mean = float(-diff[r0:r1, c0:c1][loss[r0:r1, c0:c1]].mean()) if (r1 > r0 and c1 > c0) else None

        # Severity / confidence heuristics (will tune later)
        if ndvi_drop_mean is not None and ndvi_drop_mean >= 0.40:
            severity = "high"
        elif ndvi_drop_mean is not None and ndvi_drop_mean >= 0.28:
            severity = "medium"
        else:
            severity = "low"
        # Proximity bump: a drop right on top of the pipeline (within 1 km
        # right-of-way) is operationally more urgent than the same drop 3 km
        # away in a field, so escalate one level.
        if dist_m <= 1000:
            severity = {"low": "medium", "medium": "high", "high": "high"}[severity]
        # Confidence — scale base by NDVI drop magnitude, then nudge by
        # proximity (a drop on the RoW is a more confident *pipeline* anomaly).
        prox_bonus = 0.10 if dist_m <= 1000 else (0.05 if dist_m <= 1500 else 0)
        confidence = round(min(0.98, 0.55 + (ndvi_drop_mean or 0) + prox_bonus), 2)

        detections.append({
            "type": "Feature",
            "geometry": geom_4326,
            "properties": {
                "type": "vegetation_loss",
                "severity": severity,
                "confidence": confidence,
                "ndvi_drop_mean": round(ndvi_drop_mean, 3) if ndvi_drop_mean is not None else None,
                "area_m2": round(area_m2, 1),
                "area_hectares": round(area_m2 / 10_000, 3),
                "distance_to_pipeline_m": round(dist_m, 1),
                "within_row_1km": dist_m <= 1000,
                "before_acquisition": before.datetime.isoformat(),
                "after_acquisition": after.datetime.isoformat(),
                "before_scene_id": before.id,
                "after_scene_id": after.id,
                "tile_id": args.tile,
                "source": "sentinel-2-l2a",
            },
        })

    print(f"      {len(detections)} polygons passed area + proximity filter")
    print(f"      ({skipped_far} polygons skipped: farther than "
          f"{args.max_pipeline_dist_m:.0f} m from pipeline)")

    print("[6/6] Writing output ...")
    fc = {"type": "FeatureCollection", "features": detections}
    out_path = OUT_DIR / f"veg_loss_{args.tile}_{before.datetime.date()}_to_{after.datetime.date()}.geojson"
    out_path.write_text(json.dumps(fc, indent=2))
    print(f"\n→ {out_path}")
    print(f"   {len(detections)} vegetation-loss polygons")


if __name__ == "__main__":
    main()
