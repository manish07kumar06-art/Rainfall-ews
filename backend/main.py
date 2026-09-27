"""Rainfall Early Warning + impact twin API.

Two forecast modes:
  /replay/...  -> backend/data      -> historical event replay (17-19 Jul 2021)
  /live/...    -> backend/data_live -> current + forecast prediction

Impact (hydrology, not just rain):
  /impact/city
  /impact/snapshot?mode=live|replay&hour=
  POST /impact/simulate
"""
import json
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from city_mumbai import city_profile  # noqa: E402
from impact_engine import snapshot as build_snapshot  # noqa: E402

REPLAY_DATA = BASE / "data"
LIVE_DATA = BASE / "data_live"
ROOT = BASE.parent
NATIONAL_METRICS = ROOT / "data-pipeline" / "processed" / "national_metrics.json"
MUMBAI_METRICS = ROOT / "data-pipeline" / "processed" / "mumbai_metrics.json"

app = FastAPI(title="RainGuard Impact EWS API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    return json.loads(path.read_text(encoding="utf-8"))


def folder_for(mode: str) -> Path:
    if mode == "live":
        return LIVE_DATA
    if mode == "replay":
        return REPLAY_DATA
    raise HTTPException(status_code=400, detail="mode must be live or replay")


@app.get("/health")
def health():
    return {"status": "ok", "product": "RainGuard impact twin"}


@app.get("/replay/timeline")
def replay_timeline():
    return load(REPLAY_DATA, "timeline.json")


@app.get("/replay/risk/{hour}")
def replay_risk(hour: int):
    return load(REPLAY_DATA, f"risk_{hour}.geojson")


@app.get("/replay/flood/{hour}")
def replay_flood(hour: int):
    return load(REPLAY_DATA, f"flood_{hour}.geojson")


@app.get("/live/timeline")
def live_timeline():
    return load(LIVE_DATA, "timeline.json")


@app.get("/live/risk/{hour}")
def live_risk(hour: int):
    return load(LIVE_DATA, f"risk_{hour}.geojson")


@app.get("/live/flood/{hour}")
def live_flood(hour: int):
    return load(LIVE_DATA, f"flood_{hour}.geojson")


@app.get("/timeline")
def timeline():
    return replay_timeline()


@app.get("/risk/{hour}")
def risk(hour: int):
    return replay_risk(hour)


@app.get("/flood/{hour}")
def flood(hour: int):
    return replay_flood(hour)


@app.get("/metrics")
def metrics():
    out = {}
    if MUMBAI_METRICS.exists():
        out["mumbai"] = json.loads(MUMBAI_METRICS.read_text(encoding="utf-8"))
    if NATIONAL_METRICS.exists():
        out["national"] = json.loads(NATIONAL_METRICS.read_text(encoding="utf-8"))
    return out


@app.get("/impact/city")
def impact_city():
    return city_profile()


class SimulateBody(BaseModel):
    mode: str = Field("replay", description="live or replay")
    hour: int = 0
    drain_clean_factor: float = Field(1.0, ge=0.4, le=2.0)
    failed_pumps: list[str] = Field(default_factory=list)
    extra_rain_mm: float = Field(0.0, ge=0.0, le=250.0)


def _impact(mode: str, hour: int, drain_clean_factor: float, failed_pumps: list[str], extra_rain_mm: float):
    folder = folder_for(mode)
    risk = load(folder, f"risk_{hour}.geojson")
    try:
        tl = load(folder, "timeline.json")
        hours = tl.get("hours") or []
        slot = hours[hour] if 0 <= hour < len(hours) else {}
        clock = slot.get("time")
        rain_note = slot.get("alert_text")
    except HTTPException:
        clock, rain_note = None, None
    snap = build_snapshot(
        risk,
        clock=clock,
        drain_clean_factor=drain_clean_factor,
        failed_pumps=failed_pumps,
        extra_rain_mm=extra_rain_mm,
    )
    snap["mode"] = mode
    snap["hour"] = hour
    snap["rain_alert"] = rain_note
    return snap


@app.get("/impact/snapshot")
def impact_snapshot(mode: str = "replay", hour: int = 0):
    return _impact(mode, hour, 1.0, [], 0.0)


@app.post("/impact/simulate")
def impact_simulate(body: SimulateBody):
    return _impact(
        body.mode,
        body.hour,
        body.drain_clean_factor,
        body.failed_pumps,
        body.extra_rain_mm,
    )
