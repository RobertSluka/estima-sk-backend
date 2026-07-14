"""market_index repository — daily median series for the Estima INDEX.

Computed on the fly from property_snapshots (joined to properties for the
district) rather than market_statistics: statistics groups are street-level
locality strings and only exist for days an aggregation ran, while snapshots
are the canonical one-row-per-property-per-day time series.
"""

# Raw `category` values differ per source (sreality items arrive normalized to
# English, bezrealitky keeps Czech). Buckets mirror the frontend's
# categoryBucket() so both APIs speak the same two category names.
CATEGORY_BUCKETS: dict[str, tuple[str, ...]] = {
    "apartment": ("apartment", "byty"),
    "house": ("house", "domy"),
}


def series(
    cur,
    *,
    deal_type: str,
    category: str,
    district: str | None = None,
) -> list[dict]:
    """Daily median price / price-per-sqm for one deal_type + category bucket.

    `deal_type` is the pipeline value ("buy"/"rent"); `category` is a bucket
    key from CATEGORY_BUCKETS. Without `district` the series is market-wide.
    """
    params: list = [deal_type, CATEGORY_BUCKETS[category]]
    district_sql = ""
    if district:
        district_sql = "AND p.district = %s"
        params.append(district)
    cur.execute(
        f"""
        SELECT
            s.snapshot_date,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s.price)         AS median_price,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s.price_per_sqm) AS median_price_per_sqm,
            COUNT(*) AS property_count
        FROM property_snapshots s
        JOIN properties p ON p.id = s.property_id
        WHERE s.deal_type = %s
          AND s.category IN %s
          AND s.price IS NOT NULL
          {district_sql}
        GROUP BY s.snapshot_date
        ORDER BY s.snapshot_date
        """,
        params,
    )
    return cur.fetchall()


def districts(cur, *, deal_type: str, category: str) -> list[dict]:
    """Districts with snapshot coverage — options for the index district filter."""
    cur.execute(
        """
        SELECT p.district, COUNT(DISTINCT s.property_id) AS property_count
        FROM property_snapshots s
        JOIN properties p ON p.id = s.property_id
        WHERE s.deal_type = %s
          AND s.category IN %s
          AND s.price IS NOT NULL
          AND p.district IS NOT NULL AND p.district <> ''
        GROUP BY p.district
        ORDER BY p.district
        """,
        (deal_type, CATEGORY_BUCKETS[category]),
    )
    return cur.fetchall()
