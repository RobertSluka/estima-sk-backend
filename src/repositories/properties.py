"""properties repository — canonical current state, keyed (source, source_listing_id)."""

from datetime import datetime

from psycopg2.extras import Json


def price_per_sqm_distribution(
    cur, *, district: str | None, deal_type: str | None, category: str | None
) -> dict | None:
    """Spread of price/m² across active listings in one district segment.

    Returns min/p25/median/p75/max and the sample size, or None when the
    segment is empty or under-specified. ``deal_type`` is required so sale and
    rent are never mixed in the aggregate.
    """
    if not district or not deal_type:
        return None
    cur.execute(
        """
        SELECT
            COUNT(*)                                                            AS sample_size,
            MIN(current_price_per_sqm)                                          AS min,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY current_price_per_sqm) AS p25,
            PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY current_price_per_sqm) AS median,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY current_price_per_sqm) AS p75,
            MAX(current_price_per_sqm)                                          AS max
        FROM properties
        WHERE active = TRUE
          AND district = %(district)s
          AND deal_type = %(deal_type)s
          AND current_price_per_sqm IS NOT NULL
          AND (%(category)s IS NULL OR category = %(category)s)
        """,
        {"district": district, "deal_type": deal_type, "category": category},
    )
    row = cur.fetchone()
    return row if row and row["sample_size"] else None


def get(cur, source: str, source_listing_id: str) -> dict | None:
    cur.execute(
        "SELECT id, current_price FROM properties WHERE source = %s AND source_listing_id = %s",
        (source, source_listing_id),
    )
    return cur.fetchone()


def upsert(cur, normalized: dict, scraped_at: datetime) -> tuple[int, int | None, bool]:
    """
    Insert or update a property from a normalized listing dict.

    Returns (property_id, old_current_price, is_new). old_current_price is the
    value before this upsert (used only as a fallback signal; price-change
    detection compares against the previous snapshot, not this).
    """
    existing = get(cur, normalized["source"], normalized["source_listing_id"])
    old_price = existing["current_price"] if existing else None
    is_new = existing is None

    cur.execute(
        """
        INSERT INTO properties (
            source, source_listing_id, url,
            deal_type, category, source_category,
            name, locality, city, district, layout,
            floor_area, land_area, lat, lon, image_url, images, currency,
            first_seen_at, last_seen_at,
            current_price, current_price_per_sqm,
            active
        ) VALUES (
            %(source)s, %(source_listing_id)s, %(url)s,
            %(deal_type)s, %(category)s, %(source_category)s,
            %(name)s, %(locality)s, %(city)s, %(district)s, %(layout)s,
            %(floor_area)s, %(land_area)s, %(lat)s, %(lon)s, %(image_url)s, %(images)s, %(currency)s,
            %(scraped_at)s, %(scraped_at)s,
            %(price)s, %(price_per_sqm)s,
            TRUE
        )
        ON CONFLICT (source, source_listing_id) DO UPDATE SET
            url                   = EXCLUDED.url,
            deal_type             = EXCLUDED.deal_type,
            category              = EXCLUDED.category,
            source_category       = EXCLUDED.source_category,
            name                  = EXCLUDED.name,
            locality              = EXCLUDED.locality,
            city                  = EXCLUDED.city,
            district              = EXCLUDED.district,
            layout                = EXCLUDED.layout,
            floor_area            = EXCLUDED.floor_area,
            land_area             = EXCLUDED.land_area,
            lat                   = EXCLUDED.lat,
            lon                   = EXCLUDED.lon,
            image_url             = EXCLUDED.image_url,
            images                = EXCLUDED.images,
            currency              = EXCLUDED.currency,
            last_seen_at          = EXCLUDED.last_seen_at,
            current_price         = EXCLUDED.current_price,
            current_price_per_sqm = EXCLUDED.current_price_per_sqm,
            active                = TRUE,
            updated_at            = NOW()
        RETURNING id
        """,
        {**normalized, "scraped_at": scraped_at,
         "images": Json(normalized.get("images") or [])},
    )
    property_id = cur.fetchone()["id"]
    return property_id, old_price, is_new


def mark_inactive(cur, days_since_last_seen: int = 3) -> int:
    """Mark properties not seen within N days as inactive. Returns rows updated."""
    cur.execute(
        """
        UPDATE properties
        SET active = FALSE, updated_at = NOW()
        WHERE active = TRUE
          AND last_seen_at < NOW() - make_interval(days => %s)
        """,
        (days_since_last_seen,),
    )
    return cur.rowcount
