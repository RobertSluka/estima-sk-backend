"""Estima INDEX tests — repository medians (DB, rolled back) + endpoint shapes.

All data-value assertions filter on a unique test district so they stay
deterministic even when the suite runs against a database with real rows.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src import read_api
from src.read_api import app
from src.repositories import market_index, properties, snapshots

pytestmark = pytest.mark.db

client = TestClient(app)

DISTRICT = "TestIndexDistrict"
DAY1 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
DAY2 = datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc)


def _norm(listing_id: str, deal_type: str, category: str, price: int) -> dict:
    return {
        "source": "test_index",
        "source_listing_id": listing_id,
        "url": "https://example.com",
        "deal_type": deal_type,
        "category": category,
        "source_category": category,
        "name": "x",
        "locality": "IndexLoc",
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


def _insert(cur, listing_id: str, deal_type: str, category: str, price: int, when: datetime) -> None:
    norm = _norm(listing_id, deal_type, category, price)
    property_id, _, _ = properties.upsert(cur, norm, when)
    snapshots.upsert(cur, property_id, norm, when, None)


@pytest.fixture
def seeded(db):
    # Day 1: two buy apartments across both raw category spellings + one rent.
    _insert(db, "buy-en", "buy", "apartment", 8_000_000, DAY1)
    _insert(db, "buy-cz", "buy", "byty", 10_000_000, DAY1)
    _insert(db, "rent-1", "rent", "apartment", 25_000, DAY1)
    # Day 2: only one of the buys is still listed, cheaper.
    _insert(db, "buy-en", "buy", "apartment", 7_500_000, DAY2)
    return db


def test_series_merges_category_bucket_and_excludes_rent(seeded):
    """Both raw spellings of "apartment" aggregate together; rent rows never
    leak into a buy series."""
    rows = market_index.series(
        seeded, deal_type="buy", category="apartment", district=DISTRICT,
    )
    assert [r["snapshot_date"].isoformat() for r in rows] == ["2026-01-05", "2026-01-06"]
    day1, day2 = rows
    assert day1["property_count"] == 2
    assert float(day1["median_price"]) == 9_000_000
    assert day2["property_count"] == 1
    assert float(day2["median_price"]) == 7_500_000

    rent_rows = market_index.series(
        seeded, deal_type="rent", category="apartment", district=DISTRICT,
    )
    assert [r["property_count"] for r in rent_rows] == [1]
    assert float(rent_rows[0]["median_price"]) == 25_000


def test_districts_lists_covered_districts(seeded):
    rows = market_index.districts(seeded, deal_type="buy", category="apartment")
    by_district = {r["district"]: r["property_count"] for r in rows}
    assert by_district[DISTRICT] == 2  # distinct properties, not snapshots


def _patch_cursor(monkeypatch, cur):
    @contextmanager
    def ctx(**_kw):
        yield cur

    monkeypatch.setattr(read_api, "get_cursor", ctx)


def test_market_index_endpoint_json(seeded, monkeypatch):
    _patch_cursor(monkeypatch, seeded)
    resp = client.get(
        "/market-index",
        params={"deal_type": "sale", "category": "apartment", "district": DISTRICT},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dealType"] == "sale"
    assert body["district"] == DISTRICT
    assert [p["date"] for p in body["series"]] == ["2026-01-05", "2026-01-06"]
    assert body["series"][0]["medianPrice"] == 9_000_000
    assert body["series"][0]["medianPricePerSqm"] == pytest.approx(180_000)


def test_market_index_endpoint_csv(seeded, monkeypatch):
    _patch_cursor(monkeypatch, seeded)
    resp = client.get(
        "/market-index",
        params={
            "deal_type": "sale",
            "category": "apartment",
            "district": DISTRICT,
            "format": "csv",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "estima-index-sale-apartment-testindexdistrict.csv" in resp.headers["content-disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0] == "date,median_price,median_price_per_sqm,property_count"
    assert lines[1].startswith("2026-01-05,9000000")
    assert len(lines) == 3


def test_market_index_rejects_unknown_params():
    assert client.get("/market-index", params={"deal_type": "lease"}).status_code == 422
    assert client.get("/market-index", params={"category": "castle"}).status_code == 422
