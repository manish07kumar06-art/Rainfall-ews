import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";

// Change this if your backend runs somewhere other than localhost:8000
const API = "http://localhost:8000";

const RISK_COLORS = ["#2ecc71", "#f1c40f", "#e67e22", "#c0392b"];
const RISK_OPACITY = [0.06, 0.35, 0.6, 0.85];
const FLOOD_COLORS = { low: "#9ecae1", medium: "#3182bd", high: "#08306b" };

export default function App() {
  const mapDivRef = useRef(null);   // the <div> the map draws into
  const mapRef = useRef(null);      // the Leaflet map instance itself
  const riskLayerRef = useRef(null);
  const floodLayerRef = useRef(null);
  const timerRef = useRef(null);

  const [timeline, setTimeline] = useState(null);
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState(null);

  // Create the map exactly once
  useEffect(() => {
    if (mapRef.current) return; // guard against React StrictMode double-invoking this
    mapRef.current = L.map(mapDivRef.current).setView([19.1, 72.9], 10);
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
      { attribution: "Tiles &copy; Esri", maxZoom: 19 }
    ).addTo(mapRef.current);
  }, []);

  // Load the timeline once on startup
  useEffect(() => {
    fetch(`${API}/timeline`)
      .then((r) => r.json())
      .then(setTimeline)
      .catch((e) => setError(`Could not reach the backend at ${API}. Is uvicorn running? (${e.message})`));
  }, []);

  // Redraw risk + flood layers whenever the hour changes
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
          color: "#555",
          weight: 0.5,
          fillColor: RISK_COLORS[f.properties.risk_level],
          fillOpacity: RISK_OPACITY[f.properties.risk_level],
        }),
      })
        .bindTooltip((l) => `Rain (3h): ${l.feature.properties.rain_mm_3h} mm`)
        .addTo(mapRef.current);

      floodLayerRef.current = L.geoJSON(flood, {
        style: (f) => ({
          color: FLOOD_COLORS[f.properties.depth_class],
          weight: 3,
          fillOpacity: 0,
          dashArray: f.properties.depth_class === "high" ? null : "4",
        }),
      }).addTo(mapRef.current);
    });
  }, [hour, timeline]);

  // Play/pause animation
  useEffect(() => {
    if (playing && timeline) {
      timerRef.current = setInterval(() => {
        setHour((h) => (h + 1) % timeline.hours.length);
      }, 700);
    }
    return () => clearInterval(timerRef.current);
  }, [playing, timeline]);

  const t = timeline ? timeline.hours[hour] : null;

  return (
    <div className="app">
      {error && <div className="loading">{error}</div>}
      <div ref={mapDivRef} className="map" />
      <div className="bar">
        {!timeline ? (
          <span className="label">Loading timeline...</span>
        ) : (
          <>
            <button onClick={() => setPlaying((p) => !p)}>{playing ? "Pause" : "Play"}</button>
            <input
              type="range"
              min={0}
              max={timeline.hours.length - 1}
              value={hour}
              onChange={(e) => setHour(+e.target.value)}
            />
            <span className="label">
              {t.time.replace("T", " ")} | max rain {t.max_rain_mm_3h} mm/3h | flooded cells {t.flooded_cells}
            </span>
            <div className="alert">{t.alert_text}</div>
          </>
        )}
      </div>
    </div>
  );
}
