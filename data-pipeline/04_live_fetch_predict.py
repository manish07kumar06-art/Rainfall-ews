"""LIVE pipeline: fetch REAL current + forecast weather, aggregate to DAILY
(matching the granularity of the trained model - it predicts "heavy rain
tomorrow", not hour-by-hour), and run it through the real, validated
models/rainfall_lgbm_mumbai.pkl trained in 05_ingest_imd_and_train.py.

Honesty notes, on purpose:
  - Risk is currently the same for every grid cell (regional, not spatial) -
    the model predicts one number for the whole Mumbai region per day. Spatial
    differentiation comes once the terrain/HAND layer is built and multiplied in.
  - flood_{day}.geojson is intentionally EMPTY right now - we do not have a
    validated flood-depth layer yet, so we don't draw one. An empty flood
    layer is honest; a fabricated one is not.

Run this manually to test:
    python data-pipeline/04_live_fetch_predict.py

Run this on a schedule (every few hours) once deployed to keep it current.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import requests

OUT = Path(__file__).resolve().parent.parent / "backend" / "data_live"
OUT.mkdir(parents=True, exist_ok=True)
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "rainfall_lgbm_mumbai.pkl"

# Same 5x5 grid used for training/visualization
LATS = [18.9, 19.0, 19.1, 19.2, 19.3]
LONS = [72.75, 72.825, 72.9, 72.975, 73.05]
CELL_HALF = 0.04

VARS = ["temperature_2m", "relative_humidity_2m", "precipitation",
        "surface_pressure", "cloud_cover", "wind_speed_10m"]
URL = "https://api.open-meteo.com/v1/forecast"
PAST_DAYS = 16     # history needed for the 15-day rolling rainfall feature
FORECAST_DAYS = 7  # how many days ahead to show

FEATURES = ["rainfall_mm", "rainfall_3day", "rainfall_7day", "rainfall_15day",
            "rainfall_3day_max", "rainfall_7day_max", "rainfall_previous_day",
            "humidity_avg", "pressure_avg", "pressure_min", "cloud_avg", "wind_avg", "wind_max"]

HEAVY_RAIN_MM = 64.5


def fetch_point(lat, lon):
    params = {
        "latitude": lat, "longitude": lon, "hourly": ",".join(VARS),
        "past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS, "timezone": "UTC",
    }
    r = requests.get(URL, params=params, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["hourly"])
    df["lat"], df["lon"] = lat, lon
    return df


def to_regional_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Average across all grid points (matching how the training data was a
    single basin-averaged series), then aggregate hourly -> daily."""
    df["time"] = pd.to_datetime(df["time"])
    df["date"] = df["time"].dt.date
    regional_hourly = df.groupby("time").mean(numeric_only=True).reset_index()
    regional_hourly["date"] = regional_hourly["time"].dt.date

    daily = regional_hourly.groupby("date").agg(
        rainfall_mm=("precipitation", "sum"),
        humidity_avg=("relative_humidity_2m", "mean"),
        pressure_avg=("surface_pressure", "mean"),
        pressure_min=("surface_pressure", "min"),
        cloud_avg=("cloud_cover", "mean"),
        wind_avg=("wind_speed_10m", "mean"),
        wind_max=("wind_speed_10m", "max"),
    ).reset_index()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)

    daily["rainfall_3day"] = daily["rainfall_mm"].rolling(3, min_periods=1).sum()
    daily["rainfall_7day"] = daily["rainfall_mm"].rolling(7, min_periods=1).sum()
    daily["rainfall_15day"] = daily["rainfall_mm"].rolling(15, min_periods=1).sum()
    daily["rainfall_3day_max"] = daily["rainfall_mm"].rolling(3, min_periods=1).max()
    daily["rainfall_7day_max"] = daily["rainfall_mm"].rolling(7, min_periods=1).max()
    daily["rainfall_previous_day"] = daily["rainfall_mm"].shift(1)
    return daily.dropna().reset_index(drop=True)


def risk_level_from_prob(p):
    # Rough bands around the tuned decision threshold from training (~0.3) -
    # not a precise calibration, just a readable severity scale for the map.
    if p < 0.15:
        return 0
    if p < 0.30:
        return 1
    if p < 0.55:
        return 2
    return 3


def polygon(lat, lon, half):
    a, b, c, d = lon - half, lon + half, lat - half, lat + half
    return [[[a, c], [b, c], [b, d], [a, d], [a, c]]]


def main():
    if not MODEL_PATH.exists():
        raise SystemExit(f"No trained model at {MODEL_PATH}. Run 05_ingest_imd_and_train.py first.")
    model = joblib.load(MODEL_PATH)

    print(f"Fetching live forecast for {len(LATS) * len(LONS)} grid points...")
    frames = [fetch_point(lat, lon) for lat in LATS for lon in LONS]
    daily = to_regional_daily(pd.concat(frames, ignore_index=True))

    today = pd.Timestamp.now().normalize()
    future = daily[daily["date"] >= today].head(FORECAST_DAYS).copy()
    if future.empty:
        raise SystemExit("No forecast days available - check the Open-Meteo response.")

    future["prob"] = model.predict_proba(future[FEATURES])[:, 1]
    future["risk_level"] = future["prob"].apply(risk_level_from_prob)

    summary = []
    for day_idx, row in future.reset_index(drop=True).iterrows():
        lvl = int(row.risk_level)
        risk_feats = [{
            "type": "Feature",
            "properties": {"risk_level": lvl, "rain_mm_3h": round(float(row.rainfall_mm), 1)},
            "geometry": {"type": "Polygon", "coordinates": polygon(lat, lon, CELL_HALF)},
        } for lat in LATS for lon in LONS]  # same regional risk on every cell - no spatial layer yet

        (OUT / f"risk_{day_idx}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "hour": day_idx, "mock": False, "features": risk_feats}))
        # Intentionally empty: no validated flood-depth layer yet (needs the HAND terrain step)
        (OUT / f"flood_{day_idx}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "hour": day_idx, "mock": False, "features": []}))

        alert = {3: "RED ALERT: high probability of heavy rain (>=64.5mm) in the next 24h.",
                  2: "ORANGE ALERT: elevated chance of heavy rain in the next 24h.",
                  1: "YELLOW: some chance of heavy rain. Stay updated.",
                  0: "Low chance of heavy rain."}[lvl]
        summary.append({
            "hour": day_idx, "time": row.date.strftime("%Y-%m-%d"),
            "max_rain_mm_3h": round(float(row.rainfall_mm), 1),
            "max_risk": lvl, "flooded_cells": 0,
            "alert_text": alert, "model_probability": round(float(row.prob), 3),
        })

    (OUT / "timeline.json").write_text(json.dumps({
        "region": "Mumbai (live forecast)",
        "mode": "live_forecast",
        "granularity": "daily",
        "model_used": "rainfall_lgbm_mumbai.pkl (IMD + atmospheric features, validated: CSI 0.385 vs 0.364 baseline)",
        "spatial_note": "Risk shown is regional (same across the map) - spatial detail requires the terrain/HAND layer, not yet built.",
        "flood_note": "Flood layer intentionally empty - no validated flood-depth model yet.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bbox": [72.75, 18.9, 73.05, 19.3],
        "mock": False,
        "hours": summary,
    }, indent=1))
    print(f"Wrote LIVE daily forecast for {len(summary)} days to {OUT}")
    for s in summary:
        print(s["time"], "risk", s["max_risk"], "prob", s["model_probability"], "rain", s["max_rain_mm_3h"], "mm")


if __name__ == "__main__":
    main()
