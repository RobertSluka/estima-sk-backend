-- 0006 — External market benchmarks (manually imported reference data).
--
-- Stores realized-price-per-m² benchmarks from external sources (e.g. Deloitte
-- Real Index, Sreality Atlas cen). These are city/district/period market
-- references — NOT a valuation of any specific property. The read API matches a
-- property to its best benchmark (district → city fallback) and reports the
-- difference between the listing's price/m² and the benchmark.
--
-- The natural key (source, period, country, city, district, locality,
-- property_type, segment, metric) makes the CSV import idempotent: re-importing
-- the same report updates the existing rows in place instead of duplicating.
-- NULL location parts are COALESCE'd to '' in the unique index so city-level
-- rows (district IS NULL) don't bypass the constraint.

CREATE TABLE IF NOT EXISTS market_benchmarks (
    id                      BIGSERIAL PRIMARY KEY,

    source                  VARCHAR(100) NOT NULL,
    source_name             TEXT,
    source_url              TEXT,

    period                  VARCHAR(20)  NOT NULL,
    year                    INTEGER,
    quarter                 INTEGER,

    country                 VARCHAR(100) DEFAULT 'CZ',
    city                    VARCHAR(100),
    district                VARCHAR(100),
    locality                VARCHAR(150),

    property_type           VARCHAR(100) DEFAULT 'apartment',
    segment                 VARCHAR(100) DEFAULT 'all',

    metric                  VARCHAR(100) NOT NULL DEFAULT 'realized_price_per_sqm',
    value_czk_per_sqm       NUMERIC      NOT NULL,

    change_percent          NUMERIC,
    transaction_count       INTEGER,
    transaction_volume_czk  NUMERIC,

    granularity             VARCHAR(50)  NOT NULL,
    notes                   TEXT,

    imported_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Indexes for the property → benchmark matching path.
CREATE INDEX IF NOT EXISTS idx_market_benchmarks_city          ON market_benchmarks (city);
CREATE INDEX IF NOT EXISTS idx_market_benchmarks_district      ON market_benchmarks (district);
CREATE INDEX IF NOT EXISTS idx_market_benchmarks_period        ON market_benchmarks (period);
CREATE INDEX IF NOT EXISTS idx_market_benchmarks_property_type ON market_benchmarks (property_type);
CREATE INDEX IF NOT EXISTS idx_market_benchmarks_source        ON market_benchmarks (source);

-- Idempotent-import natural key (NULL-safe via COALESCE).
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_benchmarks_natural ON market_benchmarks (
    source,
    period,
    COALESCE(country,  ''),
    COALESCE(city,     ''),
    COALESCE(district, ''),
    COALESCE(locality, ''),
    property_type,
    segment,
    metric
);
