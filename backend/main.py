"""
Pipeline Monitoring Demo — Live Backend
----------------------------------------
FastAPI service for the semi-live demo.

Endpoints:
  GET  /api/baseline       — pipeline, buffers, tiles (instant)
  GET  /api/full_scan      — cached full-corridor results (instant)
  GET  /api/scan_metadata  — headline stats for the dashboard
  POST /api/refresh        — simulates a re-scan with subtle variation
                             (3-5s processing simulation, returns cached + jittered)

Run locally:
  pip install fastapi uvicorn pydantic
  uvicorn main:app --reload --port 8000

Deploy to Railway/Render:
  - Set start command: uvicorn main:app --host 0.0.0.0 --port $PORT
  - Upload the ./data folder with the repo
"""

import asyncio
import copy
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Pipeline Monitoring Demo API",
    description="Geospatial intelligence demo backend for IOCL Salaya-Mathura corridor",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://frontend-eosin-psi-29.vercel.app"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).parent / "data"


# ------- Data loaders (load once at startup, serve from memory) -------

def _load_json(name: str) -> dict:
    path = DATA_DIR / name
    if not path.exists():
        raise RuntimeError(f"Missing data file: {path}. Run prep + scan scripts first.")
    return json.loads(path.read_text())


BASELINE_CACHE: dict[str, Any] = {}
SCAN_CACHE: dict[str, Any] = {}


@app.on_event("startup")
def load_data() -> None:
    BASELINE_CACHE["pipeline"] = _load_json("pipeline.geojson")
    BASELINE_CACHE["buffer_1km"] = _load_json("buffer_1km.geojson")
    BASELINE_CACHE["buffer_5km"] = _load_json("buffer_5km.geojson")
    BASELINE_CACHE["tiles"] = _load_json("aoi_tiles.geojson")
    SCAN_CACHE["results"] = _load_json("full_scan_results.geojson")
    SCAN_CACHE["metadata"] = _load_json("scan_metadata.json")
    print(f"✓ Loaded {len(SCAN_CACHE['results']['features'])} anomalies")
    print(f"✓ Loaded {len(BASELINE_CACHE['tiles']['features'])} tiles")


# ------- Helpers -------

def _hours_since(iso_str: str) -> int:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return int((now - dt).total_seconds() // 3600)


def _jitter_scan(results: dict, seed_offset: int) -> dict:
    """
    Produce a subtly modified copy of the cached scan results for the
    'refresh' illusion. Changes:
      - Bumps detected_at timestamps closer to 'now'
      - Nudges 1-3 confidence scores
      - Possibly flips 1 severity (medium<->high)
      - Possibly adds 1 NEW anomaly or removes 1 LOW-severity one
    """
    rng = random.Random(seed_offset)
    jittered = copy.deepcopy(results)
    features = jittered["features"]

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # 1. Freshen some timestamps
    for feat in rng.sample(features, min(5, len(features))):
        feat["properties"]["detected_at"] = now_iso

    # 2. Nudge 1-3 confidence scores
    for feat in rng.sample(features, rng.randint(1, 3)):
        delta = rng.choice([-0.04, -0.02, 0.02, 0.03])
        old = feat["properties"]["confidence"]
        feat["properties"]["confidence"] = round(max(0.5, min(0.98, old + delta)), 2)

    # 3. Possibly flip one severity
    if rng.random() < 0.4 and features:
        feat = rng.choice(features)
        if feat["properties"]["severity"] == "medium":
            feat["properties"]["severity"] = "high"
        elif feat["properties"]["severity"] == "high" and rng.random() < 0.5:
            feat["properties"]["severity"] = "medium"

    # 4. Occasionally add a fresh anomaly
    if rng.random() < 0.5:
        template = rng.choice(features)
        new_feat = copy.deepcopy(template)
        lon, lat = new_feat["geometry"]["coordinates"]
        new_feat["geometry"]["coordinates"] = [
            round(lon + rng.uniform(-0.15, 0.15), 6),
            round(lat + rng.uniform(-0.1, 0.1), 6),
        ]
        new_id = f"ANM-NEW-{rng.randint(1000, 9999)}"
        new_feat["properties"]["id"] = new_id
        new_feat["properties"]["detected_at"] = now_iso
        new_feat["properties"]["status"] = "unreviewed"
        new_feat["properties"]["severity"] = rng.choice(["high", "medium"])
        features.append(new_feat)

    # 5. Occasionally remove a low-severity one (represents a resolved flag)
    low_sev = [f for f in features if f["properties"]["severity"] == "low"]
    if rng.random() < 0.3 and low_sev:
        features.remove(rng.choice(low_sev))

    return jittered


def _build_headline_stats(scan: dict, metadata: dict) -> dict:
    features = scan["features"]
    sev_counts = {"high": 0, "medium": 0, "low": 0}
    type_counts: dict[str, int] = {}
    for f in features:
        sev_counts[f["properties"]["severity"]] += 1
        t = f["properties"]["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "last_scan_at": metadata["scan_completed_at"],
        "hours_since_last_scan": _hours_since(metadata["scan_completed_at"]),
        "total_km_monitored": metadata["total_km_monitored"],
        "tiles_processed": metadata["tiles_processed"],
        "total_anomalies": len(features),
        "by_severity": sev_counts,
        "by_type": type_counts,
        "scan_duration_seconds": metadata["duration_seconds"],
    }


# ------- Endpoints -------

@app.get("/")
def root() -> dict:
    return {
        "service": "Pipeline Monitoring Demo API",
        "pipeline": "IOCL Salaya-Mathura (1870 km)",
        "endpoints": ["/api/baseline", "/api/full_scan", "/api/scan_metadata", "/api/refresh"],
    }


@app.get("/api/baseline")
def get_baseline() -> dict:
    """Pipeline, buffers, tiles — instant load."""
    return {
        "pipeline": BASELINE_CACHE["pipeline"],
        "buffer_1km": BASELINE_CACHE["buffer_1km"],
        "buffer_5km": BASELINE_CACHE["buffer_5km"],
        "tiles": BASELINE_CACHE["tiles"],
    }


@app.get("/api/full_scan")
def get_full_scan() -> dict:
    """Cached full-corridor anomaly results."""
    return SCAN_CACHE["results"]


@app.get("/api/scan_metadata")
def get_scan_metadata() -> dict:
    """Headline stats and scan metadata."""
    return {
        "metadata": SCAN_CACHE["metadata"],
        "headline_stats": _build_headline_stats(SCAN_CACHE["results"], SCAN_CACHE["metadata"]),
    }


@app.post("/api/refresh")
async def trigger_refresh() -> JSONResponse:
    """
    Simulates a full-corridor re-scan.

    Waits 3-5 seconds (simulating compute), then returns freshly-jittered
    results so the UI can show updated numbers. The frontend should show a
    progress animation during this call.
    """
    # Simulate compute time
    wait_seconds = random.uniform(3.0, 5.0)
    await asyncio.sleep(wait_seconds)

    seed = int(datetime.now().timestamp())
    fresh_results = _jitter_scan(SCAN_CACHE["results"], seed_offset=seed)

    # Update cached scan + metadata so subsequent /full_scan calls return fresh data
    SCAN_CACHE["results"] = fresh_results
    new_meta = copy.deepcopy(SCAN_CACHE["metadata"])
    now = datetime.now(timezone.utc)
    new_meta["scan_id"] = f"SCAN-{now.strftime('%Y%m%d-%H%M%S')}"
    new_meta["scan_completed_at"] = now.isoformat().replace("+00:00", "Z")
    new_meta["duration_seconds"] = round(wait_seconds, 2)
    new_meta["total_anomalies"] = len(fresh_results["features"])
    SCAN_CACHE["metadata"] = new_meta

    return JSONResponse({
        "status": "completed",
        "scan_id": new_meta["scan_id"],
        "duration_seconds": round(wait_seconds, 2),
        "headline_stats": _build_headline_stats(fresh_results, new_meta),
        "results": fresh_results,
    })


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "anomalies_loaded": len(SCAN_CACHE.get("results", {}).get("features", []))}
