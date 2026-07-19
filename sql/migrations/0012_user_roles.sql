-- 0012 — Roles and admin-granted Pro access.
--
-- Two access levers on top of the Stripe subscription cache (0010):
--   role         'user' | 'admin' — admins reach the user-management surface
--                and always have Pro features.
--   pro_override  admin-granted Pro access independent of Stripe, for comps,
--                staff and beta users. Effective plan = active subscription OR
--                pro_override OR role='admin'.
-- Idempotent. Applied by src/migrate.py in a transaction.

ALTER TABLE users ADD COLUMN IF NOT EXISTS role         TEXT    NOT NULL DEFAULT 'user';
ALTER TABLE users ADD COLUMN IF NOT EXISTS pro_override BOOLEAN NOT NULL DEFAULT FALSE;
