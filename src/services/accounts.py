"""
Account service — registration, password verification, Google sign-in upsert.

Passwords are hashed with stdlib hashlib.scrypt (no new dependencies), encoded
as `scrypt$N$r$p$salt_b64$hash_b64` so parameters can be raised later without
invalidating existing hashes. Google accounts may have no password; a Google
sign-in whose e-mail matches an existing password account links to it (one row
per person, both methods work afterwards).

Plan gating: `effective_plan` collapses Stripe's status zoo into basic|pro.
"""

import base64
import hashlib
import hmac
import secrets

from src.repositories import users

# scrypt parameters: 16 MiB memory cost. maxmem must be raised above the
# OpenSSL default or hashlib refuses n=2**14 with r=8.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_DKLEN = 32

# Stripe statuses that keep Pro features on. past_due keeps access during the
# retry window; access drops when Stripe gives up and sends `canceled`.
_ACTIVE_STATUSES = {"active", "trialing", "past_due"}


class EmailTaken(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM, dklen=_DKLEN,
    )
    return "scrypt$%d$%d$%d$%s$%s" % (
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode(),
    )


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), maxmem=_SCRYPT_MAXMEM, dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register(cur, email: str, password: str, name: str | None = None) -> dict:
    """Create a password account. Raises EmailTaken if the e-mail is in use."""
    email = normalize_email(email)
    if users.get_by_email(cur, email):
        raise EmailTaken(email)
    return users.create(cur, email=email, name=name, password_hash=hash_password(password))


def verify_login(cur, email: str, password: str) -> dict | None:
    """Return the user for valid e-mail/password credentials, else None."""
    email = normalize_email(email)
    encoded = users.get_password_hash(cur, email)
    if not verify_password(password, encoded):
        return None
    return users.get_by_email(cur, email)


def google_sign_in(
    cur, google_sub: str, email: str, name: str | None = None, picture_url: str | None = None
) -> dict:
    """
    Upsert from verified Google OIDC claims: match by google_sub, else link by
    e-mail to an existing account, else create a fresh Google-only account.
    """
    email = normalize_email(email)
    existing = users.get_by_google_sub(cur, google_sub)
    if existing:
        return users.refresh_google_profile(cur, existing["id"], name, picture_url)
    by_email = users.get_by_email(cur, email)
    if by_email:
        return users.link_google(cur, by_email["id"], google_sub, name, picture_url)
    return users.create(
        cur, email=email, name=name, google_sub=google_sub, picture_url=picture_url
    )


def effective_plan(subscription: dict | None) -> str:
    if subscription and subscription.get("status") in _ACTIVE_STATUSES:
        return subscription.get("plan") or "pro"
    return "basic"


def public_user(cur, user: dict) -> dict:
    """User payload for the frontend: profile + subscription + effective plan."""
    sub = users.get_subscription(cur, user["id"])
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name"),
        "picture_url": user.get("picture_url"),
        "has_google": bool(user.get("google_sub")),
        "plan": effective_plan(sub),
        "subscription": _public_subscription(sub),
    }


def _public_subscription(sub: dict | None) -> dict | None:
    if not sub:
        return None
    period_end = sub.get("current_period_end")
    return {
        "status": sub.get("status"),
        "plan": sub.get("plan"),
        "stripe_customer_id": sub.get("stripe_customer_id"),
        "current_period_end": period_end.isoformat() if period_end else None,
        "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
    }
