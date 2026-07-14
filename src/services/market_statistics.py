"""
Daily market statistics aggregation.

Aggregates active properties by (source, deal_type, category, locality, layout).
deal_type is part of the grouping key so sale and rent are never mixed.
Idempotent on the same day via ON CONFLICT DO UPDATE.
"""

import logging
from datetime import date

from src.db import get_cursor

logger = logging.getLogger(__name__)


def generate(stat_date: date | None = None) -> int:
    """Compute and persist market statistics for `stat_date` (default: today)."""
    target_date = stat_date or date.today()
    with get_cursor() as cur:
        row_count = aggregate(cur, target_date)
    logger.info("Generated %d market stat rows for %s", row_count, target_date)
    return row_count


def aggregate(cur, target_date: date) -> int:
    """Run the aggregation on an existing cursor (used by generate() and tests)."""
    cur.execute(
            """
            INSERT INTO market_statistics (
                stat_date, source, deal_type, category, locality, layout,
                property_count,
                median_price,         avg_price,
                median_price_per_sqm, avg_price_per_sqm,
                min_price,            max_price
            )
            SELECT
                %s AS stat_date,
                source,
                COALESCE(deal_type, '') AS deal_type,
                COALESCE(category,  '') AS category,
                COALESCE(locality,  '') AS locality,
                COALESCE(layout,    '') AS layout,

                COUNT(*) AS property_count,

                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price)         AS median_price,
                ROUND(AVG(current_price), 2)                                       AS avg_price,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_price_per_sqm) AS median_price_per_sqm,
                ROUND(AVG(current_price_per_sqm), 2)                               AS avg_price_per_sqm,
                MIN(current_price)                                                 AS min_price,
                MAX(current_price)                                                 AS max_price

            FROM properties
            WHERE active = TRUE
              AND current_price IS NOT NULL

            GROUP BY
                source,
                COALESCE(deal_type, ''),
                COALESCE(category,  ''),
                COALESCE(locality,  ''),
                COALESCE(layout,    '')

            ON CONFLICT (stat_date, source, deal_type, category, locality, layout) DO UPDATE SET
                property_count       = EXCLUDED.property_count,
                median_price         = EXCLUDED.median_price,
                avg_price            = EXCLUDED.avg_price,
                median_price_per_sqm = EXCLUDED.median_price_per_sqm,
                avg_price_per_sqm    = EXCLUDED.avg_price_per_sqm,
                min_price            = EXCLUDED.min_price,
                max_price            = EXCLUDED.max_price
            """,
            (target_date,),
        )
    return cur.rowcount
