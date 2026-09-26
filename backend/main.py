"""Rainfall Early Warning API.

Two modes, kept clearly separate so the frontend/judges never confuse them:
  /replay/...  -> backend/data      -> historical event replay (17-19 Jul 2021)
  /live/...    -> backend/data_live -> real current + forecast prediction,
                  written by data-pipeline/04_live_fetch_predict.py

Old unprefixed routes are kept as aliases to /replay/... for backwards compatibility.
"""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

BASE = Path(__file__).parent
REPLAY_DATA = BASE / "data"
LIVE_DATA = BASE / "data_live"

app = FastAPI(title="Rainfall EWS API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for a hackathon demo
    allow_methods=["*"],
    allow_headers=["*"],
)


def load(folder: Path, name: str):
    path = folder / name
    if not path.exists():
        hint = (
            "Run data-pipeline/04_live_fetch_predict.py first."
            if folder == LIVE_DATA
            else "Run data-pipeline/make_mock_data.py or the real pipeline first."
        )
        raise HTTPException(status_code=404, detail=f"{name} not found. {hint}")
    return json.loads(path.read_text())


@app.get("/health")
def health():
    return {"status": "ok"}


# --- Replay (historical event) ---
@app.get("/replay/timeline")
def replay_timeline():
    return load(REPLAY_DATA, "timeline.json")


@app.get("/replay/risk/{hour}")
def replay_risk(hour: int):
    return load(REPLAY_DATA, f"risk_{hour}.geojson")


@app.get("/replay/flood/{hour}")
def replay_flood(hour: int):
    return load(REPLAY_DATA, f"flood_{hour}.geojson")


# --- Live (real current + forecast prediction) ---
@app.get("/live/timeline")
def live_timeline():
    return load(LIVE_DATA, "timeline.json")


@app.get("/live/risk/{hour}")
def live_risk(hour: int):
    return load(LIVE_DATA, f"risk_{hour}.geojson")


@app.get("/live/flood/{hour}")
def live_flood(hour: int):
    return load(LIVE_DATA, f"flood_{hour}.geojson")


# --- Backwards-compatible aliases (old frontend code, if any, keeps working) ---
@app.get("/timeline")
def timeline():
    return replay_timeline()


@app.get("/risk/{hour}")
def risk(hour: int):
    return replay_risk(hour)


@app.get("/flood/{hour}")
def flood(hour: int):
    return replay_flood(hour)
