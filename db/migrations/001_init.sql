-- ===========================================================================
--  Lead Priority Engine — initial schema
--  Applied automatically at container start (mounted into the postgres image's
--  /docker-entrypoint-initdb.d) and idempotently re-checked by the app.
-- ===========================================================================

CREATE SCHEMA IF NOT EXISTS pe;
SET search_path TO pe, public;

-- ---------------------------------------------------------------------------
--  leads — the raw ingested dataset, one row per CSV row.
--
--  lead_id is NOT the primary key: 180 ids legitimately appear twice (identical
--  features, created_at a few minutes apart — form re-submissions). We keep
--  both rows so ingestion stays lossless and faithful to the source, and
--  resolve the duplicate downstream in v_leads_curated.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
    id                          BIGSERIAL PRIMARY KEY,
    lead_id                     TEXT        NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL,

    -- lead context (known at creation)
    product_type                TEXT,
    channel                     TEXT,
    device                      TEXT,
    partner                     TEXT,
    city                        TEXT,
    insurance_company           TEXT,
    payment_type                TEXT,

    -- offer economics
    price                       NUMERIC(14,2),
    discount_percent            NUMERIC(6,2),
    expected_margin             NUMERIC(14,2),
    days_to_policy_expiry       INTEGER,

    -- funnel behaviour
    minutes_since_abandonment   INTEGER,
    sessions_last_7d            INTEGER,
    offer_views_last_7d         INTEGER,
    price_comparisons_last_7d   INTEGER,
    days_since_last_visit       NUMERIC(8,2),
    has_previous_purchase       SMALLINT,
    visited_offer_page          SMALLINT,
    incoming_call_last_24h      SMALLINT,

    -- outcome (NULL until the attribution window closes)
    completed_purchase          SMALLINT,

    ingested_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_leads_natural_key UNIQUE (lead_id, created_at)
);

CREATE INDEX IF NOT EXISTS ix_leads_created_at   ON leads (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_leads_lead_id      ON leads (lead_id);
CREATE INDEX IF NOT EXISTS ix_leads_target       ON leads (completed_purchase)
    WHERE completed_purchase IS NOT NULL;

-- Deduplicated view: the freshest snapshot per lead. Every consumer of lead
-- data (training, scoring, charts) reads THIS, never `leads` directly — that
-- is what stops one lead landing in both train and holdout.
CREATE OR REPLACE VIEW v_leads_curated AS
SELECT DISTINCT ON (lead_id) *
FROM leads
ORDER BY lead_id, created_at DESC, id DESC;

-- ---------------------------------------------------------------------------
--  model_versions — the model registry. One row per training run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_versions (
    id                  BIGSERIAL PRIMARY KEY,
    version             TEXT        NOT NULL UNIQUE,   -- e.g. 20260907T031500Z
    algorithm           TEXT        NOT NULL,
    is_active           BOOLEAN     NOT NULL DEFAULT FALSE,
    trained_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    train_rows          INTEGER     NOT NULL,
    test_rows           INTEGER     NOT NULL,
    train_period_start  TIMESTAMPTZ,
    train_period_end    TIMESTAMPTZ,
    test_period_start   TIMESTAMPTZ,
    test_period_end     TIMESTAMPTZ,

    base_rate_train     DOUBLE PRECISION,
    base_rate_test      DOUBLE PRECISION,

    hyperparams         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    feature_spec        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    metrics             JSONB       NOT NULL DEFAULT '{}'::jsonb,
    candidate_results   JSONB       NOT NULL DEFAULT '[]'::jsonb,
    feature_importance  JSONB       NOT NULL DEFAULT '[]'::jsonb,

    artifact_path       TEXT        NOT NULL,
    notes               TEXT
);

-- At most one active model at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_model_versions_one_active
    ON model_versions (is_active) WHERE is_active;

-- ---------------------------------------------------------------------------
--  predictions — the scoring output the sales team consumes.
--
--  Required by the task brief: which lead, the score/probability, the priority,
--  when it was generated, and which model version produced it.
--  History is retained (append-only); v_current_priority exposes the latest.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS predictions (
    id                  BIGSERIAL PRIMARY KEY,
    lead_id             TEXT             NOT NULL,
    model_version       TEXT             NOT NULL REFERENCES model_versions (version),

    -- The raw calibrated model output, as of `predicted_at`. Deliberately NOT
    -- decayed: decay depends on how much time has passed since, so it is applied
    -- when the queue is read (v_current_priority), not frozen in here. Rank and
    -- tier are derived there too, for the same reason.
    probability         DOUBLE PRECISION NOT NULL,   -- calibrated P(purchase)
    score               INTEGER          NOT NULL,   -- probability on a 0-1000 scale
    -- The abandonment age the model was asked about. While a lead is inside the
    -- fitted support this advances on each run; once it reaches the boundary it
    -- stops, and that last row becomes the anchor the read-time decay works from.
    scored_at_age_minutes DOUBLE PRECISION NOT NULL,

    lead_created_at     TIMESTAMPTZ,
    predicted_at        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    batch_id            TEXT             NOT NULL,

    CONSTRAINT ck_predictions_probability CHECK (probability >= 0 AND probability <= 1),
    CONSTRAINT uq_predictions_lead_batch  UNIQUE (lead_id, batch_id)
);

CREATE INDEX IF NOT EXISTS ix_predictions_predicted_at ON predictions (predicted_at DESC);
CREATE INDEX IF NOT EXISTS ix_predictions_lead         ON predictions (lead_id, predicted_at DESC);
CREATE INDEX IF NOT EXISTS ix_predictions_batch        ON predictions (batch_id);

-- Newest raw prediction per lead, joined to lead context. The live call list
-- (v_current_priority) is built on top of this by the application, which folds
-- in the read-time decay using the values from config.yaml.
CREATE OR REPLACE VIEW v_latest_prediction AS
SELECT DISTINCT ON (p.lead_id)
       p.lead_id, p.model_version, p.probability, p.score,
       p.scored_at_age_minutes, p.predicted_at,
       p.batch_id, l.created_at AS lead_created_at,
       l.product_type, l.channel, l.device, l.partner, l.city,
       l.insurance_company, l.payment_type, l.price, l.discount_percent,
       l.expected_margin, l.days_to_policy_expiry, l.minutes_since_abandonment,
       l.sessions_last_7d, l.offer_views_last_7d, l.days_since_last_visit,
       l.has_previous_purchase, l.visited_offer_page, l.incoming_call_last_24h,
       l.completed_purchase
FROM predictions p
JOIN v_leads_curated l USING (lead_id)
ORDER BY p.lead_id, p.predicted_at DESC, p.id DESC;

-- ---------------------------------------------------------------------------
--  job_runs — observability for the scheduled training / prediction jobs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_runs (
    id              BIGSERIAL PRIMARY KEY,
    job_name        TEXT        NOT NULL,
    status          TEXT        NOT NULL,      -- running | success | failed
    trigger         TEXT        NOT NULL,      -- schedule | startup | manual
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    rows_processed  INTEGER,
    detail          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    error           TEXT,
    CONSTRAINT ck_job_runs_status CHECK (status IN ('running','success','failed'))
);

CREATE INDEX IF NOT EXISTS ix_job_runs_name_started ON job_runs (job_name, started_at DESC);

-- ---------------------------------------------------------------------------
--  monitoring_snapshots — drift watch. The August decline in this dataset is
--  proof the base rate is not stationary, so it gets tracked explicitly.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monitoring_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_version       TEXT,
    scored_leads        INTEGER,
    mean_probability    DOUBLE PRECISION,
    p10_probability     DOUBLE PRECISION,
    p90_probability     DOUBLE PRECISION,
    observed_base_rate  DOUBLE PRECISION,
    expected_base_rate  DOUBLE PRECISION,
    detail              JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_monitoring_captured ON monitoring_snapshots (captured_at DESC);
