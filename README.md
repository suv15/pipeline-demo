# Pipeline Intelligence Demo

A semi-live geospatial web app demonstrating AI-driven pipeline monitoring
for the **IOCL Salaya–Mathura crude pipeline** (1,870 km, Gujarat → Uttar Pradesh).

Built as a credibility-builder demo: real geospatial architecture, realistic
data shape, full-corridor "live refresh" flow in under 5 seconds.

---

## What it does

- Renders the full pipeline corridor with RoW (1 km) and monitoring (5 km) buffers
- Shows 45 anomalies across 25 analysis tiles — encroachment, vegetation loss,
  excavation, thermal signatures, water pooling
- Each anomaly has: severity, confidence score, source sensor, area, distance
  to RoW, detected timestamp
- "Full Scan" button triggers a simulated Sentinel-1/Sentinel-2 re-scan:
  4-second phased progress animation, then results update in place with
  realistic jitter (new anomalies appear, severities shift, timestamps refresh)
- Dark / light theme toggle — dark for mission-control feel, light for
  screenshots and decks
- Click any anomaly in the list → map flies to location, opens detail popup

---

## Structure

```
pipeline-demo/
├── backend/          FastAPI service, port 8000
│   ├── main.py
│   ├── prep_pipeline_data.py     # one-time: build geospatial baseline
│   ├── run_full_scan.py          # one-time: generate cached scan results
│   ├── requirements.txt
│   ├── README.md
│   └── data/                     # GeoJSON + metadata (already generated)
│
└── frontend/         React + MapLibre, port 5173
    ├── src/
    │   ├── App.jsx
    │   ├── components/
    │   ├── lib/api.js
    │   └── styles/index.css
    ├── package.json
    ├── vite.config.js
    └── README.md
```

---

## Run locally (5 minutes)

Open two terminals.

### Terminal 1 — Backend

```bash
cd backend
pip install -r requirements.txt
# data/ is already populated, but if you want to regenerate:
#   python prep_pipeline_data.py
#   python run_full_scan.py
uvicorn main:app --reload --port 8000
```

Verify: http://localhost:8000/api/health → `{"status":"ok","anomalies_loaded":45}`

### Terminal 2 — Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api/*` → `http://localhost:8000`.

---

## Deploy (30 minutes, free tier)

### Backend → Railway or Render

1. Push the `backend/` folder to a GitHub repo (or use it as the root of one)
2. New service on Railway/Render, connect the repo
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Commit the `data/` folder — it must be present at startup
6. Note the public URL — you'll need it for the frontend

Tighten CORS in `main.py` (currently `*`) to your frontend domain before
sharing with anyone outside your team.

### Frontend → Vercel

1. Push the `frontend/` folder to a GitHub repo
2. Import on Vercel. Framework preset: **Vite**
3. Environment variable: `VITE_API_BASE` = `https://your-backend.up.railway.app/api`
4. Deploy → you'll get a URL like `pipeline-demo.vercel.app`

Total ongoing cost: **₹0** on free tiers for demo traffic.

---

## Demo narration script (for client calls)

> **Open the dashboard.** "This is a live view of the IOCL Salaya–Mathura
> pipeline. 1,870 kilometers from Salaya in Gujarat to Mathura in UP. The
> green line is the centerline, the darker band is the 1-kilometer
> right-of-way, and the outer band is our 5-kilometer monitoring buffer."
>
> **Point at headline stats.** "We've processed the entire corridor — 25
> analysis tiles — and flagged 45 anomalies. 17 of them are high severity.
> That's what the operations team would see first thing every morning."
>
> **Click an anomaly in the list.** "Each flag is classified by type —
> encroachment, vegetation loss, excavation, thermal — and scored by
> confidence. This one's a new structure detected within 50 meters of the
> RoW. SAR coherence change confirms it wasn't there in the last scan."
>
> **Click Full Scan.** "What if the field team reports an incident? We can
> re-scan the entire corridor on demand." *(4-second animation plays, new
> anomaly count updates.)* "Fresh Sentinel-1 and Sentinel-2 imagery, change
> detection across 25 tiles, classified with our vision model. Under five
> seconds."

---

## Important caveat

The current scan results are **simulated** — they match the exact output
format of real Sentinel processing, so the UI and deploy path are real, but
the anomaly detection itself is seeded for the demo.

To swap in real Copernicus data:

1. Get a free Copernicus Data Space Ecosystem account: https://dataspace.copernicus.eu
2. Replace the body of `analyze_tile()` in `backend/run_full_scan.py` with
   real STAC queries + SAR coherence change detection (see `backend/README.md`
   for the full drop-in recipe)
3. Nothing else in the stack changes — the API contract and frontend stay
   identical

The route alignment is also a public approximation. For a real client
engagement, replace `ROUTE_POINTS` in `prep_pipeline_data.py` with the
operator's surveyed KML or shapefile.

---

## Tech stack

**Backend:** FastAPI, Shapely, PyProj. Data served from in-memory GeoJSON
caches loaded at startup. Async simulated compute on the refresh endpoint.

**Frontend:** React 18, Vite, MapLibre GL JS 4. No UI framework — just
hand-tuned CSS with a proper design system. Manrope (display) + JetBrains
Mono (data). CARTO Positron / Dark Matter basemaps (free, no API key).

**No managed services required.** Runs entirely on free tiers.
