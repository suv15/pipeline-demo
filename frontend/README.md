# Pipeline Intelligence — Frontend

React + MapLibre GL dashboard for the IOCL Salaya–Mathura pipeline monitoring demo.

## Features

- **Dual theme** — dark (mission-control) / light (architectural). Toggle in header, persists via localStorage
- **Full-corridor map** — pipeline centerline, 1 km RoW buffer, 5 km monitoring buffer, analysis tiles
- **Anomaly feed** — sortable, filterable list with severity, confidence, type, location
- **Live refresh** — triggers backend `/api/refresh`, shows realistic progress animation with phased status messages, results update in place
- **Click-to-focus** — click any anomaly in the list to fly the map there and open its detail popup, or click a point on the map

## Setup

```bash
npm install
npm run dev
```

Open http://localhost:5173.

Vite dev server proxies `/api/*` requests to `http://localhost:8000` (the FastAPI backend). Make sure the backend is running first.

## Build & deploy

```bash
npm run build
```

Output goes to `dist/`. Deploy to Vercel, Netlify, or Cloudflare Pages.

### Vercel deploy

1. Push this `frontend/` folder to a GitHub repo (or a subfolder of a monorepo)
2. On Vercel, import the repo, set:
   - **Framework preset:** Vite
   - **Root directory:** `frontend` (if monorepo)
   - **Environment variable:** `VITE_API_BASE` = `https://your-backend-domain.com/api`
3. Deploy

## Project structure

```
frontend/
├── index.html
├── package.json
├── vite.config.js
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── lib/
    │   └── api.js
    ├── components/
    │   ├── Header.jsx
    │   ├── MapView.jsx
    │   ├── AnomalyPanel.jsx
    │   └── RefreshOverlay.jsx
    └── styles/
        └── index.css
```

## Basemap

Uses CARTO's free Positron (light) and Dark Matter (dark) GL styles. No API key required. For production with heavy traffic, consider self-hosting basemap tiles or moving to a paid tier.

## Notes

- The progress animation runs for 4 seconds by default. The backend `/api/refresh` actually takes 3–5 seconds, so these line up well. Tune `durationMs` in `App.jsx` if needed.
- Severity filter enforces at least one active severity (can't uncheck all).
- Theme toggle forces a full basemap style swap and re-adds our overlay layers.
