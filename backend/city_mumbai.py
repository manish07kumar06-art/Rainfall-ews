"""Hyperlocal Mumbai knowledge layer.

This is the city-scale digital twin the national rainfall model cannot replace.
Judges: rainfall is predicted at basin scale; inundation is computed here from
terrain, drainage, pumps, and known flood sinks.

Elevation is a calibrated PROXY DEM (relative metres), not a live SRTM download.
Replace `hand_m` / `elev_m` with Copernicus GLO-30 or NRSC CartoDEM when those
rasters are available — the hydrology equations stay the same.
"""

from __future__ import annotations

BBOX = [72.75, 18.90, 73.05, 19.30]  # lon0, lat0, lon1, lat1
NROWS, NCOLS = 22, 18
LAT0, LAT1 = BBOX[1], BBOX[3]
LON0, LON1 = BBOX[0], BBOX[2]
DLAT = (LAT1 - LAT0) / NROWS
DLON = (LON1 - LON0) / NCOLS

# Known flood basins (name, lat, lon, extra depression m, subway flag)
SINKS = [
    {"id": "andheri_subway", "name": "Andheri subway", "lat": 19.1197, "lon": 72.8465, "depression_m": 4.8, "subway": True},
    {"id": "milan_subway", "name": "Milan subway (Santacruz)", "lat": 19.0824, "lon": 72.8410, "depression_m": 4.2, "subway": True},
    {"id": "king_circle", "name": "King Circle underpass", "lat": 19.0320, "lon": 72.8595, "depression_m": 3.6, "subway": True},
    {"id": "sion", "name": "Sion circle", "lat": 19.0432, "lon": 72.8638, "depression_m": 2.8, "subway": False},
    {"id": "hindmata", "name": "Hindmata (Parel)", "lat": 19.0034, "lon": 72.8412, "depression_m": 3.1, "subway": False},
    {"id": "kurla", "name": "Kurla (LBS / CST)", "lat": 19.0650, "lon": 72.8794, "depression_m": 3.4, "subway": False},
    {"id": "chembur", "name": "Chembur-Ghatkopar nalla", "lat": 19.0588, "lon": 72.8990, "depression_m": 2.6, "subway": False},
    {"id": "dahisar", "name": "Dahisar check naka", "lat": 19.2570, "lon": 72.8680, "depression_m": 2.4, "subway": False},
    {"id": "grant_road", "name": "Grant Road / Tardeo", "lat": 18.9640, "lon": 72.8142, "depression_m": 2.2, "subway": False},
    {"id": "bandra_west", "name": "Bandra Linking Road", "lat": 19.0605, "lon": 72.8348, "depression_m": 2.0, "subway": False},
    {"id": "dadar_tt", "name": "Dadar TT", "lat": 19.0176, "lon": 72.8440, "depression_m": 2.5, "subway": False},
]

ASSETS = [
    {
        "id": "tx_andheri", "type": "transformer", "name": "Andheri East 33/11 kV",
        "lat": 19.1170, "lon": 72.8540, "critical_depth_m": 0.45,
        "serves": ["hosp_kohinoor", "area_andheri"],
        "action": "De-energise feeder if water reaches 0.45 m — avoid flashover.",
        "loss_inr": 1.8e7,
    },
    {
        "id": "tx_sion", "type": "transformer", "name": "Sion 33/11 kV",
        "lat": 19.0410, "lon": 72.8610, "critical_depth_m": 0.40,
        "serves": ["hosp_sion", "area_sion"],
        "action": "Isolate transformer. Reroute load to Matunga feeder.",
        "loss_inr": 1.5e7,
    },
    {
        "id": "tx_kurla", "type": "transformer", "name": "Kurla West 22 kV",
        "lat": 19.0680, "lon": 72.8820, "critical_depth_m": 0.50,
        "serves": ["hosp_kurla", "area_kurla"],
        "action": "Planned power cut to wet secondary — prevent grid trip cascade.",
        "loss_inr": 1.2e7,
    },
    {
        "id": "hosp_kohinoor", "type": "hospital", "name": "Kohinoor Hospital",
        "lat": 19.1145, "lon": 72.8690, "critical_depth_m": 0.30,
        "serves": [], "action": "Keep access via WEH northbound; close Andheri subway approach.",
        "loss_inr": 4.0e7,
    },
    {
        "id": "hosp_sion", "type": "hospital", "name": "Lokmanya Tilak (Sion) Hospital",
        "lat": 19.0378, "lon": 72.8602, "critical_depth_m": 0.25,
        "serves": [], "action": "Ambulance bay at 0.25 m — switch intake to eastern gate.",
        "loss_inr": 6.5e7,
    },
    {
        "id": "hosp_kurla", "type": "hospital", "name": "Rajawadi Hospital",
        "lat": 19.0755, "lon": 72.8998, "critical_depth_m": 0.30,
        "serves": [], "action": "Hold elective; keep Ghatkopar east corridor open.",
        "loss_inr": 2.5e7,
    },
    {
        "id": "pump_1", "type": "pump", "name": "Pump 1 · Andheri subway",
        "lat": 19.1190, "lon": 72.8472, "critical_depth_m": 9.0,
        "capacity_mm_per_hr": 28, "serves": ["andheri_subway"],
        "action": "Confirm both pumps online before peak cell.",
        "loss_inr": 8.0e6,
    },
    {
        "id": "pump_2", "type": "pump", "name": "Pump 2 · King Circle",
        "lat": 19.0315, "lon": 72.8600, "critical_depth_m": 9.0,
        "capacity_mm_per_hr": 22, "serves": ["king_circle"],
        "action": "Standby diesel — municipal drain backup.",
        "loss_inr": 6.0e6,
    },
    {
        "id": "pump_3", "type": "pump", "name": "Pump 3 · Kurla nalla",
        "lat": 19.0665, "lon": 72.8780, "critical_depth_m": 9.0,
        "capacity_mm_per_hr": 32, "serves": ["kurla"],
        "action": "If this pump fails, Kurla LBS floods 40–60 min faster.",
        "loss_inr": 9.0e6,
    },
]

ROADS = [
    {"id": "sv_andheri", "name": "SV Road · Andheri", "a": [19.125, 72.844], "b": [19.110, 72.844],
     "block_depth_m": 0.35, "kind": "arterial", "loss_inr_per_hr": 4.5e6},
    {"id": "weh_andheri", "name": "WEH · Andheri", "a": [19.130, 72.864], "b": [19.105, 72.864],
     "block_depth_m": 0.40, "kind": "highway", "loss_inr_per_hr": 9.0e6},
    {"id": "link_bandra", "name": "Linking Road · Bandra", "a": [19.070, 72.833], "b": [19.050, 72.836],
     "block_depth_m": 0.30, "kind": "arterial", "loss_inr_per_hr": 3.5e6},
    {"id": "sion_highway", "name": "Sion–Panvel / TT", "a": [19.050, 72.862], "b": [19.030, 72.861],
     "block_depth_m": 0.32, "kind": "highway", "loss_inr_per_hr": 8.0e6},
    {"id": "lbs_kurla", "name": "LBS Marg · Kurla", "a": [19.075, 72.882], "b": [19.055, 72.882],
     "block_depth_m": 0.35, "kind": "arterial", "loss_inr_per_hr": 5.0e6},
    {"id": "eeh_chembur", "name": "EEH · Chembur", "a": [19.070, 72.905], "b": [19.045, 72.905],
     "block_depth_m": 0.45, "kind": "highway", "loss_inr_per_hr": 7.5e6},
    {"id": "grant_rd", "name": "Grant Road", "a": [18.970, 72.814], "b": [18.958, 72.815],
     "block_depth_m": 0.28, "kind": "street", "loss_inr_per_hr": 1.8e6},
    {"id": "dadar_tt", "name": "Dadar TT flyover approach", "a": [19.025, 72.843], "b": [19.010, 72.845],
     "block_depth_m": 0.33, "kind": "arterial", "loss_inr_per_hr": 4.0e6},
    {"id": "w_e_highway_n", "name": "WEH · Goregaon–Dahisar", "a": [19.230, 72.860], "b": [19.180, 72.855],
     "block_depth_m": 0.42, "kind": "highway", "loss_inr_per_hr": 8.5e6},
    {"id": "cst_kurla", "name": "CST Road · Kurla", "a": [19.070, 72.872], "b": [19.058, 72.885],
     "block_depth_m": 0.30, "kind": "street", "loss_inr_per_hr": 2.2e6},
]

# Ambulance graph: node id -> lat, lon. Edges are road ids or named links.
GRAPH_NODES = {
    "n_andheri_w": (19.1197, 72.8400),
    "n_andheri_e": (19.1190, 72.8680),
    "n_bandra": (19.0605, 72.8348),
    "n_sion": (19.0432, 72.8638),
    "n_dadar": (19.0176, 72.8440),
    "n_kurla": (19.0650, 72.8794),
    "n_chembur": (19.0588, 72.8990),
    "n_ghatkopar": (19.0860, 72.9080),
    "n_kohinoor": (19.1145, 72.8690),
    "n_sion_hosp": (19.0378, 72.8602),
    "n_rajawadi": (19.0755, 72.8998),
    "n_powai": (19.1190, 72.9055),
}

# undirected edges: (u, v, road_id or None, minutes)
GRAPH_EDGES = [
    ("n_andheri_w", "n_andheri_e", "sv_andheri", 8),
    ("n_andheri_e", "n_kohinoor", "weh_andheri", 6),
    ("n_andheri_e", "n_powai", None, 12),
    ("n_andheri_w", "n_bandra", "link_bandra", 14),
    ("n_bandra", "n_dadar", None, 11),
    ("n_dadar", "n_sion", "dadar_tt", 7),
    ("n_sion", "n_sion_hosp", "sion_highway", 4),
    ("n_sion", "n_kurla", "lbs_kurla", 10),
    ("n_kurla", "n_chembur", "cst_kurla", 8),
    ("n_chembur", "n_rajawadi", "eeh_chembur", 6),
    ("n_ghatkopar", "n_rajawadi", None, 5),
    ("n_powai", "n_ghatkopar", None, 9),
    ("n_andheri_e", "n_kurla", "weh_andheri", 16),
    ("n_bandra", "n_sion", None, 13),
    ("n_kohinoor", "n_powai", None, 10),
]

CCTV = [
    {"id": "cam_andheri", "name": "Traffic cam · Andheri subway", "lat": 19.1195, "lon": 72.8468,
     "streetlight_m": 8.0, "tyre_m": 0.65},
    {"id": "cam_sion", "name": "Traffic cam · Sion circle", "lat": 19.0430, "lon": 72.8635,
     "streetlight_m": 7.5, "tyre_m": 0.65},
    {"id": "cam_kurla", "name": "Traffic cam · LBS Kurla", "lat": 19.0652, "lon": 72.8790,
     "streetlight_m": 8.5, "tyre_m": 0.65},
    {"id": "cam_king", "name": "Traffic cam · King Circle", "lat": 19.0322, "lon": 72.8593,
     "streetlight_m": 7.0, "tyre_m": 0.65},
    {"id": "cam_hindmata", "name": "Traffic cam · Hindmata", "lat": 19.0036, "lon": 72.8410,
     "streetlight_m": 8.0, "tyre_m": 0.65},
    {"id": "cam_bandra", "name": "Traffic cam · Linking Road", "lat": 19.0608, "lon": 72.8346,
     "streetlight_m": 7.2, "tyre_m": 0.65},
]

# Baseline municipal drain capacity (mm equivalent per 3h event) by cell class
BASE_DRAIN_MM = 18.0


def cell_center(r: int, c: int) -> tuple[float, float]:
    lat = LAT0 + (r + 0.5) * DLAT
    lon = LON0 + (c + 0.5) * DLON
    return lat, lon


def _dist2(lat1, lon1, lat2, lon2) -> float:
    return (lat1 - lat2) ** 2 + (lon1 - lon2) ** 2


def elev_and_hand(lat: float, lon: float) -> tuple[float, float]:
    """Relative elevation (m) and HAND (m above local drainage; lower = wetter)."""
    west = (lon - LON0) / (LON1 - LON0)
    north = (lat - LAT0) / (LAT1 - LAT0)
    elev = 6.0 + 32.0 * west + 8.0 * north
    elev += 22.0 * max(0.0, 1.0 - ((lat - 19.20) ** 2 / 0.012 + (lon - 72.92) ** 2 / 0.008))
    hand = elev
    for s in SINKS:
        d2 = _dist2(lat, lon, s["lat"], s["lon"])
        bowl = s["depression_m"] * pow(2.71828, -d2 / 0.00007)
        elev -= bowl
        # Known underpasses sit on the drainage network — HAND collapses there.
        hand -= bowl * (2.8 if s["subway"] else 2.1)
    return elev, max(0.12, hand)


def cell_polygon(r: int, c: int, inset: float = 0.0):
    lat_a = LAT0 + r * DLAT + inset
    lat_b = LAT0 + (r + 1) * DLAT - inset
    lon_a = LON0 + c * DLON + inset
    lon_b = LON0 + (c + 1) * DLON - inset
    return [[[lon_a, lat_a], [lon_b, lat_a], [lon_b, lat_b], [lon_a, lat_b], [lon_a, lat_a]]]


def nearest_cell(lat: float, lon: float) -> tuple[int, int]:
    r = int((lat - LAT0) / DLAT)
    c = int((lon - LON0) / DLON)
    r = max(0, min(NROWS - 1, r))
    c = max(0, min(NCOLS - 1, c))
    return r, c


def sink_hand_override(r: int, c: int) -> float | None:
    """Guarantees documented flood basins sit on the drainage network."""
    for s in SINKS:
        rr, cc = nearest_cell(s["lat"], s["lon"])
        manhattan = abs(rr - r) + abs(cc - c)
        if manhattan == 0:
            return 0.12 if s["subway"] else 0.28
        if manhattan == 1:
            return 0.40 if s["subway"] else 0.70
    return None


def city_profile() -> dict:
    return {
        "region": "Mumbai MMR — operational city twin",
        "bbox": BBOX,
        "grid": {"rows": NROWS, "cols": NCOLS},
        "sinks": SINKS,
        "assets": ASSETS,
        "roads": [
            {k: v for k, v in road.items() if k != "a" and k != "b"} | {
                "geometry": {"type": "LineString", "coordinates": [[road["a"][1], road["a"][0]], [road["b"][1], road["b"][0]]]},
            }
            for road in ROADS
        ],
        "cctv": CCTV,
        "notes": {
            "dem": "Calibrated proxy DEM + known flood sinks. Swap for Copernicus GLO-30 / CartoDEM without changing the engine.",
            "scope": "Hyperlocal by design. National LightGBM is a screening layer only.",
        },
    }
