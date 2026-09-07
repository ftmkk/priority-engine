import React from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, num, pct, toman } from "../api.js";
import { Card, Failed, Kpi, Loading, axisProps, tooltipStyle, useApi } from "../components.jsx";

const asPct = (v) => +(v * 100).toFixed(2);

export default function Dashboard() {
  const summary = useApi(api.summary, []);
  const urgency = useApi(api.urgency, []);
  const engagement = useApi(api.engagement, []);
  const weekly = useApi(api.weekly, []);
  const channel = useApi(() => api.conversionBy("channel"), []);

  if (summary.loading) return <Loading what="dashboard" />;
  if (summary.error) return <Failed error={summary.error} hint="Is the API running?" />;

  const { kpi, queue_by_tier: tiers, model } = summary.data;
  const base = asPct(kpi.conversion);

  return (
    <>
      <div className="phead">
        <span className="eyebrow">Overview</span>
        <h1>Lead conversion and the live call queue</h1>
        <p>
          Every figure is read from Postgres. The queue is refreshed by the prediction
          job every 5 minutes over leads created in the last 24 hours.
        </p>
      </div>

      <div className="kpis">
        <Kpi label="Leads" value={num(kpi.leads)} detail="deduplicated, with a known outcome" />
        <Kpi label="Conversion" value={pct(kpi.conversion, 2)} detail="base rate" />
        <Kpi label="Converters" value={num(kpi.converters)} detail="completed the purchase" />
        <Kpi label="Margin won" value={toman(kpi.margin_won)} detail="Toman, from converters" />
        <Kpi
          label="Holdout PR-AUC"
          value={model ? model.metrics.pr_auc.toFixed(3) : "—"}
          detail={model ? `${model.algorithm}, ROC-AUC ${model.metrics.roc_auc.toFixed(3)}` : "no model yet"}
        />
      </div>

      <div className="grid g2">
        <Card
          eyebrow="Live queue"
          title="Leads waiting, by priority tier"
          note="Tiers are percentile cuts on expected value (probability × margin), not on probability alone."
        >
          <div className="chart">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={tiers} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="var(--line)" vertical={false} />
                <XAxis dataKey="priority_tier" {...axisProps} />
                <YAxis {...axisProps} />
                <Tooltip {...tooltipStyle} formatter={(v) => num(v)} />
                <Bar isAnimationActive={false} dataKey="leads" radius={[4, 4, 0, 0]}>
                  {tiers.map((t) => (
                    <Cell
                      key={t.priority_tier}
                      fill={t.priority_tier === "P1" ? "var(--blue)" : "var(--deep)"}
                      fillOpacity={t.priority_tier === "P1" ? 1 : 0.55}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card
          eyebrow="Stability"
          title="Weekly conversion drifts down at the end"
          note="This is why the model is trained on the earlier period and validated on the most recent one — never a random split."
        >
          {weekly.loading ? <Loading /> : weekly.error ? <Failed error={weekly.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart
                  data={weekly.data.map((w) => ({ ...w, conv: asPct(w.conversion) }))}
                  margin={{ top: 8, right: 12, left: -18, bottom: 0 }}
                >
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="week" {...axisProps} tickFormatter={(d) => d.slice(5)} minTickGap={26} />
                  <YAxis {...axisProps} unit="%" />
                  <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} />
                  <ReferenceLine y={base} stroke="var(--orange)" strokeDasharray="4 3" />
                  <Line isAnimationActive={false} type="monotone" dataKey="conv" stroke="var(--blue)" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card
          eyebrow="Urgency · clock 1"
          title="Intent cools by the minute"
          note="Time since the user abandoned checkout. The fast-call window is real: odds fall about ×0.78 per hour."
        >
          {urgency.loading ? <Loading /> : urgency.error ? <Failed error={urgency.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={210}>
                <BarChart
                  data={urgency.data.abandonment.map((r) => ({ ...r, conv: asPct(r.conversion) }))}
                  margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
                >
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="bucket" {...axisProps} unit="m" />
                  <YAxis {...axisProps} unit="%" />
                  <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} labelFormatter={(l) => `${l}–${l + 40} min`} />
                  <ReferenceLine y={base} stroke="var(--orange)" strokeDasharray="4 3" />
                  <Bar isAnimationActive={false} dataKey="conv" fill="var(--blue)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card
          eyebrow="Urgency · clock 2"
          title="Deadline pressure pulls the other way"
          note="Days until the current policy expires. Already-expired leads convert best of all, so the negative values are kept, not clipped."
        >
          {urgency.loading ? <Loading /> : urgency.error ? <Failed error={urgency.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={210}>
                <BarChart
                  data={urgency.data.expiry.map((r) => ({ ...r, conv: asPct(r.conversion) }))}
                  margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
                >
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="bucket" {...axisProps} />
                  <YAxis {...axisProps} unit="%" />
                  <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} />
                  <ReferenceLine y={base} stroke="var(--orange)" strokeDasharray="4 3" />
                  <Bar isAnimationActive={false} dataKey="conv" fill="var(--deep)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card
          eyebrow="Behaviour"
          title="Engagement depth is the strongest signal"
          note="Offer views and sessions over the trailing 7 days. Offer views nearly triple conversion across their range."
        >
          {engagement.loading ? <Loading /> : engagement.error ? <Failed error={engagement.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis
                    dataKey="bucket" type="number" allowDecimals={false}
                    domain={[0, 6]} {...axisProps}
                  />
                  <YAxis {...axisProps} unit="%" />
                  <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} />
                  <Legend wrapperStyle={{ fontSize: 11.5, color: "var(--ink-2)" }} />
                  <Line isAnimationActive={false}
                    name="Offer views 7d" dataKey="conv" strokeWidth={2}
                    data={engagement.data.offer_views_last_7d.map((r) => ({ ...r, conv: asPct(r.conversion) }))}
                    stroke="var(--blue)" dot={{ r: 3.5 }}
                  />
                  <Line isAnimationActive={false}
                    name="Sessions 7d" dataKey="conv" strokeWidth={2}
                    data={engagement.data.sessions_last_7d.map((r) => ({ ...r, conv: asPct(r.conversion) }))}
                    stroke="var(--orange)" dot={{ r: 3.5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card
          eyebrow="Context"
          title="Where the lead came from"
          note="Real but narrow signal — roughly 8% to 11%. Useful to the model, but not what drives the ranking."
        >
          {channel.loading ? <Loading /> : channel.error ? <Failed error={channel.error} /> : (
            <div className="chart">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  layout="vertical"
                  data={channel.data.map((r) => ({ ...r, conv: asPct(r.conversion) }))}
                  margin={{ top: 8, right: 34, left: 12, bottom: 0 }}
                >
                  <CartesianGrid stroke="var(--line)" horizontal={false} />
                  <XAxis type="number" {...axisProps} unit="%" />
                  <YAxis type="category" dataKey="label" width={64} {...axisProps} />
                  <Tooltip {...tooltipStyle} formatter={(v) => `${v}%`} />
                  <ReferenceLine x={base} stroke="var(--orange)" strokeDasharray="4 3" />
                  <Bar isAnimationActive={false} dataKey="conv" fill="var(--deep)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
