"""saved_properties tests (DB, rolled back)."""

from datetime import datetime, timezone

import pytest

from src.repositories import properties, saved_properties

pytestmark = pytest.mark.db


def _make_property(db, sid: str) -> int:
    norm = {
        "source": "test_src", "source_listing_id": sid, "url": f"https://x/{sid}",
        "deal_type": "buy", "category": "apartment", "source_category": "byty",
        "name": "Test", "locality": "Praha 5", "city": "Praha", "district": "Praha 5",
        "layout": "2+kk", "floor_area": 50, "land_area": None, "lat": None, "lon": None,
        "image_url": None, "currency": "CZK", "price": 100, "price_per_sqm": 2.0,
    }
    pid, _, _ = properties.upsert(db, norm, datetime.now(timezone.utc))
    return pid


def test_save_is_idempotent(db):
    pid = _make_property(db, "s1")
    assert saved_properties.save(db, "user-1", pid) is True    # newly saved
    assert saved_properties.save(db, "user-1", pid) is False   # already saved → no-op
    assert saved_properties.is_saved(db, "user-1", pid) is True


def test_unsave(db):
    pid = _make_property(db, "s2")
    saved_properties.save(db, "user-1", pid)
    assert saved_properties.unsave(db, "user-1", pid) is True
    assert saved_properties.unsave(db, "user-1", pid) is False  # nothing left to remove
    assert saved_properties.is_saved(db, "user-1", pid) is False


def test_list_for_user_scoped_and_joined(db):
    p1 = _make_property(db, "s3")
    p2 = _make_property(db, "s4")
    saved_properties.save(db, "user-1", p1)
    saved_properties.save(db, "user-1", p2)
    saved_properties.save(db, "user-2", p1)   # different user

    rows = saved_properties.list_for_user(db, "user-1")
    assert {r["property_id"] for r in rows} == {p1, p2}
    # joined details are present
    assert rows[0]["deal_type"] == "buy"
    assert rows[0]["url"].startswith("https://x/")

    assert {r["property_id"] for r in saved_properties.list_for_user(db, "user-2")} == {p1}
