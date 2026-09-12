-- ===========================================================================
--  Three-way temporal split: train / validation / test.
--
--  Model choice used to be made on the same holdout that was later quoted as
--  the honest number. That is selection-on-test: with four candidates the bias
--  is small, but it grows silently the moment hyperparameters or thresholds are
--  tuned. The middle window now carries the selection, and the newest window is
--  scored exactly once, after the algorithm is already fixed.
--
--  The existing test_* columns keep their meaning (the untouched final window),
--  so historical rows stay readable; validation is additive.
-- ===========================================================================
SET search_path TO pe, public;

ALTER TABLE model_versions
    ADD COLUMN IF NOT EXISTS valid_rows         INTEGER,
    ADD COLUMN IF NOT EXISTS valid_period_start TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS valid_period_end   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS base_rate_valid    DOUBLE PRECISION,
    -- metrics of the selected algorithm on the validation window, before the
    -- refit on train+validation. Kept apart from `metrics`, which stays the
    -- test-window number that gets quoted.
    ADD COLUMN IF NOT EXISTS selection_metrics  JSONB NOT NULL DEFAULT '{}'::jsonb;
