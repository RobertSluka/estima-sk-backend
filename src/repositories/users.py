"""users repository — accounts and their Stripe subscription state."""

# Bare column names only: list_with_subscription() builds its SELECT by
# prefixing each of these with "u.", so no expressions/aliases here.
USER_COLUMNS = "id, email, name, picture_url, google_sub, role, pro_override, created_at"


def create(
    cur,
    email: str,
    name: str | None = None,
    password_hash: str | None = None,
    google_sub: str | None = None,
    picture_url: str | None = None,
) -> dict:
    cur.execute(
        f"""
        INSERT INTO users (email, name, password_hash, google_sub, picture_url)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING {USER_COLUMNS}
        """,
        (email, name, password_hash, google_sub, picture_url),
    )
    return dict(cur.fetchone())


def get_by_id(cur, user_id: int) -> dict | None:
    cur.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_by_email(cur, email: str) -> dict | None:
    cur.execute(f"SELECT {USER_COLUMNS} FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_password_hash(cur, email: str) -> str | None:
    cur.execute("SELECT password_hash FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    return row["password_hash"] if row else None


def get_password_hash_by_id(cur, user_id: int) -> str | None:
    cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    return row["password_hash"] if row else None


def has_password(cur, user_id: int) -> bool:
    cur.execute(
        "SELECT password_hash IS NOT NULL AS ok FROM users WHERE id = %s", (user_id,)
    )
    row = cur.fetchone()
    return bool(row and row["ok"])


def update_profile(cur, user_id: int, name: str | None = None) -> dict | None:
    """Self-service profile edit. None args leave that column untouched."""
    cur.execute(
        f"""
        UPDATE users
        SET name = COALESCE(%s, name),
            updated_at = NOW()
        WHERE id = %s
        RETURNING {USER_COLUMNS}
        """,
        (name, user_id),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def set_password(cur, user_id: int, password_hash: str) -> bool:
    """Set (or replace) a user's password hash. Returns True if the user exists."""
    cur.execute(
        "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
        (password_hash, user_id),
    )
    return cur.rowcount > 0


def get_by_google_sub(cur, google_sub: str) -> dict | None:
    cur.execute(f"SELECT {USER_COLUMNS} FROM users WHERE google_sub = %s", (google_sub,))
    row = cur.fetchone()
    return dict(row) if row else None


def link_google(cur, user_id: int, google_sub: str, name: str | None, picture_url: str | None) -> dict:
    """Attach a Google identity to an existing account; refresh name/picture."""
    cur.execute(
        f"""
        UPDATE users
        SET google_sub = %s,
            name = COALESCE(%s, name),
            picture_url = COALESCE(%s, picture_url),
            updated_at = NOW()
        WHERE id = %s
        RETURNING {USER_COLUMNS}
        """,
        (google_sub, name, picture_url, user_id),
    )
    return dict(cur.fetchone())


def refresh_google_profile(cur, user_id: int, name: str | None, picture_url: str | None) -> dict:
    cur.execute(
        f"""
        UPDATE users
        SET name = COALESCE(%s, name),
            picture_url = COALESCE(%s, picture_url),
            updated_at = NOW()
        WHERE id = %s
        RETURNING {USER_COLUMNS}
        """,
        (name, picture_url, user_id),
    )
    return dict(cur.fetchone())


def set_access(
    cur, user_id: int, role: str | None = None, pro_override: bool | None = None
) -> dict | None:
    """Admin update of a user's access. None args leave that column untouched."""
    cur.execute(
        f"""
        UPDATE users
        SET role         = COALESCE(%s, role),
            pro_override = COALESCE(%s, pro_override),
            updated_at   = NOW()
        WHERE id = %s
        RETURNING {USER_COLUMNS}
        """,
        (role, pro_override, user_id),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def list_with_subscription(
    cur, limit: int, offset: int, q: str | None = None
) -> list[dict]:
    """Users joined with their subscription summary, newest first, for the
    admin table. Optional case-insensitive filter over e-mail and name."""
    where = ""
    params: list = []
    if q:
        where = "WHERE u.email ILIKE %s OR u.name ILIKE %s"
        like = f"%{q}%"
        params += [like, like]
    params += [limit, offset]
    cur.execute(
        f"""
        SELECT {', '.join('u.' + c for c in USER_COLUMNS.split(', '))},
               s.status AS sub_status, s.plan AS sub_plan,
               s.current_period_end, s.cancel_at_period_end
        FROM users u
        LEFT JOIN subscriptions s ON s.user_id = u.id
        {where}
        ORDER BY u.created_at DESC, u.id DESC
        LIMIT %s OFFSET %s
        """,
        params,
    )
    return [dict(r) for r in cur.fetchall()]


def count_all(cur, q: str | None = None) -> int:
    if q:
        like = f"%{q}%"
        cur.execute(
            "SELECT COUNT(*) AS n FROM users WHERE email ILIKE %s OR name ILIKE %s",
            (like, like),
        )
    else:
        cur.execute("SELECT COUNT(*) AS n FROM users")
    return int(cur.fetchone()["n"])


def get_subscription(cur, user_id: int) -> dict | None:
    cur.execute("SELECT * FROM subscriptions WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_subscription_by_customer(cur, stripe_customer_id: str) -> dict | None:
    cur.execute(
        "SELECT * FROM subscriptions WHERE stripe_customer_id = %s",
        (stripe_customer_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def upsert_subscription(
    cur,
    user_id: int,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    plan: str | None = None,
    status: str | None = None,
    current_period_end=None,
    cancel_at_period_end: bool | None = None,
) -> dict:
    """
    Insert or merge the user's subscription row. None values leave the existing
    column untouched, so webhook handlers can send partial updates.
    """
    cur.execute(
        """
        INSERT INTO subscriptions
            (user_id, stripe_customer_id, stripe_subscription_id, plan, status,
             current_period_end, cancel_at_period_end)
        VALUES
            (%s, %s, %s, COALESCE(%s, 'basic'), COALESCE(%s, 'none'), %s, COALESCE(%s, FALSE))
        ON CONFLICT (user_id) DO UPDATE SET
            stripe_customer_id     = COALESCE(EXCLUDED.stripe_customer_id, subscriptions.stripe_customer_id),
            stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id, subscriptions.stripe_subscription_id),
            plan                   = COALESCE(%s, subscriptions.plan),
            status                 = COALESCE(%s, subscriptions.status),
            current_period_end     = COALESCE(EXCLUDED.current_period_end, subscriptions.current_period_end),
            cancel_at_period_end   = COALESCE(%s, subscriptions.cancel_at_period_end),
            updated_at             = NOW()
        RETURNING *
        """,
        (
            user_id,
            stripe_customer_id,
            stripe_subscription_id,
            plan,
            status,
            current_period_end,
            cancel_at_period_end,
            plan,
            status,
            cancel_at_period_end,
        ),
    )
    return dict(cur.fetchone())
