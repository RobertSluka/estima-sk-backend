"""property_snapshots repository — one row per (property, day)."""

from datetime import date, datetime


def previous_price(cur, property_id: int, before_date: date) -> int | None:
    """
    Price from the most recent snapshot strictly before `before_date`.

    Used for price-change detection: today's price is compared against the
    previous snapshot, not against properties.current_price.
    """
    cur.execute(
        """
        SELECT price
        FROM property_snapshots
        WHERE property_id = %s AND snapshot_date < %s AND price IS NOT NULL
        ORDER BY snapshot_date DESC
        LIMIT 1
        """,
        (property_id, before_date),
    )
    row = cur.fetchone()
    return row["price"] if row else None


def upsert(
    cur,
    property_id: int,
    normalized: dict,
    scraped_at: datetime,
    raw_listing_id: int,
) -> int:
    """
    Create or update today's snapshot. Idempotent on (property_id, snapshot_date):
    re-running on the same day updates the row in place.
    """
    snapshot_date = scraped_at.date()
    cur.execute(
        """
        INSERT INTO property_snapshots (
            property_id, snapshot_date, scraped_at,
            source, deal_type, category, locality, layout,
            price, price_per_sqm, floor_area, land_area,
            active, raw_listing_id
        ) VALUES (
            %(property_id)s, %(snapshot_date)s, %(scraped_at)s,
            %(source)s, %(deal_type)s, %(category)s, %(locality)s, %(layout)s,
            %(price)s, %(price_per_sqm)s, %(floor_area)s, %(land_area)s,
            TRUE, %(raw_listing_id)s
        )
        ON CONFLICT (property_id, snapshot_date) DO UPDATE SET
            scraped_at     = EXCLUDED.scraped_at,
            source         = EXCLUDED.source,
            deal_type      = EXCLUDED.deal_type,
            category       = EXCLUDED.category,
            locality       = EXCLUDED.locality,
            layout         = EXCLUDED.layout,
            price          = EXCLUDED.price,
            price_per_sqm  = EXCLUDED.price_per_sqm,
            floor_area     = EXCLUDED.floor_area,
            land_area      = EXCLUDED.land_area,
            active         = EXCLUDED.active,
            raw_listing_id = EXCLUDED.raw_listing_id
        RETURNING id
        """,
        {
            "property_id": property_id,
            "snapshot_date": snapshot_date,
            "scraped_at": scraped_at,
            "source": normalized["source"],
            "deal_type": normalized["deal_type"],
            "category": normalized.get("category"),
            "locality": normalized.get("locality"),
            "layout": normalized.get("layout"),
            "price": normalized.get("price"),
            "price_per_sqm": normalized.get("price_per_sqm"),
            "floor_area": normalized.get("floor_area"),
            "land_area": normalized.get("land_area"),
            "raw_listing_id": raw_listing_id,
        },
    )
    return cur.fetchone()["id"]
