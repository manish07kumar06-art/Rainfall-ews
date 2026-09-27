# Where the training and impact data actually comes from

RainGuard is not an OpenWeather JSON wrapper. Split the stack the way MoES
reviewers will: **meteorology (rain)** vs **hydrology (where water goes)** vs
**operations (so what)**.

Mumbai is the operational city twin on purpose. A national model at 0.25°
(~27 km) cannot tell you that Andheri subway is 3 ft under. Train national
as a *screen*; train and run inundation on one city.

---

## 1. Rainfall — official, for ML training

| Dataset | What it is | How to get it | Used for |
|---|---|---|---|
| **IMD 0.25° daily rainfall** | Official India gridded rain, 1901–present | [IMD Pune grid data](https://www.imdpune.gov.in/cmpg/Griddata/Rainfall_25_NetCDF.html) or `imdlib` (`rain`, yearwise `.grd`) | Next-day heavy rain classifier (`05_ingest_imd_and_train.py`, `06_train_national.py`) |
| **IMD station AWS/ARG** | Point rain gauges | [IMD AWS](https://aws.imd.gov.in/) / state AWS | Hyperlocal calibration, not a national grid |
| **IMD heavy-rain threshold** | 64.5 mm / 24 h = “heavy” | IMD glossary | Training label (already in the repo) |

Put yearly files in `data-pipeline/raw/imd_rain/2015.grd` … `2023.grd`.

```bash
pip install -r data-pipeline/requirements.txt
python data-pipeline/05_ingest_imd_and_train.py   # Mumbai basin model
python data-pipeline/06_train_national.py         # India screen, ~1°
```

## 2. Live rain + atmosphere (until you have radar files)

| Dataset | Notes |
|---|---|
| **Open-Meteo** (ERA5 / GFS / ICON blend) | What `04_live_fetch_predict.py` uses today. Honest stopgap: humidity, pressure, wind, 7-day forecast. **Not** the differentiator. |
| **IMD GFS / WRF** | Gridded forecast the national live layer should ingest in Phase 2 (one file, not 1000 API points). |

## 3. Doppler radar + satellite — the scientific ingest you pitch

| Dataset | What you compute | Access |
|---|---|---|
| **IMD DWR** (S-band / C-band) | Storm-cell centroid, motion vector, VIL / reflectivity → rain rate (Z–R) | [IMD DWR products](https://mausam.imd.gov.in/responsive/dwrProducts.php), MOSDAC, NCMRWF. Mumbai DWR is the first volume to wire. |
| **INSAT-3D / 3DR / 3DS** | IR brightness temperature, cloud-top cooling rate, moisture | [MOSDAC](https://www.mosdac.gov.in/) (ISRO). Register, download HDF for the west-coast sector. |
| **GPM IMERG** | Half-hourly satellite rain, global | [NASA GES DISC](https://gpm.nasa.gov/data/imerg) |
| **ERA5** | Reanalysis for historical atmosphere | CDS (`01_download_era5.py`) |

Do **not** train the city inundation model on OpenWeather `precipitation: 40`. Use DWR/INSAT as the *nowcast forcing* once files land; the impact engine already accepts a rain field.

Helper: `python data-pipeline/07_data_access.py` prints the same table and checks which local files you already have.

## 4. Terrain + drainage — inundation, not rain

| Dataset | Why |
|---|---|
| **Copernicus GLO-30 DEM** (30 m) | Default free DEM. [OpenTopography](https://portal.opentopography.org/) or [Copernicus](https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model) |
| **SRTM 30 m** | Fallback DEM |
| **NRSC CartoDEM / Bhuvan** | India-specific, often better in cities. [Bhuvan](https://bhuvan.nrsc.gov.in/) |
| **HAND** (Height Above Nearest Drainage) | Derived from DEM + flow direction. This is the hydrology feature. |
| **OpenStreetMap drains / waterways** | Nallas, rivers. Overpass API. |
| **BMC / MCGM flood spots** | Ground-truth sinks (Andheri subway, King Circle, …). Already encoded in `backend/city_mumbai.py`. |

The running engine uses a **calibrated proxy DEM + documented sinks** so the demo works offline. Swap rasters without changing `impact_engine.py`.

## 5. Roads, hospitals, power — the “so what” graph

| Dataset | Use |
|---|---|
| **OpenStreetMap** | Highways, underpasses, hospitals. |
| **Overpass** | Transformers are sparse in OSM — supplement from utility PDFs / RTI. |
| **India hospital directory** | MoHFW / state health GIS |
| **Mumbai flood-prone roads** | BMC disaster management cell lists (public PDFs every monsoon) |

Assets in `backend/city_mumbai.py` are the graph the cascade and ambulance Dijkstra run on. A GNN (Phase 2) trains on this same node/edge set plus historical outage labels.

## 6. CCTV as virtual sensors

You do **not** need new IoT. You need:

1. Public traffic-cam stills or a BMC feed MoU (many cities publish snapshot URLs).
2. A labelled set: tyre visible / half / gone, water vs streetlight.
3. YOLOv8-nano fine-tune; output `{camera_id, tyre_frac, depth_m}` into `/impact` (schema already matches `cctv` in the snapshot).

Until weights exist, the dashboard fuses inundation at camera pose into that schema (labelled as such). Do not claim live YOLO in the deck until the `.pt` file is in `models/`.

## 7. Voice alerts (Bhashini)

[Bhashini](https://bhashini.gov.in/) — TTS + translation. The API already returns `alerts[].en|hi|mr`. Wire:

- `ulca` / Bhashini TTS for Marathi + Hindi audio
- DLT-registered SMS for feature phones
- Ward polygons for who gets the blast

## 8. What not to do for MoES / SIH

- Do not put OpenWeather as the innovation slide.
- Do not train one LightGBM on all of India and draw 3 ft at Andheri — that number is a lie at 0.25°.
- Do not invent flood polygons that ignore elevation (the old mock did a west-side cheat; the new engine does HAND + drains + pumps).
- Do label proxy DEM, graph cascade vs trained GNN, and CCTV fusion vs trained YOLO. Reviewers respect that more than fake science.
