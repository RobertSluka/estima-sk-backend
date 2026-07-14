"""DB-backed ingestion tests. Run inside a transaction that is rolled back."""

from datetime import datetime, timedelta, timezone

import pytest

from src.repositories import price_changes, properties, snapshots

pytestmark = pytest.mark.db


def make_norm(**overrides) -> dict:
    norm = {
        "source": "test_src",
        "source_listing_id": "t1",
        "url": "https://example.com/t1",
        "deal_type": "buy",
        "category": "apartment",
        "source_category": "byty",
        "name": "Test listing",
        "locality": "TestLoc, Praha 5",
        "city": "Praha",
        "district": "Praha 5",
        "layout": "2+kk",
        "floor_area": 50,
        "land_area": None,
        "lat": 50.07,
        "lon": 14.39,
        "image_url": None,
        "currency": "CZK",
        "price": 100,
        "price_per_sqm": 2.0,
    }
    norm.update(overrides)
    return norm


def test_property_upsert_by_source_and_id(db):
    now = datetime.now(timezone.utc)
    pid1, old1, is_new1 = properties.upsert(db, make_norm(price=100), now)
    assert is_new1 is True
    assert old1 is None

    # Same (source, source_listing_id) → updates the SAME row, captures old price.
    pid2, old2, is_new2 = properties.upsert(db, make_norm(price=200), now)
    assert pid2 == pid1
    assert is_new2 is False
    assert old2 == 100

    db.execute("SELECT current_price FROM properties WHERE id = %s", (pid1,))
    assert db.fetchone()["current_price"] == 200


def test_snapshot_creation(db):
    now = datetime.now(timezone.utc)
    pid, _, _ = properties.upsert(db, make_norm(), now)
    snap_id = snapshots.upsert(db, pid, make_norm(), now, None)

    db.execute(
        "SELECT property_id, source, deal_type, price, layout FROM property_snapshots WHERE id = %s",
        (snap_id,),
    )
    row = db.fetchone()
    assert row["property_id"] == pid
    assert row["source"] == "test_src"
    assert row["deal_type"] == "buy"
    assert row["price"] == 100
    assert row["layout"] == "2+kk"


def test_price_change_detection(db):
    day1 = datetime(2026, 6, 17, 6, 0, tzinfo=timezone.utc)
    day2 = day1 + timedelta(days=1)
    pid, _, _ = properties.upsert(db, make_norm(price=100), day1)

    # Snapshot on day1 at price 100.
    snapshots.upsert(db, pid, make_norm(price=100), day1, None)

    # The previous price (before day2) should be 100.
    prev = snapshots.previous_price(db, pid, day2.date())
    assert prev == 100

    # Record a change to 90.
    change_id = price_changes.insert(db, pid, prev, 90, day2)
    db.execute(
        "SELECT old_price, new_price, absolute_change, percent_change FROM price_changes WHERE id = %s",
        (change_id,),
    )
    row = db.fetchone()
    assert row["old_price"] == 100
    assert row["new_price"] == 90
    assert row["absolute_change"] == -10
    assert float(row["percent_change"]) == -10.0
