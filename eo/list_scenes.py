"""
List Sentinel-2 L2A scenes over the IOCL Salaya-Mathura corridor.

Queries Microsoft Planetary Computer's STAC API for the last N days,
restricted to scenes intersecting the 5 km monitoring buffer.

Usage:
    python list_scenes.py [--days 30] [--max-cloud 30]

This is the first proof-of-life script for the EO pipeline. Once we
confirm we get real scenes back, the next step is downloading bands
and computing NDVI.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import planetary_computer
import pystac_client
from shapely.geometry import shape

# Resolve corridor AOI from the existing demo data
REPO_ROOT = Path(__file__).resolve().parent.parent
BUFFER_5KM_PATH = REPO_ROOT / "backend" / "data" / "buffer_5km.geojson"

STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"


def load_aoi() -> dict:
    """Load the 5 km monitoring buffer as a single GeoJSON geometry dict."""
    fc = json.loads(BUFFER_5KM_PATH.read_text())
    feats = fc.get("features", [])
    if not feats:
        sys.exit(f"No features in {BUFFER_5KM_PATH}")
    # Combine all features into a single MultiPolygon for the STAC query
    geoms = [shape(f["geometry"]) for f in feats]
    if len(geoms) == 1:
        return json.loads(json.dumps(geoms[0].__geo_interface__))
    from shapely.ops import unary_union
    return json.loads(json.dumps(unary_union(geoms).__geo_interface__))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30,
                        help="Look back this many days from today")
    parser.add_argument("--max-cloud", type=int, default=30,
                        help="Maximum cloud cover percent (eo:cloud_cover)")
    args = parser.parse_args()

    aoi = load_aoi()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    datetime_range = f"{start.isoformat()}/{end.isoformat()}"

    print(f"AOI: {BUFFER_5KM_PATH.name} (geometry type={aoi['type']})")
    print(f"Query: {COLLECTION}  {datetime_range}  cloud<={args.max_cloud}%")
    print(f"STAC : {STAC_API}\n")

    catalog = pystac_client.Client.open(
        STAC_API,
        modifier=planetary_computer.sign_inplace,
    )

    search = catalog.search(
        collections=[COLLECTION],
        intersects=aoi,
        datetime=datetime_range,
        query={"eo:cloud_cover": {"lt": args.max_cloud}},
    )

    items = list(search.items())
    print(f"Found {len(items)} scenes\n")
    print(f"{'date':<22} {'tile':<8} {'cloud%':>7}  id")
    print("-" * 90)
    for it in items[:50]:
        dt = it.datetime.strftime("%Y-%m-%d %H:%M")
        tile = it.properties.get("s2:mgrs_tile", "?")
        cc = it.properties.get("eo:cloud_cover", -1)
        print(f"{dt:<22} {tile:<8} {cc:>6.1f}  {it.id}")
    if len(items) > 50:
        print(f"... and {len(items)-50} more")


if __name__ == "__main__":
    main()
