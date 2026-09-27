"""Print data-access status for RainGuard training and impact layers.

This does not download multi-GB radar cubes (those need MOSDAC / IMD login).
It tells you what is already on disk and where to fetch the rest.

    python data-pipeline/07_data_access.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
IMD = RAW / "imd_rain"
ERA5 = RAW / "era5_mumbai_all.csv"
MODELS = ROOT.parent / "models"

CHECKS = [
    ("IMD daily rain .grd (2015-2023)", IMD, "https://www.imdpune.gov.in/cmpg/Griddata/Rainfall_25_NetCDF.html"),
    ("Open-Meteo / ERA5 hourly CSV", ERA5, "run data-pipeline/01_download_era5.py"),
    ("Mumbai LightGBM", MODELS / "rainfall_lgbm_mumbai.pkl", "python data-pipeline/05_ingest_imd_and_train.py"),
    ("National LightGBM", MODELS / "rainfall_lgbm_national.pkl", "python data-pipeline/06_train_national.py"),
]

LINKS = """
Radar / satellite (manual login)
  IMD DWR     https://mausam.imd.gov.in/responsive/dwrProducts.php
  MOSDAC      https://www.mosdac.gov.in/   (INSAT-3D, 3DR)
  GPM IMERG   https://gpm.nasa.gov/data/imerg

Terrain
  Copernicus GLO-30   https://portal.opentopography.org/
  Bhuvan CartoDEM     https://bhuvan.nrsc.gov.in/

City graph
  OSM Overpass        https://overpass-turbo.eu/
  BMC flood spots     encode into backend/city_mumbai.py

Voice
  Bhashini            https://bhashini.gov.in/
"""


def main():
    print("RainGuard data access\n")
    for name, path, hint in CHECKS:
        ok = path.exists()
        extra = ""
        if path.is_dir():
            n = len(list(path.glob("*.grd"))) + len(list(path.glob("*.nc")))
            extra = f" ({n} grid files)" if ok else ""
        print(f"  [{'OK' if ok else '--'}] {name}{extra}")
        if not ok:
            print(f"       -> {hint}")
    print(LINKS)


if __name__ == "__main__":
    main()
