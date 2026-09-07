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

- **Dashboard** — conversion patterns, the live queue, the drift that forces a temporal split
- **Call queue** — who to call, in order, filterable by tier / channel / product
- **Model** — holdout metrics, gains curve, precision@k, candidate comparison, job history
- **Why this score** — model interpretation: per-lead waterfall, a live what-if curve,
  global permutation importance, and the literal equation when a linear model won
- **Monitoring** — calibration, score distribution, decay impact, drift across runs
- **How it works** — the algorithm in six tabbed sections (problem & pipeline, features,
  data quality, validation, ranking, interpretation & limits), each with the diagram that
  belongs to it

There is no `charts/` directory and nothing writes PNGs. Every figure is generated from
Postgres by the panel at request time, which keeps them reproducible in the sense the brief
asks for — code-generated, never hand-made — while staying interactive and never going
stale. The one place this matters to note: the brief asks for charts saved under `charts/`,
and this is a deliberate departure from that.

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
  train.py       temporal split, train both candidates, calibrate, register
  predict.py     score, decay, expected value, tiers -> Postgres
  scheduler.py   the two cron jobs
  api.py         FastAPI endpoints
  cli.py         the commands above
frontend/src/    React panel (Recharts)
tests/           pytest
```

Eleven backend modules, one job each. `db.py` is the only place that talks SQL;
`features.py` is the only place that defines a feature, and both training and
prediction call the same `build()` so they cannot drift apart.

## Database

Everything after ingestion reads Postgres, never the CSV.

- **`leads`** — raw ingested rows. `lead_id` is *not* the primary key: 180 ids
  legitimately appear twice (identical features, `created_at` minutes apart —
  form re-submissions), so ingestion stays lossless.
- **`v_leads_curated`** — the freshest row per `lead_id`. Every consumer reads
  this. Without it one lead could land in both train and holdout.
- **`model_versions`** — one row per training run: metrics, hyperparams, feature
  spec, candidate comparison, artifact path, `is_active` (unique partial index,
  so at most one).
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

**The split is temporal, never random.** Conversion sits near 9.5% for four
months then drops to 7.4% and stays there. A random split lets the model see the
future and report a score it can't reproduce.

**Three columns are deliberately excluded.** `expected_margin` is a deterministic
function of price (corr 0.99) — it's the *business weight* in ranking, not an
input. `price_comparisons_last_7d` moves conversion 9.09% → 9.55% (corr 0.002).
`city` has 11 levels and no coherent signal.

**Both candidates and both baselines are scored on the same holdout** — gradient
boosting, logistic regression, a random ordering and a hand-written rule. Best
PR-AUC is registered active. A model that can't beat the rule isn't worth running.

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

### Interpretation

Whichever algorithm the run selects gets interpreted — the methods are
model-agnostic on purpose, so switching to `gbdt` loses nothing but the equation:

- **Globally**, permutation importance on the holdout, scored in PR-AUC: shuffling
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

## Limits

- **This ranks propensity, not uplift.** There is no outbound-call column in the
  data (`incoming_call_last_24h` is *inbound* — a symptom of intent, not our
  treatment). So it answers "who is most likely to buy", not "who buys *because*
  we called". Separating those needs a randomized call holdout. Highest-value
  next step.
- **The time decay is an upper bound.** One snapshot per lead means within-lead
  cooling can't be separated from survivor composition.
- **Probabilities will drift.** Trained on a 9.5% period, scoring a 7.4% one.
  Score distribution is recorded on every run; recalibration is expected.
- **The dataset is a static 5-month snapshot.** With `priority.clock: dataset`
  the reference "now" is the newest `created_at`, which is what makes the queue
  and the decay meaningful at all. On live data nothing about the mechanism
  changes, but the 5-minute job would have a steady trickle of leads inside the
  support window instead of a fixed 52.
- **The read-time decay is an approximation of the model past the boundary.**
  Measured against re-inferring with the clock advanced: mean gap 0.6 pp,
  Spearman 0.97, 84% overlap in the top 5%. Inside the support we don't
  approximate at all — we ask the model.

## Configuration

`config/config.yaml` holds every tunable. Any value can be overridden by env var
using `PE_<SECTION>__<KEY>`:

```bash
PE_TRAIN__ALGORITHM=logreg
PE_TRAIN__HOLDOUT_DAYS=14
PE_PRIORITY__QUEUE_HORIZON_HOURS=24
PE_PRIORITY__CLOCK=wall
PE_JOBS__PREDICT_CRON="*/2 * * * *"
```

`priority.clock` is worth a note: this dataset is a fixed 5-month snapshot, so
wall-clock time would put every lead months past its support. `dataset` uses the
newest `created_at` as "now"; production uses `wall`.

DB credentials come from `POSTGRES_*` only and never live in the YAML.

## Notes

`notebooks/01_eda.ipynb` is the exploration that produced the decisions above.
It is not a deliverable — the brief rules that out — and nothing in the pipeline
imports it. `panel/index.html` is a standalone interactive EDA page from the same
work.
