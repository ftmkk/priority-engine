# Lead Priority Engine

Scores abandoned insurance leads and turns them into an ordered call list for a
telesales floor with limited capacity.

Postgres + FastAPI + scikit-learn + React, all under `docker compose`.

---

## Run it

You need Docker. Nothing else.

**1. Put the dataset in `data/`.** It is not committed — the repository carries the
code, not the data — so copy both files in before starting:

```bash
cp /path/to/leads.csv data/leads.csv
cp /path/to/data_dictionary.csv data/data_dictionary.csv
```

`data/leads.csv` is the only one the pipeline needs; the dictionary is there for
reference. The `bootstrap` container fails fast with a clear error if the file is
missing, so you will know immediately rather than getting an empty dashboard.

**2. Start the stack.**

```bash
cp .env.example .env
docker compose up --build
```

That brings up five things in order:

| | What happens |
|---|---|
| `postgres` | schema created from `db/migrations/001_init.sql` |
| `bootstrap` | loads `data/leads.csv` into Postgres, then exits |
| `worker` | trains a model (no model exists yet), scores, generates charts, then schedules |
| `api` | FastAPI on **http://localhost:8001** (`/docs` for the OpenAPI UI) |
| `frontend` | admin panel on **http://localhost:8080** |

First boot takes ~2 minutes, most of it installing dependencies into the image.

> Host ports are `API_PORT_HOST` (8001), `PANEL_PORT_HOST` (8080) and
> `POSTGRES_PORT_HOST` (5433) in `.env` — change them if they clash.

### The panel

Four sections. Everything read-only sits under **Dashboard** as a tab, since the
model, segment and monitoring views are all dashboards over the same data.

- **Dashboard** — four tabs, each with its own URL:
  - *Overview* (`/dashboard`) — conversion patterns, the live queue, the drift that
    forces a temporal split
  - *Model* (`/dashboard/model`) — holdout metrics, gains curve, precision@k, the
    candidates it beat, job history
  - *Segments* (`/dashboard/segments`) — k-means groups faceted in two dimensions,
    with the leads we would actually dial highlighted inside each group
  - *Monitoring* (`/dashboard/monitoring`) — calibration, score distribution, decay
    impact, drift across runs
- **Call queue** — who to call, in order, filterable by tier / channel / product
- **Why this score** — per-lead waterfall, a live what-if curve, global permutation
  importance, and the literal equation when a linear model won
- **How it works** — the case in seven slides: the problem, what a lead record really is,
  the drift that decides the split, the result, how a score stays current, why any single
  lead scored what it did, and what the thing will not tell you. One claim per slide with
  a live chart behind it; the measurements themselves stay in `notebooks/`. Tabs to jump,
  arrow keys or Next to step through.

Every figure in the dashboard is generated from Postgres at request time rather than
loaded from disk, which keeps them reproducible in the sense the brief asks for —
code-generated, never hand-made — while staying interactive and never going stale. The
static counterparts the brief asks for live under `charts/`: the notebook series writes
each figure there as a PNG on execution, so the same evidence exists in both a live and a
fileable form, from one code path and never by hand.

## Individual commands

```bash
docker compose run --rm cli load-data        # CSV -> Postgres  (--force to reload)
docker compose run --rm cli train            # temporal split, train, evaluate, register
docker compose run --rm cli evaluate         # metrics for the active model
docker compose run --rm cli predict          # score recent leads -> pe.predictions
docker compose run --rm cli pipeline         # all of the above, in order
docker compose run --rm tests                # pytest
```

`docker compose run --rm cli --help` lists them all.

## Scheduled jobs

Run by the `worker` container (APScheduler), configured in `config/config.yaml`:

| Job | Schedule | What it does |
|---|---|---|
| training | `0 3 1 * *` — monthly, plus at startup if no model is registered | retrain, evaluate on the held-out tail, register the winner as active |
| prediction | `*/5 * * * *` — every 5 minutes | walk leads through the model's support window (see below) |

Every run is recorded in `pe.job_runs` (status, trigger, duration, rows, error) and
is visible on the Model page.

## Layout

```
config/config.yaml           all tunables; every value overridable by PE_* env var
db/migrations/001_init.sql   schema, applied at container start
src/priority_engine/
  config.py      load yaml + env overrides
  db.py          engine, migrations, the two queries the pipeline needs
  ingest.py      CSV -> Postgres
  features.py    feature building + the sklearn pipeline
  metrics.py     PR-AUC, precision@k, lift@k, gains curve, reliability curve
  interpret.py   permutation importance, per-lead attribution, response curves
  segments.py    k-means segmentation + PCA projection for the panel
  train.py       temporal split, train every candidate, calibrate, register
  predict.py     score, decay, expected value, tiers -> Postgres
  scheduler.py   the two cron jobs
  api.py         FastAPI endpoints
  cli.py         the commands above
frontend/src/    React panel (Recharts)
tests/           pytest
```

Twelve backend modules, one job each. `db.py` is the only place that talks SQL;
`features.py` is the only place that defines a feature, and both training and
prediction call the same `build()` so they cannot drift apart.

## Database

Everything after ingestion reads Postgres, never the CSV.

- **`leads`** — raw ingested rows. `lead_id` is *not* the primary key: 180 ids
  legitimately appear twice (identical features, `created_at` minutes apart —
  form re-submissions), so ingestion stays lossless.
- **`v_leads_curated`** — the freshest row per `lead_id`. Every consumer reads
  this. Without it one lead could land in both train and holdout.
- **`model_versions`** — one row per training run: `metrics` (holdout),
  `selection_metrics` (validation window), hyperparams, feature spec, candidate
  comparison — each candidate row records which window it was scored on —
  artifact path, `is_active` (unique partial index, so at most one).
- **`predictions`** — append-only scoring output: lead, probability, score,
  expected value, tier, rank, `predicted_at`, `model_version`. Everything the
  brief asks for, and history is kept so any past score is reproducible.
- **`v_current_priority`** — newest prediction per lead joined to lead context.
  This is the call list the panel reads.
- **`job_runs`**, **`monitoring_snapshots`** — job history and score-distribution
  drift tracking.

## Approach

Full reasoning is on the panel's **How it works** page. In short:

**It's a ranking problem, not a classification problem.** Capacity is finite, so
the metric is precision/lift at realistic call volumes. At a 7.4% base rate,
predicting "nobody buys" is >92% accurate and worthless.

**The split is temporal and three-way, never random.** Conversion sits near 9.5%
for four months then drops to 7.4% and stays there. A random split lets the model see the
future and report a score it can't reproduce. The inputs do not move with it —
every column's PSI stays inside its own sampling-noise floor and a classifier
cannot tell the two periods apart (AUC 0.499) — so what changed is the
conversion rate inside an unchanged population, not the population.

**Three columns are deliberately excluded.** `expected_margin` is a deterministic
function of price (corr 0.99) — it's the *business weight* in ranking, not an
input. `price_comparisons_last_7d` moves conversion 9.09% → 9.55% (corr 0.002).
`city` has 11 levels and no coherent signal.

**Four model families were compared; one is in production.** Logistic
regression, gradient boosting (`HistGradientBoosting`), a random forest and
extra trees, against a random ordering and a hand-written rule. The comparison
lives in `notebooks/03_model_selection.ipynb`, and **the linear model wins it by
~8%** — 0.205 PR-AUC on the validation window against 0.190 for the best tree.
Not a tuning artefact either: a 20-point sweep over leaf size and feature
sampling left the whole bagged-tree family between 0.18 and 0.19.

That follows from the EDA rather than from luck. The strongest pairwise
association in the data is 0.25 and the strongest separation from the target is
0.22, so there are no deep interactions for an ensemble to find — and the two
that do matter (`is_expired`, `expiry_x_abandonment`) are handed to every
candidate as engineered features.

So `train.candidates` holds **`[logreg]`**: the scheduled job fits the winner and
nothing else, because training three models to discard them on every run is cost
without an answer. Re-open the field in the notebook when the data changes, and
move the config if the answer moves. Names resolve through `features.MODELS`,
and an unknown one fails loudly rather than falling back to a default.

**Selection and reporting use different windows.** Each configured candidate is fitted on
the training period and scored on a **validation window**
(`train.validation_days`, the 28 days before the holdout). Best PR-AUC there is
registered active; a model that can't beat the rule isn't worth running. The
winner is then refitted on train + validation and the **holdout**
(`train.holdout_days`, the newest 28 days) is scored exactly once — that is the
number quoted anywhere. Choosing on the window you then quote is
selection-on-test: the bias is small with a handful of candidates and no tuning,
but it is the structure that leaks, not the count.

**Ranking is expected value, not probability.** `decayed_probability × expected_margin`.
Margin differs ~1.5× across products.

**Scoring is split at the edge of the model's evidence.** A lead's stored
features never change, so a blanket rescore returns identical numbers. What
changes is the lead's *age*, and that has two regimes:

- **Inside the fitted support** (total abandonment age ≤ 360 min): the model is
  valid at these ages, so the scoring job advances the lead's clock features and
  **re-infers**. Exact, no approximation. The window is finite per lead, so the
  work winds itself down — currently 52 of 642 queued leads sit here.
- **Past the boundary**: the model has no evidence out there. The last score
  inside the window becomes an anchor, and `v_current_priority` decays it in SQL
  at ×0.778/hour when the queue is *read* — so the ranking stays live without
  running the model. The two regimes join continuously at 360 minutes.

Two consequences worth stating: the decay applies **only to the time past the
boundary**, never the total age — the model already priced the age it was given,
and decaying that again would penalise the same fact twice. And leads past
`queue_horizon_hours` leave the queue entirely rather than decaying toward zero
at the bottom of it; extrapolating the constant over months is not something a
cross-sectional fit can carry (it also underflows).

The horizon is **24 hours**, and it is measured rather than picked. Carrying the
anchor scores forward at ×0.778/hour: by 19.5 hours of total age the single best
lead still in the queue is under 1% — below a tenth of the 9.2% base rate — and
by 24 hours the whole queue is under 0.5%. Every lead inside the window is
scored and tiered; the stretch from there to the 48 hours this used to run on
held nothing but dead rows occupying a ranked list. Notebook 04 section 5 shows
the curve.

### Interpretation

Whichever algorithm the run selects gets interpreted — the methods are
model-agnostic on purpose, so a tree model would lose nothing but the equation:

- **Globally**, permutation importance on the holdout (descriptive only — it is
  computed after the algorithm is already fixed, so it cannot feed selection), scored in PR-AUC: shuffling
  a column costs the model exactly this much ranking ability. `has_previous_purchase`
  (0.028) and `visited_offer_page` (0.027) dominate, then `offer_views_last_7d` and
  `incoming_call_last_24h` at about a third of that.
- **Per lead**, one-feature ablation: set a feature to the population reference,
  re-score, and the shift in log-odds is what that lead's own value contributes.
  The panel renders it as a waterfall from the average lead to this one, with every
  step labelled, so the arithmetic is readable rather than asserted.
- **What-if**, the model's response curve for one lead along one feature, holding
  the rest fixed. Sweeping `minutes_since_abandonment` on a real lead traces
  0.151 → 0.057 across the range — the model's own decay, straight out of the model
  rather than from the fitted constant.

The attribution is deliberately **not** presented as a Shapley value. One-at-a-time
ablation cannot capture interactions, and the isotonic calibration layer is monotone
but not linear, so the parts do not sum to the whole. The gap is reported as a
`residual` term in the waterfall instead of being quietly distributed.

This layer immediately earned itself: it showed raw `price` carrying a large
contribution, which contradicted the documented decision to use only the
within-product percentile. Measured head to head, the raw column changed PR-AUC not
at all (0.1569 either way), so it was removed and the code now matches the design.

### Segmentation

Ranking says who to call first; it says nothing about *what kind* of lead that is.
k-means over the same feature space the model uses, with k chosen by silhouette
(k=5 at 0.125 — low, which is what mixed tabular data looks like) recomputed with
each model version, gives five readable groups:

| Segment | Leads | Converts | Avg margin | Of its queued leads, we'd call |
|---|---|---|---|---|
| policy already expired | 6,991 | 13.2% | 281K | 17% |
| reached the offer page | 23,744 | 12.1% | 338K | 30% |
| average across the board | 928 | 9.6% | 351K | 19% |
| stale + far from expiry | 7,010 | 5.1% | 408K | 11% |
| never saw an offer | 11,327 | 3.1% | 400K | 8% |

The interesting row is the first one. It converts best of any group, yet takes far
fewer calls than the offer-page group — because it also carries the *lowest* margin.
That is the expected-value ranking working as intended: a better chance at a smaller
sale loses to a slightly worse chance at a bigger one. Ranking on probability alone
would invert those two.

The panel facets this into one small chart per segment rather than five colours on
one scatter. That is not a stylistic choice: five hues cannot be told apart reliably
on a scatter (the worst pair here measures ΔE 12.9 against a floor of 15, and
secondary encoding does not excuse that), so the groups are separated by position
and each panel uses a single hue.

### Current results (August held out)

| | |
|---|---|
| Selected | logistic regression (PR-AUC 0.157 vs GBDT 0.151) |
| ROC-AUC | 0.701 |
| Brier | 0.067 — after isotonic calibration, from 0.221 |
| Baselines | rule-based 0.112, random 0.080 |
| Precision @250 | 24.4% against a 7.38% base rate — **3.31× lift** |
| @1000 | 18.4% precision, 26.6% recall, 2.49× lift |

ROC-AUC ~0.70 is the honest ceiling here. No feature shows an implausible lift,
which is the good news: there's no leakage, and the model's job is to accumulate
weak signals rather than exploit one strong one.

## Data assumptions

The task statement doesn't say what creates a `lead` row, and several columns
disagree with each other about it. Asking upstream got no answer, so the whole
pipeline runs on one stated assumption, chosen because it's the only reading
that survives every piece of evidence in the data. The evidence is worked
through in `notebooks/02_record_generation.ipynb`, which ends in the same
decisions listed here:

**A lead row is a snapshot of a priced quote, written by a scheduled job — not
an event. And the funnel has two exits, not one.**

`price` is present for ~98% of leads whether or not they reached the offer page
(1.88% null vs 1.84%), so the quote is computed server-side, independently of
the user seeing it. `created_at` doesn't behave like an event time — seconds are
always `00`, the hour-of-day distribution is flat (CV 2.7%, which real traffic
never is), and it correlates with nothing. And both buyers and non-buyers have
rows, which rules out any trigger tied to the purchase itself.

The two exits matter because 517 leads completed a purchase with
`visited_offer_page = 0`. They aren't noise — they have a signature. Among
non-visitors, conversion is 2.6% with neither a prior purchase nor an inbound
call, 4.8% with a prior purchase, 4.2% with a call, and **8.6% with both** —
approaching the 11.8% self-serve rate. Read as two paths to the same quote:

- **Self-serve** — the user reaches the offer listing and buys on the web.
  `visited_offer_page = 1`, 11.8% conversion.
- **Assisted or renewal** — the quote is reachable without the listing page, via
  a renewal link to an existing customer or an agent closing it on an inbound
  call. `visited_offer_page = 0`, 3.3% overall.

So `visited_offer_page` is a **web-funnel depth marker, not a precondition for
buying**. It's the model's strongest single feature (permutation importance
0.027), but a `0` means "this lead's path runs through a channel the dataset
can't see", not "cold lead".

Relatedly, `offer_views_last_7d` is **prior** history that excludes the current
journey: 2,896 leads have `visited_offer_page = 1` and `offer_views_last_7d = 0`,
which is impossible on any shared scope. The two are not redundant and shouldn't
be collapsed.

Everything else follows from that one choice:

- **`minutes_since_abandonment`** is the gap from the user's last action to the
  snapshot, **right-censored at 360**. Minute 360 holds 146 rows against ~4.7
  per minute over 330–359 — a 31× spike, i.e. a clip, not a boundary of the
  natural range. So anything past six hours is recorded as exactly six hours,
  and the model has no evidence out there. This is what `queue_horizon_hours`
  and the decay boundary are built around. Inside the six hours the column is
  worth keeping as a feature: conversion runs 11.3% in the first hour down to
  4.9% in the sixth, and controlling for every other column barely moves it
  (0.778× → 0.770× odds per hour) — which is also where `decay_per_hour` comes
  from. The 180 duplicated `lead_id`s pin down what it *doesn't* do: the pairs
  differ only in `created_at`, 1–14 minutes apart, and the age column is
  identical across that gap. It is fixed at capture and copied onto each write,
  so at inference a lead's age is `minutes_since_abandonment + (now −
  created_at)`, capped at the boundary — and the file never observes one lead at
  two ages, which is why the decay is an upper bound rather than a measurement.
- **`days_since_last_visit`** is read off a different clock than the rest. Every
  row has `sessions_last_7d ≥ 1`, yet 36% have `days_since_last_visit > 7` — and
  that share barely moves (29%) even for users with 8 sessions in the last seven
  days, where a shared clock would force it to zero. The two are measured
  against different reference times, so we read this column as *profile
  staleness* (age of the CRM profile record) rather than "last visit", and never
  combine it arithmetically with the session counts. Consistent with that, the
  "never visited before" case isn't encoded at all: no nulls, no negative
  sentinel, no pile-up at 60.
- **`completed_purchase`** is backfilled, with a **7-day attribution window**.
  Since non-buyers have rows too, the label can't be known at snapshot time. The
  window length decides how much recent data carries a trustworthy label — open
  leads inside it would read as "didn't buy". The newest 28 days are already the
  holdout (`train.holdout_days`), so the affected rows never reach training; the
  cost is that holdout metrics are mildly pessimistic on the last week of it. If
  the real window is longer than 28 days, the training period itself needs
  trimming.

The task says the data is synthetic, and the evidence above (flat hours, two
incompatible clocks, a clipped ceiling) is consistent with each column being
drawn independently. So there may be no "true" answer to the trigger question.
The assumption is still worth stating explicitly, because every downstream
decision — the support boundary, the decay, the training cutoff — rests on it,
and each one is a one-line change if the assumption turns out wrong.

## Limits

- **This ranks propensity, not uplift.** There is no outbound-call column in the
  data (`incoming_call_last_24h` is *inbound* — a symptom of intent, not our
  treatment). So it answers "who is most likely to buy", not "who buys *because*
  we called". Separating those needs a randomized call holdout. Highest-value
  next step.
- **The time decay is an upper bound.** One snapshot per lead means within-lead
  cooling can't be separated from survivor composition.
- **Probabilities will drift.** Trained on a 9.5% period, scoring a 7.4% one.
  Score distribution is recorded on every run; recalibration is expected. The
  *ranking* holds up better than the levels: across the break every bin's lift
  over its own base rate is preserved to within sampling error.
- **The dataset is a static 5-month snapshot.** With `priority.current_time:
  dataset` the reference "now" is the newest `created_at`, which is what makes
  the queue and the decay meaningful at all. The dashboard says so in the header
  rather than letting a frozen clock read as stale data. On live data nothing
  about the mechanism changes, but the 5-minute job would have a steady trickle
  of leads inside the support window instead of a fixed few dozen.
- **The read-time decay is an approximation of the model past the boundary.**
  Measured against re-inferring with the clock advanced: mean gap 0.6 pp,
  Spearman 0.97, 84% overlap in the top 5%. Inside the support we don't
  approximate at all — we ask the model.

## Configuration

`config/config.yaml` holds every tunable. Any value can be overridden by env var
using `PE_<SECTION>__<KEY>`:

```bash
PE_TRAIN__LABEL_MATURITY_DAYS=14
PE_TRAIN__HOLDOUT_DAYS=14
PE_PRIORITY__QUEUE_HORIZON_HOURS=12
PE_PRIORITY__CURRENT_TIME=2026-08-28T23:58:00Z
PE_JOBS__PREDICT_CRON="*/2 * * * *"
```

`priority.current_time` is worth a note, because it decides what "now" means for
the whole queue:

| Value | Reference "now" |
|---|---|
| `dataset` | the newest `created_at` in the data — the default here, because this file is a fixed 5-month export and a real clock would put every lead months past its support |
| an instant, e.g. `2026-08-20T12:00:00Z` | exactly that moment, for replaying a point in time |
| empty / null | the real wall clock — what production runs |

`GET /api/clock` reports the resolved instant and whether it is pinned, and the
dashboard header shows it on every page, so a frozen clock never reads as a
stale screen.

DB credentials come from `POSTGRES_*` only and never live in the YAML.

## Notes

`notebooks/` holds the exploration that produced the decisions above — `01` the EDA,
written as a list of questions each cell answers, then `02` the temporal split, `03` model
selection, `04` the serving decay, `05` interpretation and the uplift limit. See
`notebooks/README.md`. They are not a deliverable — the brief rules that out — and nothing
in the pipeline imports them; the dependency runs the other way, since each notebook reads
`pe.v_leads_curated` from Postgres and imports the pipeline's own `features` / `metrics` /
`interpret` modules, so the numbers come from the code that actually runs.
`panel/index.html` is a standalone interactive EDA page from the same work.
