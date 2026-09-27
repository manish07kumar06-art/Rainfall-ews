# RainGuard — rainfall early warning + city impact twin (SIH)

This is a **B2G command dashboard**, not a consumer weather app. Rainfall is
screened nationally and forecast for Mumbai; **inundation, blocked roads,
power-cut recommendations, ambulance reroutes, CCTV virtual gauges, and
what-if planning** are computed on a hyperlocal Mumbai twin.

Data catalogue (IMD, DWR, INSAT-3D, DEM, Bhashini): [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

## Folder map
- `backend/`        FastAPI + Mumbai impact engine (`city_mumbai.py`, `impact_engine.py`)
- `data-pipeline/`  IMD training, live fetch, data-access checklist
- `frontend/`       React command UI (Vite + Leaflet)
- `models/`         trained LightGBM pickles
- `docs/`           data sources and deck notes

## API
| Endpoint | What it is |
|---|---|
| GET `/replay\|live/timeline` | Rain timeline |
| GET `/replay\|live/risk/{hour}` | Rain risk grid |
| GET `/impact/snapshot?mode=&hour=` | Depths (m/ft), blocked roads, cascade, CCTV, ROI, Bhashini alerts |
| POST `/impact/simulate` | What-if: drain cleaning, pump failure, extra rain |
| GET `/metrics` | Mumbai + national model scores |

## Run it locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python data-pipeline/make_mock_data.py
uvicorn backend.main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL. The UI talks to `http://localhost:8000`.

## Train
```bash
pip install -r data-pipeline/requirements.txt
python data-pipeline/07_data_access.py          # what files you already have
python data-pipeline/05_ingest_imd_and_train.py # Mumbai (keep this hyperlocal)
python data-pipeline/06_train_national.py       # India screen only
python data-pipeline/04_live_fetch_predict.py   # live forecast files
```

## Deploy backend on Render
- New > Web Service > connect GitHub repo
- Build command: `pip install -r backend/requirements.txt`
- Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
