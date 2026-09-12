import React from "react";
import { api, num, pct, toman } from "../api.js";
import { Card, Failed, Kpi, Loading, useApi } from "../components.jsx";
import {
  ConversionByChart, EngagementChart, QueueTierChart, UrgencyChart, WeeklyTrendChart,
} from "../charts.jsx";

export default function Dashboard() {
  const summary = useApi(api.summary, []);

  if (summary.loading) return <Loading what="dashboard" />;
  if (summary.error) return <Failed error={summary.error} hint="Is the API running?" />;

  const { kpi, model } = summary.data;
  const base = kpi.conversion;

  return (
    <>

      <div className="kpis">
        <Kpi label="Leads" value={num(kpi.leads)} detail="with a known outcome" />
        <Kpi label="Conversion" value={pct(base, 2)} detail="base rate" />
        <Kpi label="Converters" value={num(kpi.converters)} detail="completed the purchase" />
        <Kpi label="Margin won" value={toman(kpi.margin_won)} detail="Toman, from converters" />
        <Kpi label="Holdout PR-AUC"
             value={model ? model.metrics.pr_auc.toFixed(3) : "—"}
             detail={model ? `${model.algorithm}, on data it never saw`
                           : "no model yet"} />
      </div>

      <div className="grid g2">
        <Card eyebrow="Live queue" title="Leads waiting, by priority tier"
              note="Tiers cut on expected value — probability × margin. Leads leave the queue at 24h, where the decay has taken the best of them under 1%.">
          <div className="chart"><QueueTierChart /></div>
        </Card>
        <Card eyebrow="Stability" title="Weekly conversion drifts down at the end"
              note="9.5% until July, 7.4% after. The reason the model is trained and tested by time, never at random.">
          <div className="chart"><WeeklyTrendChart base={base} /></div>
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card eyebrow="Urgency · clock 1" title="Intent cools by the minute"
              note="Odds fall about ×0.78 an hour — the first hour is worth roughly twice the sixth. The rush is real.">
          <div className="chart"><UrgencyChart which="abandonment" base={base} /></div>
        </Card>
        <Card eyebrow="Urgency · clock 2" title="Deadline pressure pulls the other way"
              note="Already-expired policies convert best of all, so a negative number here is a buying signal, not bad data.">
          <div className="chart"><UrgencyChart which="expiry" base={base} /></div>
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card eyebrow="Behaviour" title="Engagement depth is the strongest signal"
              note="Trailing 7 days. How much of the offer they looked at is the single strongest thing we know about them.">
          <div className="chart"><EngagementChart /></div>
        </Card>
        <Card eyebrow="Context" title="Where the lead came from"
              note="Real but narrow — 8% to 11%. Worth knowing, not enough to rank on.">
          <div className="chart"><ConversionByChart dimension="channel" base={base} /></div>
        </Card>
      </div>
    </>
  );
}
