import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";

// Change this if your backend runs somewhere other than localhost:8000
const API_BASE = "http://localhost:8000";

const RISK_COLORS = ["#2ecc71", "#f1c40f", "#e67e22", "#c0392b"];
const RISK_OPACITY = [0.06, 0.35, 0.6, 0.85];
const RISK_LABELS = ["Low", "Moderate", "High", "Severe"];
const FLOOD_COLORS = { low: "#9ecae1", medium: "#3182bd", high: "#08306b" };

// Planned features - honestly labeled as NOT YET LIVE. Shown to communicate vision
// without claiming any of this works in the current prototype.
const ROADMAP = [
  {
    title: "Doppler radar + satellite fusion",
    desc: "Ingest raw IMD Doppler radar and INSAT-3D imagery directly, instead of reanalysis/IMERG data, for faster and more precise storm-cell tracking.",
  },
  {
    title: "CCTV as virtual sensors",
    desc: "A computer-vision model reading existing traffic cameras to estimate real-time water depth from submerged tyres/streetlights, self-calibrating the flood model.",
  },
  {
    title: "Cascading failure engine",
    desc: "A graph model over power substations, hospitals and roads to predict knock-on failures (e.g. a flooded substation cutting power to a hospital).",
  },
  {
    title: '"What-if" scenario simulator',
    desc: "Let city planners test interventions - drain cleaning, pump failures - and see the predicted change in flooding before it happens.",
  },
  {
    title: "Bhashini voice alerts",
    desc: "Automatic local-language voice/SMS warnings for areas with low smartphone or English literacy, via the Government of India's Bhashini API.",
  },
  {
    title: "Economic impact tracking",
    desc: "A validated estimate of losses prevented (rerouted traffic, protected assets), shown to demonstrate ROI to city and disaster-management stakeholders.",
  },
];


function PrecipChart({ hours, hour, onScrub }) {
  const W = 900, H = 90, PAD = 6;
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
    <svg
      className="precip-svg"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      onClick={scrub}
    >
      <polyline points={points} fill="none" stroke="#3aa0ff" strokeWidth="2" />
      <polyline
        points={`${PAD},${H - PAD} ${points} ${W - PAD},${H - PAD}`}
        fill="#3aa0ff22"
        stroke="none"
      />
      <line x1={curX} y1={0} x2={curX} y2={H} stroke="#e7edf3" strokeWidth="1.5" strokeDasharray="3,3" />
    </svg>
  );
}

export default function App() {
  const mapDivRef = useRef(null);
  const mapRef = useRef(null);
  const riskLayerRef = useRef(null);
  const floodLayerRef = useRef(null);
  const tileLayerRef = useRef(null);
  const timerRef = useRef(null);

  const [timeline, setTimeline] = useState(null);
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState(null);

  // Real, working layer toggles - only for data we actually have
  const [showRisk, setShowRisk] = useState(true);
  const [showFlood, setShowFlood] = useState(true);
  const [basemap, setBasemap] = useState("satellite"); // "satellite" | "street"
  const [showRoadmap, setShowRoadmap] = useState(false);
  const [mode, setMode] = useState("live"); // "live" | "replay"

  const API = `${API_BASE}/${mode}`;

  const TILE_URLS = {
    satellite: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    street: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
  };

  // Create the map once
  useEffect(() => {
    if (mapRef.current) return;
    mapRef.current = L.map(mapDivRef.current, { zoomControl: false }).setView([19.1, 72.9], 10);
    tileLayerRef.current = L.tileLayer(TILE_URLS.satellite, {
      attribution: "Tiles &copy; Esri",
      maxZoom: 19,
    }).addTo(mapRef.current);
    L.control.zoom({ position: "topright" }).addTo(mapRef.current);
  }, []);

  // Swap basemap when the toggle changes
  useEffect(() => {
    if (!mapRef.current || !tileLayerRef.current) return;
    tileLayerRef.current.setUrl(TILE_URLS[basemap]);
  }, [basemap]);

  useEffect(() => {
    setError(null);
    setTimeline(null);
    setHour(0);
    fetch(`${API}/timeline`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} - have you run the ${mode} data step yet?`);
        return r.json();
      })
      .then(setTimeline)
      .catch((e) => setError(`Could not load ${mode} data from ${API}. ${e.message}`));
  }, [mode]);

  useEffect(() => {
    if (!timeline || !mapRef.current) return;
    Promise.all([
      fetch(`${API}/risk/${hour}`).then((r) => r.json()),
      fetch(`${API}/flood/${hour}`).then((r) => r.json()),
    ]).then(([risk, flood]) => {
      if (riskLayerRef.current) mapRef.current.removeLayer(riskLayerRef.current);
      if (floodLayerRef.current) mapRef.current.removeLayer(floodLayerRef.current);

      riskLayerRef.current = L.geoJSON(risk, {
        style: (f) => ({
          color: "#0009",
          weight: 0.5,
          fillColor: RISK_COLORS[f.properties.risk_level],
          fillOpacity: RISK_OPACITY[f.properties.risk_level],
        }),
      }).bindTooltip((l) => `Rain (3h): ${l.feature.properties.rain_mm_3h} mm`);
      if (showRisk) riskLayerRef.current.addTo(mapRef.current);

      floodLayerRef.current = L.geoJSON(flood, {
        style: (f) => ({
          color: FLOOD_COLORS[f.properties.depth_class],
          weight: 3,
          fillOpacity: 0,
          dashArray: f.properties.depth_class === "high" ? null : "4",
        }),
      });
      if (showFlood) floodLayerRef.current.addTo(mapRef.current);
    });
  }, [hour, timeline]);

  // Show/hide layers instantly when a toggle changes, without refetching
  useEffect(() => {
    if (!mapRef.current || !riskLayerRef.current) return;
    if (showRisk) riskLayerRef.current.addTo(mapRef.current);
    else mapRef.current.removeLayer(riskLayerRef.current);
  }, [showRisk]);

  useEffect(() => {
    if (!mapRef.current || !floodLayerRef.current) return;
    if (showFlood) floodLayerRef.current.addTo(mapRef.current);
    else mapRef.current.removeLayer(floodLayerRef.current);
  }, [showFlood]);

  useEffect(() => {
    if (playing && timeline) {
      timerRef.current = setInterval(() => {
        setHour((h) => (h + 1) % timeline.hours.length);
      }, 700);
    }
    return () => clearInterval(timerRef.current);
  }, [playing, timeline]);

  const t = timeline ? timeline.hours[hour] : null;
  const warningLabel = t ? RISK_LABELS[t.max_risk] : "--";
  const warningClass = t ? `warn-${t.max_risk}` : "";

  return (
    <div className="dash">
      {/* Header */}
      <header className="dash-header">
        <div className="brand">
          <span className="brand-name">RainGuard</span>
          <span className="brand-tag">AI HEAVY RAINFALL &amp; FLOOD EARLY WARNING</span>
        </div>
        <div className="header-mid">
          {timeline ? (
            <span>{timeline.region} &middot; {timeline.event}</span>
          ) : (
            <span>Connecting...</span>
          )}
        </div>
        <div className="mode-toggle">
          <button className={mode === "live" ? "mode-btn active" : "mode-btn"} onClick={() => setMode("live")}>
            Live Forecast
          </button>
          <button className={mode === "replay" ? "mode-btn active" : "mode-btn"} onClick={() => setMode("replay")}>
            2021 Event Replay
          </button>
        </div>
        <div className={`status-pill ${error ? "status-bad" : "status-ok"}`}>
          <span className="dot" />
          {error ? "NO DATA" : mode === "live" ? "LIVE FORECAST" : "HISTORICAL REPLAY"}
        </div>
        <button className="roadmap-btn" onClick={() => setShowRoadmap(true)}>
          Roadmap
        </button>
      </header>

      {showRoadmap && (
        <div className="roadmap-overlay" onClick={() => setShowRoadmap(false)}>
          <div className="roadmap-modal" onClick={(e) => e.stopPropagation()}>
            <div className="roadmap-modal-header">
              <div>
                <div className="roadmap-modal-title">Planned - Phase 2</div>
                <div className="roadmap-modal-sub">
                  Not live in this prototype. Shown to communicate the full vision honestly.
                </div>
              </div>
              <button className="roadmap-close" onClick={() => setShowRoadmap(false)}>&times;</button>
            </div>
            <div className="roadmap-grid">
              {ROADMAP.map((item) => (
                <div className="roadmap-card" key={item.title}>
                  <div className="roadmap-card-badge">PLANNED - NOT YET LIVE</div>
                  <div className="roadmap-card-title">{item.title}</div>
                  <div className="roadmap-card-desc">{item.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Layers sidebar + map + floating panels */}
      <div className="dash-row">
        <aside className="layers-panel">
          <div className="layers-title">DATA LAYERS</div>
          <label className="layer-toggle">
            <input type="checkbox" checked={showRisk} onChange={(e) => setShowRisk(e.target.checked)} />
            Rain risk grid
          </label>
          <label className="layer-toggle">
            <input type="checkbox" checked={showFlood} onChange={(e) => setShowFlood(e.target.checked)} />
            Predicted flood zones
          </label>

          <div className="layers-title" style={{ marginTop: 14 }}>BASEMAP</div>
          <label className="layer-toggle">
            <input
              type="radio"
              name="basemap"
              checked={basemap === "satellite"}
              onChange={() => setBasemap("satellite")}
            />
            Satellite imagery
          </label>
          <label className="layer-toggle">
            <input
              type="radio"
              name="basemap"
              checked={basemap === "street"}
              onChange={() => setBasemap("street")}
            />
            Street map
          </label>
        </aside>

        <div className="dash-body">
          <div ref={mapDivRef} className="map" />

        {error && <div className="map-error">{error}</div>}

        {timeline && (
          <div className="stat-card">
            <div className="stat-card-title">{timeline.region.toUpperCase()}</div>
            <div className="stat-card-sub">{t.time.replace("T", " ")}</div>

            <div className="stat-row">
              <div className="stat-box">
                <div className="stat-label">MAX RAIN (3H)</div>
                <div className="stat-value">{t.max_rain_mm_3h} mm</div>
              </div>
              <div className="stat-box">
                <div className="stat-label">WARNING STATUS</div>
                <div className={`stat-value ${warningClass}`}>{warningLabel}</div>
              </div>
            </div>

            <div className="stat-row single">
              <div className="stat-box">
                <div className="stat-label">PREDICTED FLOODED CELLS</div>
                <div className="stat-value">{t.flooded_cells}</div>
              </div>
            </div>

            <div className="stat-alert">{t.alert_text}</div>
          </div>
        )}

        {/* Legend */}
        <div className="legend">
          <div className="legend-title">Rain risk</div>
          {RISK_LABELS.map((label, i) => (
            <div className="legend-row" key={label}>
              <span className="swatch" style={{ background: RISK_COLORS[i] }} />
              {label}
            </div>
          ))}
          <div className="legend-title" style={{ marginTop: 8 }}>Flood depth</div>
          {Object.entries(FLOOD_COLORS).map(([cls, color]) => (
            <div className="legend-row" key={cls}>
              <span className="swatch outline" style={{ borderColor: color }} />
              {cls}
            </div>
          ))}
        </div>
        </div>
      </div>

      {/* Precipitation timeline chart */}
      {timeline && (
        <div className="chart-bar">
          <div className="chart-bar-title">
            PRECIPITATION TIMELINE &middot; drag or click to scrub
          </div>
          <PrecipChart hours={timeline.hours} hour={hour} onScrub={setHour} />
        </div>
      )}

      {/* Timeline bar */}
      <div className="timebar">
        {!timeline ? (
          <span className="label">Loading timeline...</span>
        ) : (
          <>
            <button className="play-btn" onClick={() => setPlaying((p) => !p)}>
              {playing ? "Pause" : "Play"}
            </button>
            <input
              type="range"
              min={0}
              max={timeline.hours.length - 1}
              value={hour}
              onChange={(e) => setHour(+e.target.value)}
            />
            <span className="label">Hour {hour} / {timeline.hours.length - 1}</span>
          </>
        )}
      </div>
    </div>
  );
}
