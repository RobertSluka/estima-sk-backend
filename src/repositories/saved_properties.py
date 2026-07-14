"""saved_properties repository — a user's saved/liked properties."""


def save(cur, user_id: str, property_id: int) -> bool:
    """
    Save a property for a user. Idempotent: saving the same property twice is a
    no-op. Returns True if a new row was inserted, False if it already existed.
    """
    cur.execute(
        """
        INSERT INTO saved_properties (user_id, property_id)
        VALUES (%s, %s)
        ON CONFLICT (user_id, property_id) DO NOTHING
        RETURNING id
        """,
        (user_id, property_id),
    )
    return cur.fetchone() is not None


def unsave(cur, user_id: str, property_id: int) -> bool:
    """Remove a saved property. Returns True if a row was deleted."""
    cur.execute(
        "DELETE FROM saved_properties WHERE user_id = %s AND property_id = %s",
        (user_id, property_id),
    )
    return cur.rowcount > 0


def is_saved(cur, user_id: str, property_id: int) -> bool:
    cur.execute(
        "SELECT 1 FROM saved_properties WHERE user_id = %s AND property_id = %s",
        (user_id, property_id),
    )
    return cur.fetchone() is not None


def list_for_user(cur, user_id: str) -> list[dict]:
    """Return the user's saved properties (newest first) with key listing details."""
    cur.execute(
        """
        SELECT
            sp.property_id,
            sp.created_at AS saved_at,
            p.source, p.deal_type, p.category, p.name, p.locality, p.district,
            p.layout, p.floor_area, p.current_price, p.current_price_per_sqm,
            p.url, p.image_url, p.active
        FROM saved_properties sp
        JOIN properties p ON p.id = sp.property_id
        WHERE sp.user_id = %s
        ORDER BY sp.created_at DESC
        """,
        (user_id,),
    )
    return list(cur.fetchall())
