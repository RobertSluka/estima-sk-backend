-- 0011 — Street-level geocoding of Bazoš listings.
--
-- Bazoš only provides town-level locations; lat/lon are town centroids. When a
-- street can be extracted from the listing's free text and geocoded, the
-- precise position lands here — the read API then prefers geo_lat/geo_lon over
-- the centroid so map pins move from "somewhere in Košice" to the street.
--
--   street         extracted street name (nominative), NULL when none found
--   geo_lat/lon    geocoded street position; NULL when geocoding failed
--   geo_precision  'street' when geo_lat/lon are street-level; NULL otherwise
--   geocoded_at    when extraction+geocoding last ran (NULL = never attempted)
-- Idempotent. Applied by src/migrate.py in a transaction.

ALTER TABLE properties ADD COLUMN IF NOT EXISTS street        TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS geo_lat       DOUBLE PRECISION;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS geo_lon       DOUBLE PRECISION;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS geo_precision TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS geocoded_at   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_properties_geocoded_at ON properties(geocoded_at)
    WHERE geocoded_at IS NULL;
