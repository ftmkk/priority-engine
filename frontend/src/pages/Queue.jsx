import React, { useEffect, useState } from "react";
import { api, clockLabel, num, pct, toman } from "../api.js";
import { Card, Failed, Loading, Tier, useApi } from "../components.jsx";
import { GlobalImportance, LeadBreakdown, LeadSweep, ModelEquation } from "../leadexplain.jsx";

const PAGE = 20;

export default function Queue() {
  const [tier, setTier] = useState("");
  const [channel, setChannel] = useState("");
  const [product, setProduct] = useState("");
  const [page, setPage] = useState(0);
  const [picked, setPicked] = useState(null);

  const { loading, data, error } = useApi(
    () => api.queue({ tier, channel, product_type: product, limit: PAGE, offset: page * PAGE }),
    [tier, channel, product, page]
  );
  const clock = useApi(api.clock, []);

  // keep a lead selected so the explanation panel is never empty
  useEffect(() => {
    if (data?.items?.length && !data.items.some((i) => i.lead_id === picked))
      setPicked(data.items[0].lead_id);
  }, [data, picked]);

  const onFilter = (set) => (e) => { set(e.target.value); setPage(0); };
  const lead = data?.items?.find((i) => i.lead_id === picked);

  return (
    <>
      <div className="phead">
        <span className="eyebrow">Call queue</span>
        <h1>Who to call, and why</h1>
        <p>
          Ranked by expected value. Click any lead to see how its score was built.
          {clock.data && (
            <>
              {" "}Every lead abandoned within the last {clock.data.horizon_hours} hours is
              scored and tiered; past that the decay has taken even the best of them under
              1%, so they leave the queue.
              {clock.data.pinned && <> Ages are measured from <b>{clockLabel(clock.data.at)}</b>,
                the fixed reference time this deployment reads (<code>priority.current_time</code>).</>}
            </>
          )}
        </p>
      </div>

      <div className="controls">
        <select value={tier} onChange={onFilter(setTier)} aria-label="Priority tier">
          <option value="">All tiers</option>
          <option value="P1">P1 — call now</option>
          <option value="P2">P2 — call today</option>
          <option value="P3">P3 — queue</option>
          <option value="P4">P4 — deprioritize</option>
        </select>
        <select value={channel} onChange={onFilter(setChannel)} aria-label="Channel">
          <option value="">All channels</option>
          {["CRM", "SEO", "Paid", "Referral"].map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={product} onChange={onFilter(setProduct)} aria-label="Product type">
          <option value="">All products</option>
          <option value="thirdparty">thirdparty</option>
          <option value="carbody">carbody</option>
        </select>
        {data && (
          <span className="pill">
            {num(data.total)} leads · {page * PAGE + 1}–{Math.min((page + 1) * PAGE, data.total)}
          </span>
        )}
      </div>

      <div className="master-detail">
        {/* ---- the list ---- */}
        <Card>
          {loading ? <Loading what="queue" /> : error ? (
            <Failed error={error} hint="Has the scoring job run yet?" />
          ) : data.items.length === 0 ? (
            <div className="state">No leads match these filters.</div>
          ) : (
            <>
              <div className="tablewrap">
                <table className="pickable">
                  <thead>
                    <tr>
                      <th>Lead</th><th>Tier</th><th>#</th><th>P(buy)</th>
                      <th>Exp. value</th><th>Product</th><th>Aband.</th><th>Expiry</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((r) => (
                      <tr key={r.lead_id}
                          className={r.lead_id === picked ? "picked" : ""}
                          onClick={() => setPicked(r.lead_id)}
                          tabIndex={0}
                          onKeyDown={(e) => e.key === "Enter" && setPicked(r.lead_id)}>
                        <td>{r.lead_id}</td>
                        <td><Tier tier={r.priority_tier} /></td>
                        <td>{r.priority_rank}</td>
                        <td>{pct(r.decayed_probability, 1)}</td>
                        <td>{toman(r.expected_value)}</td>
                        <td>{r.product_type}</td>
                        <td>{r.minutes_since_abandonment}m</td>
                        <td>{r.days_to_policy_expiry}d</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="controls" style={{ marginTop: 12, marginBottom: 2 }}>
                <button className="btn" disabled={page === 0}
                        onClick={() => setPage((p) => p - 1)}>Previous</button>
                <button className="btn" disabled={(page + 1) * PAGE >= data.total}
                        onClick={() => setPage((p) => p + 1)}>Next</button>
              </div>
            </>
          )}
        </Card>

        {/* ---- why this one ---- */}
        <div className="detail">
          <Card eyebrow="Why this score"
                title={lead ? lead.lead_id : "Pick a lead"}
                note={lead
                  ? `${lead.product_type} · ${lead.channel} · margin ${toman(lead.expected_margin)}`
                  : undefined}>
            <div className="chart"><LeadBreakdown leadId={picked} /></div>
          </Card>
          <Card>
            <LeadSweep leadId={picked} />
          </Card>
        </div>
      </div>

      {/* ---- the model itself, the same for every lead ---- */}
      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card eyebrow="Global" title="What the model relies on"
              note="PR-AUC lost when a column is shuffled. Colour shows direction.">
          <div className="chart"><GlobalImportance /></div>
        </Card>
        <Card eyebrow="Global" title="The equation behind every score"
              note="Standardised weights, so they compare directly.">
          <ModelEquation />
        </Card>
      </div>
    </>
  );
}
