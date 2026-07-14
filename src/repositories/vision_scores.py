"""vision_scores repository — latest per-property photo-quality metrics.

Keyed by property_id (one current score per property); re-scoring upserts in
place. Two column groups mirror the vision-scoring-service response:

* QUALITY_FIELDS — honest, measurable photo-quality metrics (the live
  contract; heuristic-cv >= 0.2.0). These feed feature generation.
* SCORE_FIELDS — DEPRECATED semantic attributes (kitchen quality, luxury,
  renovation…). Local providers cannot measure them; they stay NULL going
  forward and exist only so historic rows keep reading cleanly.

`image_set_hash` + `model_version` together are the skip-rescoring cache key
(see services/vision_scoring.py).
"""

import json

# DEPRECATED: semantic attributes local providers always leave NULL.
SCORE_FIELDS = (
    "overall_condition",
    "kitchen_quality",
    "bathroom_quality",
    "floor_quality",
    "natural_light",
    "renovation_need",
    "interior_modernity",
    "photo_quality",
    "luxury_level",
)

# Honest photo-quality metrics — the live contract with the vision service.
# Order is part of the feature-schema contract: feature generation and model
# training derive vision_* feature names from this tuple.
QUALITY_FIELDS = (
    "brightness",
    "contrast",
    "sharpness",
    "resolution_quality",
    "exposure_quality",
    "colorfulness",
    "image_quality",
    "gallery_consistency",
    "gallery_size",
    "blurry_image_ratio",
    "dark_image_ratio",
    "overexposed_image_ratio",
)


def mark_empty_attempt(cur, *, property_id: int, image_set_hash: str) -> bool:
    """Record that scoring this gallery produced an empty result.

    UPDATE-only and touches nothing but the two attempt columns, so stored
    metrics are never degraded by a transient outage. Returns False when the
    property has no vision_scores row at all (nothing to mark — such
    properties simply stay pending and are retried next run).
    """
    cur.execute(
        """
        UPDATE vision_scores
        SET empty_attempt_hash = %s, empty_attempted_at = NOW()
        WHERE property_id = %s
        """,
        (image_set_hash, property_id),
    )
    return cur.rowcount > 0


def get(cur, property_id: int) -> dict | None:
    """Return the stored row (all score + quality columns) or None."""
    cols = ", ".join(SCORE_FIELDS + QUALITY_FIELDS)
    cur.execute(
        f"""
        SELECT {cols}, model_provider, model_name, model_version,
               image_set_hash, warnings, confidence, image_count, scored_at
        FROM vision_scores WHERE property_id = %s
        """,
        (property_id,),
    )
    return cur.fetchone()


def upsert(
    cur,
    *,
    property_id: int,
    snapshot_id: int | None,
    model_provider: str,
    model_name: str,
    model_version: str,
    scores: dict,
    confidence: float | None,
    image_count: int | None,
    scored_at,
    quality: dict | None = None,
    image_set_hash: str | None = None,
    warnings: list[str] | None = None,
) -> int:
    """Insert or replace the vision score for one property. Returns its id.

    `scores` is the (deprecated) semantic block; `quality` the measurable
    photo-quality metrics. Missing attributes become NULL. Unique on
    property_id, so a re-score overwrites the previous row.
    """
    quality = quality or {}
    params = {
        "property_id": property_id,
        "snapshot_id": snapshot_id,
        "model_provider": model_provider,
        "model_name": model_name,
        "model_version": model_version,
        "confidence": confidence,
        "image_count": image_count,
        "scored_at": scored_at,
        "image_set_hash": image_set_hash,
        "warnings": json.dumps(warnings) if warnings is not None else None,
        **{field: scores.get(field) for field in SCORE_FIELDS},
        **{field: quality.get(field) for field in QUALITY_FIELDS},
    }
    all_fields = SCORE_FIELDS + QUALITY_FIELDS
    cur.execute(
        f"""
        INSERT INTO vision_scores (
            property_id, snapshot_id,
            model_provider, model_name, model_version,
            {", ".join(all_fields)},
            image_set_hash, warnings,
            confidence, image_count, scored_at
        ) VALUES (
            %(property_id)s, %(snapshot_id)s,
            %(model_provider)s, %(model_name)s, %(model_version)s,
            {", ".join(f"%({f})s" for f in all_fields)},
            %(image_set_hash)s, %(warnings)s,
            %(confidence)s, %(image_count)s, %(scored_at)s
        )
        ON CONFLICT (property_id) DO UPDATE SET
            snapshot_id    = EXCLUDED.snapshot_id,
            model_provider = EXCLUDED.model_provider,
            model_name     = EXCLUDED.model_name,
            model_version  = EXCLUDED.model_version,
            {", ".join(f"{f} = EXCLUDED.{f}" for f in all_fields)},
            image_set_hash = EXCLUDED.image_set_hash,
            warnings       = EXCLUDED.warnings,
            confidence     = EXCLUDED.confidence,
            image_count    = EXCLUDED.image_count,
            scored_at      = EXCLUDED.scored_at
        RETURNING id
        """,
        params,
    )
    return cur.fetchone()["id"]
