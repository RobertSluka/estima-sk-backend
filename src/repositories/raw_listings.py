"""raw_listings repository — append-only verbatim scraper items, all sources."""

from datetime import datetime

from psycopg2.extras import Json


def insert(
    cur,
    *,
    ingestion_run_id: int | None,
    source: str,
    source_listing_id: str,
    url: str | None,
    scraped_at: datetime,
    raw_json: dict,
    content_hash: str | None,
) -> int:
    """Append a raw listing. Always inserts — never updates or deletes."""
    cur.execute(
        """
        INSERT INTO raw_listings (
            ingestion_run_id, source, source_listing_id, url,
            scraped_at, raw_json, content_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (ingestion_run_id, source, source_listing_id, url,
         scraped_at, Json(raw_json), content_hash),
    )
    return cur.fetchone()["id"]
