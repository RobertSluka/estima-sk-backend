"""
Account service + internal API tests.

Hashing/plan tests are pure; account flows use the rolled-back `db` cursor
fixture (skip when Postgres is down); the API-key guard tests run without a DB.
"""

import pytest
from fastapi.testclient import TestClient

from src import config
from src.read_api import app
from src.repositories import users
from src.services import accounts


# --- password hashing (pure) -----------------------------------------------

def test_hash_and_verify_roundtrip():
    encoded = accounts.hash_password("s3cret-pass")
    assert encoded.startswith("scrypt$")
    assert accounts.verify_password("s3cret-pass", encoded)
    assert not accounts.verify_password("wrong-pass", encoded)


def test_verify_rejects_malformed_hashes():
    assert not accounts.verify_password("x", None)
    assert not accounts.verify_password("x", "")
    assert not accounts.verify_password("x", "plaintext")
    assert not accounts.verify_password("x", "md5$1$2$3$YWJj$YWJj")


def test_hashes_are_salted():
    assert accounts.hash_password("same") != accounts.hash_password("same")


# --- effective plan (pure) --------------------------------------------------

@pytest.mark.parametrize(
    "sub,expected",
    [
        (None, "basic"),
        ({"status": "none", "plan": "basic"}, "basic"),
        ({"status": "canceled", "plan": "pro"}, "basic"),
        ({"status": "active", "plan": "pro"}, "pro"),
        ({"status": "trialing", "plan": "pro"}, "pro"),
        ({"status": "past_due", "plan": "pro"}, "pro"),
    ],
)
def test_effective_plan(sub, expected):
    assert accounts.effective_plan(sub) == expected


@pytest.mark.parametrize(
    "user,sub,expected",
    [
        ({"role": "user", "pro_override": False}, None, "basic"),
        ({"role": "user", "pro_override": True}, None, "pro"),
        ({"role": "admin", "pro_override": False}, None, "pro"),
        ({"role": "user", "pro_override": False}, {"status": "active", "plan": "pro"}, "pro"),
    ],
)
def test_entitled_plan(user, sub, expected):
    assert accounts.entitled_plan(user, sub) == expected


# --- account flows (DB, rolled back) ----------------------------------------

@pytest.mark.db
def test_register_verify_and_email_taken(db):
    user = accounts.register(db, "Test@Example.com ", "hunter2-hunter2", "Test User")
    assert user["email"] == "test@example.com"  # normalized

    assert accounts.verify_login(db, "test@example.com", "hunter2-hunter2")["id"] == user["id"]
    assert accounts.verify_login(db, "test@example.com", "wrong-password") is None

    with pytest.raises(accounts.EmailTaken):
        accounts.register(db, "test@example.com", "another-password")


@pytest.mark.db
def test_google_sign_in_creates_then_matches_by_sub(db):
    created = accounts.google_sign_in(db, "gsub-1", "g@example.com", "G User", "http://pic")
    again = accounts.google_sign_in(db, "gsub-1", "g@example.com", "G Renamed", None)
    assert again["id"] == created["id"]
    assert again["name"] == "G Renamed"
    assert again["picture_url"] == "http://pic"  # COALESCE keeps old picture


@pytest.mark.db
def test_google_sign_in_links_to_existing_password_account(db):
    pw_user = accounts.register(db, "both@example.com", "password-123")
    linked = accounts.google_sign_in(db, "gsub-2", "both@example.com", "Linked")
    assert linked["id"] == pw_user["id"]
    assert linked["google_sub"] == "gsub-2"
    # password still works after linking
    assert accounts.verify_login(db, "both@example.com", "password-123")["id"] == pw_user["id"]


@pytest.mark.db
def test_subscription_upsert_partial_updates(db):
    user = accounts.register(db, "sub@example.com", "password-123")
    users.upsert_subscription(db, user["id"], stripe_customer_id="cus_1", plan="pro", status="active")
    # partial update must not clobber existing columns
    updated = users.upsert_subscription(db, user["id"], status="past_due")
    assert updated["stripe_customer_id"] == "cus_1"
    assert updated["plan"] == "pro"
    assert updated["status"] == "past_due"

    by_customer = users.get_subscription_by_customer(db, "cus_1")
    assert by_customer["user_id"] == user["id"]

    public = accounts.public_user(db, user)
    assert public["plan"] == "pro"
    assert "password_hash" not in public


# --- roles & admin-granted access -------------------------------------------

@pytest.mark.db
def test_new_users_default_to_basic_non_admin(db):
    user = accounts.register(db, "plain@example.com", "password-123")
    public = accounts.public_user(db, user)
    assert public["role"] == "user"
    assert public["pro_override"] is False
    assert public["plan"] == "basic"


@pytest.mark.db
def test_set_access_grants_pro_and_admin(db):
    user = accounts.register(db, "grantee@example.com", "password-123")

    granted = accounts.set_access(db, user["id"], pro_override=True)
    assert granted["pro_override"] is True
    assert granted["plan"] == "pro"

    promoted = accounts.set_access(db, user["id"], role="admin")
    assert promoted["role"] == "admin"
    assert promoted["pro_override"] is True  # untouched by the role-only update

    revoked = accounts.set_access(db, user["id"], role="user", pro_override=False)
    assert revoked["plan"] == "basic"


@pytest.mark.db
def test_set_access_rejects_bad_role_and_missing_user(db):
    user = accounts.register(db, "role@example.com", "password-123")
    with pytest.raises(ValueError):
        accounts.set_access(db, user["id"], role="superuser")
    assert accounts.set_access(db, 9_999_999, pro_override=True) is None


@pytest.mark.db
def test_list_users_paginates_and_searches(db):
    a = accounts.register(db, "alice@example.com", "password-123", "Alice")
    accounts.register(db, "bob@example.com", "password-123", "Bob")
    accounts.set_access(db, a["id"], pro_override=True)

    everyone = accounts.list_users(db, limit=50, offset=0)
    assert everyone["total"] >= 2
    alice_row = next(u for u in everyone["users"] if u["email"] == "alice@example.com")
    assert alice_row["plan"] == "pro"

    filtered = accounts.list_users(db, limit=50, offset=0, q="bob")
    assert filtered["total"] == 1
    assert filtered["users"][0]["email"] == "bob@example.com"


# --- internal API key guard (no DB) -----------------------------------------

client = TestClient(app)


def test_internal_endpoints_fail_closed_without_key(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_API_KEY", "")
    r = client.post("/internal/auth/verify", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 503


def test_internal_endpoints_reject_wrong_key(monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_API_KEY", "right-key")
    r = client.post(
        "/internal/auth/verify",
        json={"email": "a@b.c", "password": "x"},
        headers={"X-Internal-Key": "wrong-key"},
    )
    assert r.status_code == 401
