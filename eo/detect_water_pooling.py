"""
Detect new water pooling from a pair of Sentinel-2 L2A scenes.

NDWI (McFeeters, 1996) = (Green - NIR) / (Green + NIR)
  - Low (<0)        = vegetation / dry land
  - Mid (0 to 0.3)  = wet soil, mixed
  - High (> 0.3)    = open water

Water pooling = NDWI is high in the after scene but was NOT high in the
before scene. Same tile/scene-pair logic as the NDVI veg-loss detector,
but reads Green (B03) instead of Red (B04) and flips the threshold sign:
NDWI rose by >= --ndwi-rise AND prior NDWI < --max-prior-ndwi.

Same proximity filter (drop polygons further than --max-pipeline-dist-m
from the pipeline; bump severity inside the 1 km RoW).

Output: eo/out/water_pooling_<tile>_<beforeDate>_to_<afterDate>.geojson

Usage:
    python detect_water_pooling.py --tile 43QDE
    python detect_water_pooling.py --tile 42QYL --ndwi-rise 0.25 --min-area-ha 0.3
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
    # Retry on transient timeouts (STAC API occasionally returns 504 under load).
    import time as _time
    from pystac_client.exceptions import APIError
    last_err = None
    for attempt in range(3):
        try:
            search = catalog.search(
                collections=[COLLECTION],
                datetime=f"{start.isoformat()}/{end.isoformat()}",
                query={
                    "eo:cloud_cover": {"lt": max_cloud},
                    "s2:mgrs_tile": {"eq": tile_id},
                },
            )
            items = sorted(search.items(), key=lambda i: i.datetime, reverse=True)
            break
        except APIError as e:
            last_err = e
            if attempt < 2:
                wait = 5 * (2 ** attempt)
                print(f"      STAC retry {attempt+1}/3 after {wait}s: {e}",
                      flush=True)
                _time.sleep(wait)
            else:
                raise
    if len(items) < 2:
        sys.exit(f"Only {len(items)} cloud-free scenes for tile {tile_id} — need 2.")
    after = items[0]
    before = next(
        (i for i in items[1:] if (after.datetime - i.datetime).days >= min_gap_days),
        items[-1],
    )
    return before, after


# GDAL/CURL tuning for streaming COG reads from Planetary Computer.
# These shave a lot of latency off the open() handshake and let slow links
# survive transient hiccups instead of dying mid-tile.
_RIO_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff",
    GDAL_HTTP_MAX_RETRY=5,
    GDAL_HTTP_RETRY_DELAY=2,
    GDAL_HTTP_TIMEOUT=120,
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    VSI_CACHE=True,
    VSI_CACHE_SIZE=67108864,  # 64 MB per-file cache
    GDAL_CACHEMAX=512,
)


def read_band_window(item, band_name, aoi_geom_4326, retries: int = 2):
    """Read a Sentinel-2 band, windowed to the AOI bbox (in image CRS).

    Retries on transient HTTP errors that occasionally surface from
    Planetary Computer's blob backend during heavy parallel reads.
    """
    import time as _time
    asset = item.assets[band_name]
    last_err = None
    for attempt in range(retries + 1):
        try:
            with rasterio.Env(**_RIO_ENV):
                with rasterio.open(asset.href) as src:
                    aoi_bounds = transform_bounds(
                        "EPSG:4326", src.crs, *aoi_geom_4326.bounds
                    )
                    window = window_from_bounds(
                        *aoi_bounds, transform=src.transform
                    )
                    window = window.round_offsets().round_lengths().intersection(
                        rasterio.windows.Window(0, 0, src.width, src.height)
                    )
                    data = src.read(1, window=window).astype("float32")
                    win_transform = src.window_transform(window)
                    return data, win_transform, src.crs
        except (rasterio.errors.RasterioIOError, OSError) as e:
            last_err = e
            if attempt < retries:
                wait = 4 * (2 ** attempt)
                print(f"      band-read retry {attempt+1}/{retries} "
                      f"({band_name}) after {wait}s: {type(e).__name__}: {e}",
                      flush=True)
                _time.sleep(wait)
            else:
                raise


def ndwi(green, nir):
    """McFeeters NDWI: (Green - NIR) / (Green + NIR). Range [-1, 1]; >0.3 = water."""
    denom = nir + green
    out = np.zeros_like(denom, dtype="float32")
    np.divide(green - nir, denom, out=out, where=denom > 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tile", default="43QDE",
                    help="MGRS tile id (e.g. 43QDE, 42QYL)")
    ap.add_argument("--max-cloud", type=float, default=10,
                    help="Max cloud cover percent for scene selection")
    ap.add_argument("--min-gap-days", type=int, default=10,
                    help="Minimum days between before/after scenes")
    ap.add_argument("--ndwi-rise", type=float, default=0.30,
                    help="Minimum NDWI rise (after - before) to flag")
    ap.add_argument("--max-prior-ndwi", type=float, default=0.10,
                    help="Maximum NDWI in the BEFORE scene — anything wetter "
                         "than this was already water, not new pooling")
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

    print(f"[3/6] Reading Green (B03) + NIR (B08) windowed to corridor ...")
    grn_b, win_t, win_crs = read_band_window(before, "B03", clipped)
    nir_b, _, _ = read_band_window(before, "B08", clipped)
    grn_a, _, _ = read_band_window(after, "B03", clipped)
    nir_a, _, _ = read_band_window(after, "B08", clipped)
    print(f"      array shape: {grn_b.shape}  dtype: {grn_b.dtype}")

    print("[4/6] Computing NDWI difference ...")
    ndwi_b = ndwi(grn_b, nir_b)
    ndwi_a = ndwi(grn_a, nir_a)
    diff = ndwi_a - ndwi_b
    valid = (grn_b > 0) & (grn_a > 0)
    diff_valid = diff[valid]
    print(f"      NDWI before: mean={ndwi_b[valid].mean():+.3f}  std={ndwi_b[valid].std():.3f}")
    print(f"      NDWI after : mean={ndwi_a[valid].mean():+.3f}  std={ndwi_a[valid].std():.3f}")
    print(f"      NDWI diff  : min={diff_valid.min():+.3f}  max={diff_valid.max():+.3f}  mean={diff_valid.mean():+.3f}")

    # Water-pooling mask: NDWI rose by >= threshold AND was not already wet
    # in the before scene (so we don't double-count permanent waterbodies).
    rise = (diff >= args.ndwi_rise) & (ndwi_b < args.max_prior_ndwi) & valid
    print(f"      pixels with NDWI rise ≥ {args.ndwi_rise} (and prior <{args.max_prior_ndwi}): "
          f"{int(rise.sum()):,} / {rise.size:,} "
          f"({100 * rise.sum() / rise.size:.3f}%)")

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

    mask_u8 = rise.astype("uint8")
    detections = []
    skipped_far = 0
    for geom, _val in shapes(mask_u8, mask=(mask_u8 == 1), transform=win_t):
        poly_utm = shape(geom)
        area_m2 = poly_utm.area
        if area_m2 < args.min_area_ha * 10_000:
            continue
        # Same proximity filter as the veg detector.
        dist_m = poly_utm.distance(pipe_utm)
        if dist_m > args.max_pipeline_dist_m:
            skipped_far += 1
            continue
        geom_4326 = transform_geom(win_crs, "EPSG:4326", geom)

        # Mean NDWI rise inside the polygon (positive sign), via the polygon's
        # bbox window into the diff array.
        minx, miny, maxx, maxy = poly_utm.bounds
        col_min = int((minx - win_t.c) / win_t.a)
        row_min = int((miny - win_t.f) / win_t.e)
        col_max = int((maxx - win_t.c) / win_t.a)
        row_max = int((maxy - win_t.f) / win_t.e)
        r0, r1 = sorted((max(0, row_min), min(diff.shape[0], row_max)))
        c0, c1 = sorted((max(0, col_min), min(diff.shape[1], col_max)))
        ndwi_rise_mean = float(diff[r0:r1, c0:c1][rise[r0:r1, c0:c1]].mean()) if (r1 > r0 and c1 > c0) else None

        # Severity from NDWI rise magnitude. Water pooling is a sharper
        # signal than veg change — a rise of 0.45+ is an unambiguous new
        # waterbody. Scaled accordingly.
        if ndwi_rise_mean is not None and ndwi_rise_mean >= 0.45:
            severity = "high"
        elif ndwi_rise_mean is not None and ndwi_rise_mean >= 0.35:
            severity = "medium"
        else:
            severity = "low"
        if dist_m <= 1000:
            severity = {"low": "medium", "medium": "high", "high": "high"}[severity]
        prox_bonus = 0.10 if dist_m <= 1000 else (0.05 if dist_m <= 1500 else 0)
        confidence = round(min(0.98, 0.55 + (ndwi_rise_mean or 0) + prox_bonus), 2)

        detections.append({
            "type": "Feature",
            "geometry": geom_4326,
            "properties": {
                "type": "water_pooling",
                "severity": severity,
                "confidence": confidence,
                "ndwi_rise_mean": round(ndwi_rise_mean, 3) if ndwi_rise_mean is not None else None,
                "area_m2": round(area_m2, 1),
                "area_hectares": round(area_m2 / 10_000, 3),
                "distance_to_pipeline_m": round(dist_m, 1),
                "within_row_1km": dist_m <= 1000,
                "before_acquisition": before.datetime.isoformat(),
                "after_acquisition": after.datetime.isoformat(),
                "before_scene_id": before.id,
                "after_scene_id": after.id,
                "tile_id": args.tile,
                "source": "sentinel-2-l2a_ndwi",
            },
        })

    print(f"      {len(detections)} polygons passed area + proximity filter")
    print(f"      ({skipped_far} polygons skipped: farther than "
          f"{args.max_pipeline_dist_m:.0f} m from pipeline)")

    print("[6/6] Writing output ...")
    fc = {"type": "FeatureCollection", "features": detections}
    out_path = OUT_DIR / f"water_pooling_{args.tile}_{before.datetime.date()}_to_{after.datetime.date()}.geojson"
    out_path.write_text(json.dumps(fc, indent=2))
    print(f"\n→ {out_path}")
    print(f"   {len(detections)} water-pooling polygons")


if __name__ == "__main__":
    main()
