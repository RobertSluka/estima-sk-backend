-- 0002 — Fix bezrealitky listing URLs.
--
-- The cz-reality / bezrealitky scraper emits listing URLs missing the
-- "/nemovitosti-byty-domy/" path segment, e.g.
--   https://www.bezrealitky.cz/1033493-nabidka-pronajem-bytu-...   (404)
-- should be
--   https://www.bezrealitky.cz/nemovitosti-byty-domy/1033493-nabidka-...
--
-- We only correct the derived properties.url. raw_listings.raw_json is left
-- verbatim (it is the append-only audit log of exactly what the scraper returned).
-- Idempotent via the NOT LIKE guard. Applied by src/migrate.py in a transaction.

UPDATE properties
SET url = replace(
        url,
        'https://www.bezrealitky.cz/',
        'https://www.bezrealitky.cz/nemovitosti-byty-domy/'
    )
WHERE source = 'bezrealitky'
  AND url LIKE 'https://www.bezrealitky.cz/%'
  AND url NOT LIKE 'https://www.bezrealitky.cz/nemovitosti-byty-domy/%';
