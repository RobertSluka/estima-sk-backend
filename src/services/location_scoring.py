"""
Location-score warmup: properties' coordinates → Overpass → location_scores.

Reads active properties with coordinates but no cached location score, queries
Overpass once per property (see src/services/reports/geo.py), and upserts the
counts + score into `location_scores`. This is what makes report generation
fast for previously-warmed properties even after a process restart — the
in-process cache in geo.py is lost on restart, but this table isn't.

Throttled: Overpass is a shared public service (usage policy asks for
reasonable, non-bulk request rates — observed in practice to 429 above
roughly 1 request/sec under load), so this sleeps between requests rather
than firing all of them at once. A full pass over ~1,900 properties at the
default rate takes a bit over an hour; rerunning only processes properties
still missing a score, so a partial/interrupted run is safe to resume.

Run via:  python -m src.main warm-locations --limit 100 --rate 0.5
"""

from __future__ import annotations

import logging
import time

from src.db import get_cursor
from src.repositories import location_scores
from src.services.reports import geo

logger = logging.getLogger(__name__)

_PENDING_SQL = """
    SELECT id, lat, lon
    FROM properties
    WHERE active
      AND lat IS NOT NULL
      AND lon IS NOT NULL
      {missing_clause}
    ORDER BY id
    LIMIT %(limit)s
"""


def _select_pending(cur, *, limit: int, rescore: bool) -> list[dict]:
    missing_clause = (
        "" if rescore
        else "AND NOT EXISTS (SELECT 1 FROM location_scores l WHERE l.property_id = id)"
    )
    cur.execute(_PENDING_SQL.format(missing_clause=missing_clause), {"limit": limit})
    return cur.fetchall()


def run(*, limit: int = 100, rescore: bool = False, rate: float = 0.5) -> dict:
    """Warm location scores for pending properties. Returns counts.

    `rate` caps requests per second against Overpass (politeness throttle,
    not a hard rate-limiter — one Overpass call takes several seconds itself,
    so this mostly matters for the sleep between fast cache hits/failures).
    One failed lookup is logged and skipped; the rest of the batch proceeds.
    """
    with get_cursor() as cur:
        pending = _select_pending(cur, limit=limit, rescore=rescore)

    delay = 1.0 / rate if rate > 0 else 0.0
    scored = 0
    failed = 0
    for i, row in enumerate(pending):
        if i > 0 and delay:
            time.sleep(delay)

        counts = geo.fetch_poi_counts(row["lat"], row["lon"])
        if counts is None:
            failed += 1
            logger.warning("Location warmup failed for property %s", row["id"])
            continue

        score = geo.location_score(counts)
        with get_cursor() as cur:
            location_scores.upsert(
                cur,
                property_id=row["id"],
                counts=geo.poi_counts_to_location_fields(counts),
                location_score=score,
            )
        scored += 1

    logger.info("Location warmup complete — scored: %d, failed: %d, pending seen: %d",
                scored, failed, len(pending))
    return {"scored": scored, "failed": failed, "pending": len(pending)}
