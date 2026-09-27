"""REAL pipeline using official IMD gridded rainfall data (2015-2023), adapted
from a teammate's Periyar-basin notebooks to the Mumbai region.

BEFORE RUNNING: put the 9 .grd files (2015.grd ... 2023.grd) into:
    data-pipeline/raw/imd_rain/

Run:
    pip install imdlib lightgbm joblib scikit-learn   # (already done if Step 48 succeeded)
    python data-pipeline/05_ingest_imd_and_train.py

Output:
    data-pipeline/processed/mumbai_imd_features.csv
    data-pipeline/processed/mumbai_metrics.json   <- put these numbers straight in your deck
    models/rainfall_lgbm_mumbai.pkl
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

# Mumbai metropolitan region. IMD's grid is 0.25 deg (~27km) resolution, so this
# box covers a small number of real grid cells - same basin-average approach
# your teammate used for Periyar, just relocated.
LAT_RANGE = (18.75, 19.5)
LON_RANGE = (72.5, 73.25)

HEAVY_RAIN_MM = 64.5          # IMD's official "heavy rain" threshold (24h)
TRAIN_END_YEAR = 2019         # train on 2015-2019
VAL_END_YEAR = 2021           # tune the decision threshold on 2020-2021 (never used for training)
TEST_START_YEAR = 2022        # final honest evaluation on 2022-2023 - touched only once, at the end


def load_and_slice():
    data = imd.open_data("rain", 2015, 2023, "yearwise", str(RAW_DIR))
    ds = data.get_xarray()
    region = ds.sel(lat=slice(*LAT_RANGE), lon=slice(*LON_RANGE))
    daily = region["rain"].mean(dim=["lat", "lon"], skipna=True)
    df = daily.to_dataframe(name="rainfall_mm").reset_index()
    df = df.sort_values("time").reset_index(drop=True)
    df = df[df["rainfall_mm"] > -100].reset_index(drop=True)  # drop IMD's -999 missing-value flag
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df["rainfall_3day"] = df["rainfall_mm"].rolling(3).sum()
    df["rainfall_7day"] = df["rainfall_mm"].rolling(7).sum()
    df["rainfall_15day"] = df["rainfall_mm"].rolling(15).sum()
    df["rainfall_3day_max"] = df["rainfall_mm"].rolling(3).max()
    df["rainfall_7day_max"] = df["rainfall_mm"].rolling(7).max()
    df["rainfall_previous_day"] = df["rainfall_mm"].shift(1)
    df["target_heavy_rain_next_day"] = (df["rainfall_mm"].shift(-1) >= HEAVY_RAIN_MM).astype(int)
    return df.dropna().reset_index(drop=True)


def critical_success_index(y_true, y_pred):
    """CSI = TP / (TP + FN + FP). Standard verification score for rare weather
    events - stricter than accuracy, doesn't reward "always predict no rain"."""
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    denom = tp + fn + fp
    return tp / denom if denom else 0.0


ERA5_CSV = Path(__file__).resolve().parent / "raw" / "era5_mumbai_all.csv"


def load_atmospheric_daily():
    """Aggregate the hourly Open-Meteo pull (humidity/pressure/wind/cloud cover)
    to one row per day, averaged across the Mumbai grid points, so it can be
    joined against the daily IMD rainfall table by date."""
    if not ERA5_CSV.exists():
        print(f"NOTE: {ERA5_CSV} not found - training on rainfall-only features.")
        print("Run 01_download_era5.py first to add atmospheric features.")
        return None
    df = pd.read_csv(ERA5_CSV, parse_dates=["time"])
    df["date"] = df["time"].dt.date
    daily = df.groupby("date").agg(
        humidity_avg=("relative_humidity_2m", "mean"),
        pressure_avg=("surface_pressure", "mean"),
        pressure_min=("surface_pressure", "min"),
        cloud_avg=("cloud_cover", "mean"),
        wind_avg=("wind_speed_10m", "mean"),
        wind_max=("wind_speed_10m", "max"),
    ).reset_index()
    daily["date"] = pd.to_datetime(daily["date"])
    return daily


def main():
    print("Loading + slicing IMD data for the Mumbai region...")
    df = add_features(load_and_slice())

    atmo = load_atmospheric_daily()
    extra_features = []
    if atmo is not None:
        df["date"] = pd.to_datetime(df["time"]).dt.normalize()
        before = len(df)
        df = df.merge(atmo, on="date", how="inner")
        print(f"Merged atmospheric data: {before} rows -> {len(df)} rows after joining on date")
        extra_features = ["humidity_avg", "pressure_avg", "pressure_min", "cloud_avg", "wind_avg", "wind_max"]

    df.to_csv(PROC / "mumbai_imd_features.csv", index=False)
    print("Rows:", len(df))
    print("Heavy-rain-next-day rate:", round(df["target_heavy_rain_next_day"].mean(), 4))

    df["year"] = pd.to_datetime(df["time"]).dt.year
    train = df[df.year <= TRAIN_END_YEAR]
    val = df[(df.year > TRAIN_END_YEAR) & (df.year <= VAL_END_YEAR)]
    test = df[df.year >= TEST_START_YEAR]
    if train.empty or val.empty or test.empty:
        raise SystemExit("Train, validation or test split is empty - check the years in the .grd files you uploaded.")

    features = ["rainfall_mm", "rainfall_3day", "rainfall_7day", "rainfall_15day",
                "rainfall_3day_max", "rainfall_7day_max", "rainfall_previous_day"] + extra_features
    print("Using features:", features)
    Xtr, ytr = train[features], train["target_heavy_rain_next_day"]
    Xval, yval = val[features], val["target_heavy_rain_next_day"]
    Xte, yte = test[features], test["target_heavy_rain_next_day"]

    model = lgb.LGBMClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        is_unbalance=True,  # heavy rain days are rare - don't let the model just predict "no" always
    )
    model.fit(Xtr, ytr)
    joblib.dump(model, MODELS / "rainfall_lgbm_mumbai.pkl")

    # Tune the decision threshold on VALIDATION data only (never on test) - pick
    # whichever cutoff maximizes CSI, instead of blindly using 0.5.
    val_prob = model.predict_proba(Xval)[:, 1]
    best_threshold, best_csi = 0.5, -1
    for t in [i / 100 for i in range(5, 96, 5)]:
        csi = critical_success_index(yval, (val_prob >= t).astype(int))
        if csi > best_csi:
            best_threshold, best_csi = t, csi
    print(f"Tuned decision threshold on validation (2020-{VAL_END_YEAR}): {best_threshold} (validation CSI {round(best_csi, 3)})")

    # Final, one-time evaluation on the untouched test set
    test_prob = model.predict_proba(Xte)[:, 1]
    pred = (test_prob >= best_threshold).astype(int)
    baseline_pred = (test["rainfall_mm"] >= HEAVY_RAIN_MM).astype(int)  # "today's heavy rain repeats tomorrow"

    def year_range(d):
        yrs = pd.to_datetime(d["time"]).dt.year
        return f"{yrs.min()}-{yrs.max()}" if len(d) else "none (empty!)"

    metrics = {
        "region": "Mumbai metropolitan area",
        "data_source": "IMD 0.25deg gridded daily rainfall (2015-2023, official)"
        + (" + Open-Meteo humidity/pressure/wind/cloud cover" if extra_features else ""),
        "train_years": year_range(train),
        "validation_years": year_range(val) + " (used only to tune the decision threshold)",
        "test_years": year_range(test) + " (untouched until final evaluation)",
        "tuned_decision_threshold": best_threshold,
        "model": {
            "precision": round(precision_score(yte, pred, zero_division=0), 3),
            "recall": round(recall_score(yte, pred, zero_division=0), 3),
            "f1": round(f1_score(yte, pred, zero_division=0), 3),
            "csi": round(critical_success_index(yte, pred), 3),
            "confusion_matrix": confusion_matrix(yte, pred).tolist(),  # [[TN,FP],[FN,TP]]
        },
        "persistence_baseline": {
            "precision": round(precision_score(yte, baseline_pred, zero_division=0), 3),
            "recall": round(recall_score(yte, baseline_pred, zero_division=0), 3),
            "f1": round(f1_score(yte, baseline_pred, zero_division=0), 3),
            "csi": round(critical_success_index(yte, baseline_pred), 3),
        },
        "n_test_days": int(len(test)),
        "positive_rate_test": round(float(yte.mean()), 3),
    }
    (PROC / "mumbai_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    print("\nModel saved to", MODELS / "rainfall_lgbm_mumbai.pkl")
    print("Metrics saved to", PROC / "mumbai_metrics.json", "- put this comparison in your deck.")


if __name__ == "__main__":
    main()
