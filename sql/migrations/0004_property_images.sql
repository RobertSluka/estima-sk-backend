-- 0004 — Add a full image gallery to properties.
--
-- properties.image_url keeps the single main/thumbnail image (used for cards).
-- The new richer bezrealitky-task scraper provides a full publicImages gallery;
-- we store every image URL here so the property detail page can show them all.
-- JSONB array of URL strings, defaulting to '[]'. Idempotent.

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS images JSONB NOT NULL DEFAULT '[]'::jsonb;
