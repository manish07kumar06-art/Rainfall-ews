"""Rainfall Early Warning API - serves PRECOMPUTED files from backend/data.

Data contract (agreed by whole team):
  GET /timeline      -> timeline.json  (list of hours + summary + alert text)
  GET /risk/{hour}   -> risk_{hour}.geojson   (grid cells: risk_level 0-3, rain_mm_3h)
  GET /flood/{hour}  -> flood_{hour}.geojson  (polygons: depth_class low/medium/high)
"""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

DATA = Path(__file__).parent / "data"

app = FastAPI(title="Rainfall EWS API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for a hackathon demo
    allow_methods=["*"],
    allow_headers=["*"],
)


def load(name: str):
    path = DATA / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return json.loads(path.read_text())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/timeline")
def timeline():
    return load("timeline.json")


@app.get("/risk/{hour}")
def risk(hour: int):
    return load(f"risk_{hour}.geojson")


@app.get("/flood/{hour}")
def flood(hour: int):
    return load(f"flood_{hour}.geojson")
