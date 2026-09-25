# Rainfall Early Warning + Inundation Prototype (SIH)

Starter kit. Everything here runs on MOCK data first so the whole team can work in parallel.

## Folder map
- `backend/`        FastAPI app + `data/` (files that follow the data contract)
- `data-pipeline/`  scripts: mock data generator, real data download
- `frontend-mock/`  one-file map UI (reference). The frontend person builds the React version.
- `docs/`           architecture diagram, deck notes

## Data contract (do not change without telling everyone)
| Endpoint | File | Key fields |
|---|---|---|
| GET /timeline | timeline.json | hours[], each: hour, time, max_rain_mm_3h, max_risk, flooded_cells, alert_text |
| GET /risk/{hour} | risk_{hour}.geojson | properties: risk_level (0-3), rain_mm_3h |
| GET /flood/{hour} | flood_{hour}.geojson | properties: depth_class (low / medium / high) |

## Run it locally (5 minutes)
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      Mac/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
python data-pipeline/make_mock_data.py
uvicorn backend.main:app --reload --port 8000
```
Open http://localhost:8000/docs to test the API, then double-click `frontend-mock/index.html`.
(If the map is blank, open the browser console: it is almost always a wrong API address.)

## Real pipeline (after the mock works)
```bash
pip install -r data-pipeline/requirements.txt
python data-pipeline/01_download_era5.py
```

## Deploy backend on Render
- New > Web Service > connect GitHub repo
- Build command: `pip install -r backend/requirements.txt`
- Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
