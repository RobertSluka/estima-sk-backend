import psycopg2
from psycopg2.extras import RealDictCursor, execute_values  # noqa: F401  (re-exported for callers)
from contextlib import contextmanager
from src.config import DATABASE_URL


def get_connection():
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def get_cursor(commit: bool = True):
    """
    Yield a RealDictCursor inside a managed transaction.
    Commits on clean exit; rolls back and re-raises on any exception.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
            if commit:
                conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def test_connection() -> bool:
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False
