-- 0010 — User accounts and Stripe subscription state.
--
-- First real users table: e-mail/password accounts (scrypt hash) and Google
-- OIDC accounts (google_sub) can coexist on one row — a Google sign-in with a
-- known e-mail links to the existing account. Subscription state is a 1:1
-- mirror of the latest Stripe webhook truth; Stripe itself stays the billing
-- source of record, this table only caches what the app needs for gating.
-- Idempotent. Applied by src/migrate.py in a transaction.

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL    PRIMARY KEY,
    email         TEXT         NOT NULL UNIQUE,
    name          TEXT,
    picture_url   TEXT,
    password_hash TEXT,                 -- scrypt encoding; NULL for Google-only accounts
    google_sub    TEXT         UNIQUE,  -- Google OIDC subject; NULL for password-only accounts
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id                BIGINT       PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    stripe_customer_id     TEXT         UNIQUE,
    stripe_subscription_id TEXT         UNIQUE,
    plan                   TEXT         NOT NULL DEFAULT 'basic',  -- basic | pro
    status                 TEXT         NOT NULL DEFAULT 'none',   -- Stripe subscription status verbatim
    current_period_end     TIMESTAMPTZ,
    cancel_at_period_end   BOOLEAN      NOT NULL DEFAULT FALSE,
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_customer ON subscriptions(stripe_customer_id);
