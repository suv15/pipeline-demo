# Pipeline Intelligence Demo — Deployment Context for Claude Code

## What this project is
A completed geospatial web app: a pipeline monitoring dashboard for the IOCL Salaya–Mathura crude pipeline (1,870 km, Gujarat → UP).

## Structure
- `backend/` — FastAPI service (port 8000). Data in `backend/data/` is already generated, do NOT regenerate.
- `frontend/` — React 18 + Vite + MapLibre GL dashboard.
- `README.md` — full architectural docs.

## Tech stack
- Backend: FastAPI, Shapely, PyProj. In-memory GeoJSON caches loaded at startup.
- Frontend: React 18, Vite, MapLibre GL 4. No UI framework — hand-tuned CSS.
- No managed services, no API keys, no paid tiers required.

## What is already done
- Both apps build cleanly and run together (tested locally).
- Backend: `uvicorn main:app --port 8000` — serves 5 endpoints, returns 45 anomalies.
- Frontend: `npm run dev` on port 5173, proxies `/api/*` to backend.
- Production build: `npm run build` produces ~966 kB JS bundle (270 kB gzipped).

## Deployment goal
Get this live on free tiers:
- GitHub: one public repo with both folders
- Railway (or Render): backend/
- Vercel: frontend/
- Wire them together via `VITE_API_BASE` env var
- Tighten CORS in backend/main.py from `*` to the Vercel domain once known

## Critical constraints
- Do NOT modify application logic. The code is tested.
- The `backend/data/` folder MUST be committed — the backend loads it at startup.
- If a CLI step requires interactive login (gh, railway, vercel), stop and tell the user what command to run. Wait for confirmation before continuing.

## Known gotchas
- The frontend `package.json` uses ESM (`"type": "module"`) — Vite handles this fine.
- MapLibre CSS is loaded via CDN from `index.html`, not imported in JS.
- The refresh endpoint takes 3-5 seconds by design (simulates compute). Don't "fix" it.
- CORS is currently `*` for convenience. Tighten before sharing publicly.
