"""market_statistics repository — read access to the daily aggregates.

Writes happen in src/services/market_statistics.py (bulk INSERT…SELECT);
this module only reads.
"""


def latest_context(
    cur,
    *,
    deal_type: str,
    category: str | None,
    locality: str | None,
    layout: str | None,
) -> dict | None:
    """Most recent market stats for one (deal_type, category, locality, layout) group.

    Source-agnostic: a valuation request has no listing source, so across
    sources the row with the largest sample on the latest stat_date wins.
    The table stores '' (never NULL) for absent grouping values.
    """
    cur.execute(
        """
        SELECT stat_date, median_price, median_price_per_sqm, property_count
        FROM market_statistics
        WHERE deal_type = %s AND category = %s AND locality = %s AND layout = %s
        ORDER BY stat_date DESC, property_count DESC
        LIMIT 1
        """,
        (deal_type, category or "", locality or "", layout or ""),
    )
    return cur.fetchone()


def district_context(
    cur,
    *,
    deal_type: str,
    category: str | None,
    district: str,
    layout: str | None,
) -> dict | None:
    """Live median over active listings in one district — fallback for requests
    whose locality doesn't exact-match a `market_statistics` group (those groups
    are street-level strings; user input is typically district-level).

    Tries a layout-specific sample first, then layout-agnostic.
    """
    for with_layout in ((True,) if layout else ()) + (False,):
        cur.execute(
            f"""
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)         AS median_price,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price_per_sqm) AS median_price_per_sqm,
                COUNT(*) AS property_count
            FROM properties
            WHERE active = TRUE
              AND current_price IS NOT NULL
              AND deal_type = %s
              AND category = %s
              AND district = %s
              {"AND layout = %s" if with_layout else ""}
            """,
            (deal_type, category, district) + ((layout,) if with_layout else ()),
        )
        row = cur.fetchone()
        if row and row["property_count"]:
            return row
    return None
