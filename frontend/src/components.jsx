// Small shared pieces. Kept in one file — none of them is big enough to own one.
import React, { useEffect, useState } from "react";

/** Fetch-on-mount with loading/error states, so pages don't each repeat it. */
export function useApi(fn, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    fn()
      .then((data) => alive && setState({ loading: false, data, error: null }))
      .catch((error) => alive && setState({ loading: false, data: null, error }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export const Loading = ({ what = "data" }) => (
  <div className="state">Loading {what}…</div>
);

export const Failed = ({ error, hint }) => (
  <div className="state err">
    Couldn’t load: {String(error.message || error)}
    {hint && <div style={{ color: "var(--ink-3)", marginTop: 6 }}>{hint}</div>}
  </div>
);

export const Kpi = ({ label, value, detail }) => (
  <div className="kpi">
    <span className="eyebrow">{label}</span>
    <div className="v num">{value}</div>
    <div className="d">{detail}</div>
  </div>
);

export const Card = ({ title, eyebrow, note, children, action }) => (
  <section className="card">
    <div className="rowsplit">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        {title && <h3>{title}</h3>}
      </div>
      {action}
    </div>
    {note && <p className="note">{note}</p>}
    {children}
  </section>
);

export const Tier = ({ tier }) => <span className={`tier t-${tier}`}>{tier}</span>;

/** Recharts tooltip that inherits the panel's theme instead of its own white box. */
export const tooltipStyle = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--line-strong)",
    borderRadius: 7,
    fontSize: 12,
    fontFamily: "IBM Plex Sans, sans-serif",
    boxShadow: "var(--shadow)",
    color: "var(--ink)",
  },
  labelStyle: { color: "var(--ink-3)", fontSize: 11, marginBottom: 3 },
  itemStyle: { color: "var(--ink)" },
};

export const axisProps = {
  tick: { fill: "var(--ink-3)", fontSize: 10, fontFamily: "IBM Plex Mono, monospace" },
  stroke: "var(--line)",
  tickLine: false,
  axisLine: { stroke: "var(--line)" },
};


/** Keeps one failing panel from taking the whole app down with it. */
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    console.error("panel crashed:", error, info);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="state err">
        This view hit an error: {String(this.state.error.message || this.state.error)}
        <div style={{ marginTop: 10 }}>
          <button className="btn" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      </div>
    );
  }
}
