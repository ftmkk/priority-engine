// One place that knows how to talk to the backend.
const get = async (path) => {
  const r = await fetch(`/api${path}`);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
};
const post = async (path) => {
  const r = await fetch(`/api${path}`, { method: "POST" });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
};

export const api = {
  health: () => get("/health"),
  summary: () => get("/summary"),
  queue: (p = {}) =>
    get("/queue?" + new URLSearchParams(Object.entries(p).filter(([, v]) => v))),
  model: () => get("/model"),
  versions: () => get("/model/versions"),
  urgency: () => get("/analytics/urgency"),
  engagement: () => get("/analytics/engagement"),
  conversionBy: (d) => get(`/analytics/conversion-by/${d}`),
  weekly: () => get("/analytics/weekly"),
  targetBalance: () => get("/analytics/target-balance"),
  calibration: () => get("/analytics/calibration"),
  scoreDistribution: () => get("/analytics/score-distribution"),
  decayImpact: () => get("/analytics/decay-impact"),
  queueComposition: () => get("/analytics/queue-composition"),
  importance: () => get("/interpret/importance"),
  sweepable: () => get("/interpret/features"),
  explain: (leadId) => get(`/interpret/explain/${leadId}`),
  sweep: (leadId, feature) =>
    get(`/interpret/sweep/${leadId}?feature=${encodeURIComponent(feature)}`),
  jobs: () => get("/jobs"),
  monitoring: () => get("/monitoring"),
  runTrain: () => post("/jobs/train"),
  runPredict: () => post("/jobs/predict"),
};

export const pct = (x, d = 1) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
export const num = (x) =>
  x == null ? "—" : Number(x).toLocaleString("en-US", { maximumFractionDigits: 0 });
export const toman = (x) => {
  if (x == null) return "—";
  const n = Number(x);
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  return num(n);
};
