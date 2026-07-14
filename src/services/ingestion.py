"""
Ingestion flow: Apify items → ingestion_runs → raw_listings → properties →
property_snapshots → price_changes, then recompute market_statistics.

raw_listings is append-only; properties/snapshots are upserted (idempotent per
day). Each item is processed inside a SAVEPOINT so one bad row can't abort the
whole batch.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.db import get_cursor
from src.repositories import (
    ingestion_runs,
    price_changes,
    properties,
    raw_listings,
    snapshots,
)
from src.services import normalizer

logger = logging.getLogger(__name__)


def _content_hash(raw: dict) -> str:
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ingest_items(
    items: list[dict],
    *,
    source: str | None = None,
    apify_meta: dict | None = None,
) -> dict:
    """
    Ingest a batch of raw scraper items as one ingestion run.

    Args:
        items:      raw scraper dicts (one source per batch is typical).
        source:     run-level source label; auto-detected from items if omitted.
        apify_meta: optional {actor_id, task_id, run_id, dataset_id}.

    Returns a stats dict.
    """
    run_time = datetime.now(timezone.utc)
    meta = apify_meta or {}
    run_source = source or (normalizer.detect_source(items[0]) if items else "unknown")

    stats = {
        "total": len(items),
        "new_properties": 0,
        "updated_properties": 0,
        "price_changes": 0,
        "failed": 0,
    }

    with get_cursor() as cur:
        run_id = ingestion_runs.create(
            cur,
            source=run_source,
            status="running",
            started_at=run_time,
            apify_actor_id=meta.get("actor_id"),
            apify_task_id=meta.get("task_id"),
            apify_run_id=meta.get("run_id"),
            apify_dataset_id=meta.get("dataset_id"),
        )

        for item in items:
            cur.execute("SAVEPOINT item")
            try:
                result = _ingest_one(cur, item, run_id, run_time)
                cur.execute("RELEASE SAVEPOINT item")
                stats["new_properties" if result["is_new"] else "updated_properties"] += 1
                if result["price_changed"]:
                    stats["price_changes"] += 1
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT item")
                logger.error("Failed to ingest item (%s): %s",
                             item.get("url") or item.get("listingId") or "?", exc)
                stats["failed"] += 1

        ingestion_runs.finish(
            cur,
            run_id,
            status="succeeded" if stats["failed"] == 0 else "completed_with_errors",
            finished_at=datetime.now(timezone.utc),
            item_count=stats["total"] - stats["failed"],
        )

    # Refresh market statistics for today (separate transaction).
    from src.services import market_statistics
    stats["market_stat_rows"] = market_statistics.generate(run_time.date())

    logger.info(
        "Ingestion run %s (%s) — new: %d, updated: %d, price changes: %d, failed: %d",
        run_id, run_source, stats["new_properties"], stats["updated_properties"],
        stats["price_changes"], stats["failed"],
    )
    return stats


def ingest_file(filepath: str, *, source: str | None = None,
                apify_meta: dict | None = None) -> dict:
    """Load listings from a JSON file (list or single object) and ingest them."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Listings file not found: {filepath}")

    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else [data]
    logger.info("Loaded %d listings from %s", len(items), filepath)
    return ingest_items(items, source=source, apify_meta=apify_meta)


# ── Internal ──────────────────────────────────────────────────────────────────


def _ingest_one(cur, item: dict, run_id: int, run_time: datetime) -> dict:
    norm = normalizer.normalize(item, run_time)

    raw_id = raw_listings.insert(
        cur,
        ingestion_run_id=run_id,
        source=norm["source"],
        source_listing_id=norm["source_listing_id"] or "unknown",
        url=norm["url"],
        scraped_at=norm["scraped_at"],
        raw_json=item,
        content_hash=_content_hash(item),
    )

    property_id, _old_price, is_new = properties.upsert(cur, norm, norm["scraped_at"])
    snapshot_id = snapshots.upsert(cur, property_id, norm, norm["scraped_at"], raw_id)

    # Price-change detection: compare today's price to the PREVIOUS snapshot.
    price_changed = False
    new_price = norm.get("price")
    snapshot_date = norm["scraped_at"].date()
    prev_price = snapshots.previous_price(cur, property_id, snapshot_date)
    if prev_price is not None and new_price is not None and prev_price != new_price:
        price_changes.insert(cur, property_id, prev_price, new_price, norm["scraped_at"])
        price_changed = True

    return {"is_new": is_new, "price_changed": price_changed,
            "property_id": property_id, "snapshot_id": snapshot_id}
