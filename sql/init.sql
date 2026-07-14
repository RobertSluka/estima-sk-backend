-- Prague Real Estate Intelligence — Database Schema (universal, multi-source)
--
-- Pipeline / data-model layers:
--   ingestion_runs      → one row per Apify scrape batch (lineage / provenance)
--   raw_listings        → append-only verbatim scraper items for EVERY source
--   properties          → current canonical state of each unique listing
--   property_snapshots  → one row per property per day (core historical record)
--   price_changes       → derived events when price moves between scrapes
--   market_statistics   → aggregated daily context by source/deal_type/category/locality/layout
--   feature_sets        → named+versioned feature definitions per ML target
--   property_features   → materialized features per snapshot (leakage-free)
--   ml_dataset_exports  → lineage for exported training CSVs
--   model_versions      → trained model registry (artifact path only, no binaries)
--   predictions         → logged prediction requests + outputs
--
-- This file initializes a FRESH database. Existing databases are upgraded via
-- sql/migrations/*.sql (see `python -m src.main migrate`).

-- ---------------------------------------------------------------------------
-- ingestion_runs — one per Apify run; every raw listing belongs to a run.
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- raw_listings — append-only. One universal table for all sources. The full
-- original scraper item is stored in raw_json. Never UPDATE/DELETE.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_listings (
    id                BIGSERIAL PRIMARY KEY,
    ingestion_run_id  BIGINT        REFERENCES ingestion_runs(id),
    source            VARCHAR(100)  NOT NULL,
    source_listing_id VARCHAR(200)  NOT NULL,
    url               TEXT,
    scraped_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    raw_json          JSONB         NOT NULL,
    content_hash      VARCHAR(100),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_listings_run        ON raw_listings(ingestion_run_id);
CREATE INDEX IF NOT EXISTS idx_raw_listings_source_id  ON raw_listings(source, source_listing_id);
CREATE INDEX IF NOT EXISTS idx_raw_listings_source_at  ON raw_listings(source, scraped_at);
CREATE INDEX IF NOT EXISTS idx_raw_listings_raw_json   ON raw_listings USING GIN(raw_json);

-- ---------------------------------------------------------------------------
-- properties — one row per unique listing (source + source_listing_id).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS properties (
    id                    BIGSERIAL PRIMARY KEY,
    source                VARCHAR(100)  NOT NULL,
    source_listing_id     VARCHAR(200)  NOT NULL,
    url                   TEXT,
    deal_type             VARCHAR(50)   NOT NULL,           -- buy | rent
    category              VARCHAR(100),                     -- apartment, house, land, commercial
    source_category       VARCHAR(100),                     -- original source category (byty/domy)
    name                  TEXT,
    locality              TEXT,
    city                  TEXT,
    district              TEXT,
    layout                VARCHAR(100),
    floor_area            NUMERIC(10, 2),
    land_area             NUMERIC(10, 2),
    lat                   DOUBLE PRECISION,
    lon                   DOUBLE PRECISION,
    image_url             TEXT,
    images                JSONB         NOT NULL DEFAULT '[]'::jsonb,
    currency              VARCHAR(10),
    first_seen_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    last_seen_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    current_price         BIGINT,
    current_price_per_sqm NUMERIC(12, 2),
    active                BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_properties_source_id UNIQUE (source, source_listing_id)
);

CREATE INDEX IF NOT EXISTS idx_properties_deal_category ON properties(deal_type, category);
CREATE INDEX IF NOT EXISTS idx_properties_active        ON properties(active);
CREATE INDEX IF NOT EXISTS idx_properties_district      ON properties(district);
CREATE INDEX IF NOT EXISTS idx_properties_last_seen     ON properties(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_properties_price         ON properties(current_price);

-- ---------------------------------------------------------------------------
-- property_snapshots — one row per (property, day). The core historical record.
-- Carries denormalized source/deal_type/category/locality so the snapshot is
-- self-describing for time-series analysis even if the property row changes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS property_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    property_id     BIGINT        NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    snapshot_date   DATE          NOT NULL,
    scraped_at      TIMESTAMPTZ   NOT NULL,
    source          VARCHAR(100)  NOT NULL,
    deal_type       VARCHAR(50)   NOT NULL,
    category        VARCHAR(100),
    locality        TEXT,
    layout          VARCHAR(100),
    price           BIGINT,
    price_per_sqm   NUMERIC(12, 2),
    floor_area      NUMERIC(10, 2),
    land_area       NUMERIC(10, 2),
    active          BOOLEAN       NOT NULL DEFAULT TRUE,
    raw_listing_id  BIGINT        REFERENCES raw_listings(id),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_snapshot_property_date UNIQUE (property_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_snapshot_date ON property_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_deal_cat_loc  ON property_snapshots(deal_type, category, locality);
CREATE INDEX IF NOT EXISTS idx_snapshots_property_id   ON property_snapshots(property_id);

-- ---------------------------------------------------------------------------
-- price_changes — recorded at the moment a price change is detected during
-- ingestion (today's snapshot vs the previous snapshot). Not recomputed.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_changes (
    id               BIGSERIAL PRIMARY KEY,
    property_id      BIGINT        NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    changed_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    old_price        BIGINT        NOT NULL,
    new_price        BIGINT        NOT NULL,
    absolute_change  BIGINT        NOT NULL,       -- new - old (negative = reduction)
    percent_change   NUMERIC(8, 4) NOT NULL,        -- (new - old) / old * 100
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_changes_property_id ON price_changes(property_id);
CREATE INDEX IF NOT EXISTS idx_price_changes_changed_at  ON price_changes(changed_at);

-- ---------------------------------------------------------------------------
-- market_statistics — daily aggregates. deal_type is part of the grouping so
-- sale and rent statistics are never mixed. Group-by columns are NOT NULL
-- (use '' for "no value") so the UNIQUE constraint works.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_statistics (
    id                   BIGSERIAL PRIMARY KEY,
    stat_date            DATE          NOT NULL,
    source               VARCHAR(100)  NOT NULL DEFAULT '',
    deal_type            VARCHAR(50)   NOT NULL DEFAULT '',
    category             VARCHAR(100)  NOT NULL DEFAULT '',
    locality             TEXT          NOT NULL DEFAULT '',
    layout               VARCHAR(100)  NOT NULL DEFAULT '',
    property_count       INTEGER       NOT NULL,
    median_price         NUMERIC(12, 2),
    avg_price            NUMERIC(12, 2),
    median_price_per_sqm NUMERIC(12, 2),
    avg_price_per_sqm    NUMERIC(12, 2),
    min_price            BIGINT,
    max_price            BIGINT,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_market_stat UNIQUE (stat_date, source, deal_type, category, locality, layout)
);

CREATE INDEX IF NOT EXISTS idx_market_stats_date     ON market_statistics(stat_date);
CREATE INDEX IF NOT EXISTS idx_market_stats_locality ON market_statistics(locality);

-- ---------------------------------------------------------------------------
-- feature_sets — named, versioned feature definitions per ML target.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feature_sets (
    id           BIGSERIAL PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    version      VARCHAR(50)  NOT NULL,
    target       VARCHAR(100) NOT NULL,   -- sale_price, rent_price, sale_price_per_sqm, ...
    description  TEXT,
    code_version TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_feature_set UNIQUE (name, version, target)
);

-- ---------------------------------------------------------------------------
-- property_features — materialized features per snapshot for a feature_set.
-- features_json must NOT contain the target (current_price / *_per_sqm); the
-- target is stored separately to prevent leakage.
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- ml_dataset_exports — lineage for exported training CSVs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml_dataset_exports (
    id              BIGSERIAL PRIMARY KEY,
    feature_set_id  BIGINT       NOT NULL REFERENCES feature_sets(id),
    export_path     TEXT         NOT NULL,
    row_count       INTEGER,
    target          VARCHAR(100) NOT NULL,
    generated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- model_versions — trained model registry. Artifact path only; no binaries.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_versions (
    id                    BIGSERIAL PRIMARY KEY,
    model_name            VARCHAR(100) NOT NULL,
    version               VARCHAR(50)  NOT NULL,
    target                VARCHAR(100) NOT NULL,
    framework             VARCHAR(100) NOT NULL,   -- xgboost
    artifact_path         TEXT         NOT NULL,
    feature_set_id        BIGINT       NOT NULL REFERENCES feature_sets(id),
    training_export_id    BIGINT       REFERENCES ml_dataset_exports(id),
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

-- ---------------------------------------------------------------------------
-- predictions — logged prediction requests and outputs.
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- saved_properties — properties a user has saved/liked. user_id is an opaque
-- external auth id (no users table required here yet).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS saved_properties (
    id           BIGSERIAL PRIMARY KEY,
    user_id      VARCHAR(200) NOT NULL,
    property_id  BIGINT       NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_saved_user_property UNIQUE (user_id, property_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_user     ON saved_properties(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_property ON saved_properties(property_id);
