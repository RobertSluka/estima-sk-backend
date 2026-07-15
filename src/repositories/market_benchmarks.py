"""market_benchmarks repository — external realized-price references (e.g. Deloitte).

Idempotent upsert keyed on the natural key (the COALESCE-based unique index from
migration 0006), plus the read paths the API needs: latest period, all rows for a
period/granularity, and the best benchmark for a given district (district → city
fallback).
"""

# Columns written by the importer, in insert order. The natural key subset is
# referenced by the ON CONFLICT clause below.
_COLUMNS = (
    "source", "source_name", "source_url",
    "period", "year", "quarter",
    "country", "city", "district", "locality",
    "property_type", "segment",
    "metric", "value_czk_per_sqm",
    "change_percent", "transaction_count", "transaction_volume_czk",
    "granularity", "notes",
)

# Non-key columns refreshed on re-import (everything except the natural key).
_UPDATE_COLUMNS = (
    "source_name", "source_url", "year", "quarter",
    "value_czk_per_sqm", "change_percent",
    "transaction_count", "transaction_volume_czk", "notes",
)


def upsert(cur, row: dict) -> int:
    """Insert or update one benchmark row. Returns its id. Idempotent per report."""
    cols = ", ".join(_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in _COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATE_COLUMNS)
    cur.execute(
        f"""
        INSERT INTO market_benchmarks ({cols})
        VALUES ({placeholders})
        ON CONFLICT (source, period, COALESCE(country, ''), COALESCE(city, ''),
                     COALESCE(district, ''), COALESCE(locality, ''),
                     property_type, segment, metric)
        DO UPDATE SET {updates}, imported_at = NOW()
        RETURNING id
        """,
        {c: row.get(c) for c in _COLUMNS},
    )
    return cur.fetchone()["id"]


def latest_period(cur, *, source: str | None = None, metric: str = "realized_price_per_sqm") -> str | None:
    """Most recent period present (optionally for one source/metric)."""
    cur.execute(
        """
        SELECT period FROM market_benchmarks
        WHERE metric = %(metric)s AND (%(source)s IS NULL OR source = %(source)s)
        ORDER BY year DESC NULLS LAST, quarter DESC NULLS LAST, period DESC
        LIMIT 1
        """,
        {"source": source, "metric": metric},
    )
    row = cur.fetchone()
    return row["period"] if row else None


def list_benchmarks(
    cur,
    *,
    period: str | None = None,
    granularity: str | None = None,
    segment: str | None = None,
    metric: str = "realized_price_per_sqm",
    city: str | None = None,
) -> list[dict]:
    """Benchmarks for a period (defaults to latest), filterable by granularity/segment/city."""
    if period is None:
        period = latest_period(cur, metric=metric)
        if period is None:
            return []
    cur.execute(
        """
        SELECT * FROM market_benchmarks
        WHERE period = %(period)s AND metric = %(metric)s
          AND (%(granularity)s IS NULL OR granularity = %(granularity)s)
          AND (%(segment)s IS NULL OR segment = %(segment)s)
          AND (%(city)s IS NULL OR city = %(city)s)
        ORDER BY granularity, district NULLS FIRST, segment
        """,
        {"period": period, "metric": metric, "granularity": granularity, "segment": segment, "city": city},
    )
    return cur.fetchall()


def series_for_district(
    cur,
    *,
    district: str,
    metric: str = "realized_price_per_sqm",
    segment: str = "all",
    limit: int = 16,
) -> list[dict]:
    """Benchmark values across periods for one district (city fallback),
    oldest first — the data behind the report's index trend chart.

    Same scope rule as `for_district`, applied per period: the district row
    when one exists, else the city-level row.
    """
    cur.execute(
        """
        SELECT DISTINCT ON (period)
               period, year, quarter, source_name, granularity, city, district,
               value_czk_per_sqm
        FROM market_benchmarks
        WHERE metric = %(metric)s AND segment = %(segment)s
          AND granularity IN ('district', 'city')
          AND (district = %(district)s OR granularity = 'city')
          AND value_czk_per_sqm IS NOT NULL
        ORDER BY period, (district = %(district)s) DESC NULLS LAST
        """,
        {"metric": metric, "segment": segment, "district": district},
    )
    rows = sorted(
        cur.fetchall(),
        key=lambda r: (r["year"] or 0, r["quarter"] or 0, r["period"]),
    )
    return rows[-limit:]


def for_district(
    cur,
    *,
    district: str,
    period: str | None = None,
    metric: str = "realized_price_per_sqm",
    segment: str = "all",
) -> dict | None:
    """Best benchmark for a district: exact district match, else city-level fallback."""
    if period is None:
        period = latest_period(cur, metric=metric)
        if period is None:
            return None
    cur.execute(
        """
        SELECT * FROM market_benchmarks
        WHERE period = %(period)s AND metric = %(metric)s AND segment = %(segment)s
          AND granularity IN ('district', 'city')
          AND (district = %(district)s OR granularity = 'city')
        -- prefer the district row over the city fallback. NULLS LAST matters: the
        -- city row's `district = ?` is NULL, which DESC would otherwise sort first.
        ORDER BY (district = %(district)s) DESC NULLS LAST
        LIMIT 1
        """,
        {"period": period, "metric": metric, "segment": segment, "district": district},
    )
    return cur.fetchone()
