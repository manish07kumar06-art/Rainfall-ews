"""LIVE pipeline: fetch REAL current + forecast weather (not historical replay),
run the trained model (or an honest fallback rule if you haven't trained one yet),
and write risk_{h}.geojson / flood_{h}.geojson / timeline.json for backend/data_live.

Data source: Open-Meteo FORECAST API (not the archive API from step 01) - free,
no key, gives real current conditions + up to 16 days of hourly forecast, plus
`past_days` so we can compute the same rolling features used in training.

Run this manually to test:
    python data-pipeline/04_live_fetch_predict.py

Run this on a schedule (every 30-60 min) once deployed - e.g. a cron job, a
GitHub Action, or Render's "Cron Job" feature - to keep predictions current.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent.parent / "backend" / "data_live"
OUT.mkdir(parents=True, exist_ok=True)
PROC = Path(__file__).resolve().parent / "processed"

# Same 5x5 grid used in 01_download_era5.py, so a trained model's features line up
LATS = [18.9, 19.0, 19.1, 19.2, 19.3]
LONS = [72.75, 72.825, 72.9, 72.975, 73.05]
CELL_HALF = 0.04  # visual square half-width per grid point (cells won't perfectly tile - fine for a prototype)

VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation",
    "surface_pressure", "cloud_cover", "wind_speed_10m", "wind_direction_10m",
]
FEATURES = [
    "precip_past_3h", "precip_past_6h", "pressure_trend_3h", "humidity_avg_3h",
    "temperature_2m", "cloud_cover", "wind_speed_10m",
]
URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_HOURS = 24   # how far ahead to show predictions
PAST_DAYS = 2          # history needed to compute "past 3h/6h rain" for the FIRST forecast hour


def fetch_point(lat, lon):
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(VARS),
        "past_days": PAST_DAYS,
        "forecast_days": 2,
        "timezone": "UTC",
    }
    r = requests.get(URL, params=params, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["hourly"])
    df["lat"], df["lon"] = lat, lon
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["lat", "lon", "time"]).reset_index(drop=True)
    g = df.groupby(["lat", "lon"], group_keys=False)
    df["precip_past_3h"] = g["precipitation"].transform(lambda s: s.rolling(3, min_periods=1).sum())
    df["precip_past_6h"] = g["precipitation"].transform(lambda s: s.rolling(6, min_periods=1).sum())
    df["pressure_trend_3h"] = g["surface_pressure"].transform(lambda s: s.diff(3))
    df["humidity_avg_3h"] = g["relative_humidity_2m"].transform(lambda s: s.rolling(3, min_periods=1).mean())
    return df


def fallback_risk(row):
    """Used only if no trained model is found yet. Simple, explainable, and
    clearly weaker than the real model - replace by running 01-03 first."""
    mm3h = row["precip_past_3h"]
    if mm3h < 10:
        return 0, mm3h
    if mm3h < 25:
        return 1, mm3h
    if mm3h < 50:
        return 2, mm3h
    return 3, mm3h


def risk_level_from_prob(p):
    if p < 0.15:
        return 0
    if p < 0.35:
        return 1
    if p < 0.6:
        return 2
    return 3


def polygon(lat, lon, half):
    a, b, c, d = lon - half, lon + half, lat - half, lat + half
    return [[[a, c], [b, c], [b, d], [a, d], [a, c]]]


def main():
    print(f"Fetching live forecast for {len(LATS) * len(LONS)} grid points...")
    frames = [fetch_point(lat, lon) for lat in LATS for lon in LONS]
    df = pd.concat(frames, ignore_index=True)
    df = add_features(df)
    df["time"] = pd.to_datetime(df["time"])

    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    future = df[df["time"] >= now].copy()
    future = future.groupby(["lat", "lon"], group_keys=False).head(FORECAST_HOURS)
    future = future.dropna(subset=["pressure_trend_3h"])

    model_path = PROC / "model.json"
    used_model = model_path.exists()
    if used_model:
        import xgboost as xgb
        model = xgb.XGBClassifier()
        model.load_model(model_path)
        future["prob"] = model.predict_proba(future[FEATURES])[:, 1]
        future["risk_level"] = future["prob"].apply(risk_level_from_prob)
        future["rain_mm_3h"] = future["precip_past_3h"]  # best available "next 3h" proxy at inference time
    else:
        print("WARNING: no trained model found at", model_path)
        print("Using a simple fallback rule instead - run 01_download_era5.py,")
        print("02_build_training_table.py and 03_train_and_predict.py for the real model.")
        results = future.apply(fallback_risk, axis=1, result_type="expand")
        future["risk_level"], future["rain_mm_3h"] = results[0], results[1]

    hours_sorted = sorted(future["time"].unique())
    summary = []
    for h_idx, t in enumerate(hours_sorted):
        rows = future[future["time"] == t]
        risk_feats, flood_feats = [], []
        for _, r in rows.iterrows():
            lvl = int(r.risk_level)
            risk_feats.append({
                "type": "Feature",
                "properties": {"risk_level": lvl, "rain_mm_3h": round(float(r.rain_mm_3h), 1)},
                "geometry": {"type": "Polygon", "coordinates": polygon(r.lat, r.lon, CELL_HALF)},
            })
            if lvl >= 2:
                depth = "high" if lvl == 3 else "medium"
                flood_feats.append({
                    "type": "Feature",
                    "properties": {"depth_class": depth},
                    "geometry": {"type": "Polygon", "coordinates": polygon(r.lat, r.lon, CELL_HALF * 0.7)},
                })
        (OUT / f"risk_{h_idx}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "hour": h_idx, "mock": False, "features": risk_feats}))
        (OUT / f"flood_{h_idx}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "hour": h_idx, "mock": False, "features": flood_feats}))

        max_lvl = int(rows.risk_level.max())
        alert = {3: "RED ALERT: extremely heavy rain expected in next 3 hours. Move to higher ground.",
                  2: "ORANGE ALERT: very heavy rain likely. Avoid low-lying roads and underpasses.",
                  1: "YELLOW: moderate to heavy rain. Stay updated.",
                  0: "No significant rain expected."}[max_lvl]
        summary.append({
            "hour": h_idx, "time": str(t), "max_rain_mm_3h": round(float(rows.rain_mm_3h.max()), 1),
            "max_risk": max_lvl, "flooded_cells": len(flood_feats), "alert_text": alert,
        })

    (OUT / "timeline.json").write_text(json.dumps({
        "region": "Mumbai (live forecast)",
        "mode": "live_forecast",
        "model_used": "trained_xgboost" if used_model else "fallback_rule (train the real model for better accuracy)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bbox": [72.75, 18.9, 73.05, 19.3],
        "mock": False,
        "hours": summary,
    }, indent=1))
    print(f"Wrote LIVE forecast for {len(hours_sorted)} hours to {OUT}")
    print("model_used:", "trained_xgboost" if used_model else "fallback_rule")


if __name__ == "__main__":
    main()
