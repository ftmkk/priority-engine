import React from "react";
import {
  CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { api, num, pct, toman } from "../api.js";
import { Card, Failed, Loading, Tier, axisProps, tooltipStyle, useApi } from "../components.jsx";

// One hue per segment, in the fixed order the palette defines — never cycled,
// and never reassigned when a filter changes the set on screen.
// Segments are separated by position (one panel each), not by hue — five hues
// cannot be told apart reliably on a scatter. The table therefore carries the
// segment number and label as the identity, with no colour swatch to mislead.
export default function Segments() {
  const profiles = useApi(api.segments, []);
  const scatter = useApi(() => api.segmentScatter(2000), []);
  const clock = useApi(api.clock, []);     // the horizon lives in config, not here

  if (profiles.loading) return <Loading what="segments" />;
  if (profiles.error)
    return <Failed error={profiles.error} hint="Has the training job run? Segments are built with each model version." />;

  const segs = profiles.data.segments;
  const totalQueued = segs.reduce((a, s) => a + s.in_queue, 0);
  const totalCalled = segs.reduce((a, s) => a + s.called, 0);
  const best = [...segs].sort((a, b) => b.conversion - a.conversion)[0];
  const mostCalled = [...segs].sort((a, b) => b.called - a.called)[0];

  const pts = scatter.data?.points ?? [];
  const bounds = pts.length ? {
    x: [Math.min(...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.x))],
    y: [Math.min(...pts.map((p) => p.y)), Math.max(...pts.map((p) => p.y))],
  } : { x: [-1, 1], y: [-1, 1] };

  return (
    <>

      <div className="kpis">
        <div className="kpi">
          <span className="eyebrow">Segments</span>
          <div className="v num">{segs.length}</div>
          <div className="d">chosen by silhouette</div>
        </div>
        <div className="kpi">
          <span className="eyebrow">In the queue</span>
          <div className="v num">{num(totalQueued)}</div>
          <div className="d">within the {clock.data?.horizon_hours ?? 24}h horizon</div>
        </div>
        <div className="kpi">
          <span className="eyebrow">We would call</span>
          <div className="v num" style={{ color: "var(--blue)" }}>{num(totalCalled)}</div>
          <div className="d">tiers P1 and P2</div>
        </div>
        <div className="kpi">
          <span className="eyebrow">Best converting</span>
          <div className="v num" style={{ fontSize: 17 }}>segment {best.segment}</div>
          <div className="d">{pct(best.conversion, 2)} · {best.label}</div>
        </div>
      </div>

      <Card
        eyebrow="Two dimensions"
        title="Where each segment sits — one panel each, since five hues cannot be told apart on a scatter"
        note={`Ringed dots are the leads we would dial.${
          scatter.data ? ` All ${num(scatter.data.queued)} queued leads, plus ${num(scatter.data.background)} faint for context.` : ""}`}
      >
        {scatter.loading ? <Loading what="projection" /> :
         scatter.error ? <Failed error={scatter.error} /> : (
          <div className="facets">
            {segs.map((seg) => {
              const mine = pts.filter((p) => p.segment === seg.segment);
              const dial = mine.filter((p) => p.priority_tier === "P1" || p.priority_tier === "P2");
              return (
                <figure key={seg.segment} className="facet">
                  <div className="facet-head">
                    <span className="eyebrow">segment {seg.segment}</span>
                    <span className="num" style={{ fontSize: 11, color: "var(--blue)" }}>
                      {dial.length} to call
                    </span>
                  </div>
                  <div className="facet-label">{seg.label}</div>
                  <ResponsiveContainer width="100%" height={215}>
                    <ScatterChart margin={{ top: 6, right: 8, left: -26, bottom: 0 }}>
                      <CartesianGrid stroke="var(--line)" />
                      <XAxis type="number" dataKey="x" domain={bounds.x} hide />
                      <YAxis type="number" dataKey="y" domain={bounds.y} hide />
                      <ZAxis range={[10, 10]} />
                      <Tooltip
                        {...tooltipStyle}
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const p = payload[0].payload;
                          return (
                            <div style={tooltipStyle.contentStyle}>
                              <div style={{ fontWeight: 600 }}>{p.lead_id}</div>
                              <div style={{ color: "var(--ink-2)" }}>segment {p.segment}</div>
                              {p.priority_tier
                                ? <div>tier <b>{p.priority_tier}</b>{p.score != null &&
                                    <> · {(p.score * 100).toFixed(1)}%</>}</div>
                                : <div style={{ color: "var(--ink-3)" }}>past the queue horizon</div>}
                            </div>
                          );
                        }}
                      />
                      {/* context: the whole population, deliberately recessive */}
                      <Scatter data={pts} fill="var(--line-strong)" fillOpacity={0.34}
                               isAnimationActive={false} />
                      {/* this segment */}
                      <Scatter data={mine} fill="var(--blue)" fillOpacity={0.5}
                               isAnimationActive={false} />
                      {/* the ones we would actually dial */}
                      <Scatter data={dial} fill="var(--blue)" shape="circle"
                               stroke="var(--surface)" strokeWidth={1.5}
                               isAnimationActive={false} />
                    </ScatterChart>
                  </ResponsiveContainer>
                </figure>
              );
            })}
          </div>
        )}
      </Card>

      <div style={{ marginTop: 18 }}>
        <Card
          eyebrow="Who gets the calls"
          title="Conversion is not the same as call priority"
          note="Ordered by conversion. Call share is that segment’s queued leads landing in P1–P2."
        >
          <div className="callout" style={{ marginTop: 14 }}>
            <p>
              Segment <b>{best.segment}</b> converts best at {pct(best.conversion, 2)}, but
              segment <b>{mostCalled.segment}</b> takes the most calls
              ({num(mostCalled.called)} of {num(totalCalled)}). That is the expected-value
              ranking doing its job: {best.label} carries the lowest margin of any group
              ({toman(best.avg_margin)}), so a higher chance of a smaller sale loses to a
              slightly lower chance of a bigger one.
            </p>
          </div>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Segment</th><th>Leads</th><th>Conversion</th><th>Avg margin</th>
                  <th>In queue</th><th>We&rsquo;d call</th><th>Call share</th><th>Queue value</th>
                </tr>
              </thead>
              <tbody>
                {segs.map((s) => (
                  <tr key={s.segment}>
                    <td><b className="num">{s.segment}</b> · {s.label}</td>
                    <td>{num(s.size)}</td>
                    <td>{pct(s.conversion, 2)}</td>
                    <td>{toman(s.avg_margin)}</td>
                    <td>{num(s.in_queue)}</td>
                    <td style={{ color: "var(--blue)", fontWeight: 600 }}>{num(s.called)}</td>
                    <td>{s.in_queue ? pct(s.called / s.in_queue, 0) : "—"}</td>
                    <td>{toman(s.queue_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid g2" style={{ marginTop: 18 }}>
        {segs.map((s) => (
          <Card
            key={s.segment}
            eyebrow={`Segment ${s.segment}`}
            title={s.label}
            note={`${num(s.size)} leads · converts at ${pct(s.conversion, 2)} · ${
              s.in_queue ? `${s.called} of ${s.in_queue} queued leads would be called` :
              "none currently in the queue"}`}
            action={
              <span className="pill">
                {s.in_queue ? pct(s.called / s.in_queue, 0) : "0%"} called
              </span>
            }
          >
            {(s.traits ?? []).length === 0 ? (
              <p className="note">
                Nothing stands out — this group sits near the population average on every
                trait, which is why it is small.
              </p>
            ) : (
              <div className="tablewrap" style={{ marginTop: 4 }}>
                <table>
                  <thead>
                    <tr><th>Trait</th><th>This segment</th><th>All leads</th><th>Gap</th></tr>
                  </thead>
                  <tbody>
                    {s.traits.slice(0, 5).map((t) => (
                      <tr key={t.trait}>
                        <td>{t.trait}</td>
                        <td>{t.value}</td>
                        <td>{t.population}</td>
                        <td style={{ color: t.z > 0 ? "var(--good)" : "var(--bad)" }}>
                          {t.z > 0 ? "+" : ""}{t.z}σ
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}
