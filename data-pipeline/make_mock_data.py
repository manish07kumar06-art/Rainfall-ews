"""Generates SYNTHETIC files that follow the team's data contract.
Purpose: frontend + backend can work before the real model is ready.
Later, the ML/GIS people write the SAME file formats from real model output.
Run:  python data-pipeline/make_mock_data.py
"""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "backend" / "data"
OUT.mkdir(parents=True, exist_ok=True)

LAT0, LAT1, LON0, LON1 = 18.9, 19.3, 72.75, 73.05   # Mumbai region box
STEP = 0.05
START = datetime(2021, 7, 17, 0, 0)
HOURS = 48


def frange(a, b, s):
    return [round(a + i * s, 4) for i in range(int(round((b - a) / s)))]


LATS, LONS = frange(LAT0, LAT1, STEP), frange(LON0, LON1, STEP)


def rain_mm_3h(lat, lon, h):
    """Fake moving rain blob that peaks around hour 30."""
    cx = LON0 + (LON1 - LON0) * (0.2 + 0.6 * h / HOURS)
    cy = LAT0 + (LAT1 - LAT0) * 0.5
    d2 = ((lon - cx) / 0.12) ** 2 + ((lat - cy) / 0.18) ** 2
    peak = 90 * math.exp(-(((h - 30) / 10) ** 2))
    return round(peak * math.exp(-d2), 1)


def risk_level(mm):
    # MOCK thresholds - replace with your real ones (e.g. IMD categories)
    return 0 if mm < 10 else 1 if mm < 25 else 2 if mm < 50 else 3


def square(lat, lon, inset=0.0):
    a, b = lon + inset, lon + STEP - inset
    c, d = lat + inset, lat + STEP - inset
    return [[[a, c], [b, c], [b, d], [a, d], [a, c]]]


def fc(features, hour):
    return {"type": "FeatureCollection", "hour": hour, "mock": True, "features": features}


summary = []
for h in range(HOURS):
    risk_feats, flood_feats, max_mm, max_r = [], [], 0.0, 0
    for lat in LATS:
        for lon in LONS:
            mm = rain_mm_3h(lat, lon, h)
            r = risk_level(mm)
            max_mm, max_r = max(max_mm, mm), max(max_r, r)
            risk_feats.append({
                "type": "Feature",
                "properties": {"risk_level": r, "rain_mm_3h": mm},
                "geometry": {"type": "Polygon", "coordinates": square(lat, lon)},
            })
            low_lying = lon < LON0 + 0.5 * (LON1 - LON0)   # pretend coast side floods first
            depth = None
            if r == 3:
                depth = "high" if low_lying else "medium"
            elif r == 2 and low_lying:
                depth = "medium"
            if depth:
                flood_feats.append({
                    "type": "Feature",
                    "properties": {"depth_class": depth},
                    "geometry": {"type": "Polygon", "coordinates": square(lat, lon, 0.006)},
                })
    (OUT / f"risk_{h}.geojson").write_text(json.dumps(fc(risk_feats, h)))
    (OUT / f"flood_{h}.geojson").write_text(json.dumps(fc(flood_feats, h)))
    alert = {3: "RED ALERT: extremely heavy rain expected in next 3 hours. Move to higher ground.",
             2: "ORANGE ALERT: very heavy rain likely. Avoid low-lying roads and underpasses.",
             1: "YELLOW: moderate to heavy rain. Stay updated.",
             0: "No significant rain expected."}[max_r]
    summary.append({
        "hour": h,
        "time": (START + timedelta(hours=h)).isoformat(),
        "max_rain_mm_3h": max_mm,
        "max_risk": max_r,
        "flooded_cells": len(flood_feats),
        "alert_text": alert,
    })

timeline = {
    "region": "Mumbai (demo box)",
    "event": "Replay of heavy-rain event, 17-18 Jul 2021",
    "bbox": [LON0, LAT0, LON1, LAT1],
    "mock": True,
    "hours": summary,
}
(OUT / "timeline.json").write_text(json.dumps(timeline, indent=1))
print(f"Wrote {HOURS} risk + {HOURS} flood files and timeline.json to {OUT}")
