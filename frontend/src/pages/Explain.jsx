import React, { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, ErrorBar, LabelList, Line,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, num, pct } from "../api.js";
import { Card, Failed, Loading, axisProps, tooltipStyle, useApi } from "../components.jsx";

const nice = (f) => f.replace(/_/g, " ").replace(/\b7d\b/, "7d");

/* --- the waterfall: base rate -> each feature's push -> this lead's score --- */
function Waterfall({ data }) {
  const rows = [];
  let running = data.base_logit;
  rows.push({ label: "average lead", start: 0, delta: 0, cum: running, kind: "anchor" });
  data.contributions.forEach((c) => {
    rows.push({
      label: nice(c.feature), value: c.value, reference: c.reference,
      start: running, delta: c.contribution, cum: running + c.contribution,
      kind: c.contribution >= 0 ? "up" : "down",
    });
    running += c.contribution;
  });
  if (Math.abs(data.other_contributions) > 0.005) {
    rows.push({ label: "everything else", start: running, delta: data.other_contributions,
                cum: running + data.other_contributions,
                kind: data.other_contributions >= 0 ? "up" : "down" });
    running += data.other_contributions;
  }
  if (Math.abs(data.residual) > 0.005) {
    rows.push({ label: "interactions + calibration", start: running, delta: data.residual,
                cum: running + data.residual, kind: "residual" });
    running += data.residual;
  }
  rows.push({ label: "this lead", start: 0, delta: 0, cum: data.final_logit, kind: "anchor" });

  // floating bars: an invisible base, then the visible delta stacked on top
  const chart = rows.map((r) => {
    if (r.kind === "anchor") {
      const lo = Math.min(r.cum, data.base_logit, data.final_logit) - 0.6;
      return { ...r, floor: lo, bar: r.cum - lo, isAnchor: true,
               tag: r.cum.toFixed(2) };
    }
    const lo = Math.min(r.start, r.cum);
    return { ...r, floor: lo, bar: Math.abs(r.delta), isAnchor: false,
             tag: `${r.delta > 0 ? "+" : ""}${r.delta.toFixed(2)}` };
  });
  const colour = { anchor: "var(--ink-3)", up: "var(--blue)",
                   down: "var(--orange)", residual: "var(--line-strong)" };

  return (
    <ResponsiveContainer width="100%" height={330}>
      <BarChart data={chart} margin={{ top: 10, right: 16, left: -8, bottom: 60 }}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis dataKey="label" {...axisProps} angle={-34} textAnchor="end"
               height={86} interval={0} tick={{ ...axisProps.tick, fontSize: 9 }} />
        <YAxis {...axisProps} label={{ value: "log-odds", angle: -90, position: "insideLeft",
                                       fill: "var(--ink-3)", fontSize: 10, offset: 16 }} />
        <Tooltip
          {...tooltipStyle}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const r = payload[0].payload;
            return (
              <div style={tooltipStyle.contentStyle}>
                <div style={{ fontWeight: 600, marginBottom: 3 }}>{r.label}</div>
                {r.value !== undefined && (
                  <div style={{ color: "var(--ink-2)" }}>
                    this lead <b>{String(r.value)}</b> · average <b>{String(r.reference)}</b>
                  </div>
                )}
                {!r.isAnchor && (
                  <div>moves the score <b>{r.delta > 0 ? "+" : ""}{r.delta.toFixed(3)}</b> log-odds</div>
                )}
                <div style={{ color: "var(--ink-3)" }}>
                  running total {r.cum.toFixed(3)}
                </div>
              </div>
            );
          }}
        />
        <Bar dataKey="floor" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="bar" stackId="w" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {chart.map((r, i) => <Cell key={i} fill={colour[r.kind]} />)}
          {/* anchors show the running total, the rest show their own push */}
          <LabelList
            dataKey="tag" position="top" offset={7}
            style={{ fontSize: 9.5, fontFamily: "IBM Plex Mono, monospace",
                     fill: "var(--ink-2)" }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function Explain() {
  const queue = useApi(() => api.queue({ limit: 40 }), []);
  const imp = useApi(api.importance, []);
  const [leadId, setLeadId] = useState(null);
  const [feature, setFeature] = useState("minutes_since_abandonment");

  useEffect(() => {
    if (!leadId && queue.data?.items?.length) setLeadId(queue.data.items[0].lead_id);
  }, [queue.data, leadId]);

  const exp = useApi(() => (leadId ? api.explain(leadId) : Promise.resolve(null)), [leadId]);
  const swp = useApi(
    () => (leadId ? api.sweep(leadId, feature) : Promise.resolve(null)), [leadId, feature]);

  return (
    <>
      <div className="phead">
        <span className="eyebrow">Interpretation</span>
        <h1>Why did this lead get that score?</h1>
        <p>
          Whichever algorithm the training run picked, the same two questions get answered:
          what the model relies on overall, and how one particular lead's score was arrived
          at. Pick a lead from the queue and follow the arithmetic.
        </p>
      </div>

      <div className="controls">
        <select value={leadId ?? ""} onChange={(e) => setLeadId(e.target.value)}
                aria-label="Lead to explain" style={{ minWidth: 230 }}>
          {queue.data?.items?.map((i) => (
            <option key={i.lead_id} value={i.lead_id}>
              {i.lead_id} — {i.priority_tier} · {pct(i.probability, 1)} · {i.product_type}
            </option>
          ))}
        </select>
        {imp.data && (
          <span className="pill">
            model: {imp.data.algorithm}
            {imp.data.equation ? " · has a closed-form equation" : " · tree ensemble"}
          </span>
        )}
      </div>

      <Card
        eyebrow="Per-lead breakdown"
        title={exp.data ? `From the average lead to ${exp.data.lead_id}` : "Breakdown"}
        note="Each bar is one feature's own value, measured against an average lead. Blue pushes the score up, orange pulls it down. The last grey bar is what a one-feature-at-a-time view cannot explain: interactions between features, plus the calibration layer, which is monotone but not linear."
      >
        {exp.loading ? <Loading what="explanation" /> : exp.error ? <Failed error={exp.error} /> :
          !exp.data ? <div className="state">Pick a lead above.</div> : (
            <>
              <div className="kpis" style={{ marginTop: 14, marginBottom: 0 }}>
                <div className="kpi">
                  <span className="eyebrow">Average lead</span>
                  <div className="v num">{pct(exp.data.base_probability, 2)}</div>
                  <div className="d">every feature at its median</div>
                </div>
                <div className="kpi">
                  <span className="eyebrow">This lead</span>
                  <div className="v num" style={{ color: "var(--blue)" }}>
                    {pct(exp.data.probability, 2)}
                  </div>
                  <div className="d">
                    {(exp.data.probability / exp.data.base_probability).toFixed(2)}× the average
                  </div>
                </div>
                <div className="kpi">
                  <span className="eyebrow">Biggest lift</span>
                  <div className="v num" style={{ fontSize: 17 }}>
                    {nice(exp.data.contributions[0]?.feature ?? "—")}
                  </div>
                  <div className="d">
                    {exp.data.contributions[0]?.contribution > 0 ? "+" : ""}
                    {exp.data.contributions[0]?.contribution} log-odds
                  </div>
                </div>
                <div className="kpi">
                  <span className="eyebrow">Unexplained</span>
                  <div className="v num">{exp.data.residual}</div>
                  <div className="d">log-odds, from interactions</div>
                </div>
              </div>
              <div className="chart"><Waterfall data={exp.data} /></div>
            </>
          )}
      </Card>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card
          eyebrow="What-if"
          title="Move one feature, hold the rest"
          note="The model's own response curve for this exact lead — not a population average. The dot marks where the lead actually sits."
          action={
            <select value={feature} onChange={(e) => setFeature(e.target.value)}
                    aria-label="Feature to sweep">
              {(api.sweepableCache ?? [
                "minutes_since_abandonment", "days_to_policy_expiry", "offer_views_last_7d",
                "sessions_last_7d", "discount_percent", "days_since_last_visit",
                "price_pct_in_product", "has_previous_purchase", "visited_offer_page",
                "incoming_call_last_24h", "channel", "payment_type", "product_type",
                "insurance_company", "device", "partner",
              ]).map((f) => <option key={f} value={f}>{nice(f)}</option>)}
            </select>
          }
        >
          {swp.loading ? <Loading /> : swp.error ? <Failed error={swp.error} /> :
            !swp.data ? null : (
              <div className="chart">
                <ResponsiveContainer width="100%" height={260}>
                  <ComposedChart
                    data={swp.data.points.map((p) => ({
                      value: p.value, prob: +(p.probability * 100).toFixed(3),
                    }))}
                    margin={{ top: 10, right: 16, left: -12, bottom: 20 }}
                  >
                    <CartesianGrid stroke="var(--line)" vertical={false} />
                    <XAxis dataKey="value" {...axisProps}
                           tick={{ ...axisProps.tick, fontSize: 9.5 }} />
                    <YAxis {...axisProps} unit="%" />
                    <Tooltip {...tooltipStyle} formatter={(v) => [`${v}%`, "P(purchase)"]}
                             labelFormatter={(l) => `${nice(feature)} = ${l}`} />
                    <Line dataKey="prob" stroke="var(--blue)" strokeWidth={2.5}
                          dot={false} isAnimationActive={false} />
                    <ReferenceLine
                      x={swp.data.points.reduce((best, p) =>
                        Math.abs(String(p.value) === String(swp.data.current) ? 0 : 1) <
                        Math.abs(String(best.value) === String(swp.data.current) ? 0 : 1)
                          ? p : best, swp.data.points[0]).value}
                      stroke="var(--orange)" strokeDasharray="4 3"
                      label={{ value: "this lead", fontSize: 10, fill: "var(--ink-3)",
                               position: "top" }}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
        </Card>

        <Card
          eyebrow="Global"
          title="What the model relies on"
          note="Permutation importance on the held-out period: how much PR-AUC is lost when a column is shuffled. Model-agnostic, so this reads the same whichever algorithm was selected. Bars are coloured by which way the feature pushes."
        >
          {imp.loading ? <Loading /> : imp.error ? <Failed error={imp.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={Math.max(260, imp.data.permutation.length * 21)}>
                <BarChart
                  layout="vertical"
                  data={imp.data.permutation.map((r) => ({ ...r, name: nice(r.feature) }))}
                  margin={{ top: 6, right: 30, left: 118, bottom: 20 }}
                >
                  <CartesianGrid stroke="var(--line)" horizontal={false} />
                  <XAxis type="number" {...axisProps}
                         tick={{ ...axisProps.tick, fontSize: 9.5 }} />
                  <YAxis type="category" dataKey="name" width={114} {...axisProps}
                         tick={{ ...axisProps.tick, fontSize: 9 }} />
                  <Tooltip {...tooltipStyle}
                           formatter={(v, n, p) => [
                             `${Number(v).toFixed(5)} PR-AUC`,
                             `pushes ${p.payload.direction}`]} />
                  <Bar dataKey="importance" radius={[0, 3, 3, 0]} isAnimationActive={false}>
                    {imp.data.permutation.map((r, i) => (
                      <Cell key={i} fill={
                        r.direction === "up" ? "var(--blue)"
                        : r.direction === "down" ? "var(--orange)"
                        : "var(--deep)"} />
                    ))}
                    <ErrorBar dataKey="std" width={3} strokeWidth={1}
                              stroke="var(--ink-3)" direction="x" />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      {imp.data?.equation && (
        <div style={{ marginTop: 18 }}>
          <Card
            eyebrow="The equation"
            title="Because a linear model was selected, there is a literal formula"
            note="Weights on standardised features, so they are directly comparable. A tree ensemble has no equivalent — this card simply disappears when one is selected."
          >
            <p className="note num" style={{ marginTop: 12, fontSize: 12.5 }}>
              log-odds = {imp.data.equation.intercept}
              {imp.data.equation.terms.slice(0, 6).map((t) => (
                <span key={t.term}>
                  {" "}{t.weight >= 0 ? "+" : "−"} {Math.abs(t.weight)}·{nice(t.term)}
                </span>
              ))}
              {imp.data.equation.terms.length > 6 && " + …"}
            </p>
            <div className="tablewrap" style={{ maxHeight: 300, overflowY: "auto" }}>
              <table>
                <thead><tr><th>Term</th><th>Weight</th><th>Direction</th></tr></thead>
                <tbody>
                  {imp.data.equation.terms.map((t) => (
                    <tr key={t.term}>
                      <td>{nice(t.term)}</td>
                      <td>{t.weight}</td>
                      <td style={{ color: t.weight >= 0 ? "var(--good)" : "var(--bad)" }}>
                        {t.weight >= 0 ? "raises" : "lowers"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
