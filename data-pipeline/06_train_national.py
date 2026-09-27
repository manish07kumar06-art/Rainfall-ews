"""REAL nationwide training: same official IMD data (2015-2023), but instead of
averaging one small Mumbai box down to a single daily number, this keeps
EVERY land grid cell across India as its own location and pools them all into
one training set. Same target definition as before: will THIS location see
heavy rain (>=64.5mm, IMD's official threshold) TOMORROW, given its own recent
rainfall history.

Deliberately rainfall-only (no atmospheric merge): getting live humidity/
pressure/wind for ~1000+ national grid points isn't practical with a free
per-point API - that's exactly why "live nationwide" is a Phase 2 item
(needs a single gridded forecast file like GFS, not per-point calls). This
script proves the MODEL scales nationwide; live nationwide is a separate,
later piece of engineering.

Uses a ~1 degree grid (every 4th IMD point in each direction) instead of the
full 0.25 degree resolution, to keep this runnable on a normal laptop in a
few minutes instead of risking an hours-long run or an out-of-memory crash.

Run:
    python data-pipeline/06_train_national.py

Output:
    data-pipeline/processed/national_metrics.json  <- put this in your deck
    models/rainfall_lgbm_national.pkl
"""
import json
from pathlib import Path

import imdlib as imd
import joblib
import lightgbm as lgb
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

RAW_DIR = Path(__file__).resolve().parent / "raw" / "imd_rain"
PROC = Path(__file__).resolve().parent / "processed"
PROC.mkdir(exist_ok=True)
MODELS = Path(__file__).resolve().parent.parent / "models"
MODELS.mkdir(exist_ok=True)

GRID_STRIDE = 4  # 0.25deg * 4 = ~1deg resolution across India
HEAVY_RAIN_MM = 64.5
MIN_VALID_DAYS = 1000  # drop grid points with too little real data (ocean/mostly-missing cells)
TRAIN_END_YEAR = 2019
VAL_END_YEAR = 2021
TEST_START_YEAR = 2022

import numpy as np

FEATURES = ["rainfall_mm", "rainfall_3day", "rainfall_7day", "rainfall_15day",
            "rainfall_3day_max", "rainfall_7day_max", "rainfall_previous_day",
            "lat", "lon", "day_of_year_sin", "day_of_year_cos"]


def critical_success_index(y_true, y_pred):
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    denom = tp + fn + fp
    return tp / denom if denom else 0.0


def load_national_grid():
    print("Loading full India grid from IMD .grd files (this may take a minute)...")
    data = imd.open_data("rain", 2015, 2023, "yearwise", str(RAW_DIR))
    ds = data.get_xarray()

    # Coarsen from 0.25deg to ~1deg by taking every Nth point - not smoothing,
    # just a lighter sample, so training stays fast and memory-safe.
    ds_sub = ds.isel(lat=slice(None, None, GRID_STRIDE), lon=slice(None, None, GRID_STRIDE))
    print(f"Grid points after coarsening: {ds_sub.dims['lat']} x {ds_sub.dims['lon']} "
          f"= {ds_sub.dims['lat'] * ds_sub.dims['lon']} locations")

    df = ds_sub["rain"].to_dataframe(name="rainfall_mm").reset_index()
    df = df[df["rainfall_mm"] > -100]  # drop IMD's -999 missing/ocean flag
    df["rainfall_mm"] = df["rainfall_mm"].astype("float32")
    return df


def add_features_per_point(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["lat", "lon", "time"]).reset_index(drop=True)

    counts = df.groupby(["lat", "lon"])["rainfall_mm"].transform("size")
    df = df[counts >= MIN_VALID_DAYS].reset_index(drop=True)  # drop ocean / mostly-missing cells

    g = df.groupby(["lat", "lon"], group_keys=False)
    df["rainfall_3day"] = g["rainfall_mm"].transform(lambda s: s.rolling(3).sum())
    df["rainfall_7day"] = g["rainfall_mm"].transform(lambda s: s.rolling(7).sum())
    df["rainfall_15day"] = g["rainfall_mm"].transform(lambda s: s.rolling(15).sum())
    df["rainfall_3day_max"] = g["rainfall_mm"].transform(lambda s: s.rolling(3).max())
    df["rainfall_7day_max"] = g["rainfall_mm"].transform(lambda s: s.rolling(7).max())
    df["rainfall_previous_day"] = g["rainfall_mm"].transform(lambda s: s.shift(1))
    df["target_heavy_rain_next_day"] = g["rainfall_mm"].transform(
        lambda s: (s.shift(-1) >= HEAVY_RAIN_MM).astype(int)
    )

    # Seasonality: cyclical encoding so Dec 31 and Jan 1 are treated as adjacent,
    # not maximally far apart. This matters a lot for India - monsoon timing is
    # THE dominant driver of heavy rain, and the model previously couldn't see it at all.
    day_of_year = pd.to_datetime(df["time"]).dt.dayofyear
    df["day_of_year_sin"] = np.sin(2 * np.pi * day_of_year / 365.25)
    df["day_of_year_cos"] = np.cos(2 * np.pi * day_of_year / 365.25)

    return df.dropna().reset_index(drop=True)


def main():
    df = add_features_per_point(load_national_grid())
    df["year"] = pd.to_datetime(df["time"]).dt.year
    n_points = df[["lat", "lon"]].drop_duplicates().shape[0]

    print("Total rows (location-days):", len(df))
    print("Unique valid land locations:", n_points)
    print("Heavy-rain-next-day rate:", round(df["target_heavy_rain_next_day"].mean(), 4))

    train = df[df.year <= TRAIN_END_YEAR]
    val = df[(df.year > TRAIN_END_YEAR) & (df.year <= VAL_END_YEAR)]
    test = df[df.year >= TEST_START_YEAR]
    if train.empty or val.empty or test.empty:
        raise SystemExit("A split is empty - check the years in your .grd files.")

    Xtr, ytr = train[FEATURES], train["target_heavy_rain_next_day"]
    Xval, yval = val[FEATURES], val["target_heavy_rain_next_day"]
    Xte, yte = test[FEATURES], test["target_heavy_rain_next_day"]

    print(f"Training on {len(Xtr):,} location-days across {n_points} locations...")
    model = lgb.LGBMClassifier(n_estimators=300, max_depth=5, learning_rate=0.05, is_unbalance=True)
    model.fit(Xtr, ytr)
    joblib.dump(model, MODELS / "rainfall_lgbm_national.pkl")

    val_prob = model.predict_proba(Xval)[:, 1]
    best_threshold, best_csi = 0.5, -1
    for t in [i / 100 for i in range(5, 96, 5)]:
        csi = critical_success_index(yval, (val_prob >= t).astype(int))
        if csi > best_csi:
            best_threshold, best_csi = t, csi
    print(f"Tuned threshold on validation: {best_threshold} (val CSI {round(best_csi, 3)})")

    test_prob = model.predict_proba(Xte)[:, 1]
    pred = (test_prob >= best_threshold).astype(int)
    baseline_pred = (test["rainfall_mm"] >= HEAVY_RAIN_MM).astype(int)

    def year_range(d):
        yrs = d["year"]
        return f"{yrs.min()}-{yrs.max()}" if len(d) else "none"

    metrics = {
        "scope": "Nationwide (India), ~1deg grid, rainfall history + location + seasonality features",
        "data_source": "IMD 0.25deg gridded daily rainfall, 2015-2023 (official), coarsened to ~1deg",
        "n_locations": int(n_points),
        "train_years": year_range(train),
        "validation_years": year_range(val) + " (threshold tuning only)",
        "test_years": year_range(test) + " (untouched until final evaluation)",
        "tuned_decision_threshold": best_threshold,
        "model": {
            "precision": round(precision_score(yte, pred, zero_division=0), 3),
            "recall": round(recall_score(yte, pred, zero_division=0), 3),
            "f1": round(f1_score(yte, pred, zero_division=0), 3),
            "csi": round(critical_success_index(yte, pred), 3),
            "confusion_matrix": confusion_matrix(yte, pred).tolist(),
        },
        "persistence_baseline": {
            "precision": round(precision_score(yte, baseline_pred, zero_division=0), 3),
            "recall": round(recall_score(yte, baseline_pred, zero_division=0), 3),
            "f1": round(f1_score(yte, baseline_pred, zero_division=0), 3),
            "csi": round(critical_success_index(yte, baseline_pred), 3),
        },
        "n_test_rows": int(len(test)),
        "positive_rate_test": round(float(yte.mean()), 3),
    }
    (PROC / "national_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    print("\nModel saved to", MODELS / "rainfall_lgbm_national.pkl")


if __name__ == "__main__":
    main()
