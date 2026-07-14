-- 0003 — Saved / liked properties per user.
--
-- A join table linking an (opaque) user id to the properties they saved. user_id
-- is a VARCHAR so it works with any external auth subject (email, Clerk/Auth0 id,
-- etc.) without requiring a users table in this database yet.
-- Idempotent. Applied by src/migrate.py in a transaction.

CREATE TABLE IF NOT EXISTS saved_properties (
    id           BIGSERIAL PRIMARY KEY,
    user_id      VARCHAR(200) NOT NULL,
    property_id  BIGINT       NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_saved_user_property UNIQUE (user_id, property_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_user     ON saved_properties(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_property ON saved_properties(property_id);
