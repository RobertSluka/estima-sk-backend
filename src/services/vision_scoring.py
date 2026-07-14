"""
Vision scoring bridge: properties' galleries → vision-scoring-service → vision_scores.

Reads active properties with a photo gallery, POSTs each gallery to the local
vision-scoring-service `/score` endpoint (deterministic photo-quality metrics,
no external AI APIs), and upserts the returned metrics into `vision_scores`.

Scoring is cached on (image_set_hash, model_version): a property is skipped
when its current gallery hashes to what's already stored AND the stored row
was produced by the vision service's currently active scoring version (looked
up once per run via GET /models; unavailable → hash-only skip). Re-running
the batch only touches new/changed galleries or rows from an older scoring
version. `--rescore` forces everything.
Empty results (no image could be downloaded/decoded) are never persisted, so
a transient outage cannot overwrite or poison a valid stored score.

Run via:  python -m src.main score-vision --limit 100 [--rescore]

`score_on_demand` is a second entry point for a single property, used by
report generation (src/services/reports/builder.py) to fill in a score at
request time when the batch job hasn't reached that property yet.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from src import config
from src.db import get_cursor
from src.repositories import vision_scores

logger = logging.getLogger(__name__)

# The vision service accepts only these source labels; anything else → "other".
_KNOWN_SOURCES = {"sreality", "bezrealitky"}

# Candidate properties: active with a non-empty gallery. The stored hash and
# scoring version ride along so Python can decide what actually needs scoring.
# The lateral join attaches the most recent snapshot id purely for lineage.
_CANDIDATES_SQL = """
    SELECT
        p.id           AS property_id,
        p.source,
        p.images,
        p.layout,
        p.floor_area,
        p.district,
        s.id           AS snapshot_id,
        v.image_set_hash AS stored_hash,
        v.model_version  AS stored_model_version,
        v.gallery_size   AS stored_gallery_size,
        v.image_count    AS stored_image_count,
        v.empty_attempt_hash,
        v.empty_attempted_at
    FROM properties p
    LEFT JOIN LATERAL (
        SELECT id FROM property_snapshots ps
        WHERE ps.property_id = p.id
        ORDER BY ps.snapshot_date DESC
        LIMIT 1
    ) s ON TRUE
    LEFT JOIN vision_scores v ON v.property_id = p.id
    WHERE p.active
      AND jsonb_array_length(p.images) > 0
    ORDER BY p.id
"""


def gallery_hash(image_urls: list[str]) -> str:
    """Stable identity of an ordered image gallery.

    SHA-256 over the newline-joined URLs in order — the identical algorithm
    the vision service uses (app/vision/base.py:image_set_hash), so both
    sides agree on when a gallery is "the same". Cross-repo contract: change
    it in both places or not at all.
    """
    return hashlib.sha256("\n".join(image_urls).encode("utf-8")).hexdigest()


def fetch_active_model_version(
    base_url: str,
    *,
    timeout: int,
    session: requests.Session | None = None,
) -> str | None:
    """The vision service's currently active scoring version, or None.

    One GET /models per batch run. None (endpoint unreachable, malformed
    response, no active provider) degrades the skip check to hash-only rather
    than blocking the batch.
    """
    http = session or requests
    try:
        resp = http.get(f"{base_url.rstrip('/')}/models", timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        for provider in body.get("providers", []):
            if provider.get("active"):
                return provider.get("model_version")
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not fetch active vision model version: %s", exc)
    return None


def _in_empty_cooldown(row: dict, current_hash: str, now: datetime) -> bool:
    """True while a gallery that last yielded an empty result should rest.

    Applies only while the gallery is unchanged (same hash) and the attempt
    is younger than VISION_EMPTY_RETRY_DAYS — new photos or an aged-out
    attempt retry normally.
    """
    if row.get("empty_attempt_hash") != current_hash:
        return False
    attempted_at = row.get("empty_attempted_at")
    if attempted_at is None:
        return False
    return now - attempted_at < timedelta(days=config.VISION_EMPTY_RETRY_DAYS)


def _select_pending(
    cur, *, limit: int, rescore: bool, max_images: int,
    active_version: str | None = None,
) -> list[dict]:
    """Candidates that actually need scoring, capped at `limit`.

    Without `rescore`, a property is skipped when a score row exists, its
    stored image_set_hash matches the current gallery (same images, already
    scored), and — when `active_version` is known — the row was scored by
    that version. Hash mismatch, a pre-hash legacy row, or an outdated
    scoring version re-scores. Galleries whose last attempt analysed zero
    images rest for VISION_EMPTY_RETRY_DAYS (see _in_empty_cooldown).
    """
    cur.execute(_CANDIDATES_SQL)
    rows = cur.fetchall()

    now = datetime.now(timezone.utc)
    pending: list[dict] = []
    for row in rows:
        current_hash = gallery_hash(list(row["images"])[:max_images])
        version_current = (
            active_version is None
            or row["stored_model_version"] == active_version
        )
        if not rescore and row["stored_hash"] == current_hash and version_current:
            continue
        if not rescore and _in_empty_cooldown(row, current_hash, now):
            continue
        row["current_hash"] = current_hash
        pending.append(row)
        if len(pending) >= limit:
            break
    return pending


def _build_request(row: dict, *, max_images: int) -> dict:
    """Map a property row to a vision-service /score request body."""
    source = row["source"] if row["source"] in _KNOWN_SOURCES else "other"
    metadata = {
        "layout": row.get("layout"),
        "floor_area": float(row["floor_area"]) if row.get("floor_area") is not None else None,
        "district": row.get("district"),
    }
    return {
        "property_id": str(row["property_id"]),
        "snapshot_id": str(row["snapshot_id"]) if row.get("snapshot_id") is not None else "0",
        "image_urls": list(row["images"])[:max_images],
        "source": source,
        "metadata": {k: v for k, v in metadata.items() if v is not None},
    }


def score_one(
    payload: dict,
    *,
    base_url: str,
    timeout: int,
    session: requests.Session | None = None,
) -> dict:
    """POST one /score request and return the parsed ScoreResponse JSON.

    Raises requests.HTTPError on a non-2xx response so the caller can count it
    as a failure without aborting the whole batch.
    """
    http = session or requests
    resp = http.post(f"{base_url.rstrip('/')}/score", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _result_is_empty(result: dict) -> bool:
    """True when scoring analysed zero images (nothing worth persisting)."""
    quality = result.get("quality") or {}
    if quality.get("gallery_size"):
        return False
    return "no_images_provided" in (result.get("warnings") or []) or not quality


def _persist(cur_factory, row: dict, payload: dict, result: dict) -> None:
    with cur_factory() as cur:
        vision_scores.upsert(
            cur,
            property_id=row["property_id"],
            snapshot_id=row.get("snapshot_id"),
            model_provider=result.get("model_provider", "unknown"),
            model_name=result.get("model_name", "unknown"),
            model_version=result.get("model_version", "unknown"),
            scores=result.get("scores") or {},
            quality=result.get("quality") or {},
            # Prefer the hash the service reports; fall back to the local
            # computation over the exact list we sent (same algorithm).
            image_set_hash=result.get("image_set_hash")
            or gallery_hash(payload["image_urls"]),
            warnings=result.get("warnings") or [],
            confidence=result.get("confidence"),
            image_count=len(payload["image_urls"]),
            scored_at=result.get("scored_at"),
        )


def run(
    *,
    limit: int = 100,
    rescore: bool = False,
    base_url: str | None = None,
    timeout: int | None = None,
    max_images: int | None = None,
) -> dict:
    """Score pending properties and store results. Returns counts.

    One failed listing (HTTP error, bad payload, empty gallery result) is
    logged and skipped; the rest of the batch still proceeds. Empty results
    are counted under `empty` and never overwrite an existing row.
    """
    base_url = base_url or config.VISION_SERVICE_URL
    timeout = timeout or config.VISION_SCORE_TIMEOUT_SECONDS
    max_images = max_images or config.VISION_MAX_IMAGES

    session = requests.Session()
    active_version = fetch_active_model_version(
        base_url, timeout=timeout, session=session,
    )

    with get_cursor() as cur:
        pending = _select_pending(
            cur, limit=limit, rescore=rescore, max_images=max_images,
            active_version=active_version,
        )

    scored = 0
    failed = 0
    empty = 0
    for row in pending:
        payload = _build_request(row, max_images=max_images)
        try:
            result = score_one(payload, base_url=base_url, timeout=timeout, session=session)
        except (requests.RequestException, ValueError) as exc:
            failed += 1
            logger.warning("Vision scoring failed for property %s: %s",
                           row["property_id"], exc)
            continue

        if _result_is_empty(result):
            # Nothing was analysable (dead URLs, undecodable files). Keep any
            # existing metrics untouched; record the attempt so this gallery
            # rests for VISION_EMPTY_RETRY_DAYS instead of re-downloading on
            # every run. Properties without a row yet stay pending.
            empty += 1
            with get_cursor() as cur:
                vision_scores.mark_empty_attempt(
                    cur,
                    property_id=row["property_id"],
                    image_set_hash=row.get("current_hash")
                    or gallery_hash(payload["image_urls"]),
                )
            logger.warning("Vision scoring returned an empty result for property %s; "
                           "not persisting", row["property_id"])
            continue

        _persist(get_cursor, row, payload, result)
        scored += 1

    logger.info(
        "Vision scoring complete — scored: %d, failed: %d, empty: %d, pending seen: %d",
        scored, failed, empty, len(pending),
    )
    return {"scored": scored, "failed": failed, "empty": empty, "pending": len(pending)}


def score_on_demand(prop_row: dict) -> Optional[dict]:
    """Score one property's gallery synchronously and persist the result.

    `prop_row` needs: id, source, images, layout, floor_area, district
    (report generation's own property fetch already selects all of these —
    see builder.py's `_fetch_property`). No snapshot_id is attached — the
    report path doesn't look one up, and it's lineage-only.

    Bounded by VISION_ON_DEMAND_TIMEOUT_SECONDS / _MAX_IMAGES (tighter than
    the batch job) so a slow or unreachable vision service degrades the
    report's vision section instead of stalling PDF generation. Returns a
    dict shaped like a `vision_scores` row (SCORE_FIELDS + QUALITY_FIELDS +
    model_provider + warnings + confidence + image_count + scored_at) — the
    same shape the repository's `get` returns — or None if there are no
    images or the call fails or yields an empty (zero analysed images)
    result. Empty results are never persisted.
    """
    if not prop_row.get("images"):
        return None

    # _build_request (shared with the batch path) keys off "property_id";
    # callers here only need to supply the property's "id".
    request_row = {**prop_row, "property_id": prop_row["id"]}
    payload = _build_request(request_row, max_images=config.VISION_ON_DEMAND_MAX_IMAGES)
    if not payload["image_urls"]:
        return None

    try:
        result = score_one(
            payload,
            base_url=config.VISION_SERVICE_URL,
            timeout=config.VISION_ON_DEMAND_TIMEOUT_SECONDS,
        )
    except (requests.RequestException, ValueError) as exc:
        logger.warning("On-demand vision scoring failed for property %s: %s",
                       prop_row["id"], exc)
        return None

    if _result_is_empty(result):
        logger.warning("On-demand vision scoring analysed no images for property %s",
                       prop_row["id"])
        return None

    _persist(get_cursor, request_row, payload, result)

    scores = result.get("scores") or {}
    quality = result.get("quality") or {}
    row = {field: scores.get(field) for field in vision_scores.SCORE_FIELDS}
    row.update({field: quality.get(field) for field in vision_scores.QUALITY_FIELDS})
    row["model_provider"] = result.get("model_provider", "unknown")
    row["model_name"] = result.get("model_name", "unknown")
    row["model_version"] = result.get("model_version", "unknown")
    row["image_set_hash"] = result.get("image_set_hash")
    row["warnings"] = result.get("warnings") or []
    row["confidence"] = result.get("confidence")
    row["image_count"] = len(payload["image_urls"])
    row["scored_at"] = result.get("scored_at")
    return row
