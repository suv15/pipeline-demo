"""
Batch vegetation-loss detection across every MGRS tile intersecting the
IOCL Salaya-Mathura corridor.

  1. Discovers tiles by running one STAC query intersecting the 5 km buffer
     for a recent ~14-day window (any cloud cover) and collecting unique
     s2:mgrs_tile values.
  2. For each tile, shells out to detect_veg_loss.py with the supplied args.
  3. Reads every per-tile GeoJSON written by those runs and merges into a
     single corridor-wide FeatureCollection at eo/out/corridor_veg_loss.geojson.

Why subprocess instead of importing? — keeps detect_veg_loss.py runnable
standalone, isolates per-tile failures, and gives us per-tile log output for
debugging without restructuring the detector.

Usage:
    python batch_detect_corridor.py
        [--min-gap-days 25] [--max-cloud 10]
        [--ndvi-drop 0.20] [--min-area-ha 0.5]
        [--max-pipeline-dist-m 1500] [--lookback-days 60]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import planetary_computer
import pystac_client
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).resolve().parent.parent
EO_DIR = Path(__file__).resolve().parent
OUT_DIR = EO_DIR / "out"
BUFFER_5KM_PATH = REPO_ROOT / "backend" / "data" / "buffer_5km.geojson"
DETECTOR = EO_DIR / "detect_veg_loss.py"
PYTHON = EO_DIR / ".venv" / "bin" / "python"
STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
COMBINED_OUT = OUT_DIR / "corridor_veg_loss.geojson"


def load_aoi():
    fc = json.loads(BUFFER_5KM_PATH.read_text())
    geoms = [shape(f["geometry"]) for f in fc["features"]]
    return unary_union(geoms) if len(geoms) > 1 else geoms[0]


def discover_tiles(aoi, lookback_days: int = 14) -> list[str]:
    """Return unique MGRS tile IDs that intersect the corridor AOI."""
    catalog = pystac_client.Client.open(
        STAC_API, modifier=planetary_computer.sign_inplace
    )
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    search = catalog.search(
        collections=[COLLECTION],
        intersects=mapping(aoi),
        datetime=f"{start.isoformat()}/{end.isoformat()}",
    )
    tiles = set()
    for it in search.items():
        t = it.properties.get("s2:mgrs_tile")
        if t:
            tiles.add(t)
    return sorted(tiles)


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_detector(tile: str, args, log_dir: Path) -> Path | None:
    """Run detect_veg_loss.py for one tile. Returns the output GeoJSON path or None.

    Uses python -u so per-tile logs stream live. Captures full stdout+stderr
    to logs/<tile>.log for post-mortem on failures (timeouts, no scene pair,
    etc).
    """
    cmd = [
        str(PYTHON), "-u", str(DETECTOR),
        "--tile", tile,
        "--min-gap-days", str(args.min_gap_days),
        "--max-cloud", str(args.max_cloud),
        "--ndvi-drop", str(args.ndvi_drop),
        "--min-area-ha", str(args.min_area_ha),
        "--max-pipeline-dist-m", str(args.max_pipeline_dist_m),
        "--lookback-days", str(args.lookback_days),
    ]
    log_path = log_dir / f"{tile}.log"
    print(f"[{_stamp()}] {tile}: starting", flush=True)
    t0 = time.time()
    try:
        with log_path.open("w") as fp:
            proc = subprocess.run(
                cmd, stdout=fp, stderr=subprocess.STDOUT,
                text=True, timeout=args.per_tile_timeout,
            )
    except subprocess.TimeoutExpired:
        print(f"[{_stamp()}] {tile}: TIMEOUT after "
              f"{args.per_tile_timeout}s (log: {log_path.name})", flush=True)
        return None
    elapsed = time.time() - t0

    log_text = log_path.read_text()
    if proc.returncode != 0:
        last = log_text.strip().splitlines()[-3:]
        print(f"[{_stamp()}] {tile}: FAILED ({elapsed:.0f}s) — "
              f"{' | '.join(last)}", flush=True)
        return None

    # Parse output path from the detector's last "→" line
    out_path = None
    for line in log_text.splitlines():
        line = line.strip()
        if line.startswith("→") and ".geojson" in line:
            out_path = Path(line.split("→", 1)[1].strip())
            break
    if out_path is None or not out_path.exists():
        print(f"[{_stamp()}] {tile}: WARN ({elapsed:.0f}s) — "
              f"output path not found in log", flush=True)
        return None

    summary = next(
        (l.strip() for l in reversed(log_text.splitlines())
         if "polygons" in l), "?"
    )
    print(f"[{_stamp()}] {tile}: OK ({elapsed:.0f}s) — {summary}", flush=True)
    return out_path


def merge(per_tile_paths: list[Path]) -> dict:
    """Merge per-tile FeatureCollections into one corridor-wide collection."""
    features = []
    for p in per_tile_paths:
        try:
            fc = json.loads(p.read_text())
        except Exception as e:
            print(f"  skip {p.name}: {e}")
            continue
        for i, feat in enumerate(fc.get("features", [])):
            props = feat["properties"]
            tile_id = props.get("tile_id", "?")
            after_dt = props.get("after_acquisition", "")[:10]
            # Synthesize a stable id and a few demo-friendly fields
            props["id"] = f"S2-VEG-{tile_id}-{after_dt.replace('-','')}-{i+1:03d}"
            props.setdefault("status", "unreviewed")
            props.setdefault("detected_at",
                             datetime.now(timezone.utc).isoformat()
                             .replace("+00:00", "Z"))
            ndvi_drop = props.get("ndvi_drop_mean")
            ha = props.get("area_hectares")
            dist = props.get("distance_to_pipeline_m")
            props.setdefault(
                "description",
                f"NDVI dropped {ndvi_drop:+.2f} over {ha} ha "
                f"({dist:.0f} m from pipeline) between "
                f"{props.get('before_acquisition','')[:10]} and {after_dt}",
            )
            features.append(feat)
    return {"type": "FeatureCollection", "features": features}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-gap-days", type=int, default=25)
    ap.add_argument("--max-cloud", type=float, default=10)
    ap.add_argument("--ndvi-drop", type=float, default=0.20)
    ap.add_argument("--min-area-ha", type=float, default=0.5)
    ap.add_argument("--max-pipeline-dist-m", type=float, default=1500)
    ap.add_argument("--lookback-days", type=int, default=60)
    ap.add_argument("--only-tiles", default="",
                    help="Comma-separated tile IDs (skip discovery)")
    ap.add_argument("--workers", type=int, default=4,
                    help="Parallel detector workers (network-IO-bound)")
    ap.add_argument("--per-tile-timeout", type=int, default=420,
                    help="Per-tile subprocess timeout in seconds")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    log_dir = OUT_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    if args.only_tiles:
        tiles = [t.strip() for t in args.only_tiles.split(",") if t.strip()]
        print(f"Using {len(tiles)} tile(s) from --only-tiles", flush=True)
    else:
        print("Discovering MGRS tiles intersecting the corridor...", flush=True)
        aoi = load_aoi()
        tiles = discover_tiles(aoi)
        print(f"Found {len(tiles)} tiles", flush=True)
    print(f"Tiles: {tiles}", flush=True)
    print(f"Workers: {args.workers}   per-tile timeout: "
          f"{args.per_tile_timeout}s   log dir: {log_dir}", flush=True)

    paths: list[Path] = []
    completed = 0
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(run_detector, t, args, log_dir): t for t in tiles}
        for fut in as_completed(futures):
            completed += 1
            tile = futures[fut]
            out = fut.result()
            if out is not None:
                paths.append(out)
            elapsed_total = time.time() - t_start
            print(f"  -- progress: {completed}/{len(tiles)} done "
                  f"({len(paths)} produced output) "
                  f"after {elapsed_total/60:.1f} min", flush=True)

    print(f"\nMerging {len(paths)} per-tile outputs ...")
    fc = merge(paths)
    COMBINED_OUT.write_text(json.dumps(fc, separators=(",", ":")))
    print(f"\nWrote {COMBINED_OUT}")
    print(f"  total features: {len(fc['features'])}")

    # Severity summary
    from collections import Counter
    sev = Counter(f["properties"]["severity"] for f in fc["features"])
    in_row = sum(1 for f in fc["features"]
                 if f["properties"].get("within_row_1km"))
    print(f"  by severity   : {dict(sev)}")
    print(f"  inside RoW    : {in_row} / {len(fc['features'])}")


if __name__ == "__main__":
    sys.exit(main())
