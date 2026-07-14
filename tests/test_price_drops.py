"""Price Drops tests — repository query (DB, rolled back) + endpoint shape.

Value assertions filter on a unique test district so they stay deterministic
even when the suite runs against a database that already holds real rows.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.read_api import app
from src.repositories import price_changes, properties, snapshots

pytestmark = pytest.mark.db

client = TestClient(app)

DISTRICT = "TestDropsDistrict"
DAY1 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
DAY2 = datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc)


def _norm(listing_id: str, price: int) -> dict:
    return {
        "source": "test_drops",
        "source_listing_id": listing_id,
        "url": "https://example.com/prodej/byt",
        "deal_type": "buy",
        "category": "apartment",
        "source_category": "apartment",
        "name": "x",
        "locality": "DropsLoc",
        "city": "Praha",
        "district": DISTRICT,
        "layout": "2+kk",
        "floor_area": 50,
        "land_area": None,
        "lat": None,
        "lon": None,
        "image_url": None,
        "currency": "CZK",
        "price": price,
        "price_per_sqm": price / 50,
    }


def _seed_change(cur, listing_id: str, old_price: int, new_price: int) -> int:
    """Create/refresh a property and record one price change between two days."""
    properties.upsert(cur, _norm(listing_id, old_price), DAY1)
    property_id, _, _ = properties.upsert(cur, _norm(listing_id, new_price), DAY2)
    snapshots.upsert(cur, property_id, _norm(listing_id, new_price), DAY2, None)
    return price_changes.insert(cur, property_id, old_price, new_price, DAY2)


@pytest.fixture
def seeded(db):
    _seed_change(db, "drop-1", 10_000_000, 9_000_000)   # -10% reduction
    _seed_change(db, "drop-2", 8_000_000, 7_600_000)    # -5% reduction
    _seed_change(db, "rise-1", 5_000_000, 5_500_000)    # +10% increase (excluded)
    return db


def test_recent_drops_returns_only_reductions(seeded):
    """Increases never appear; both reductions do, newest first."""
    total, rows = price_changes.recent_drops(seeded, district=DISTRICT)
    assert total == 2
    assert all(r["absolute_change"] < 0 for r in rows)
    assert {r["new_price"] for r in rows} == {9_000_000, 7_600_000}


def test_recent_drops_joins_listing_fields(seeded):
    _, rows = price_changes.recent_drops(seeded, district=DISTRICT)
    row = rows[0]
    assert row["district"] == DISTRICT
    assert row["layout"] == "2+kk"
    assert row["current_price"] is not None


def test_recent_drops_since_days_window_excludes_old(seeded):
    """The seeded changes are dated 2026-01-06, so a 1-day window excludes them."""
    total, rows = price_changes.recent_drops(seeded, district=DISTRICT, since_days=1)
    assert total == 0
    assert rows == []


def test_price_drops_endpoint_shape():
    """The endpoint responds 200 with the paginated envelope and item keys."""
    res = client.get("/price-drops?limit=5")
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"total", "limit", "offset", "items"}
    assert isinstance(body["items"], list)
    if body["items"]:
        item = body["items"][0]
        assert set(item) >= {
            "id", "propertyId", "changedAt", "oldPrice", "newPrice",
            "absoluteChange", "percentChange", "district", "url",
        }
        assert item["absoluteChange"] < 0
