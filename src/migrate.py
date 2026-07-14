"""
Minimal SQL migration runner.

Applies sql/migrations/*.sql in filename order, recording each applied file in a
schema_migrations table so re-runs are no-ops. Each file runs in its own
transaction (the files themselves wrap their body in BEGIN/COMMIT, and we also
guard with the tracking table).

Usage:
    python -m src.main migrate
    python -m src.migrate            # equivalent
"""

import logging
from pathlib import Path

from src.db import get_cursor

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"


def _ensure_tracking_table() -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    TEXT        PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def _applied() -> set[str]:
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row["filename"] for row in cur.fetchall()}


def run_migrations() -> list[str]:
    """Apply all pending migrations. Returns the list of filenames applied."""
    _ensure_tracking_table()
    applied = _applied()

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        logger.warning("No migration files found in %s", MIGRATIONS_DIR)
        return []

    newly_applied: list[str] = []
    for path in files:
        if path.name in applied:
            logger.info("skip  %s (already applied)", path.name)
            continue

        logger.info("apply %s", path.name)
        sql = path.read_text(encoding="utf-8")
        # Each migration file manages its own BEGIN/COMMIT; get_cursor commits
        # the tracking insert. We run the file body then record it.
        with get_cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (path.name,),
            )
        newly_applied.append(path.name)

    logger.info("Migrations complete — %d applied, %d already present",
                len(newly_applied), len(files) - len(newly_applied))
    return newly_applied


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_migrations()
