-- 0005 — Vision scores per property, produced by the vision-scoring-service.
--
-- The vision service scores a listing's photo gallery and returns per-attribute
-- quality scores (condition, kitchen, light, …). We store the latest score per
-- property; feature generation LEFT JOINs these into the training feature set so
-- XGBoost can use physical quality the price/area signals can't capture.
--
-- snapshot_id records which snapshot's gallery was scored (lineage only); the
-- unique key is property_id, so re-scoring upserts in place. Idempotent.

CREATE TABLE IF NOT EXISTS vision_scores (
    id                  BIGSERIAL PRIMARY KEY,
    property_id         BIGINT       NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    snapshot_id         BIGINT       REFERENCES property_snapshots(id) ON DELETE SET NULL,
    model_provider      VARCHAR(50)  NOT NULL,
    model_name          VARCHAR(100) NOT NULL,
    model_version       VARCHAR(50)  NOT NULL,
    overall_condition   NUMERIC(5, 2),
    kitchen_quality     NUMERIC(5, 2),
    bathroom_quality    NUMERIC(5, 2),
    floor_quality       NUMERIC(5, 2),
    natural_light       NUMERIC(5, 2),
    renovation_need     NUMERIC(5, 2),
    interior_modernity  NUMERIC(5, 2),
    photo_quality       NUMERIC(5, 2),
    luxury_level        NUMERIC(5, 2),
    confidence          NUMERIC(5, 2),
    image_count         INTEGER,
    scored_at           TIMESTAMPTZ  NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_vision_scores_property UNIQUE (property_id)
);

CREATE INDEX IF NOT EXISTS idx_vision_scores_property ON vision_scores(property_id);
