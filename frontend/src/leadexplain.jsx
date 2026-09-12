/* Per-lead explanation pieces, plus the two global views of the model.
   Split out so the call queue can show them beside the list it drives. */
import React, { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ErrorBar, LabelList, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, num, pct } from "./api.js";
import { Failed, Loading, axisProps, tooltipStyle, useApi } from "./components.jsx";

export const nice = (f) => f.replace(/_/g, " ");

/* --- the waterfall: average lead -> this lead ----------------------------- */
function Waterfall({ data, height = 250 }) {
  const rows = [];
  let run = data.base_logit;
  rows.push({ label: "average", cum: run, kind: "anchor" });
  data.contributions.forEach((c) => {
    rows.push({ label: nice(c.feature), value: c.value, reference: c.reference,
                start: run, delta: c.contribution, cum: run + c.contribution,
                kind: c.contribution >= 0 ? "up" : "down" });
    run += c.contribution;
  });
  const rest = data.other_contributions + data.residual;
  if (Math.abs(rest) > 0.005) {
    rows.push({ label: "other", start: run, delta: rest, cum: run + rest,
                kind: "residual" });
    run += rest;
  }
  rows.push({ label: "this lead", cum: data.final_logit, kind: "anchor" });

  const floorAll = Math.min(data.base_logit, data.final_logit,
                            ...rows.map((r) => Math.min(r.cum, r.start ?? r.cum))) - 0.45;
  const chart = rows.map((r) => r.kind === "anchor"
    ? { ...r, floor: floorAll, bar: r.cum - floorAll, isAnchor: true, tag: r.cum.toFixed(2) }
    : { ...r, floor: Math.min(r.start, r.cum), bar: Math.abs(r.delta), isAnchor: false,
        tag: `${r.delta > 0 ? "+" : ""}${r.delta.toFixed(2)}` });

  const colour = { anchor: "var(--ink-3)", up: "var(--blue)",
                   down: "var(--orange)", residual: "var(--line-strong)" };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={chart} margin={{ top: 20, right: 8, left: -18, bottom: 54 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="label" {...axisProps} angle={-32} textAnchor="end"
               height={62} interval={0} tick={{ ...axisProps.tick, fontSize: 8.5 }} />
        <YAxis {...axisProps} tick={{ ...axisProps.tick, fontSize: 9 }} />
        <Tooltip
          {...tooltipStyle}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const r = payload[0].payload;
            return (
              <div style={tooltipStyle.contentStyle}>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>{r.label}</div>
                {r.value !== undefined && (
                  <div style={{ color: "var(--ink-2)" }}>
                    this lead <b>{String(r.value)}</b> · average <b>{String(r.reference)}</b>
                  </div>
                )}
                {!r.isAnchor && <div>moves it <b>{r.tag}</b> log-odds</div>}
              </div>
            );
          }}
        />
        <Bar dataKey="floor" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="bar" stackId="w" radius={[2, 2, 0, 0]} isAnimationActive={false}>
          {chart.map((r, i) => <Cell key={i} fill={colour[r.kind]} />)}
          <LabelList dataKey="tag" position="top" offset={5}
                     style={{ fontSize: 8.5, fontFamily: "IBM Plex Mono, monospace",
                              fill: "var(--ink-3)" }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function LeadBreakdown({ leadId, topN = 7 }) {
  const s = useApi(() => (leadId ? api.explain(leadId) : Promise.resolve(null)), [leadId]);
  if (!leadId) return <div className="state">Pick a lead from the queue.</div>;
  if (s.error) return <Failed error={s.error} />;
  if (s.loading || !s.data) return <Loading what="breakdown" />;
  const d = { ...s.data, contributions: s.data.contributions.slice(0, topN) };
  const dropped = s.data.contributions.slice(topN)
    .reduce((a, c) => a + c.contribution, 0);
  return (
    <>
      <div className="minikpis">
        <div><span className="eyebrow">Average lead</span>
             <b className="num">{pct(d.base_probability, 1)}</b></div>
        <div><span className="eyebrow">This lead</span>
             <b className="num" style={{ color: "var(--blue)" }}>{pct(d.probability, 1)}</b></div>
        <div><span className="eyebrow">Lift</span>
             <b className="num">{(d.probability / d.base_probability).toFixed(2)}×</b></div>
      </div>
      <Waterfall data={{ ...d, other_contributions: dropped }} />
      <div className="key">
        <span><i style={{ background: "var(--blue)" }} />raises</span>
        <span><i style={{ background: "var(--orange)" }} />lowers</span>
        <span><i style={{ background: "var(--line-strong)" }} />interactions + calibration</span>
      </div>
    </>
  );
}

/* --- what-if -------------------------------------------------------------- */
const SWEEPABLE = [
  "minutes_since_abandonment", "days_to_policy_expiry", "offer_views_last_7d",
  "sessions_last_7d", "discount_percent", "days_since_last_visit",
  "price_pct_in_product", "has_previous_purchase", "visited_offer_page",
  "incoming_call_last_24h", "channel", "payment_type", "product_type",
  "insurance_company", "device", "partner",
];

export function LeadSweep({ leadId, height = 185 }) {
  const [feature, setFeature] = useState("minutes_since_abandonment");
  const s = useApi(() => (leadId ? api.sweep(leadId, feature) : Promise.resolve(null)),
                   [leadId, feature]);
  if (!leadId) return null;
  const ready = !s.loading && !s.error && s.data;
  return (
    <>
      <div className="rowsplit" style={{ marginBottom: 8 }}>
        <span className="eyebrow">Move one feature, hold the rest</span>
        <select value={feature} onChange={(e) => setFeature(e.target.value)}
                aria-label="Feature to sweep" style={{ fontSize: 12, padding: "5px 7px" }}>
          {SWEEPABLE.map((f) => <option key={f} value={f}>{nice(f)}</option>)}
        </select>
      </div>
      {s.error ? <Failed error={s.error} /> : !ready ? <Loading /> : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={s.data.points.map((p) => ({
            value: p.value, prob: +(p.probability * 100).toFixed(2) }))}
            margin={{ top: 8, right: 10, left: -20, bottom: 4 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis dataKey="value" {...axisProps} tick={{ ...axisProps.tick, fontSize: 8.5 }} />
            <YAxis {...axisProps} unit="%" tick={{ ...axisProps.tick, fontSize: 9 }} />
            <Tooltip {...tooltipStyle} formatter={(v) => [`${v}%`, "P(purchase)"]}
                     labelFormatter={(l) => `${nice(feature)} = ${l}`} />
            <ReferenceLine x={s.data.current} stroke="var(--orange)" strokeDasharray="3 3"
                           label={{ value: "now", fontSize: 9, fill: "var(--ink-3)",
                                    position: "top" }} />
            <Line dataKey="prob" stroke="var(--blue)" strokeWidth={2} dot={false}
                  isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </>
  );
}

/* --- global: what the model relies on, and its equation ------------------- */
export function GlobalImportance({ top = 9, height = 235 }) {
  const s = useApi(api.importance, []);
  if (s.loading) return <Loading />;
  if (s.error) return <Failed error={s.error} />;
  const d = s.data.permutation.slice(0, top).map((r) => ({ ...r, name: nice(r.feature) }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart layout="vertical" data={d} margin={{ top: 4, right: 22, left: 108, bottom: 12 }}>
        <CartesianGrid stroke="var(--line)" horizontal={false} />
        <XAxis type="number" {...axisProps} tick={{ ...axisProps.tick, fontSize: 9 }} />
        <YAxis type="category" dataKey="name" width={104} {...axisProps}
               tick={{ ...axisProps.tick, fontSize: 9 }} />
        <Tooltip {...tooltipStyle}
                 formatter={(v, n, p) => [`${Number(v).toFixed(5)} PR-AUC`,
                                          `pushes ${p.payload.direction}`]} />
        <Bar dataKey="importance" radius={[0, 2, 2, 0]} barSize={11} isAnimationActive={false}>
          {d.map((r, i) => (
            <Cell key={i} fill={r.direction === "up" ? "var(--blue)"
              : r.direction === "down" ? "var(--orange)" : "var(--deep)"} />
          ))}
          <ErrorBar dataKey="std" width={2} strokeWidth={1} stroke="var(--ink-3)" direction="x" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ModelEquation({ terms = 7 }) {
  const s = useApi(api.importance, []);
  if (s.loading) return <Loading />;
  if (s.error) return <Failed error={s.error} />;
  const eq = s.data.equation;
  if (!eq)
    return (
      <div className="state">
        {s.data.algorithm} is a tree ensemble — there is no closed-form equation to show.
      </div>
    );
  return (
    <>
      <p className="note num" style={{ fontSize: 12, lineHeight: 1.7, marginTop: 4 }}>
        log-odds = {eq.intercept}
        {eq.terms.slice(0, terms).map((t) => (
          <span key={t.term}>
            {" "}{t.weight >= 0 ? "+" : "−"} {Math.abs(t.weight)}·{nice(t.term)}
          </span>
        ))}
        {eq.terms.length > terms && " + …"}
      </p>
      <div className="tablewrap" style={{ maxHeight: 168, overflowY: "auto" }}>
        <table>
          <thead><tr><th>Term</th><th>Weight</th></tr></thead>
          <tbody>
            {eq.terms.slice(0, 12).map((t) => (
              <tr key={t.term}>
                <td>{nice(t.term)}</td>
                <td style={{ color: t.weight >= 0 ? "var(--good)" : "var(--bad)" }}>
                  {t.weight >= 0 ? "+" : ""}{t.weight}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
