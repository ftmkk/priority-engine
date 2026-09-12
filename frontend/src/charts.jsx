/* Reusable, self-fetching charts.
   Each one owns its own data call, so it can be dropped into a dashboard page
   or into the story deck with no props and no duplicated definition. */
import React from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, ErrorBar,
  Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, num, pct, toman } from "./api.js";
import { Failed, Loading, axisProps, tooltipStyle, useApi } from "./components.jsx";

const p2 = (v) => +(v * 100).toFixed(2);
const wrap = (s, h, body) =>
  s.loading ? <Loading /> : s.error ? <Failed error={s.error} /> : body();

/* --- funnel / target ----------------------------------------------------- */
export function TargetBalanceChart({ height = 210 }) {
  const s = useApi(api.targetBalance, []);
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={s.data.map((r) => ({
        label: r.outcome === 1 ? "purchased" : "did not purchase", leads: r.leads }))}
        margin={{ top: 8, right: 14, left: -4, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="label" {...axisProps} />
        <YAxis {...axisProps} />
        <Tooltip {...tooltipStyle} formatter={(v) => num(v)} />
        <Bar dataKey="leads" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          <Cell fill="var(--ink-3)" /><Cell fill="var(--blue)" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  ));
}

/* --- behaviour ----------------------------------------------------------- */
export function EngagementChart({ height = 230 }) {
  const s = useApi(api.engagement, []);
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="bucket" type="number" allowDecimals={false} domain={[0, 6]} {...axisProps} />
        <YAxis {...axisProps} unit="%" />
        <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} />
        <Legend wrapperStyle={{ fontSize: 12, color: "var(--ink-2)" }} />
        <Line name="Offer views 7d" dataKey="conv" strokeWidth={2} isAnimationActive={false}
              data={s.data.offer_views_last_7d.map((r) => ({ ...r, conv: p2(r.conversion) }))}
              stroke="var(--blue)" dot={{ r: 2.6 }} />
        <Line name="Sessions 7d" dataKey="conv" strokeWidth={2} isAnimationActive={false}
              data={s.data.sessions_last_7d.map((r) => ({ ...r, conv: p2(r.conversion) }))}
              stroke="var(--orange)" dot={{ r: 2.6 }} />
      </LineChart>
    </ResponsiveContainer>
  ));
}

/* --- urgency ------------------------------------------------------------- */
export function UrgencyChart({ which = "abandonment", base, height = 215 }) {
  const s = useApi(api.urgency, []);
  const isAband = which === "abandonment";
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={s.data[isAband ? "abandonment" : "expiry"]
        .map((r) => ({ ...r, conv: p2(r.conversion) }))}
        margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="bucket" {...axisProps} unit={isAband ? "m" : ""} />
        <YAxis {...axisProps} unit="%" />
        <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} />
        {base != null && <ReferenceLine y={p2(base)} stroke="var(--orange)" strokeDasharray="4 3" />}
        <Bar dataKey="conv" fill={isAband ? "var(--blue)" : "var(--deep)"}
             radius={[3, 3, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  ));
}

/* --- context ------------------------------------------------------------- */
export function ConversionByChart({ dimension = "channel", base, height = 220 }) {
  const s = useApi(() => api.conversionBy(dimension), [dimension]);
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart layout="vertical" data={s.data.map((r) => ({ ...r, conv: p2(r.conversion) }))}
        margin={{ top: 8, right: 36, left: 20, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" horizontal={false} />
        <XAxis type="number" {...axisProps} unit="%" />
        <YAxis type="category" dataKey="label" width={80} {...axisProps} />
        <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} />
        {base != null && <ReferenceLine x={p2(base)} stroke="var(--orange)" strokeDasharray="4 3" />}
        <Bar dataKey="conv" fill="var(--deep)" radius={[0, 3, 3, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  ));
}

/* --- stability ----------------------------------------------------------- */
export function WeeklyTrendChart({ base, height = 230 }) {
  const s = useApi(api.weekly, []);
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={s.data.map((w) => ({ ...w, conv: p2(w.conversion) }))}
        margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="week" {...axisProps} tickFormatter={(d) => d.slice(5)} minTickGap={26} />
        <YAxis {...axisProps} unit="%" />
        <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} />
        {base != null && <ReferenceLine y={p2(base)} stroke="var(--orange)" strokeDasharray="4 3" />}
        <Line type="monotone" dataKey="conv" stroke="var(--blue)" strokeWidth={2}
              dot={{ r: 2.4 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  ));
}

/* --- model value --------------------------------------------------------- */
export function GainsChart({ height = 250 }) {
  const s = useApi(api.model, []);
  return wrap(s, height, () => {
    const g = (s.data.metrics.gains || []).map((r) => ({
      depth: +(r.depth * 100).toFixed(1),
      model: +(r.captured * 100).toFixed(1),
      random: +(r.depth * 100).toFixed(1),
    }));
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={g} margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
          <CartesianGrid stroke="var(--line)" />
          <XAxis dataKey="depth" {...axisProps} unit="%" />
          <YAxis {...axisProps} unit="%" />
          <Tooltip {...tooltipStyle} formatter={(v, n) => [`${v}%`, n === "model" ? "Model" : "Random"]}
                   labelFormatter={(l) => `top ${l}% of the queue`} />
          <Legend wrapperStyle={{ fontSize: 12, color: "var(--ink-2)" }} />
          <Line name="Model" dataKey="model" stroke="var(--blue)" strokeWidth={2}
                dot={false} isAnimationActive={false} />
          <Line name="Random" dataKey="random" stroke="var(--ink-3)" strokeWidth={2}
                strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    );
  });
}

export function AtKTable() {
  const s = useApi(api.model, []);
  return wrap(s, 0, () => (
    <div className="tablewrap">
      <table>
        <thead><tr><th>Calls made</th><th>Precision</th><th>Converters caught</th><th>Lift</th></tr></thead>
        <tbody>
          {s.data.metrics.at_k.map((k) => (
            <tr key={k.k}>
              <td>{num(k.k)}</td><td>{pct(k.precision, 1)}</td>
              <td>{pct(k.recall, 1)}</td>
              <td style={{ color: "var(--blue)", fontWeight: 600 }}>{k.lift.toFixed(2)}×</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ));
}

export function CandidateTable() {
  const s = useApi(api.model, []);
  return wrap(s, 0, () => (
    <div className="tablewrap">
      <table>
        <thead><tr><th>Candidate</th><th>Window</th><th>PR-AUC</th><th>ROC-AUC</th></tr></thead>
        <tbody>
          {/* The window column is the point: algorithms are compared on validation
              only. Holdout rows are baselines, shown so the quoted gap is like-for-like. */}
          {[...s.data.candidate_results]
            .sort((a, b) => (a.scored_on || "validation").localeCompare(b.scored_on || "validation")
              || b.pr_auc - a.pr_auc)
            .map((c) => (
            <tr key={`${c.scored_on || "validation"}:${c.algorithm}`}>
              <td>{c.algorithm}{c.algorithm === s.data.algorithm &&
                (c.scored_on || "validation") === "validation" &&
                <span className="pill ok" style={{ marginLeft: 8 }}>chosen</span>}</td>
              <td style={{ color: "var(--ink-3)" }}>{c.scored_on || "validation"}</td>
              <td>{c.pr_auc.toFixed(4)}</td><td>{c.roc_auc.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ));
}

/* --- honesty checks ------------------------------------------------------ */
export function CalibrationChart({ height = 250 }) {
  const s = useApi(api.calibration, []);
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={s.data.map((r) => ({
        predicted: p2(r.predicted), observed: p2(r.observed), ideal: p2(r.predicted) }))}
        margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" />
        <XAxis dataKey="predicted" type="number" {...axisProps} unit="%" domain={["dataMin", "dataMax"]} />
        <YAxis {...axisProps} unit="%" />
        <Tooltip {...tooltipStyle} formatter={(v, n) => [`${v}%`, n === "observed" ? "Observed" : "Perfect"]}
                 labelFormatter={(l) => `predicted ${l}%`} />
        <Legend wrapperStyle={{ fontSize: 12, color: "var(--ink-2)" }} />
        <Line name="Perfect" dataKey="ideal" stroke="var(--ink-3)" strokeWidth={2}
              strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        <Line name="Observed" dataKey="observed" stroke="var(--blue)" strokeWidth={2}
              dot={{ r: 2.6 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  ));
}

export function ScoreDistributionChart({ height = 250 }) {
  const s = useApi(api.scoreDistribution, []);
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={s.data} margin={{ top: 8, right: 14, left: -8, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="score_pct" {...axisProps} unit="%" />
        <YAxis {...axisProps} />
        <Tooltip {...tooltipStyle} formatter={(v) => num(v)}
                 labelFormatter={(l) => `score ${l}–${l + 2}%`} />
        <Bar dataKey="leads" fill="var(--blue)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  ));
}

export function QueueTierChart({ height = 220 }) {
  const s = useApi(api.summary, []);
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={s.data.queue_by_tier} margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="priority_tier" {...axisProps} />
        <YAxis {...axisProps} />
        <Tooltip {...tooltipStyle} formatter={(v) => num(v)} />
        <Bar dataKey="leads" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {s.data.queue_by_tier.map((t) => (
            <Cell key={t.priority_tier}
                  fill={t.priority_tier === "P1" ? "var(--blue)" : "var(--deep)"}
                  fillOpacity={t.priority_tier === "P1" ? 1 : 0.55} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  ));
}

export function DecayImpactChart({ height = 240 }) {
  const s = useApi(api.decayImpact, []);
  return wrap(s, height, () => (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={s.data.map((r) => ({
        age: r.age_hours, raw: p2(r.raw), decayed: p2(r.decayed) }))}
        margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="age" {...axisProps} unit="h" />
        <YAxis {...axisProps} unit="%" />
        <Tooltip {...tooltipStyle}
                 formatter={(v, n) => [`${v}%`, n === "raw" ? "Raw score" : "After decay"]} />
        <Legend wrapperStyle={{ fontSize: 12, color: "var(--ink-2)" }} />
        <ReferenceLine x={4} stroke="var(--blue)" strokeDasharray="4 3" />
        <Line name="Raw score" dataKey="raw" stroke="var(--ink-3)" strokeWidth={2}
              dot={{ r: 2.4 }} isAnimationActive={false} />
        <Line name="After decay" dataKey="decayed" stroke="var(--orange)" strokeWidth={2}
              dot={{ r: 2.4 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  ));
}

export function DriftChart({ height = 230 }) {
  const s = useApi(api.monitoring, []);
  return wrap(s, height, () => {
    if (s.data.length < 2)
      return <div className="state">Only {s.data.length} scoring run recorded so far.</div>;
    const d = [...s.data].reverse().map((r, i) => ({
      run: i + 1, mean: p2(r.mean_probability), lo: p2(r.p10_probability),
      band: +(p2(r.p90_probability) - p2(r.p10_probability)).toFixed(2),
    }));
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={d} margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis dataKey="run" {...axisProps} />
          <YAxis {...axisProps} unit="%" />
          <Tooltip {...tooltipStyle}
                   formatter={(v, n) => (n === "band" ? null : [`${v}%`, "Mean score"])}
                   labelFormatter={(l) => `run ${l}`} />
          <Area dataKey="lo" stackId="b" stroke="none" fill="none" isAnimationActive={false} />
          <Area dataKey="band" stackId="b" stroke="none" fill="var(--pale)"
                fillOpacity={0.85} isAnimationActive={false} />
          <Line dataKey="mean" stroke="var(--blue)" strokeWidth={2.25}
                dot={{ r: 3, fill: "var(--blue)", stroke: "var(--surface)", strokeWidth: 1.5 }}
                isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    );
  });
}

/* --- A/B rollout (template) ----------------------------------------------
   Illustrative only — no experiment has run yet. Standing in for the
   comparison a real rollout would report: conversion by arm, with the
   uncertainty band that says whether the gap is real or noise. Numbers are
   a plausible mock-up, sized off the ≈3× lift in `Result`, not a measurement. */
export function ABTestTemplateChart({ height = 230 }) {
  const arms = [
    { arm: "Control\n(random order)", rate: 7.4, lo: 6.6, hi: 8.2, n: "5,000 leads" },
    { arm: "Heuristic\n(rule of thumb)", rate: 11.8, lo: 10.8, hi: 12.8, n: "5,000 leads" },
    { arm: "Model\n(ranked queue)", rate: 20.6, lo: 19.2, hi: 22.0, n: "5,000 leads" },
  ].map((r) => ({ ...r, err: [r.rate - r.lo, r.hi - r.rate] }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={arms} margin={{ top: 8, right: 14, left: -4, bottom: 6 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="arm" {...axisProps} />
        <YAxis {...axisProps} unit="%" />
        <Tooltip {...tooltipStyle}
                 formatter={(v, n, p) => [`${p.payload.rate}% (95% CI ${p.payload.lo}–${p.payload.hi}%)`, "Conversion"]}
                 labelFormatter={(l) => l.replace("\n", " ")} />
        <Bar dataKey="rate" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          <Cell fill="var(--ink-3)" /><Cell fill="var(--orange)" /><Cell fill="var(--blue)" />
          <ErrorBar dataKey="err" width={4} strokeWidth={1.5} stroke="var(--ink-2)" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
