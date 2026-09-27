const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function getJSON(path, options) {
  const r = await fetch(`${API_BASE}${path}`, options);
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`HTTP ${r.status} ${path} — ${detail.slice(0, 180)}`);
  }
  return r.json();
}

export { API_BASE };

export const fetchTimeline = (mode) => getJSON(`/${mode}/timeline`);
export const fetchRisk = (mode, hour) => getJSON(`/${mode}/risk/${hour}`);
export const fetchSnapshot = (mode, hour) =>
  getJSON(`/impact/snapshot?mode=${mode}&hour=${hour}`);
export const fetchMetrics = () => getJSON(`/metrics`);
export const simulateImpact = (body) =>
  getJSON(`/impact/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
