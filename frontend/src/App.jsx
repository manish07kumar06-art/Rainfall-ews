import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";

const API = "http://localhost:8000";

const RISK_COLORS = ["#3dd68c", "#f5c542", "#f08a3a", "#e24b4b"];
const RISK_OPACITY = [0.08, 0.38, 0.62, 0.86];
const RISK_LABELS = ["Low", "Moderate", "High", "Severe"];
const FLOOD_COLORS = { low: "#8ecae6", medium: "#219ebc", high: "#023047" };

function formatStamp(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.replace("T", " ");
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function PrecipChart({ hours, hour, onScrub }) {
  const W = 960;
  const H = 88;
  const PAD_X = 10;
  const PAD_Y = 10;
  const max = Math.max(1, ...hours.map((h) => h.max_rain_mm_3h));
  const step = hours.length > 1 ? (W - PAD_X * 2) / (hours.length - 1) : 0;

  const coords = hours.map((h, i) => {
    const x = PAD_X + i * step;
    const y = H - PAD_Y - (h.max_rain_mm_3h / max) * (H - PAD_Y * 2);
    return { x, y };
  });

  const line = coords.map((p) => `${p.x},${p.y}`).join(" ");
  const area = `${PAD_X},${H - PAD_Y} ${line} ${W - PAD_X},${H - PAD_Y}`;
  const cur = coords[hour] || coords[0];

  const pick = (evt) => {
    const rect = evt.currentTarget.getBoundingClientRect();
    const relX = ((evt.clientX - rect.left) / rect.width) * W;
    const idx = Math.round((relX - PAD_X) / step);
    onScrub(Math.min(hours.length - 1, Math.max(0, idx)));
  };

  return (
    <svg
      className="precip-svg"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Precipitation timeline"
      onClick={pick}
      onMouseMove={(e) => e.buttons === 1 && pick(e)}
    >
      <defs>
        <linearGradient id="rainFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#4cc9f0" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#4cc9f0" stopOpacity="0.02" />
        </linearGradient>
        <linearGradient id="rainStroke" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#7bf0d0" />
          <stop offset="100%" stopColor="#4cc9f0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((t) => (
        <line
          key={t}
          x1={PAD_X}
          x2={W - PAD_X}
          y1={PAD_Y + t * (H - PAD_Y * 2)}
          y2={PAD_Y + t * (H - PAD_Y * 2)}
          className="chart-grid"
        />
      ))}
      <polygon points={area} fill="url(#rainFill)" />
      <polyline points={line} fill="none" stroke="url(#rainStroke)" strokeWidth="2.4" />
      <line x1={cur.x} y1={6} x2={cur.x} y2={H - 6} className="chart-playhead" />
      <circle cx={cur.x} cy={cur.y} r="4.5" className="chart-dot" />
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
  const [showRisk, setShowRisk] = useState(true);
  const [showFlood, setShowFlood] = useState(true);
  const [basemap, setBasemap] = useState("satellite");

  const TILE_URLS = {
    satellite:
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    street:
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
  };

  useEffect(() => {
    if (mapRef.current) return;
    mapRef.current = L.map(mapDivRef.current, { zoomControl: false }).setView([19.1, 72.9], 10);
    tileLayerRef.current = L.tileLayer(TILE_URLS.satellite, {
      attribution: "Tiles © Esri",
      maxZoom: 19,
    }).addTo(mapRef.current);
    L.control.zoom({ position: "topright" }).addTo(mapRef.current);
  }, []);

  useEffect(() => {
    if (!mapRef.current || !tileLayerRef.current) return;
    tileLayerRef.current.setUrl(TILE_URLS[basemap]);
  }, [basemap]);

  useEffect(() => {
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 5000);
    fetch(`${API}/timeline`, { signal: ctrl.signal })
      .then((r) => r.json())
      .then((data) => {
        setError(null);
        setTimeline(data);
      })
      .catch((e) => {
        if (e.name === "AbortError") return;
        setError(`Could not reach the backend at ${API}. Is uvicorn running? (${e.message})`);
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      clearTimeout(timeout);
      ctrl.abort();
    };
  }, []);

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
  const warningLabel = t ? RISK_LABELS[t.max_risk] : "—";
  const lastHour = timeline ? timeline.hours.length - 1 : 0;

  return (
    <div className="dash">
      <header className="dash-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="28" height="28">
              <path
                d="M16 3c5 7 11 12 11 18a11 11 0 1 1-22 0c0-6 6-11 11-18z"
                fill="url(#drop)"
              />
              <defs>
                <linearGradient id="drop" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#7bf0d0" />
                  <stop offset="100%" stopColor="#3aa0ff" />
                </linearGradient>
              </defs>
            </svg>
          </span>
          <div>
            <div className="brand-name">RainGuard</div>
            <div className="brand-tag">Heavy rainfall &amp; flood early warning</div>
          </div>
        </div>

        <div className="header-mid">
          {timeline ? (
            <>
              <span className="region-chip">{timeline.region}</span>
              <span className="event-label">{timeline.event}</span>
            </>
          ) : (
            <span className="event-label">Connecting to forecast service…</span>
          )}
        </div>

        <div className={`status-pill ${error ? "status-bad" : "status-ok"}`}>
          <span className="dot" />
          {error ? "Backend offline" : "Live replay"}
        </div>
      </header>

      <div className="dash-row">
        <aside className="layers-panel">
          <section className="side-block">
            <div className="layers-title">Data layers</div>
            <label className="switch-row">
              <span>
                <strong>Rain risk grid</strong>
                <small>3-hour accumulation cells</small>
              </span>
              <input
                type="checkbox"
                checked={showRisk}
                onChange={(e) => setShowRisk(e.target.checked)}
              />
              <span className="switch" />
            </label>
            <label className="switch-row">
              <span>
                <strong>Flood zones</strong>
                <small>Predicted inundation outlines</small>
              </span>
              <input
                type="checkbox"
                checked={showFlood}
                onChange={(e) => setShowFlood(e.target.checked)}
              />
              <span className="switch" />
            </label>
          </section>

          <section className="side-block">
            <div className="layers-title">Basemap</div>
            <div className="segment">
              <button
                type="button"
                className={basemap === "satellite" ? "on" : ""}
                onClick={() => setBasemap("satellite")}
              >
                Satellite
              </button>
              <button
                type="button"
                className={basemap === "street" ? "on" : ""}
                onClick={() => setBasemap("street")}
              >
                Streets
              </button>
            </div>
          </section>

          <section className="side-block legend-block">
            <div className="layers-title">Legend</div>
            <div className="legend-kicker">Rain risk</div>
            {RISK_LABELS.map((label, i) => (
              <div className="legend-row" key={label}>
                <span className="swatch" style={{ background: RISK_COLORS[i] }} />
                {label}
              </div>
            ))}
            <div className="legend-kicker" style={{ marginTop: 12 }}>
              Flood depth
            </div>
            {Object.entries(FLOOD_COLORS).map(([cls, color]) => (
              <div className="legend-row" key={cls}>
                <span className="swatch outline" style={{ borderColor: color }} />
                {cls}
              </div>
            ))}
          </section>
        </aside>

        <div className="dash-body">
          <div ref={mapDivRef} className="map" />

          {error && <div className="map-error">{error}</div>}

          {timeline && t && (
            <div className="kpi-strip">
              <div className="kpi">
                <div className="kpi-label">Valid time</div>
                <div className="kpi-value kpi-time">{formatStamp(t.time)}</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Max rain (3h)</div>
                <div className="kpi-value">
                  {t.max_rain_mm_3h}
                  <span className="unit">mm</span>
                </div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Warning</div>
                <div className={`kpi-value warn-${t.max_risk}`}>{warningLabel}</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Flooded cells</div>
                <div className="kpi-value">{t.flooded_cells}</div>
              </div>
            </div>
          )}

          {t && (
            <div className={`alert-banner warn-${t.max_risk}`}>
              <span className="alert-kicker">Advisory</span>
              <p>{t.alert_text}</p>
            </div>
          )}
        </div>
      </div>

      <footer className="dock">
        {timeline && t ? (
          <>
            <div className="dock-head">
              <div>
                <div className="chart-bar-title">Precipitation timeline</div>
                <div className="chart-bar-hint">Click or drag to scrub hours</div>
              </div>
              <div className="dock-meta">
                Hour {hour} / {lastHour}
                <span>·</span>
                {t.max_rain_mm_3h} mm
              </div>
            </div>
            <PrecipChart hours={timeline.hours} hour={hour} onScrub={setHour} />
            <div className="timebar">
              <button
                className="play-btn"
                type="button"
                onClick={() => setPlaying((p) => !p)}
                aria-label={playing ? "Pause replay" : "Play replay"}
              >
                {playing ? (
                  <svg viewBox="0 0 24 24" width="16" height="16">
                    <rect x="6" y="5" width="4" height="14" rx="1" />
                    <rect x="14" y="5" width="4" height="14" rx="1" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" width="16" height="16">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                )}
                {playing ? "Pause" : "Play"}
              </button>
              <input
                type="range"
                min={0}
                max={lastHour}
                value={hour}
                onChange={(e) => setHour(+e.target.value)}
                aria-label="Forecast hour"
              />
              <span className="label">{formatStamp(t.time)}</span>
            </div>
          </>
        ) : (
          <div className="dock-loading">Loading timeline…</div>
        )}
      </footer>
    </div>
  );
}
