-- 0001 — Universal raw-listings refactor + ML pipeline tables.
--
-- Idempotent, additive, and safe on a database that already contains data
-- (existing rows are backfilled, never dropped before being copied).
-- Safe to run after sql/init.sql on a fresh DB (everything no-ops).
--
-- Applied by src/migrate.py inside a single transaction (no BEGIN/COMMIT here).

-- ===========================================================================
-- 1. New tables (created first so later FKs resolve)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id                BIGSERIAL PRIMARY KEY,
    source            VARCHAR(100)  NOT NULL,
    apify_actor_id    TEXT,
    apify_task_id     TEXT,
    apify_run_id      TEXT,
    apify_dataset_id  TEXT,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    status            VARCHAR(50)   NOT NULL,
    item_count        INTEGER,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source ON ingestion_runs(source);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status ON ingestion_runs(status);

CREATE TABLE IF NOT EXISTS feature_sets (
    id           BIGSERIAL PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    version      VARCHAR(50)  NOT NULL,
    target       VARCHAR(100) NOT NULL,
    description  TEXT,
    code_version TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_feature_set UNIQUE (name, version, target)
);

CREATE TABLE IF NOT EXISTS property_features (
    id                    BIGSERIAL PRIMARY KEY,
    property_id           BIGINT       NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    snapshot_id           BIGINT       NOT NULL REFERENCES property_snapshots(id) ON DELETE CASCADE,
    feature_set_id        BIGINT       NOT NULL REFERENCES feature_sets(id),
    snapshot_date         DATE         NOT NULL,
    target_price          BIGINT,
    target_price_per_sqm  NUMERIC(12, 2),
    features_json         JSONB        NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_property_features UNIQUE (snapshot_id, feature_set_id)
);
CREATE INDEX IF NOT EXISTS idx_property_features_set_date
    ON property_features(feature_set_id, snapshot_date);

CREATE TABLE IF NOT EXISTS model_versions (
    id                    BIGSERIAL PRIMARY KEY,
    model_name            VARCHAR(100) NOT NULL,
    version               VARCHAR(50)  NOT NULL,
    target                VARCHAR(100) NOT NULL,
    framework             VARCHAR(100) NOT NULL,
    artifact_path         TEXT         NOT NULL,
    feature_set_id        BIGINT       NOT NULL REFERENCES feature_sets(id),
    training_export_id    BIGINT,      -- FK added after ml_dataset_exports is upgraded
    train_row_count       INTEGER,
    validation_row_count  INTEGER,
    metrics_json          JSONB,
    hyperparameters_json  JSONB,
    trained_at            TIMESTAMPTZ  NOT NULL,
    is_active             BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_model_version UNIQUE (model_name, version)
);
CREATE INDEX IF NOT EXISTS idx_model_versions_target_active ON model_versions(target, is_active);

CREATE TABLE IF NOT EXISTS predictions (
    id                       BIGSERIAL PRIMARY KEY,
    model_version_id         BIGINT        NOT NULL REFERENCES model_versions(id),
    property_id              BIGINT        REFERENCES properties(id),
    request_json             JSONB         NOT NULL,
    features_json            JSONB         NOT NULL,
    predicted_price          BIGINT,
    predicted_price_per_sqm  NUMERIC(12, 2),
    confidence_low           BIGINT,
    confidence_high          BIGINT,
    created_at               TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_predictions_model      ON predictions(model_version_id);
CREATE INDEX IF NOT EXISTS idx_predictions_property   ON predictions(property_id);
CREATE INDEX IF NOT EXISTS idx_predictions_created_at ON predictions(created_at);

-- ===========================================================================
-- 2. raw_listings — add provenance + content hash; enforce source_listing_id
-- ===========================================================================

ALTER TABLE raw_listings ADD COLUMN IF NOT EXISTS ingestion_run_id BIGINT;
ALTER TABLE raw_listings ADD COLUMN IF NOT EXISTS content_hash     VARCHAR(100);

UPDATE raw_listings SET source_listing_id = 'unknown' WHERE source_listing_id IS NULL;
ALTER TABLE raw_listings ALTER COLUMN source_listing_id SET NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'raw_listings_ingestion_run_fk') THEN
        ALTER TABLE raw_listings
            ADD CONSTRAINT raw_listings_ingestion_run_fk
            FOREIGN KEY (ingestion_run_id) REFERENCES ingestion_runs(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_raw_listings_run       ON raw_listings(ingestion_run_id);
CREATE INDEX IF NOT EXISTS idx_raw_listings_source_at ON raw_listings(source, scraped_at);

-- ===========================================================================
-- 3. properties — add deal_type (+ city/district/source_category/currency)
-- ===========================================================================

ALTER TABLE properties ADD COLUMN IF NOT EXISTS deal_type       VARCHAR(50);
ALTER TABLE properties ADD COLUMN IF NOT EXISTS city            TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS district        TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS source_category VARCHAR(100);
ALTER TABLE properties ADD COLUMN IF NOT EXISTS currency        VARCHAR(10);

-- Backfill deal_type from the URL (works for both sources: sreality /prodej/,
-- bezrealitky -prodej-/-pronajem-).
UPDATE properties SET deal_type = CASE
        WHEN url ILIKE '%pronajem%' THEN 'rent'
        WHEN url ILIKE '%prodej%'   THEN 'buy'
        ELSE deal_type
    END
WHERE deal_type IS NULL;

-- Fallback: sreality stores dealType in the raw payload.
UPDATE properties p SET deal_type = CASE
        WHEN lower(r.dt) IN ('rent', 'pronajem')        THEN 'rent'
        WHEN lower(r.dt) IN ('buy', 'sale', 'prodej')   THEN 'buy'
        ELSE p.deal_type
    END
FROM (
    SELECT DISTINCT ON (source, source_listing_id)
        source, source_listing_id, raw_json->>'dealType' AS dt
    FROM raw_listings
    ORDER BY source, source_listing_id, scraped_at DESC
) r
WHERE p.source = r.source
  AND p.source_listing_id = r.source_listing_id
  AND p.deal_type IS NULL;

-- Last resort so the NOT NULL constraint can be applied; corrected on next ingest.
UPDATE properties SET deal_type = 'buy' WHERE deal_type IS NULL;
ALTER TABLE properties ALTER COLUMN deal_type SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_properties_deal_category ON properties(deal_type, category);
CREATE INDEX IF NOT EXISTS idx_properties_district      ON properties(district);

-- ===========================================================================
-- 4. property_snapshots — denormalize source/deal_type/category/locality
-- ===========================================================================

ALTER TABLE property_snapshots ADD COLUMN IF NOT EXISTS source    VARCHAR(100);
ALTER TABLE property_snapshots ADD COLUMN IF NOT EXISTS deal_type VARCHAR(50);
ALTER TABLE property_snapshots ADD COLUMN IF NOT EXISTS category  VARCHAR(100);
ALTER TABLE property_snapshots ADD COLUMN IF NOT EXISTS locality  TEXT;

UPDATE property_snapshots s SET
        source    = COALESCE(s.source,    p.source),
        deal_type = COALESCE(s.deal_type, p.deal_type),
        category  = COALESCE(s.category,  p.category),
        locality  = COALESCE(s.locality,  p.locality)
FROM properties p
WHERE s.property_id = p.id
  AND (s.source IS NULL OR s.deal_type IS NULL);

ALTER TABLE property_snapshots ALTER COLUMN source    SET NOT NULL;
ALTER TABLE property_snapshots ALTER COLUMN deal_type SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_snapshots_deal_cat_loc
    ON property_snapshots(deal_type, category, locality);

-- ===========================================================================
-- 5. market_statistics — deal_type becomes part of the grouping key.
--    Derived table → swap the unique constraint and clear it for regeneration.
-- ===========================================================================

ALTER TABLE market_statistics ADD COLUMN IF NOT EXISTS deal_type VARCHAR(50) NOT NULL DEFAULT '';
ALTER TABLE market_statistics DROP CONSTRAINT IF EXISTS uq_market_stat;
ALTER TABLE market_statistics
    ADD CONSTRAINT uq_market_stat
    UNIQUE (stat_date, source, deal_type, category, locality, layout);
TRUNCATE market_statistics;

-- ===========================================================================
-- 6. ml_dataset_exports — link to a feature_set + target (legacy rows kept)
-- ===========================================================================

ALTER TABLE ml_dataset_exports ADD COLUMN IF NOT EXISTS feature_set_id BIGINT;
ALTER TABLE ml_dataset_exports ADD COLUMN IF NOT EXISTS target         VARCHAR(100);
ALTER TABLE ml_dataset_exports ADD COLUMN IF NOT EXISTS generated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW();

INSERT INTO feature_sets (name, version, target, description)
VALUES ('legacy', 'v0', 'legacy', 'Auto-created in migration 0001 for pre-existing exports')
ON CONFLICT (name, version, target) DO NOTHING;

UPDATE ml_dataset_exports SET
        feature_set_id = COALESCE(feature_set_id,
            (SELECT id FROM feature_sets WHERE name='legacy' AND version='v0' AND target='legacy')),
        target = COALESCE(target, 'legacy')
WHERE feature_set_id IS NULL OR target IS NULL;

ALTER TABLE ml_dataset_exports ALTER COLUMN feature_set_id SET NOT NULL;
ALTER TABLE ml_dataset_exports ALTER COLUMN target         SET NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ml_dataset_exports_feature_set_fk') THEN
        ALTER TABLE ml_dataset_exports
            ADD CONSTRAINT ml_dataset_exports_feature_set_fk
            FOREIGN KEY (feature_set_id) REFERENCES feature_sets(id);
    END IF;
END $$;

-- model_versions.training_export_id FK (deferred from table creation above)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'model_versions_training_export_fk') THEN
        ALTER TABLE model_versions
            ADD CONSTRAINT model_versions_training_export_fk
            FOREIGN KEY (training_export_id) REFERENCES ml_dataset_exports(id);
    END IF;
END $$;

-- ===========================================================================
-- 7. Deprecate source-specific raw tables: copy into raw_listings, then drop.
-- ===========================================================================

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sreality_raw_listings') THEN
        INSERT INTO raw_listings (source, source_listing_id, scraped_at, raw_json)
        SELECT 'sreality', listing_id, scraped_at, raw_json FROM sreality_raw_listings;
        DROP TABLE sreality_raw_listings;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'bezrealitky_raw_listings') THEN
        INSERT INTO raw_listings (source, source_listing_id, scraped_at, raw_json)
        SELECT 'bezrealitky', listing_id, scraped_at, raw_json FROM bezrealitky_raw_listings;
        DROP TABLE bezrealitky_raw_listings;
    END IF;
END $$;
