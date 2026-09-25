"""REAL pipeline, step 1: hourly ERA5 reanalysis for a 5x5 grid around Mumbai,
monsoon months (Jun-Sep) of 2018-2022, via the free Open-Meteo archive API (no key needed).

Run:  python data-pipeline/01_download_era5.py
Output: data-pipeline/raw/era5_mumbai_all.csv   (one row per hour per grid point)

Notes for the ML person:
  * Split by TIME. Suggested: train on 2018-2020 + 2022, TEST on 2021 (the demo event).
  * Label idea: rain in the NEXT 3 hours >= threshold -> heavy rain (1) else 0.
  * NOTE: this script was written without being run against the live API - if a
    variable name is rejected, read the error text and check the Open-Meteo docs.
"""
import time
from pathlib import Path

import pandas as pd
import requests

RAW = Path(__file__).resolve().parent / "raw"
RAW.mkdir(exist_ok=True)

LATS = [18.9, 19.0, 19.1, 19.2, 19.3]
LONS = [72.75, 72.825, 72.9, 72.975, 73.05]
YEARS = range(2018, 2023)
VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation",
    "surface_pressure", "cloud_cover", "wind_speed_10m", "wind_direction_10m",
]
URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch(lat, lon, year):
    out = RAW / f"era5_{lat}_{lon}_{year}.csv"
    if out.exists():                      # cached -> safe to re-run after a crash
        return out
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": f"{year}-06-01", "end_date": f"{year}-09-30",
        "hourly": ",".join(VARS), "timezone": "UTC",
    }
    for attempt in range(5):
        r = requests.get(URL, params=params, timeout=60)
        if r.status_code == 200:
            df = pd.DataFrame(r.json()["hourly"])
            df["lat"], df["lon"] = lat, lon
            df.to_csv(out, index=False)
            return out
        print(f"  retry {attempt + 1}: HTTP {r.status_code} {r.text[:120]}")
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"failed for {lat},{lon},{year}")


if __name__ == "__main__":
    files = []
    total = len(LATS) * len(LONS) * len(YEARS)
    for lat in LATS:
        for lon in LONS:
            for year in YEARS:
                files.append(fetch(lat, lon, year))
                print(f"[{len(files)}/{total}] {lat},{lon},{year}")
                time.sleep(0.5)           # be polite to the free API
    all_df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    all_df.to_csv(RAW / "era5_mumbai_all.csv", index=False)
    print("Done:", all_df.shape, "->", RAW / "era5_mumbai_all.csv")
