import React from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, num, pct, toman } from "../api.js";
import { Card, Failed, Loading, axisProps, tooltipStyle, useApi } from "../components.jsx";

const p2 = (v) => +(v * 100).toFixed(2);

/** A flat mean across runs is the healthy state; say so rather than leaving the
 *  reader to guess whether a straight line means "stable" or "broken". */
function driftVerdict(snapshots) {
  const means = snapshots.map((s) => s.mean_probability).filter((v) => v != null);
  if (means.length < 2) return { ok: true, label: "not enough runs" };
  const spread = Math.max(...means) - Math.min(...means);
  const rel = spread / (means.reduce((a, b) => a + b, 0) / means.length);
  return rel < 0.05
    ? { ok: true, label: `stable across ${means.length} runs` }
    : { ok: false, label: `moved ${(rel * 100).toFixed(0)}% across runs` };
}

export default function Monitoring() {
  const cal = useApi(api.calibration, []);
  const dist = useApi(api.scoreDistribution, []);
  const decay = useApi(api.decayImpact, []);
  const drift = useApi(api.monitoring, []);
  const comp = useApi(api.queueComposition, []);
  const balance = useApi(api.targetBalance, []);

  return (
    <>
      <div className="phead">
        <span className="eyebrow">Monitoring</span>
        <h1>Is the model still telling the truth?</h1>
        <p>
          Ranking quality lives on the Model page. These are the checks that catch the
          failure modes a ranking metric hides: probabilities drifting out of calibration,
          the score distribution shifting under us, and how much the read-time decay is
          actually moving the queue.
        </p>
      </div>

      <div className="grid g2">
        <Card
          eyebrow="Calibration"
          title="Predicted vs what actually happened"
          note="Measured on the held-out period, where a prediction and its outcome refer to the same moment in the lead's life. On the diagonal means the probability column can be trusted; above it means the model over-predicts."
        >
          {cal.loading ? <Loading /> : cal.error ? <Failed error={cal.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={260}>
                <LineChart
                  data={cal.data.map((r) => ({
                    predicted: p2(r.predicted), observed: p2(r.observed),
                    ideal: p2(r.predicted), leads: r.leads,
                  }))}
                  margin={{ top: 8, right: 14, left: -16, bottom: 6 }}
                >
                  <CartesianGrid stroke="var(--line)" />
                  <XAxis dataKey="predicted" type="number" {...axisProps} unit="%"
                         domain={["dataMin", "dataMax"]} />
                  <YAxis {...axisProps} unit="%" />
                  <Tooltip
                    {...tooltipStyle}
                    formatter={(v, n) => [`${v}%`, n === "observed" ? "Observed" : "Perfect"]}
                    labelFormatter={(l) => `predicted ${l}%`}
                  />
                  <Legend wrapperStyle={{ fontSize: 11.5, color: "var(--ink-2)" }} />
                  <Line name="Perfect" dataKey="ideal" stroke="var(--ink-3)" strokeWidth={2}
                        strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                  <Line name="Observed" dataKey="observed" stroke="var(--blue)"
                        strokeWidth={2.5} dot={{ r: 3.5 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card
          eyebrow="Score distribution"
          title="Where the scores land"
          note="The shape to watch. A sudden shift here is the earliest sign that the incoming population has changed, and it shows up long before outcomes do."
        >
          {dist.loading ? <Loading /> : dist.error ? <Failed error={dist.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={dist.data} margin={{ top: 8, right: 14, left: -12, bottom: 6 }}>
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="score_pct" {...axisProps} unit="%" />
                  <YAxis {...axisProps} />
                  <Tooltip {...tooltipStyle} formatter={(v) => num(v)}
                           labelFormatter={(l) => `score ${l}–${l + 2}%`} />
                  <Bar dataKey="leads" fill="var(--blue)" radius={[3, 3, 0, 0]}
                       isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card
          eyebrow="Decay"
          title="What the read-time decay costs a lead"
          note="Raw model score against the score the queue actually ranks on, by lead age. Inside the support window they are identical — the score was re-inferred, so there is nothing to decay."
        >
          {decay.loading ? <Loading /> : decay.error ? <Failed error={decay.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={250}>
                <LineChart
                  data={decay.data.map((r) => ({
                    age: r.age_hours, raw: p2(r.raw), decayed: p2(r.decayed),
                    leads: r.leads, regime: r.regime,
                  }))}
                  margin={{ top: 8, right: 14, left: -16, bottom: 6 }}
                >
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="age" {...axisProps} unit="h" />
                  <YAxis {...axisProps} unit="%" />
                  <Tooltip {...tooltipStyle}
                           formatter={(v, n) => [`${v}%`, n === "raw" ? "Raw model score" : "After decay"]}
                           labelFormatter={(l) => `${l}h old`} />
                  <Legend wrapperStyle={{ fontSize: 11.5, color: "var(--ink-2)" }} />
                  <ReferenceLine x={4} stroke="var(--blue)" strokeDasharray="4 3"
                                 label={{ value: "support edge", fontSize: 10,
                                          fill: "var(--ink-3)", position: "top" }} />
                  <Line name="Raw model score" dataKey="raw" stroke="var(--ink-3)"
                        strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                  <Line name="After decay" dataKey="decayed" stroke="var(--orange)"
                        strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card
          eyebrow="Drift"
          title="Score distribution over successive runs"
          note="Mean and the 10th–90th percentile band of the queue, recorded on every scoring run. A flat series is the healthy result; a step or a widening band means the incoming population moved and the model needs recalibrating."
          action={
            drift.data?.length > 1 && (
              <span className={`pill ${driftVerdict(drift.data).ok ? "ok" : "err"}`}>
                {driftVerdict(drift.data).label}
              </span>
            )
          }
        >
          {drift.loading ? <Loading /> : drift.error ? <Failed error={drift.error} /> : (
            drift.data.length < 2 ? (
              <div className="state">
                Only {drift.data.length} run recorded so far — the band appears once the
                scoring job has run a few times.
              </div>
            ) : (
              <div className="chart">
                <ResponsiveContainer width="100%" height={250}>
                  <AreaChart
                    data={[...drift.data].reverse().map((r, i) => ({
                      run: i + 1,
                      mean: p2(r.mean_probability),
                      lo: p2(r.p10_probability),
                      // Recharts has no band mark: stack an invisible floor at p10
                      // and a filled segment of height p90-p10 on top of it.
                      band: +(p2(r.p90_probability) - p2(r.p10_probability)).toFixed(2),
                    }))}
                    margin={{ top: 8, right: 14, left: -16, bottom: 6 }}
                  >
                    <CartesianGrid stroke="var(--line)" vertical={false} />
                    <XAxis dataKey="run" {...axisProps} />
                    <YAxis {...axisProps} unit="%" />
                    <Tooltip
                      {...tooltipStyle}
                      formatter={(v, n) => n === "band" ? null : [`${v}%`, "Mean score"]}
                      labelFormatter={(l) => `run ${l}`}
                    />
                    <Area dataKey="lo" stackId="band" stroke="none" fill="none"
                          isAnimationActive={false} legendType="none" />
                    <Area dataKey="band" stackId="band" stroke="none"
                          fill="var(--pale)" fillOpacity={0.85}
                          isAnimationActive={false} legendType="none" />
                    <Line
                      dataKey="mean" stroke="var(--blue)" strokeWidth={3}
                      dot={{ r: 4, fill: "var(--blue)", stroke: "var(--surface)", strokeWidth: 2 }}
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )
          )}
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card
          eyebrow="Queue"
          title="What the call list is made of"
          note="Expected value by tier and product. carbody carries roughly 1.5× the margin, which is why it concentrates at the top even at a lower probability."
        >
          {comp.loading ? <Loading /> : comp.error ? <Failed error={comp.error} /> : (
            <div className="tablewrap">
              <table>
                <thead>
                  <tr><th>Tier</th><th>Product</th><th>Leads</th><th>Expected value</th></tr>
                </thead>
                <tbody>
                  {comp.data.map((r) => (
                    <tr key={`${r.priority_tier}-${r.product_type}`}>
                      <td>{r.priority_tier}</td>
                      <td>{r.product_type}</td>
                      <td>{num(r.leads)}</td>
                      <td>{toman(r.expected_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card
          eyebrow="Target"
          title="Class balance"
          note="9.2% of leads convert. Not extreme, but enough that accuracy is meaningless and a 0.5 threshold would never fire."
        >
          {balance.loading ? <Loading /> : balance.error ? <Failed error={balance.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={210}>
                <BarChart
                  data={balance.data.map((r) => ({
                    label: r.outcome === 1 ? "purchased" : "did not purchase",
                    leads: r.leads,
                  }))}
                  margin={{ top: 8, right: 14, left: -8, bottom: 6 }}
                >
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="label" {...axisProps} />
                  <YAxis {...axisProps} />
                  <Tooltip {...tooltipStyle} formatter={(v) => num(v)} />
                  <Bar dataKey="leads" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                    <Cell fill="var(--ink-3)" />
                    <Cell fill="var(--blue)" />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}