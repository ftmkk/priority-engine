-- ===========================================================================
--  Lead segmentation: who the leads are, independent of how they are ranked.
--  Recomputed by the training job so a segmentation always belongs to a model
--  version, and old assignments stay readable after a retrain.
-- ===========================================================================
SET search_path TO pe, public;

CREATE TABLE IF NOT EXISTS segments (
    model_version TEXT    NOT NULL REFERENCES model_versions (version) ON DELETE CASCADE,
    segment       INTEGER NOT NULL,
    label         TEXT    NOT NULL,   -- derived from the traits that stand out
    size          INTEGER NOT NULL,
    centroid      JSONB   NOT NULL DEFAULT '{}'::jsonb,
    traits        JSONB   NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (model_version, segment)
);

CREATE TABLE IF NOT EXISTS lead_segments (
    lead_id       TEXT    NOT NULL,
    model_version TEXT    NOT NULL REFERENCES model_versions (version) ON DELETE CASCADE,
    segment       INTEGER NOT NULL,
    -- 2-D projection used only for display; the clustering happens in the full
    -- feature space, never on these two coordinates
    x             DOUBLE PRECISION,
    y             DOUBLE PRECISION,
    PRIMARY KEY (lead_id, model_version)
);

CREATE INDEX IF NOT EXISTS ix_lead_segments_seg ON lead_segments (model_version, segment);
