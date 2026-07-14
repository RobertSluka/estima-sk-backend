-- 0007 — Nearby-facility (POI) counts per property, from OpenStreetMap Overpass.
--
-- src/services/reports/geo.py's Overpass lookup was cached in-process only,
-- which meant every report-service restart (or a separate batch job's process)
-- lost all warmed coverage. This table is the durable counterpart: one row per
-- property, upserted on (re)computation, so report generation and the
-- warm-locations batch job (src/services/location_scoring.py) share the same
-- cache regardless of which process populated it.
--
-- No static map image here — that stays generated on demand per report
-- request. OSM's tile-server usage policy explicitly discourages bulk/scripted
-- downloading, so pre-fetching map tiles for every property is out of scope;
-- the single Overpass POST per property this table backs is within normal use.

CREATE TABLE IF NOT EXISTS location_scores (
    id                              BIGSERIAL PRIMARY KEY,
    property_id                     BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    nearby_transport_count_500m     INTEGER,
    nearby_grocery_count_500m       INTEGER,
    nearby_schools_count_1km        INTEGER,
    nearby_parks_count_1km          INTEGER,
    nearby_restaurants_count_1km    INTEGER,
    nearby_healthcare_count_1km     INTEGER,
    nearby_transport_count_1km      INTEGER,
    nearby_grocery_count_1km        INTEGER,
    nearby_transport_count_3km      INTEGER,
    location_score                  NUMERIC(5, 2),
    computed_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_location_scores_property UNIQUE (property_id)
);

CREATE INDEX IF NOT EXISTS idx_location_scores_property ON location_scores(property_id);
