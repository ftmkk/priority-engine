import React, { useState } from "react";
import { api, num, pct } from "../api.js";
import { Card, useApi } from "../components.jsx";
import {
  FeatureRoutingDiagram, PipelineDiagram, RegimeDiagram, SplitDiagram,
} from "../diagrams.jsx";

/* Long enough that reading it top to bottom is a chore, so it is split into
   sections with one mounted at a time. Each keeps the diagram that belongs to it. */

function SecProblem() {
  const { data: m } = useApi(api.model, []);
  return (
    <div className="prose">
          <h2>The problem</h2>
          <p>
            Thousands of leads enter the insurance purchase funnel and most never finish.
            Telesales capacity is finite, so the useful output is not "will this lead buy?"
            but <strong>"who should we call next?"</strong> That makes this a{" "}
            <strong>ranking problem under a capacity constraint</strong>, and it is why the
            headline metrics are precision and lift at realistic call volumes rather than
            accuracy — at a {m ? pct(m.base_rate_test, 1) : "~9%"} base rate, a model that
            predicts "nobody buys" would be over 90% accurate and completely useless.
          </p>

          <h2>Pipeline</h2>
          <ol>
            <li>
              <strong>Ingest.</strong> <code>leads.csv</code> is loaded into Postgres once
              at stack start. Everything downstream reads Postgres, never the CSV.
            </li>
            <li>
              <strong>Deduplicate.</strong> 180 lead IDs appear twice — identical features,
              a few minutes apart in <code>created_at</code>. Those are form re-submissions,
              not distinct leads, so <code>v_leads_curated</code> keeps only the freshest row
              per lead. Skipping this would let one lead sit in both train and holdout.
            </li>
            <li>
              <strong>Train.</strong> Monthly, and once on startup if no model is registered.
            </li>
            <li>
              <strong>Score.</strong> Every 5 minutes, but only for leads whose age has moved
              past what their last score was computed at — see the two regimes below.
            </li>
            <li>
              <strong>Prioritize.</strong> Probability becomes an ordered call list.
            </li>
          </ol>

          <PipelineDiagram />
    </div>
  );
}

function SecFeatures() {
  return (
    <div className="prose">
          <h2>What the model uses</h2>
          <p>Three groups of signal, in descending order of strength:</p>
          <h3>1. Behavioural intent — the strongest signal</h3>
          <ul>
            <li>
              <code>visited_offer_page</code> — 3.5× spread. Reaching the offer page is the
              single most discriminating fact about a lead.
            </li>
            <li>
              <code>offer_views_last_7d</code> — conversion climbs from 5.9% at zero views to
              16.1% at four or more.
            </li>
            <li><code>sessions_last_7d</code>, <code>has_previous_purchase</code>, <code>incoming_call_last_24h</code>.</li>
          </ul>

          <h3>2. Urgency — two clocks pulling in opposite directions</h3>
          <ul>
            <li>
              <code>minutes_since_abandonment</code> — decay. 11.7% under 40 minutes, 6.0%
              past 151. Intent cools fast.
            </li>
            <li>
              <code>days_to_policy_expiry</code> — escalation. 13.1% at a day or less
              (including already-expired) against 6.1% at 25+ days. A looming deadline
              pushes people to buy.
            </li>
          </ul>
          <p>
            These interact rather than simply adding: leads far from expiry cool off faster
            (2.03× decay) than urgent ones (1.59×), so <code>expiry × abandonment</code> is
            an explicit feature.
          </p>

          <h3>3. Offer and context — real but narrow</h3>
          <ul>
            <li><code>discount_percent</code> — monotonic, 8.4% → 10.7%.</li>
            <li>
              <code>price</code> enters only as a <strong>percentile within product type</strong>.
              Raw price looks predictive but is mostly a proxy for the product: carbody's median
              is ~19.6M against thirdparty's ~7.5M, and within each product the effect nearly
              vanishes. Measured head to head, adding the raw column back changes PR-AUC not at
              all — so it stays out.
            </li>
            <li>
              <code>channel</code>, <code>payment_type</code>, <code>insurance_company</code>,{" "}
              <code>device</code>, <code>partner</code> — roughly 8% to 11%. CRM beats Paid;
              BNPL beats cash. Useful, but not decisive.
            </li>
          </ul>

          <h2>What is deliberately excluded</h2>
          <div className="callout">
            <p>
              A column existing in the dataset is not a reason to feed it to the model. Each
              exclusion below is a finding, not an oversight.
            </p>
          </div>
          <ul>
            <li>
              <strong><code>expected_margin</code></strong> — a deterministic function of
              price (a fixed ~2.7% band for thirdparty, ~3.9% for carbody; correlation 0.99).
              As an input it adds collinearity and zero information. Its real role is the{" "}
              <strong>business weight in the ranking</strong>, which is where we use it.
            </li>
            <li>
              <strong><code>price_comparisons_last_7d</code></strong> — looks like a
              purchase-intent feature, but conversion moves only 9.09% → 9.55% across its
              whole range (correlation 0.002). Uninformative.
            </li>
            <li>
              <strong><code>city</code></strong> — 11 levels, 8.1% to 10.6% on small samples,
              no coherent pattern. Dropped rather than spending model capacity on noise.
            </li>
            <li>
              <strong>Hour of day and day of week</strong> — flat within noise (8.0%–10.7%).
            </li>
          </ul>

          <FeatureRoutingDiagram />
    </div>
  );
}

function SecQuality() {
  return (
    <div className="prose">
          <h2>Data quality decisions</h2>
          <ul>
            <li>
              <strong>Missing values (all under 2%).</strong> No rows are dropped — such rows
              arrive in production too. <code>price</code> and <code>discount_percent</code>{" "}
              are imputed with the median <em>within product type</em> (a global median would
              distort both products), and a missing-flag is kept because the missingness
              itself carries signal: <code>price</code> is absent 3.5% of the time on the
              Referral channel against ~1.5% elsewhere.
            </li>
            <li>
              <strong>Negative <code>days_to_policy_expiry</code> (14% of rows).</strong> Not
              an error — the policy already lapsed. It is also the highest-converting group,
              so the values are kept unclipped and the sign is exposed as{" "}
              <code>is_expired</code>.
            </li>
            <li>
              <strong>The 21% offer-page "contradiction."</strong>{" "}
              <code>visited_offer_page</code> and <code>offer_views_last_7d</code> disagree on
              about a fifth of rows. That is two different time windows — one is the current
              session, the other a 7-day rolling count — not a bug. Neither is "corrected".
            </li>
          </ul>
    </div>
  );
}

function SecValidation() {
  const { data: m } = useApi(api.model, []);
  return (
    <div className="prose">
          <h2>Validation</h2>
          <div className="callout">
            <p>
              <strong>The split is by time, never random.</strong> Conversion holds near 9.5%
              for four months and then falls to 7.4%, staying there for several consecutive
              weeks. A random split would let the model learn from the future and report a
              flattering score it could never reproduce in production.
            </p>
          </div>
          {m && (
            <dl className="kv">
              <dt>Train</dt>
              <dd>
                {num(m.train_rows)} rows · base rate {pct(m.base_rate_train, 2)}
              </dd>
              <dt>Held out</dt>
              <dd>
                {num(m.test_rows)} rows · base rate {pct(m.base_rate_test, 2)}
              </dd>
              <dt>Selected</dt>
              <dd>{m.algorithm}</dd>
              <dt>PR-AUC / ROC-AUC</dt>
              <dd>
                {m.metrics.pr_auc.toFixed(4)} / {m.metrics.roc_auc.toFixed(4)}
              </dd>
            </dl>
          )}
          <SplitDiagram />

          <p>
            Labels younger than the 7-day attribution window are excluded from training. An
            outcome is not known the moment a lead is created, and counting still-open leads
            as non-buyers would teach the model that recent leads never convert.
          </p>

          <h2>Model choice</h2>
          <p>
            Gradient boosting and logistic regression are both trained on every run and
            scored on the same holdout; the better PR-AUC is registered active. They are also
            compared against two baselines — random ordering, and a hand-written rule
            (reached the offer page + returning customer + expiry within a week + abandoned
            under an hour ago) which on its own isolates a segment converting at 25%. A model
            that cannot beat that rule is not worth operating.
          </p>
          <p>
            The 1:9.9 class imbalance is handled with <code>class_weight="balanced"</code>{" "}
            rather than resampling. That helps ranking but inflates the raw scores, so the
            winner is wrapped in isotonic calibration — which fixes the level without
            touching the order. This matters because the ranking multiplies probability by
            margin, and that product is only meaningful if the probability is real.
          </p>
    </div>
  );
}

function SecRanking() {
  return (
    <div className="prose">
          <h2>From probability to a call list</h2>
          <p>
            A lead's stored features never change, so re-running the model over the same rows
            returns identical numbers. What does change is the lead's <strong>age</strong>, and
            that splits the work at the edge of the model's evidence:
          </p>
          <ol>
            <li>
              <strong>Inside the fitted support</strong> (total abandonment age ≤ 360 minutes).
              The model was trained on these ages, so we ask it rather than approximate: the
              scoring job advances the lead's clock features — abandonment age up, days-to-expiry
              down — and re-infers. This window is finite per lead, so the work winds itself down.
            </li>
            <li>
              <strong>Past the boundary.</strong> The model has no evidence out there. Its last
              score inside the window becomes an anchor, and the queue decays it at ×0.778/hour
              in SQL <em>when the queue is read</em> — so the ranking stays live without running
              the model again. The two regimes join continuously at 360 minutes.
            </li>
          </ol>
          <RegimeDiagram />

          <div className="callout">
            <p>
              The decay applies only to time <strong>past the boundary</strong>, never the total
              age. The model already priced the abandonment age it was handed; decaying that
              again would penalise the same fact twice — which is a real bug we found and fixed,
              and it was moving 16% of the top of the queue.
            </p>
          </div>
          <p>
            Final rank is <code>decayed_probability × expected_margin</code>: margin differs
            ~1.5× across products, so ranking on probability alone leaves money on the table.
            Tiers (P1–P4) are percentile cuts on expected value.
          </p>
          <p>
            Leads past the queue horizon leave the list entirely rather than sitting at the
            bottom of it. Extrapolating the decay over months is not something a
            cross-sectional fit can carry — and it underflows.
          </p>
    </div>
  );
}

function SecInterpret() {
  return (
    <div className="prose">
          <h2>Interpretation</h2>
          <p>
            Whichever algorithm the run selects gets interpreted, because both methods are
            model-agnostic: <strong>permutation importance</strong> on the holdout for what the
            model relies on globally, and <strong>one-feature ablation</strong> for how a
            particular lead's score was arrived at. The <em>Why this score</em> page renders the
            second as a waterfall from the average lead to the one you pick, with every step
            labelled — plus a live what-if curve that sweeps a single feature and leaves
            everything else fixed.
          </p>
          <div className="callout">
            <p>
              These are not Shapley values, and the page says so. One-at-a-time ablation cannot
              see interactions, and the calibration layer is monotone but not linear, so the
              parts do not sum to the whole. The gap is shown as an explicit{" "}
              <code>residual</code> bar rather than smeared across the other features.
            </p>
          </div>
          <p>
            It paid for itself straight away: the breakdown showed raw <code>price</code> carrying
            a large contribution, which contradicted the decision above to use only the
            within-product percentile. Head to head the raw column changed PR-AUC not at all, so
            it came out — and the code now matches what this page claims.
          </p>

          <h2>Limits — what this cannot tell you</h2>
          <div className="callout">
            <p>
              <strong>This ranks propensity, not uplift.</strong> There is no
              outbound-call variable in the data — <code>incoming_call_last_24h</code> is
              inbound, a symptom of intent rather than our treatment. So the model answers
              "who is most likely to buy", not "who buys <em>because</em> we called".
              Separating those requires randomly holding back calls and measuring the
              difference. That is the single highest-value next step.
            </p>
          </div>
          <ul>
            <li>
              <strong>The decay constant is an upper bound.</strong> There is exactly one
              snapshot per lead, so within-lead cooling cannot be separated from survivor
              composition — leads still open at five hours are systematically less eager to
              begin with. The measured ×0.778/hour mixes both effects. This is also why we
              only use it past the boundary: inside the support we ask the model instead, and
              measured against that the closed-form decay is off by 0.6 percentage points on
              average (Spearman 0.97).
            </li>
            <li>
              <strong>Probabilities will drift.</strong> Trained on a 9.5% period and scoring
              a 7.4% one, the model over-predicts in level even when the ranking stays sound.
              Score distribution and base rate are recorded on every scoring run for exactly
              this reason, and recalibration is expected.
            </li>
            <li>
              <strong>ROC-AUC near 0.70 is the honest ceiling here.</strong> No feature shows
              an implausible lift, which is a good sign: there is no leakage, the target is
              genuinely hard, and the model's job is to accumulate weak signals rather than
              exploit one strong one.
            </li>
          </ul>
    </div>
  );
}

const SECTIONS = [
  { id: "problem", label: "Problem & pipeline", Body: SecProblem },
  { id: "features", label: "Features", Body: SecFeatures },
  { id: "quality", label: "Data quality", Body: SecQuality },
  { id: "validation", label: "Validation & model", Body: SecValidation },
  { id: "ranking", label: "Ranking", Body: SecRanking },
  { id: "interpret", label: "Interpretation & limits", Body: SecInterpret },
];

export default function About() {
  const [active, setActive] = useState(SECTIONS[0].id);
  const current = SECTIONS.find((s) => s.id === active) ?? SECTIONS[0];

  return (
    <>
      <div className="phead">
        <span className="eyebrow">How it works</span>
        <h1>The algorithm, and the decisions behind it</h1>
        <p>
          What the model uses, what it deliberately ignores, how it is validated, and
          what it cannot tell you. Every number comes from the dataset in Postgres.
        </p>
      </div>

      <div className="tabs" role="tablist" aria-label="Sections">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            role="tab"
            aria-selected={s.id === active}
            className={s.id === active ? "tab on" : "tab"}
            onClick={() => setActive(s.id)}
          >
            {s.label}
          </button>
        ))}
      </div>

      <Card>
        <current.Body />
      </Card>
    </>
  );
}
