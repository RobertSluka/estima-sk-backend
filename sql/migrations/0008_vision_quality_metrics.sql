-- 0008: honest photo-quality metrics for vision_scores.
--
-- The vision service (heuristic-cv >= 0.2.0) reports only measurable
-- photo-quality metrics; the nine legacy semantic columns (kitchen_quality,
-- luxury_level, ...) are deprecated and stay NULL going forward. The new
-- image_set_hash + model_version pair lets the bridge skip galleries that
-- were already scored with the same images and scoring version.
-- Idempotent: safe to re-run.

ALTER TABLE vision_scores
    ADD COLUMN IF NOT EXISTS brightness              NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS contrast                NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS sharpness               NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS resolution_quality      NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS exposure_quality        NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS colorfulness            NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS image_quality           NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS gallery_consistency     NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS gallery_size            INTEGER,
    ADD COLUMN IF NOT EXISTS blurry_image_ratio      NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS dark_image_ratio        NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS overexposed_image_ratio NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS image_set_hash          VARCHAR(64),
    ADD COLUMN IF NOT EXISTS warnings                JSONB;

COMMENT ON COLUMN vision_scores.image_set_hash IS
    'sha256 over the newline-joined, ordered image URLs sent for scoring; '
    'skip-rescoring cache key together with model_version';
