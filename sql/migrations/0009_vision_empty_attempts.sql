-- 0009: back-off marker for galleries that yielded an empty vision result.
--
-- When scoring analyses zero images (dead URLs, undecodable files) the bridge
-- keeps the stored metrics untouched but records WHICH gallery failed
-- (empty_attempt_hash) and WHEN (empty_attempted_at). The batch job then
-- skips that gallery until the hash changes, the cool-down
-- (VISION_EMPTY_RETRY_DAYS) elapses, or --rescore forces a retry — so a few
-- hundred permanently dead galleries don't get re-downloaded on every run.
-- Idempotent: safe to re-run.

ALTER TABLE vision_scores
    ADD COLUMN IF NOT EXISTS empty_attempt_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS empty_attempted_at TIMESTAMPTZ;

COMMENT ON COLUMN vision_scores.empty_attempt_hash IS
    'image_set_hash of the most recent gallery that produced an empty result; '
    'never overwrites score columns — see services/vision_scoring.py';
