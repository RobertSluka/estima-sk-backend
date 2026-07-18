"""users repository — accounts and their Stripe subscription state."""

USER_COLUMNS = "id, email, name, picture_url, google_sub, created_at"


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
