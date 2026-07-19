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


def entitled_plan(user: dict, subscription: dict | None) -> str:
    """Effective plan including access an admin has granted outside Stripe:
    admins and pro_override users always resolve to Pro."""
    if user.get("role") == "admin" or user.get("pro_override"):
        return "pro"
    return effective_plan(subscription)


def public_user(cur, user: dict) -> dict:
    """User payload for the frontend: profile + subscription + effective plan."""
    sub = users.get_subscription(cur, user["id"])
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name"),
        "picture_url": user.get("picture_url"),
        "has_google": bool(user.get("google_sub")),
        "role": user.get("role") or "user",
        "pro_override": bool(user.get("pro_override")),
        "plan": entitled_plan(user, sub),
        "subscription": _public_subscription(sub),
    }


def set_access(
    cur, user_id: int, role: str | None = None, pro_override: bool | None = None
) -> dict | None:
    """Admin-only update of a user's role / Pro override. Returns the refreshed
    public payload, or None if the user does not exist."""
    if role is not None and role not in ("user", "admin"):
        raise ValueError("role must be 'user' or 'admin'")
    updated = users.set_access(cur, user_id, role=role, pro_override=pro_override)
    if not updated:
        return None
    return public_user(cur, updated)


def list_users(cur, limit: int, offset: int, q: str | None = None) -> dict:
    """Paginated user directory for the admin table."""
    rows = users.list_with_subscription(cur, limit, offset, q)
    total = users.count_all(cur, q)
    items = []
    for r in rows:
        sub = (
            {"status": r["sub_status"], "plan": r["sub_plan"]}
            if r.get("sub_status")
            else None
        )
        created = r.get("created_at")
        items.append(
            {
                "id": r["id"],
                "email": r["email"],
                "name": r.get("name"),
                "picture_url": r.get("picture_url"),
                "has_google": bool(r.get("google_sub")),
                "role": r.get("role") or "user",
                "pro_override": bool(r.get("pro_override")),
                "plan": entitled_plan(r, sub),
                "sub_status": r.get("sub_status"),
                "created_at": created.isoformat() if created else None,
            }
        )
    return {"users": items, "total": total, "limit": limit, "offset": offset}


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
