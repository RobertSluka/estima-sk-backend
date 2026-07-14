"""
Shared test fixtures.

`db` yields a RealDictCursor inside a transaction that is ALWAYS rolled back, so
DB tests never persist data. If Postgres is unreachable the test is skipped.
"""

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from src.config import DATABASE_URL


@pytest.fixture
def db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield cur
    finally:
        conn.rollback()
        cur.close()
        conn.close()
