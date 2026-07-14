"""Market statistics grouping tests (DB, rolled back)."""

from datetime import date, datetime, timezone

import pytest

from src.repositories import properties
from src.services import market_statistics

pytestmark = pytest.mark.db


def _norm(deal_type: str, price: int) -> dict:
    return {
        "source": "test_stats",
        "source_listing_id": f"{deal_type}-1",
        "url": "https://example.com",
        "deal_type": deal_type,
        "category": "apartment",
        "source_category": "byty",
        "name": "x",
        "locality": "StatsLoc",
        "city": "Praha",
        "district": "Praha 5",
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


def test_market_stats_grouped_by_deal_type(db):
    """A buy and a rent listing in the same locality/category/layout must NOT be
    aggregated together — deal_type is part of the grouping key."""
    now = datetime.now(timezone.utc)
    today = date.today()

    properties.upsert(db, _norm("buy", 8_000_000), now)
    properties.upsert(db, _norm("rent", 25_000), now)

    market_statistics.aggregate(db, today)

    db.execute(
        """
        SELECT deal_type, property_count, median_price
        FROM market_statistics
        WHERE source = 'test_stats' AND locality = 'StatsLoc'
          AND category = 'apartment' AND layout = '2+kk' AND stat_date = %s
        ORDER BY deal_type
        """,
        (today,),
    )
    rows = db.fetchall()
    by_deal = {r["deal_type"]: r for r in rows}

    assert set(by_deal) == {"buy", "rent"}            # two separate groups
    assert by_deal["buy"]["property_count"] == 1
    assert by_deal["rent"]["property_count"] == 1
    assert float(by_deal["buy"]["median_price"]) == 8_000_000.0
    assert float(by_deal["rent"]["median_price"]) == 25_000.0
