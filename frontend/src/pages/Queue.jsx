import React, { useState } from "react";
import { api, num, pct, toman } from "../api.js";
import { Card, Failed, Loading, Tier, useApi } from "../components.jsx";

const PAGE = 50;

export default function Queue() {
  const [tier, setTier] = useState("");
  const [channel, setChannel] = useState("");
  const [product, setProduct] = useState("");
  const [page, setPage] = useState(0);

  const { loading, data, error } = useApi(
    () => api.queue({ tier, channel, product_type: product, limit: PAGE, offset: page * PAGE }),
    [tier, channel, product, page]
  );

  const onFilter = (setter) => (e) => {
    setter(e.target.value);
    setPage(0);
  };

  return (
    <>
      <div className="phead">
        <span className="eyebrow">Call queue</span>
        <h1>Who to call, in order</h1>
        <p>
          Ranked by expected value — calibrated probability × expected margin, after the
          abandonment-age decay. Written by the prediction job, read straight from Postgres.
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
          {["CRM", "SEO", "Paid", "Referral"].map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select value={product} onChange={onFilter(setProduct)} aria-label="Product type">
          <option value="">All products</option>
          <option value="thirdparty">thirdparty</option>
          <option value="carbody">carbody</option>
        </select>
        {data && (
          <span className="pill">
            {num(data.total)} leads · showing {page * PAGE + 1}–
            {Math.min((page + 1) * PAGE, data.total)}
          </span>
        )}
      </div>

      <Card>
        {loading ? <Loading what="queue" /> : error ? (
          <Failed error={error} hint="Has the prediction job run yet?" />
        ) : data.items.length === 0 ? (
          <div className="state">No leads match these filters.</div>
        ) : (
          <>
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>Lead</th><th>Tier</th><th>Rank</th><th>P(buy)</th><th>Decayed</th>
                    <th>Exp. value</th><th>Margin</th><th>Product</th><th>Channel</th>
                    <th>Aband.</th><th>To expiry</th><th>Views 7d</th><th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={r.lead_id}>
                      <td>{r.lead_id}</td>
                      <td><Tier tier={r.priority_tier} /></td>
                      <td>{r.priority_rank}</td>
                      <td>{pct(r.probability, 1)}</td>
                      <td>{pct(r.decayed_probability, 1)}</td>
                      <td>{toman(r.expected_value)}</td>
                      <td>{toman(r.expected_margin)}</td>
                      <td>{r.product_type}</td>
                      <td>{r.channel}</td>
                      <td>{r.minutes_since_abandonment}m</td>
                      <td>{r.days_to_policy_expiry}d</td>
                      <td>{r.offer_views_last_7d}</td>
                      <td>{r.completed_purchase === 1 ? "bought" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="controls" style={{ marginTop: 14, marginBottom: 4 }}>
              <button className="btn" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <button
                className="btn"
                disabled={(page + 1) * PAGE >= data.total}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
