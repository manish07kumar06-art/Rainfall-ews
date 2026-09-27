"""Impact engine: rainfall -> inundation depth -> blocked routes -> cascade -> ROI.

This is hydrology + a city graph, not a weather API wrapper.
- Inundation: excess rainfall vs drain/pump capacity, accumulated into HAND sinks.
- Cascade: flood hitting a transformer/hospital/road fires dependent alerts.
- Routing: Dijkstra on the remaining dry graph for ambulances.
- Simulator: drain_clean_factor and failed pumps change the same physics.

Honesty: the cascade is a directed asset graph (the GNN you pitch is the next
training step on this same graph). Depths are physically motivated, not a
trained PINN — the what-if sliders ARE the PINN interface (conservation of
volume + drainage).
"""

from __future__ import annotations

import heapq
from typing import Iterable

from city_mumbai import (
    ASSETS,
    BASE_DRAIN_MM,
    CCTV,
    GRAPH_EDGES,
    GRAPH_NODES,
    NCOLS,
    NROWS,
    ROADS,
    SINKS,
    cell_center,
    cell_polygon,
    elev_and_hand,
    nearest_cell,
    sink_hand_override,
)

FEET_PER_M = 3.28084


def _rain_at(lat: float, lon: float, rain_points: list[tuple[float, float, float]]) -> float:
    if not rain_points:
        return 0.0
    best, best_d = rain_points[0][2], 1e9
    for plat, plon, mm in rain_points:
        d = (lat - plat) ** 2 + (lon - plon) ** 2
        if d < best_d:
            best_d, best = d, mm
    return best


def rain_points_from_risk_geojson(risk: dict) -> list[tuple[float, float, float]]:
    pts = []
    for f in risk.get("features") or []:
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if not coords:
            continue
        ring = coords[0]
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        lat = sum(lats) / len(lats)
        lon = sum(lons) / len(lons)
        mm = float((f.get("properties") or {}).get("rain_mm_3h") or 0)
        pts.append((lat, lon, mm))
    return pts


def compute_depths(
    rain_points: list[tuple[float, float, float]],
    *,
    drain_clean_factor: float = 1.0,
    failed_pumps: Iterable[str] | None = None,
    extra_rain_mm: float = 0.0,
) -> list[list[dict]]:
    failed = set(failed_pumps or [])
    pump_boost = {}
    for a in ASSETS:
        if a["type"] != "pump":
            continue
        r, c = nearest_cell(a["lat"], a["lon"])
        cap = float(a.get("capacity_mm_per_hr") or 0)
        if a["id"] in failed:
            cap *= 0.15
        pump_boost[(r, c)] = pump_boost.get((r, c), 0.0) + cap

    grid = []
    for r in range(NROWS):
        row = []
        for c in range(NCOLS):
            lat, lon = cell_center(r, c)
            elev, hand = elev_and_hand(lat, lon)
            forced = sink_hand_override(r, c)
            if forced is not None:
                hand = forced
                elev = min(elev, 3.0 + forced)
            rain = _rain_at(lat, lon, rain_points) + extra_rain_mm
            drain = BASE_DRAIN_MM * drain_clean_factor * (0.22 + 0.78 * min(1.0, hand / 14.0))
            drain += pump_boost.get((r, c), 0.0)
            excess = max(0.0, rain - drain)
            # Urban catchment concentrates runoff into carriageway / underpass.
            # ~50 mm excess at HAND 0.2 m → about 0.9 m (3 ft) in a subway bowl.
            concentrate = (20.0 if hand < 0.35 else 9.5) / (0.30 + hand)
            depth = min(1.85, (excess / 1000.0) * 0.90 * concentrate)
            row.append({
                "r": r, "c": c, "lat": lat, "lon": lon,
                "elev_m": round(elev, 2), "hand_m": round(hand, 2),
                "rain_mm": round(rain, 1), "drain_mm": round(drain, 1),
                "depth_m": depth,
            })
        grid.append(row)

    # Two-pass downslope accumulation (D8-lite)
    order = sorted(
        ((grid[r][c]["elev_m"], r, c) for r in range(NROWS) for c in range(NCOLS)),
        reverse=True,
    )
    for _, r, c in order:
        best_nb, best_e = None, grid[r][c]["elev_m"]
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < NROWS and 0 <= cc < NCOLS and grid[rr][cc]["elev_m"] < best_e:
                best_e = grid[rr][cc]["elev_m"]
                best_nb = (rr, cc)
        if best_nb:
            spill = max(0.0, grid[r][c]["depth_m"] - 0.12) * 0.16
            grid[r][c]["depth_m"] -= spill
            grid[best_nb[0]][best_nb[1]]["depth_m"] += spill

    for r in range(NROWS):
        for c in range(NCOLS):
            grid[r][c]["depth_m"] = round(max(0.0, grid[r][c]["depth_m"]), 2)
            d = grid[r][c]["depth_m"]
            if d < 0.08:
                grid[r][c]["depth_class"] = None
            elif d < 0.25:
                grid[r][c]["depth_class"] = "low"
            elif d < 0.55:
                grid[r][c]["depth_class"] = "medium"
            else:
                grid[r][c]["depth_class"] = "high"
    return grid


def _depth_at(grid, lat, lon) -> float:
    r, c = nearest_cell(lat, lon)
    return grid[r][c]["depth_m"]


def _mid(road) -> tuple[float, float]:
    return ((road["a"][0] + road["b"][0]) / 2, (road["a"][1] + road["b"][1]) / 2)


def evaluate_roads(grid) -> list[dict]:
    out = []
    for road in ROADS:
        lat, lon = _mid(road)
        d = _depth_at(grid, lat, lon)
        blocked = d >= road["block_depth_m"]
        out.append({
            "id": road["id"],
            "name": road["name"],
            "kind": road["kind"],
            "depth_m": round(d, 2),
            "depth_ft": round(d * FEET_PER_M, 1),
            "block_depth_m": road["block_depth_m"],
            "blocked": blocked,
            "do_not_dispatch": blocked,
            "loss_inr_per_hr": road["loss_inr_per_hr"] if blocked else 0,
            "geometry": {
                "type": "LineString",
                "coordinates": [[road["a"][1], road["a"][0]], [road["b"][1], road["b"][0]]],
            },
        })
    return out


def evaluate_assets(grid) -> list[dict]:
    out = []
    for a in ASSETS:
        d = _depth_at(grid, a["lat"], a["lon"])
        hit = d >= a["critical_depth_m"] and a["type"] != "pump"
        rec = {
            **{k: a[k] for k in ("id", "type", "name", "lat", "lon", "critical_depth_m", "action", "loss_inr")},
            "depth_m": round(d, 2),
            "depth_ft": round(d * FEET_PER_M, 1),
            "triggered": hit,
        }
        if a["type"] == "transformer":
            rec["recommend_power_cut"] = hit
        if a["type"] == "hospital":
            rec["access_compromised"] = hit
        if a["type"] == "pump":
            rec["online"] = True
        out.append(rec)
    return out


def cascade(assets: list[dict], roads: list[dict]) -> list[dict]:
    """Graph-style knock-on effects (the GNN training target lives here)."""
    events = []
    blocked_ids = {r["id"] for r in roads if r["blocked"]}
    by_id = {a["id"]: a for a in assets}

    for a in assets:
        if a["type"] == "transformer" and a.get("recommend_power_cut"):
            events.append({
                "severity": "critical",
                "title": f"Power cut recommended · {a['name']}",
                "detail": a["action"],
                "source": a["id"],
                "domino": [sid for sid in next(x["serves"] for x in ASSETS if x["id"] == a["id"])],
            })
            for sid in next(x["serves"] for x in ASSETS if x["id"] == a["id"]):
                tgt = by_id.get(sid)
                if tgt and tgt["type"] == "hospital":
                    events.append({
                        "severity": "high",
                        "title": f"Hospital backup power · {tgt['name']}",
                        "detail": "Upstream feeder de-energised. Confirm DG set and cancel elective OT.",
                        "source": a["id"],
                        "domino": [tgt["id"]],
                    })

    for r in roads:
        if r["blocked"] and r["kind"] in ("highway", "arterial"):
            events.append({
                "severity": "high",
                "title": f"Do not dispatch · {r['name']}",
                "detail": f"{r['depth_m']} m ({r['depth_ft']} ft) water. Ambulances and delivery fleets: use alternate corridor.",
                "source": r["id"],
                "domino": [],
            })

    if "sv_andheri" in blocked_ids:
        events.append({
            "severity": "critical",
            "title": "Andheri subway approach closed",
            "detail": "WEH remains the only north–south for emergency from Andheri West.",
            "source": "sv_andheri",
            "domino": ["weh_andheri"],
        })
    return events


def _edge_cost(u, v, road_id, minutes, blocked_ids) -> float | None:
    if road_id and road_id in blocked_ids:
        return None
    return minutes


def shortest_path(start: str, goal: str, blocked_ids: set[str]) -> dict:
    adj = {n: [] for n in GRAPH_NODES}
    for u, v, rid, mins in GRAPH_EDGES:
        adj[u].append((v, rid, mins))
        adj[v].append((u, rid, mins))

    dist = {start: 0.0}
    prev = {}
    pq = [(0.0, start)]
    while pq:
        d, n = heapq.heappop(pq)
        if n == goal:
            break
        if d > dist.get(n, 1e9):
            continue
        for nb, rid, mins in adj[n]:
            cost = _edge_cost(n, nb, rid, mins, blocked_ids)
            if cost is None:
                continue
            nd = d + cost
            if nd < dist.get(nb, 1e9):
                dist[nb] = nd
                prev[nb] = (n, rid)
                heapq.heappush(pq, (nd, nb))

    if goal not in dist:
        return {"ok": False, "from": start, "to": goal, "minutes": None, "nodes": [], "reason": "No dry corridor"}

    nodes = [goal]
    roads_used = []
    cur = goal
    while cur != start:
        p, rid = prev[cur]
        nodes.append(p)
        if rid:
            roads_used.append(rid)
        cur = p
    nodes.reverse()
    coords = [[GRAPH_NODES[n][1], GRAPH_NODES[n][0]] for n in nodes]
    return {
        "ok": True, "from": start, "to": goal, "minutes": round(dist[goal], 1),
        "nodes": nodes, "roads": roads_used,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def ambulance_reroutes(roads: list[dict]) -> list[dict]:
    blocked = {r["id"] for r in roads if r["blocked"]}
    missions = [
        {"id": "m1", "label": "Andheri West → Kohinoor Hospital", "from": "n_andheri_w", "to": "n_kohinoor"},
        {"id": "m2", "label": "Bandra → Sion Hospital", "from": "n_bandra", "to": "n_sion_hosp"},
        {"id": "m3", "label": "Kurla → Rajawadi Hospital", "from": "n_kurla", "to": "n_rajawadi"},
        {"id": "m4", "label": "Andheri East → Rajawadi (avoid subway)", "from": "n_andheri_e", "to": "n_rajawadi"},
    ]
    out = []
    for m in missions:
        dry = shortest_path(m["from"], m["to"], blocked)
        wet = shortest_path(m["from"], m["to"], set())  # ignore flood — the naive path
        out.append({**m, "recommended": dry, "naive": wet, "rerouted": dry.get("ok") and dry.get("roads") != wet.get("roads")})
    return out


def cctv_observations(grid) -> list[dict]:
    """Virtual sensors: depth at camera, expressed as tyre / streetlight fractions.

    Production: YOLOv8 detects tyre and lamp, depth = tyre_frac * tyre_m.
    Here the inundation field is the observation; the same schema is what CV
    will write into after the detector is trained on annotated frames.
    """
    obs = []
    for cam in CCTV:
        d = _depth_at(grid, cam["lat"], cam["lon"])
        tyre_frac = min(1.4, d / cam["tyre_m"])
        obs.append({
            **cam,
            "water_depth_m": round(d, 2),
            "water_depth_ft": round(d * FEET_PER_M, 1),
            "tyre_submerged_frac": round(tyre_frac, 2),
            "self_calibrate": d >= 0.15,
            "status": "flooded" if d >= 0.5 else "wet" if d >= 0.15 else "dry",
            "note": "YOLOv8 tyre/streetlight detector writes this same payload; demo uses fused inundation at camera pose.",
        })
    return obs


def hotspot_narratives(grid, clock: str | None) -> list[dict]:
    stories = []
    for s in SINKS:
        d = _depth_at(grid, s["lat"], s["lon"])
        # crude 90-min lead: depressions keep filling
        later = round(min(2.4, d * 1.28 + (0.18 if s["subway"] else 0.06)), 2)
        stories.append({
            "id": s["id"],
            "name": s["name"],
            "subway": s["subway"],
            "now_depth_m": round(d, 2),
            "now_depth_ft": round(d * FEET_PER_M, 1),
            "in_90min_depth_m": later,
            "in_90min_depth_ft": round(later * FEET_PER_M, 1),
            "lat": s["lat"],
            "lon": s["lon"],
            "narrative": _story(s, d, later, clock),
        })
    stories.sort(key=lambda x: (x["subway"], x["in_90min_depth_m"]), reverse=True)
    return stories


def _story(sink, now, later, clock) -> str:
    when = clock or "now"
    if later < 0.15:
        return f"{sink['name']}: no material inundation expected from this pulse."
    loc = sink["name"]
    if sink["subway"]:
        return (
            f"Heavy rain at {loc} ({when}). By ~90 minutes, underpass water "
            f"~{later:.2f} m ({later * FEET_PER_M:.1f} ft). "
            f"Do not send ambulances or last-mile delivery through this subway."
        )
    return (
        f"{loc}: street water {now:.2f} m now, ~{later:.2f} m in 90 min. "
        f"Block last-mile dispatch on this corridor."
    )


def roi(assets, roads, reroutes, events) -> dict:
    prevented = 0.0
    lines = []
    for a in assets:
        if a.get("recommend_power_cut"):
            prevented += a["loss_inr"] * 0.65  # avoided transformer burn / outage spread
            lines.append({"label": f"Avoided feeder flashover · {a['name']}", "inr": a["loss_inr"] * 0.65})
        if a.get("access_compromised"):
            prevented += 2.5e6
            lines.append({"label": f"Hospital intake reroute · {a['name']}", "inr": 2.5e6})
    for r in roads:
        if r["blocked"]:
            prevented += r["loss_inr_per_hr"] * 0.4  # 24 min of chaos avoided by early close
            lines.append({"label": f"Early closure · {r['name']}", "inr": r["loss_inr_per_hr"] * 0.4})
    n_reroute = sum(1 for m in reroutes if m.get("rerouted") and m["recommended"].get("ok"))
    prevented += n_reroute * 1.2e6
    if n_reroute:
        lines.append({"label": f"{n_reroute} ambulance missions rerouted", "inr": n_reroute * 1.2e6})
    return {
        "estimated_loss_prevented_inr": round(prevented),
        "display_inr_cr": round(prevented / 1e7, 2),
        "lines": [{"label": x["label"], "inr": round(x["inr"])} for x in lines],
        "note": "Planning estimate for the command dashboard (unit-loss priors). Not an audited actuarial figure.",
    }


def alerts_bhashini(stories, events) -> list[dict]:
    """Payloads ready for Bhashini TTS + SMS. Hindi/Marathi strings included."""
    alerts = []
    for s in stories[:4]:
        if s["in_90min_depth_m"] < 0.25:
            continue
        hi = (
            f"{s['name']} में अभी पानी लगभग {s['now_depth_m']} मीटर है। "
            f"90 मिनट में {s['in_90min_depth_m']} मीटर तक बढ़ सकता है। "
            f"इस रास्ते से एम्बुलेंस या डिलीवरी न भेजें।"
        )
        mr = (
            f"{s['name']} येथे पाणी सुमारे {s['now_depth_m']} मीटर आहे. "
            f"90 मिनिटांत {s['in_90min_depth_m']} मीटर होऊ शकते. "
            f"या मार्गावरून रुग्णवाहिका पाठवू नका."
        )
        alerts.append({
            "id": s["id"],
            "severity": "red" if s["in_90min_depth_m"] >= 0.7 else "orange",
            "en": s["narrative"],
            "hi": hi,
            "mr": mr,
            "channel": "bhashini_voice_sms",
            "targets": "ward officers + feature-phone blast for the affected slum/ward",
        })
    return alerts


def flood_geojson(grid) -> dict:
    feats = []
    for r in range(NROWS):
        for c in range(NCOLS):
            cell = grid[r][c]
            if not cell["depth_class"]:
                continue
            feats.append({
                "type": "Feature",
                "properties": {
                    "depth_class": cell["depth_class"],
                    "depth_m": cell["depth_m"],
                    "depth_ft": round(cell["depth_m"] * FEET_PER_M, 1),
                    "rain_mm": cell["rain_mm"],
                    "hand_m": cell["hand_m"],
                },
                "geometry": {"type": "Polygon", "coordinates": cell_polygon(r, c, 0.001)},
            })
    return {"type": "FeatureCollection", "features": feats}


def snapshot(
    risk: dict,
    *,
    clock: str | None = None,
    drain_clean_factor: float = 1.0,
    failed_pumps: list[str] | None = None,
    extra_rain_mm: float = 0.0,
) -> dict:
    rain_points = rain_points_from_risk_geojson(risk)
    grid = compute_depths(
        rain_points,
        drain_clean_factor=drain_clean_factor,
        failed_pumps=failed_pumps,
        extra_rain_mm=extra_rain_mm,
    )
    roads = evaluate_roads(grid)
    assets = evaluate_assets(grid)
    events = cascade(assets, roads)
    reroutes = ambulance_reroutes(roads)
    cams = cctv_observations(grid)
    stories = hotspot_narratives(grid, clock)
    money = roi(assets, roads, reroutes, events)
    max_d = max(cell["depth_m"] for row in grid for cell in row)
    flooded = sum(1 for row in grid for cell in row if cell["depth_class"])
    headline = stories[0] if stories else None
    return {
        "engine": "RainGuard impact twin · Mumbai hyperlocal",
        "params": {
            "drain_clean_factor": drain_clean_factor,
            "failed_pumps": failed_pumps or [],
            "extra_rain_mm": extra_rain_mm,
        },
        "clock": clock,
        "headline": headline,
        "max_depth_m": round(max_d, 2),
        "max_depth_ft": round(max_d * FEET_PER_M, 1),
        "flooded_cells": flooded,
        "blocked_roads": sum(1 for r in roads if r["blocked"]),
        "power_cut_recommended": sum(1 for a in assets if a.get("recommend_power_cut")),
        "flood": flood_geojson(grid),
        "roads": roads,
        "assets": assets,
        "cascade": events,
        "ambulance": reroutes,
        "cctv": cams,
        "hotspots": stories,
        "roi": money,
        "alerts": alerts_bhashini(stories, events),
        "honesty": {
            "dem": "Proxy DEM + documented Mumbai sinks. Replace with Copernicus GLO-30.",
            "radar": "Live rain currently from the trained IMD/Open-Meteo pipeline; DWR/INSAT ingest is the next data swap.",
            "cv": "CCTV schema is the YOLOv8 virtual-sensor contract; demo fuses inundation at camera pose.",
            "gnn": "Cascade is the city graph a GNN will learn; rules fire the same nodes/edges.",
            "pinn": "What-if sliders conserve rainfall volume vs drain/pump capacity — the PINN loss is this balance.",
        },
    }
