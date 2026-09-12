import React from "react";
import { api, num, pct, toman } from "../api.js";
import { Card, Failed, Loading, useApi } from "../components.jsx";
import {
  CalibrationChart, DecayImpactChart, DriftChart, ScoreDistributionChart,
  TargetBalanceChart,
} from "../charts.jsx";

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
  const drift = useApi(api.monitoring, []);
  const comp = useApi(api.queueComposition, []);

  return (
    <>

      <div className="grid g2">
        <Card eyebrow="Calibration" title="Predicted vs what actually happened"
              note="On the diagonal, the percentage on the queue means what it says. Above it, the model is promising more than it delivers.">
          <div className="chart"><CalibrationChart /></div>
        </Card>
        <Card eyebrow="Score distribution" title="Where the scores land"
              note="The earliest warning there is: this moves weeks before anyone notices fewer sales.">
          <div className="chart"><ScoreDistributionChart /></div>
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card eyebrow="Decay" title="What the read-time decay costs a lead"
              note="What ageing costs a lead. Identical for the first six hours, because there the model is asked again rather than faded.">
          <div className="chart"><DecayImpactChart /></div>
        </Card>
        <Card eyebrow="Drift" title="Score distribution over successive runs"
              note="Flat is the healthy result. A step or a widening band means recalibrate."
              action={drift.data?.length > 1 && (
                <span className={`pill ${driftVerdict(drift.data).ok ? "ok" : "err"}`}>
                  {driftVerdict(drift.data).label}
                </span>
              )}>
          <div className="chart"><DriftChart /></div>
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card eyebrow="Queue" title="What the call list is made of"
              note="carbody carries roughly 1.5× the margin, so it concentrates at the top.">
          {comp.loading ? <Loading /> : comp.error ? <Failed error={comp.error} /> : (
            <div className="tablewrap">
              <table>
                <thead><tr><th>Tier</th><th>Product</th><th>Leads</th><th>Expected value</th></tr></thead>
                <tbody>
                  {comp.data.map((r) => (
                    <tr key={`${r.priority_tier}-${r.product_type}`}>
                      <td>{r.priority_tier}</td><td>{r.product_type}</td>
                      <td>{num(r.leads)}</td><td>{toman(r.expected_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card eyebrow="Target" title="Class balance"
              note="9.2% convert — enough that accuracy is meaningless and 0.5 never fires.">
          <div className="chart"><TargetBalanceChart /></div>
        </Card>
      </div>
    </>
  );
}
