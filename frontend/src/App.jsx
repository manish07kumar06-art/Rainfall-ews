import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";
import {
  fetchMetrics,
  fetchRisk,
  fetchSnapshot,
  fetchTimeline,
  simulateImpact,
} from "./api";

const RISK_COLORS = ["#2ecc71", "#f1c40f", "#e67e22", "#c0392b"];
const RISK_OPACITY = [0.05, 0.28, 0.48, 0.7];
const RISK_LABELS = ["Low", "Moderate", "High", "Severe"];
const FLOOD_FILL = { low: "#7ec8e3", medium: "#2b6cb0", high: "#1a365d" };

function inrCr(n) {
  if (n == null) return "—";
  return `₹ ${Number(n).toFixed(2)} Cr`;
}

function PrecipChart({ hours, hour, onScrub }) {
  const W = 900,
    H = 78,
    PAD = 6;
  const max = Math.max(1, ...hours.map((h) => h.max_rain_mm_3h));
  const step = hours.length > 1 ? (W - PAD * 2) / (hours.length - 1) : 0;
  const points = hours
    .map((h, i) => {
      const x = PAD + i * step;
      const y = H - PAD - (h.max_rain_mm_3h / max) * (H - PAD * 2);
      return `${x},${y}`;
    })
    .join(" ");
  const scrub = (evt) => {
    const rect = evt.currentTarget.getBoundingClientRect();
    const relX = ((evt.clientX - rect.left) / rect.width) * W;
    const idx = Math.round((relX - PAD) / step);
    onScrub(Math.min(hours.length - 1, Math.max(0, idx)));
  };
  const curX = PAD + hour * step;
  return (
    <svg className="precip-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" onClick={scrub}>
      <polyline points={points} fill="none" stroke="#5ec8ff" strokeWidth="2" />
      <polyline
        points={`${PAD},${H - PAD} ${points} ${W - PAD},${H - PAD}`}
        fill="#5ec8ff22"
        stroke="none"
      />
      <line x1={curX} y1={0} x2={curX} y2={H} stroke="#e7edf3" strokeWidth="1.5" strokeDasharray="3,3" />
    </svg>
  );
}

function RoiTicker({ cr }) {
  return (
    <div className="roi-ticker" title="Planning estimate of loss avoided by early power cuts and reroutes">
      <span className="roi-kicker">LOSS PREVENTED</span>
      <span className="roi-value">{inrCr(cr)}</span>
    </div>
  );
}

export default function App() {
  const mapDivRef = useRef(null);
  const mapRef = useRef(null);
  const layersRef = useRef({});
  const tileLayerRef = useRef(null);
  const timerRef = useRef(null);

  const [timeline, setTimeline] = useState(null);
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState("replay");
  const [basemap, setBasemap] = useState("street");
  const [showRisk, setShowRisk] = useState(true);
  const [showFlood, setShowFlood] = useState(true);
  const [showRoads, setShowRoads] = useState(true);
  const [showAssets, setShowAssets] = useState(true);
  const [showCctv, setShowCctv] = useState(true);
  const [showRoutes, setShowRoutes] = useState(true);
  const [snapshot, setSnapshot] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [tab, setTab] = useState("impact");
  const [lang, setLang] = useState("en");
  const [scenarioOn, setScenarioOn] = useState(false);
  const [drain, setDrain] = useState(1);
  const [extraRain, setExtraRain] = useState(0);
  const [failPump3, setFailPump3] = useState(false);
  const [simulating, setSimulating] = useState(false);

  const TILES = {
    satellite:
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    street:
      "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  };

  useEffect(() => {
    if (mapRef.current) return;
    mapRef.current = L.map(mapDivRef.current, { zoomControl: false }).setView([19.08, 72.88], 11);
    tileLayerRef.current = L.tileLayer(TILES.street, {
      attribution: "&copy; OSM &copy; CARTO",
      maxZoom: 19,
    }).addTo(mapRef.current);
    L.control.zoom({ position: "bottomright" }).addTo(mapRef.current);
  }, []);

  useEffect(() => {
    if (!tileLayerRef.current) return;
    tileLayerRef.current.setUrl(TILES[basemap]);
  }, [basemap]);

  useEffect(() => {
    setError(null);
    setTimeline(null);
    setSnapshot(null);
    setHour(0);
    setScenarioOn(false);
    fetchTimeline(mode)
      .then(setTimeline)
      .catch((e) => setError(`Could not load ${mode} timeline. ${e.message}`));
    fetchMetrics().then(setMetrics).catch(() => {});
  }, [mode]);

  useEffect(() => {
    if (!timeline) return;
    let cancelled = false;
    Promise.all([fetchRisk(mode, hour), fetchSnapshot(mode, hour)])
      .then(([risk, snap]) => {
        if (cancelled) return;
        setSnapshot(snap);
        drawMap(risk, snap);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [hour, timeline, mode]);

  function clearDynamic() {
    const map = mapRef.current;
    if (!map) return;
    Object.values(layersRef.current).forEach((ly) => {
      if (ly && map.hasLayer(ly)) map.removeLayer(ly);
    });
    layersRef.current = {};
  }

  function drawMap(risk, snap) {
    const map = mapRef.current;
    if (!map) return;
    clearDynamic();

    layersRef.current.risk = L.geoJSON(risk, {
      style: (f) => ({
        color: "#0006",
        weight: 0.4,
        fillColor: RISK_COLORS[f.properties.risk_level] || "#2ecc71",
        fillOpacity: RISK_OPACITY[f.properties.risk_level] ?? 0.1,
      }),
    }).bindTooltip((l) => `Rain: ${l.feature.properties.rain_mm_3h} mm`);
    if (showRisk) layersRef.current.risk.addTo(map);

    if (snap?.flood) {
      layersRef.current.flood = L.geoJSON(snap.flood, {
        style: (f) => ({
          color: FLOOD_FILL[f.properties.depth_class],
          weight: 0,
          fillColor: FLOOD_FILL[f.properties.depth_class],
          fillOpacity: f.properties.depth_class === "high" ? 0.72 : 0.5,
        }),
      }).bindTooltip(
        (l) =>
          `${l.feature.properties.depth_m} m · ${l.feature.properties.depth_ft} ft water`
      );
      if (showFlood) layersRef.current.flood.addTo(map);
    }

    if (snap?.roads) {
      layersRef.current.roads = L.geoJSON(
        {
          type: "FeatureCollection",
          features: snap.roads.map((r) => ({
            type: "Feature",
            properties: r,
            geometry: r.geometry,
          })),
        },
        {
          style: (f) => ({
            color: f.properties.blocked ? "#ff4d4d" : "#3dd68c",
            weight: f.properties.blocked ? 5 : 2.5,
            opacity: 0.95,
            dashArray: f.properties.blocked ? "6,6" : null,
          }),
        }
      ).bindTooltip(
        (l) =>
          `${l.feature.properties.name}<br/>${l.feature.properties.depth_m} m · ${
            l.feature.properties.blocked ? "BLOCKED — do not dispatch" : "passable"
          }`
      );
      if (showRoads) layersRef.current.roads.addTo(map);
    }

    const assetGroup = L.layerGroup();
    (snap?.assets || []).forEach((a) => {
      const color =
        a.type === "hospital" ? "#ff6b8a" : a.type === "transformer" ? "#ffd166" : "#5ec8ff";
      const m = L.circleMarker([a.lat, a.lon], {
        radius: a.triggered ? 9 : 6,
        color,
        weight: 2,
        fillColor: color,
        fillOpacity: a.triggered ? 0.95 : 0.55,
      }).bindPopup(
        `<strong>${a.name}</strong><br/>${a.type}<br/>Water ${a.depth_m} m / critical ${a.critical_depth_m} m<br/>${a.action}`
      );
      assetGroup.addLayer(m);
    });
    layersRef.current.assets = assetGroup;
    if (showAssets) assetGroup.addTo(map);

    const camGroup = L.layerGroup();
    (snap?.cctv || []).forEach((c) => {
      const color = c.status === "flooded" ? "#ff4d4d" : c.status === "wet" ? "#f1c40f" : "#9ae6b4";
      const m = L.circleMarker([c.lat, c.lon], {
        radius: 5,
        color,
        fillColor: color,
        fillOpacity: 0.9,
        weight: 1,
      }).bindPopup(
        `<strong>${c.name}</strong><br/>Virtual sensor depth ${c.water_depth_m} m<br/>Tyre submerged ${c.tyre_submerged_frac}×`
      );
      camGroup.addLayer(m);
    });
    layersRef.current.cctv = camGroup;
    if (showCctv) camGroup.addTo(map);

    const routeGroup = L.layerGroup();
    (snap?.ambulance || []).forEach((m) => {
      const g = m.recommended?.geometry;
      if (!g || !m.recommended?.ok) return;
      L.geoJSON(g, {
        style: { color: "#b794f4", weight: 3, opacity: 0.9 },
      })
        .bindTooltip(`${m.label} · ${m.recommended.minutes} min`)
        .addTo(routeGroup);
    });
    layersRef.current.routes = routeGroup;
    if (showRoutes) routeGroup.addTo(map);
  }

  useEffect(() => {
    const map = mapRef.current;
    const Lrs = layersRef.current;
    if (!map) return;
    const apply = (key, on) => {
      if (!Lrs[key]) return;
      if (on) Lrs[key].addTo(map);
      else map.removeLayer(Lrs[key]);
    };
    apply("risk", showRisk);
    apply("flood", showFlood);
    apply("roads", showRoads);
    apply("assets", showAssets);
    apply("cctv", showCctv);
    apply("routes", showRoutes);
  }, [showRisk, showFlood, showRoads, showAssets, showCctv, showRoutes]);

  useEffect(() => {
    if (playing && timeline) {
      timerRef.current = setInterval(() => {
        setHour((h) => (h + 1) % timeline.hours.length);
        setScenarioOn(false);
      }, 850);
    }
    return () => clearInterval(timerRef.current);
  }, [playing, timeline]);

  const t = timeline ? timeline.hours[hour] : null;
  const headline = snapshot?.headline;
  const roiCr = snapshot?.roi?.display_inr_cr ?? 0;

  const runSim = async () => {
    setSimulating(true);
    setError(null);
    try {
      const snap = await simulateImpact({
        mode,
        hour,
        drain_clean_factor: drain,
        failed_pumps: failPump3 ? ["pump_3"] : [],
        extra_rain_mm: extraRain,
      });
      const risk = await fetchRisk(mode, hour);
      setSnapshot(snap);
      setScenarioOn(true);
      drawMap(risk, snap);
    } catch (e) {
      setError(e.message);
    } finally {
      setSimulating(false);
    }
  };

  const resetSim = async () => {
    setDrain(1);
    setExtraRain(0);
    setFailPump3(false);
    setScenarioOn(false);
    const [risk, snap] = await Promise.all([fetchRisk(mode, hour), fetchSnapshot(mode, hour)]);
    setSnapshot(snap);
    drawMap(risk, snap);
  };

  const blocked = (snapshot?.roads || []).filter((r) => r.blocked);
  const cuts = (snapshot?.assets || []).filter((a) => a.recommend_power_cut);

  const alertText = useMemo(() => {
    const a = snapshot?.alerts?.[0];
    if (!a) return headline?.narrative;
    return a[lang] || a.en;
  }, [snapshot, lang, headline]);

  return (
    <div className="ops">
      <header className="ops-top">
        <div className="brand">
          <div className="brand-name">RainGuard</div>
          <div className="brand-tag">B2G IMPACT TWIN · MUMBAI</div>
        </div>
        <div className="ops-meta">
          {timeline ? (
            <>
              <span>{timeline.region}</span>
              <span className="sep">·</span>
              <span>{t?.time?.replace("T", " ")}</span>
            </>
          ) : (
            "Connecting command feed…"
          )}
        </div>
        <div className="mode-toggle">
          <button className={mode === "live" ? "on" : ""} onClick={() => setMode("live")}>
            Live
          </button>
          <button className={mode === "replay" ? "on" : ""} onClick={() => setMode("replay")}>
            2021 replay
          </button>
        </div>
        <div className={`pill ${error ? "bad" : "ok"}`}>
          <i />
          {error ? "FEED DOWN" : scenarioOn ? "WHAT-IF SCENARIO" : mode === "live" ? "LIVE" : "REPLAY"}
        </div>
        <RoiTicker cr={roiCr} />
      </header>

      <div className="ops-main">
        <aside className="rail">
          <div className="rail-h">LAYERS</div>
          {[
            ["Rain risk", showRisk, setShowRisk],
            ["Inundation depth", showFlood, setShowFlood],
            ["Roads / dispatch", showRoads, setShowRoads],
            ["Critical assets", showAssets, setShowAssets],
            ["CCTV virtual sensors", showCctv, setShowCctv],
            ["Ambulance corridors", showRoutes, setShowRoutes],
          ].map(([label, val, set]) => (
            <label key={label} className="chk">
              <input type="checkbox" checked={val} onChange={(e) => set(e.target.checked)} />
              {label}
            </label>
          ))}
          <div className="rail-h">BASEMAP</div>
          <label className="chk">
            <input type="radio" checked={basemap === "street"} onChange={() => setBasemap("street")} />
            Dark streets
          </label>
          <label className="chk">
            <input type="radio" checked={basemap === "satellite"} onChange={() => setBasemap("satellite")} />
            Satellite
          </label>
          {metrics?.mumbai && (
            <>
              <div className="rail-h">CITY MODEL</div>
              <div className="metric">
                Mumbai CSI <b>{metrics.mumbai.model.csi}</b>
                <span> vs persistence {metrics.mumbai.persistence_baseline.csi}</span>
              </div>
            </>
          )}
          {metrics?.national && (
            <div className="metric dim">
              National screen CSI {metrics.national.model.csi} · {metrics.national.n_locations} cells
            </div>
          )}
        </aside>

        <div className="stage">
          <div ref={mapDivRef} className="map" />
          {error && <div className="banner err">{error}</div>}
          {headline && (
            <div className="banner story">
              <div className="story-kicker">IMPACT, NOT JUST RAIN</div>
              <div className="story-body">{headline.narrative}</div>
            </div>
          )}
          <div className="legend">
            <div className="lg-h">Rain</div>
            {RISK_LABELS.map((lb, i) => (
              <div className="lg-row" key={lb}>
                <i style={{ background: RISK_COLORS[i] }} />
                {lb}
              </div>
            ))}
            <div className="lg-h">Water</div>
            {Object.entries(FLOOD_FILL).map(([k, c]) => (
              <div className="lg-row" key={k}>
                <i style={{ background: c }} />
                {k}
              </div>
            ))}
            <div className="lg-row">
              <i style={{ background: "#ff4d4d" }} />
              blocked road
            </div>
          </div>
        </div>

        <aside className="side">
          <div className="tabs">
            {["impact", "dispatch", "cctv", "simulate", "alerts"].map((id) => (
              <button key={id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
                {id}
              </button>
            ))}
          </div>

          {tab === "impact" && snapshot && (
            <div className="pane">
              <div className="kpis">
                <div>
                  <span>Peak depth</span>
                  <b>
                    {snapshot.max_depth_m} m
                    <em>{snapshot.max_depth_ft} ft</em>
                  </b>
                </div>
                <div>
                  <span>Blocked roads</span>
                  <b>{snapshot.blocked_roads}</b>
                </div>
                <div>
                  <span>Power cuts</span>
                  <b>{snapshot.power_cut_recommended}</b>
                </div>
              </div>
              <div className="h">Cascade</div>
              <ul className="feed">
                {(snapshot.cascade || []).slice(0, 8).map((ev, i) => (
                  <li key={i} className={ev.severity}>
                    <strong>{ev.title}</strong>
                    <p>{ev.detail}</p>
                  </li>
                ))}
                {!(snapshot.cascade || []).length && <li className="muted">No knock-on failures at this hour.</li>}
              </ul>
              <div className="h">Hotspots (now → +90 min)</div>
              <ul className="hot">
                {(snapshot.hotspots || []).slice(0, 6).map((h) => (
                  <li key={h.id}>
                    <div>
                      {h.name}
                      {h.subway ? <em> subway</em> : null}
                    </div>
                    <span>
                      {h.now_depth_ft} ft → {h.in_90min_depth_ft} ft
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {tab === "dispatch" && snapshot && (
            <div className="pane">
              <div className="h">Do not dispatch</div>
              <ul className="feed">
                {blocked.map((r) => (
                  <li key={r.id} className="high">
                    <strong>{r.name}</strong>
                    <p>
                      {r.depth_m} m ({r.depth_ft} ft) — ambulances and delivery stay off this corridor.
                    </p>
                  </li>
                ))}
                {!blocked.length && <li className="muted">All monitored corridors passable.</li>}
              </ul>
              <div className="h">Power</div>
              <ul className="feed">
                {cuts.map((a) => (
                  <li key={a.id} className="critical">
                    <strong>{a.name}</strong>
                    <p>
                      Water {a.depth_m} m vs cut-off {a.critical_depth_m} m. {a.action}
                    </p>
                  </li>
                ))}
                {!cuts.length && <li className="muted">No feeder at critical depth.</li>}
              </ul>
              <div className="h">Ambulance graph</div>
              <ul className="feed">
                {(snapshot.ambulance || []).map((m) => (
                  <li key={m.id} className={m.recommended?.ok ? "" : "critical"}>
                    <strong>{m.label}</strong>
                    <p>
                      {m.recommended?.ok
                        ? `${m.recommended.minutes} min${m.rerouted ? " · REROUTED off flooded edges" : " · clear"}`
                        : m.recommended?.reason}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {tab === "cctv" && snapshot && (
            <div className="pane">
              <p className="fine">
                City cameras as virtual flood gauges. Production writes YOLOv8 tyre/streetlight ratios into this
                same contract; the live demo fuses inundation at camera pose so the command UI is real.
              </p>
              <ul className="cams">
                {(snapshot.cctv || []).map((c) => (
                  <li key={c.id} className={c.status}>
                    <div className="cam-top">
                      <b>{c.name.replace("Traffic cam · ", "")}</b>
                      <span>{c.status}</span>
                    </div>
                    <div className="cam-bar">
                      <i style={{ width: `${Math.min(100, c.tyre_submerged_frac * 70)}%` }} />
                    </div>
                    <div className="cam-meta">
                      {c.water_depth_m} m · tyre {c.tyre_submerged_frac}× {c.self_calibrate ? "· calibrating model" : ""}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {tab === "simulate" && (
            <div className="pane">
              <p className="fine">
                Digital twin for BMC / disaster cells. Same physics as the live inundation field — change drains,
                kill a pump, add a 100 mm cell.
              </p>
              <label className="slider">
                Drain cleaning ×{drain.toFixed(2)}
                <input
                  type="range"
                  min="0.6"
                  max="1.6"
                  step="0.05"
                  value={drain}
                  onChange={(e) => setDrain(+e.target.value)}
                />
                <span>{drain < 1 ? "clogged" : drain > 1.05 ? "cleaned" : "as-is"}</span>
              </label>
              <label className="slider">
                Extra rain {extraRain} mm
                <input
                  type="range"
                  min="0"
                  max="120"
                  step="5"
                  value={extraRain}
                  onChange={(e) => setExtraRain(+e.target.value)}
                />
              </label>
              <label className="chk">
                <input type="checkbox" checked={failPump3} onChange={(e) => setFailPump3(e.target.checked)} />
                Pump 3 (Kurla nalla) failed
              </label>
              <div className="sim-actions">
                <button className="primary" disabled={simulating} onClick={runSim}>
                  {simulating ? "Running…" : "Run what-if"}
                </button>
                <button onClick={resetSim}>Reset</button>
              </div>
              {scenarioOn && snapshot && (
                <div className="scenario-box">
                  Peak {snapshot.max_depth_m} m · blocked {snapshot.blocked_roads} · {inrCr(snapshot.roi.display_inr_cr)}{" "}
                  still protected under this plan.
                </div>
              )}
            </div>
          )}

          {tab === "alerts" && snapshot && (
            <div className="pane">
              <div className="lang">
                {["en", "hi", "mr"].map((l) => (
                  <button key={l} className={lang === l ? "on" : ""} onClick={() => setLang(l)}>
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
              <p className="fine">Bhashini-ready copy. Voice/SMS hook is this JSON — not a consumer weather app.</p>
              <div className="voice">{alertText}</div>
              <ul className="feed">
                {(snapshot.alerts || []).map((a) => (
                  <li key={a.id} className={a.severity === "red" ? "critical" : "high"}>
                    <strong>{a.id}</strong>
                    <p>{a[lang] || a.en}</p>
                  </li>
                ))}
              </ul>
              <div className="h">ROI breakdown</div>
              <ul className="hot">
                {(snapshot.roi?.lines || []).map((ln, i) => (
                  <li key={i}>
                    <div>{ln.label}</div>
                    <span>₹ {(ln.inr / 1e7).toFixed(2)} Cr</span>
                  </li>
                ))}
              </ul>
              <p className="fine">{snapshot.roi?.note}</p>
            </div>
          )}
        </aside>
      </div>

      {timeline && (
        <div className="ops-bottom">
          <div className="chart-wrap">
            <div className="chart-h">PRECIPITATION · click to scrub time</div>
            <PrecipChart hours={timeline.hours} hour={hour} onScrub={(i) => { setHour(i); setScenarioOn(false); }} />
          </div>
          <div className="timebar">
            <button className="play" onClick={() => setPlaying((p) => !p)}>
              {playing ? "Pause" : "Play"}
            </button>
            <input
              type="range"
              min={0}
              max={timeline.hours.length - 1}
              value={hour}
              onChange={(e) => {
                setHour(+e.target.value);
                setScenarioOn(false);
              }}
            />
            <span>
              {hour}/{timeline.hours.length - 1} · {t?.max_rain_mm_3h} mm
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
