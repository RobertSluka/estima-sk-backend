"""price_changes repository — events recorded when price moves between snapshots."""

from datetime import datetime


def insert(
    cur,
    property_id: int,
    old_price: int,
    new_price: int,
    changed_at: datetime,
) -> int:
    absolute_change = new_price - old_price
    percent_change = round((new_price - old_price) / old_price * 100, 4) if old_price else 0
    cur.execute(
        """
        INSERT INTO price_changes
            (property_id, changed_at, old_price, new_price, absolute_change, percent_change)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (property_id, changed_at, old_price, new_price, absolute_change, percent_change),
    )
    return cur.fetchone()["id"]


def recent_drops(
    cur,
    *,
    deal_type: str | None = None,   # "sale" | "rent" | None (URL-slug based, like /listings)
    category: str | None = None,
    district: str | None = None,
    since_days: int | None = None,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    """Recent price reductions joined to their listing, newest first.

    Only reductions (``absolute_change < 0``) — a price drop is the event the
    Price Drops page cares about. The live schema has no deal_type column, so
    `deal_type` filters on the URL slug (prodej = sale, pronajem = rent), the
    same convention as /listings. Returns ``(total, rows)`` for pagination.
    """
    where = ["pc.absolute_change < 0"]
    params: list = []
    if active_only:
        where.append("p.active = TRUE")
    if category is not None:
        where.append("p.category = %s")
        params.append(category)
    if district is not None:
        where.append("p.district = %s")
        params.append(district)
    if deal_type == "sale":
        where.append("p.url ILIKE '%%prodej%%'")
    elif deal_type == "rent":
        where.append("(p.url ILIKE '%%pronajem%%' OR p.url ILIKE '%%pronájem%%')")
    if since_days is not None:
        where.append("pc.changed_at >= NOW() - make_interval(days => %s)")
        params.append(since_days)
    where_sql = " AND ".join(where)

    cur.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM price_changes pc
        JOIN properties p ON p.id = pc.property_id
        WHERE {where_sql}
        """,
        params,
    )
    total = cur.fetchone()["n"]

    cur.execute(
        f"""
        SELECT
            pc.id, pc.property_id, pc.changed_at,
            pc.old_price, pc.new_price, pc.absolute_change, pc.percent_change,
            p.source, p.url, p.category, p.name, p.locality, p.district,
            p.layout, p.floor_area, p.image_url,
            p.current_price, p.current_price_per_sqm, p.active
        FROM price_changes pc
        JOIN properties p ON p.id = pc.property_id
        WHERE {where_sql}
        ORDER BY pc.changed_at DESC, pc.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [limit, offset],
    )
    return total, cur.fetchall()
