"""
Street geocoding batch — extract streets from listing text and geocode them.

For every property not yet attempted (geocoded_at IS NULL): find a street
mention in the title/description (street_extraction), geocode the candidate
spellings against the listing's town (geocoding, cached + rate-limited), and
store the outcome. Every attempt is recorded — also misses — so re-runs only
process new listings; `--retry-missing` widens a run to previous misses.

Run via:  python -m src.main geocode-streets [--limit N] [--retry-missing]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.db import get_cursor
from src.repositories import properties
from src.services import geocoding, street_extraction

logger = logging.getLogger(__name__)


@dataclass
class GeocodeStats:
    processed: int = 0
    with_street: int = 0
    geocoded: int = 0


def run(limit: int = 500, retry_missing: bool = False) -> GeocodeStats:
    stats = GeocodeStats()
    with get_cursor() as cur:
        if retry_missing:
            cur.execute(
                "UPDATE properties SET geocoded_at = NULL "
                "WHERE geocoded_at IS NOT NULL AND geo_precision IS NULL"
            )
        pending = properties.list_geocode_pending(cur, limit)

    for row in pending:
        stats.processed += 1
        town = row.get("city") or row.get("locality")
        mention = street_extraction.extract_street(row.get("name"), row.get("content"))

        street = None
        geo: tuple[str, float, float] | None = None
        if mention and town:
            stats.with_street += 1
            geo = geocoding.geocode_mention(mention, town, row.get("lat"), row.get("lon"))
            street = geo[0] if geo else mention.candidates[0]

        # One commit per property so an interrupted batch keeps its progress.
        with get_cursor() as cur:
            properties.set_geocode_result(
                cur,
                row["id"],
                street=street,
                geo_lat=geo[1] if geo else None,
                geo_lon=geo[2] if geo else None,
                geo_precision="street" if geo else None,
            )
        if geo:
            stats.geocoded += 1
            logger.info("Property %s: %s, %s → %.5f, %.5f", row["id"], geo[0], town, geo[1], geo[2])

    logger.info(
        "Geocoding done: %d processed, %d had a street, %d geocoded",
        stats.processed, stats.with_street, stats.geocoded,
    )
    return stats
