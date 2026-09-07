import React, { useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, num, pct } from "../api.js";
import { Card, Failed, Loading, axisProps, tooltipStyle, useApi } from "../components.jsx";

export default function Model() {
  const [busy, setBusy] = useState(null);
  const [tick, setTick] = useState(0);
  const model = useApi(api.model, [tick]);
  const versions = useApi(api.versions, [tick]);
  const jobs = useApi(api.jobs, [tick]);

  const run = async (name, fn) => {
    setBusy(name);
    try {
      await fn();
      setTick((t) => t + 1);
    } catch (e) {
      alert(`${name} failed: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  if (model.loading) return <Loading what="model" />;
  if (model.error)
    return <Failed error={model.error} hint="No model registered yet — run the training job." />;

  const m = model.data;
  const gains = (m.metrics.gains || []).map((g) => ({
    depth: +(g.depth * 100).toFixed(1),
    model: +(g.captured * 100).toFixed(1),
    random: +(g.depth * 100).toFixed(1),
  }));

  return (
    <>
      <div className="phead">
        <div className="rowsplit">
          <div>
            <span className="eyebrow">Active model</span>
            <h1>{m.version}</h1>
            <p>
              {m.algorithm} · trained on {num(m.train_rows)} rows, validated on{" "}
              {num(m.test_rows)} held out by time.
            </p>
          </div>
          <div className="controls">
            <button className="btn" disabled={busy} onClick={() => run("training", api.runTrain)}>
              {busy === "training" ? "Training…" : "Retrain now"}
            </button>
            <button className="btn" disabled={busy} onClick={() => run("prediction", api.runPredict)}>
              {busy === "prediction" ? "Scoring…" : "Rescore now"}
            </button>
          </div>
        </div>
      </div>

      <div className="kpis">
        <div className="kpi">
          <span className="eyebrow">PR-AUC</span>
          <div className="v num">{m.metrics.pr_auc.toFixed(4)}</div>
          <div className="d">primary metric</div>
        </div>
        <div className="kpi">
          <span className="eyebrow">ROC-AUC</span>
          <div className="v num">{m.metrics.roc_auc.toFixed(4)}</div>
          <div className="d">secondary</div>
        </div>
        <div className="kpi">
          <span className="eyebrow">Brier</span>
          <div className="v num">{m.metrics.brier.toFixed(4)}</div>
          <div className="d">calibration error</div>
        </div>
        <div className="kpi">
          <span className="eyebrow">Holdout base rate</span>
          <div className="v num">{pct(m.base_rate_test, 2)}</div>
          <div className="d">train was {pct(m.base_rate_train, 2)}</div>
        </div>
      </div>

      <div className="grid g2">
        <Card
          eyebrow="Capacity"
          title="Cumulative gains on the held-out period"
          note="How many of all converters you catch by working down the ranked queue. The diagonal is calling at random."
        >
          <div className="chart">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={gains} margin={{ top: 8, right: 12, left: -18, bottom: 4 }}>
                <CartesianGrid stroke="var(--line)" />
                <XAxis dataKey="depth" {...axisProps} unit="%" />
                <YAxis {...axisProps} unit="%" />
                <Tooltip
                  {...tooltipStyle}
                  formatter={(v, n) => [`${v}%`, n === "model" ? "Model" : "Random"]}
                  labelFormatter={(l) => `top ${l}% of queue`}
                />
                <Legend wrapperStyle={{ fontSize: 11.5, color: "var(--ink-2)" }} />
                <Line isAnimationActive={false} name="Model" dataKey="model" stroke="var(--blue)" strokeWidth={2} dot={false} />
                <Line isAnimationActive={false}
                  name="Random" dataKey="random" stroke="var(--ink-3)"
                  strokeWidth={2} strokeDasharray="5 4" dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card
          eyebrow="Capacity"
          title="Precision and lift at realistic call volumes"
          note="k is how many leads the floor can actually get through. This — not accuracy — is the metric that matters."
        >
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>k</th><th>Precision</th><th>Recall</th><th>Lift</th><th>Margin captured</th>
                </tr>
              </thead>
              <tbody>
                {m.metrics.at_k.map((k) => (
                  <tr key={k.k}>
                    <td>{num(k.k)}</td>
                    <td>{pct(k.precision, 1)}</td>
                    <td>{pct(k.recall, 1)}</td>
                    <td>{k.lift.toFixed(2)}×</td>
                    <td>{pct(k.margin_capture, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card
          eyebrow="Selection"
          title="What we compared, and against what"
          note="Both algorithms and both baselines are scored on the same held-out period. The best PR-AUC is registered active."
        >
          <div className="tablewrap">
            <table>
              <thead>
                <tr><th>Candidate</th><th>PR-AUC</th><th>ROC-AUC</th></tr>
              </thead>
              <tbody>
                {[...m.candidate_results]
                  .sort((a, b) => b.pr_auc - a.pr_auc)
                  .map((c) => (
                    <tr key={c.algorithm}>
                      <td>
                        {c.algorithm}
                        {c.algorithm === m.algorithm && (
                          <span className="pill ok" style={{ marginLeft: 8 }}>active</span>
                        )}
                      </td>
                      <td>{c.pr_auc.toFixed(4)}</td>
                      <td>{c.roc_auc.toFixed(4)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card eyebrow="Operations" title="Recent job runs" note="Written by the scheduler on every run.">
          {jobs.loading ? <Loading /> : jobs.error ? <Failed error={jobs.error} /> : (
            <div className="tablewrap" style={{ maxHeight: 260, overflowY: "auto" }}>
              <table>
                <thead>
                  <tr><th>Job</th><th>Status</th><th>Trigger</th><th>Duration</th><th>Rows</th></tr>
                </thead>
                <tbody>
                  {jobs.data.length === 0 ? (
                    <tr><td colSpan={5}>No runs recorded yet.</td></tr>
                  ) : jobs.data.map((j) => (
                    <tr key={j.id}>
                      <td>{j.job_name}</td>
                      <td>
                        <span className={`pill ${j.status === "success" ? "ok" : j.status === "failed" ? "err" : ""}`}>
                          {j.status}
                        </span>
                      </td>
                      <td>{j.trigger}</td>
                      <td>{j.duration_ms == null ? "—" : `${num(j.duration_ms)}ms`}</td>
                      <td>{j.rows_processed ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <div style={{ marginTop: 18 }}>
        <Card
          eyebrow="Registry"
          title="Model versions"
          note="Every training run is registered. Predictions record which version produced them, so any score is traceable."
        >
          {versions.loading ? <Loading /> : versions.error ? <Failed error={versions.error} /> : (
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>Version</th><th>Algorithm</th><th>Trained</th>
                    <th>Train rows</th><th>Test rows</th><th>PR-AUC</th><th>ROC-AUC</th>
                  </tr>
                </thead>
                <tbody>
                  {versions.data.map((v) => (
                    <tr key={v.version}>
                      <td>
                        {v.version}
                        {v.is_active && <span className="pill ok" style={{ marginLeft: 8 }}>active</span>}
                      </td>
                      <td>{v.algorithm}</td>
                      <td>{new Date(v.trained_at).toISOString().slice(0, 16).replace("T", " ")}</td>
                      <td>{num(v.train_rows)}</td>
                      <td>{num(v.test_rows)}</td>
                      <td>{v.pr_auc?.toFixed(4) ?? "—"}</td>
                      <td>{v.roc_auc?.toFixed(4) ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

    </>
  );
}
