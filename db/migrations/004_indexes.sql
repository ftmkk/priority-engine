-- ===========================================================================
--  Index tidy-up, from pg_stat_user_indexes after several days of real traffic.
--
--  Three were never scanned once or duplicate another index's leading columns,
--  and every one of them still cost a write on each of the 50k lead inserts and
--  100k prediction inserts. One is added: the dedupe view is read by nearly
--  every query in the app and had no index matching its sort order.
-- ===========================================================================
SET search_path TO pe, public;

-- 0 scans. completed_purchase is a 0/1 column, so the planner reads the table
-- instead -- which is the right call, and the index was never going to be used.
DROP INDEX IF EXISTS ix_leads_target;

-- 0 scans. Nothing orders predictions by time alone; the per-lead index below
-- already covers "the newest score for this lead".
DROP INDEX IF EXISTS ix_predictions_predicted_at;

-- Redundant: uq_leads_natural_key (lead_id, created_at) has lead_id as its
-- leading column, so it answers everything this one did.
DROP INDEX IF EXISTS ix_leads_lead_id;

-- v_leads_curated is DISTINCT ON (lead_id) ORDER BY lead_id, created_at DESC,
-- id DESC -- mixed directions, which the ascending unique key cannot serve even
-- backwards. This matches it exactly.
CREATE INDEX IF NOT EXISTS ix_leads_dedupe ON leads (lead_id, created_at DESC, id DESC);
