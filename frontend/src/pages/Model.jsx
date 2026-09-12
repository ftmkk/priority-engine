import React, { useState } from "react";
import { api, num, pct } from "../api.js";
import { Card, Failed, Loading, useApi } from "../components.jsx";
import { AtKTable, CandidateTable, GainsChart } from "../charts.jsx";

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
  return (
    <>

      <div className="kpis">
        <div className="kpi">
          <span className="eyebrow">PR-AUC</span>
          <div className="v num">{m.metrics.pr_auc.toFixed(4)}</div>
          <div className="d">how well it ranks buyers</div>
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
          <div className="d">
            train {pct(m.base_rate_train, 2)}
            {m.base_rate_valid != null && <> · validation {pct(m.base_rate_valid, 2)}</>}
          </div>
        </div>
      </div>

      <div className="grid g2">
        <Card
          eyebrow="Capacity"
          title="Cumulative gains on the held-out period"
          note="Buyers caught as you work down the list. The diagonal is what calling in a random order gets you."
        >
          <div className="chart"><GainsChart /></div>
        </Card>

        <Card
          eyebrow="Capacity"
          title="Precision and lift at realistic call volumes"
          note="k is how many calls the floor can actually make. This table, not accuracy, is the business case."
        >
          <AtKTable />
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card
          eyebrow="Selection"
          title="What we compared, and against what"
          note="Algorithms are compared on the validation window; the holdout is opened once, after the winner is fixed. Best validation PR-AUC goes live."
        >
          <CandidateTable />
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
          note="Every run is registered, and each prediction records the version behind it."
        >
          {versions.loading ? <Loading /> : versions.error ? <Failed error={versions.error} /> : (
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>Version</th><th>Algorithm</th><th>Trained</th>
                    <th>Train rows</th><th>Valid rows</th><th>Test rows</th>
                    <th>Valid PR-AUC</th><th>PR-AUC</th><th>ROC-AUC</th>
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
                      <td>{v.valid_rows != null ? num(v.valid_rows) : "—"}</td>
                      <td>{num(v.test_rows)}</td>
                      <td>{v.selection_pr_auc?.toFixed(4) ?? "—"}</td>
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
