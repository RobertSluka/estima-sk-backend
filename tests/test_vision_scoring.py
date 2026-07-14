"""Vision scoring bridge tests.

The pure request-building, hash/skip logic, and the HTTP call are tested
without a network or the vision service. The repository upsert runs against
Postgres inside the rolled-back `db` fixture (skipped if Postgres is
unavailable).
"""

from datetime import datetime, timezone

import pytest
import requests

from src.repositories import vision_scores
from src.services import vision_scoring as vs

SCORED_AT = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)

# Legacy semantic block — local providers now always send nulls, but the
# repository must still round-trip historic non-null rows.
SAMPLE_SCORES = {field: None for field in vision_scores.SCORE_FIELDS}

SAMPLE_QUALITY = {
    "brightness": 0.68,
    "contrast": 0.37,
    "sharpness": 0.44,
    "resolution_quality": 0.52,
    "exposure_quality": 1.0,
    "colorfulness": 0.32,
    "image_quality": 0.53,
    "gallery_consistency": 0.13,
    "gallery_size": 2,
    "blurry_image_ratio": 0.0,
    "dark_image_ratio": 0.0,
    "overexposed_image_ratio": 0.0,
}


def _service_result(**overrides) -> dict:
    result = {
        "scores": dict(SAMPLE_SCORES),
        "quality": dict(SAMPLE_QUALITY),
        "image_set_hash": vs.gallery_hash(["a.jpg", "b.jpg"]),
        "warnings": [],
        "confidence": 0.8,
        "model_provider": "heuristic",
        "model_name": "heuristic-cv",
        "model_version": "0.2.0",
        "scored_at": SCORED_AT.isoformat(),
    }
    result.update(overrides)
    return result


# ── gallery_hash (cross-repo contract) ────────────────────────────────────────


def test_gallery_hash_is_stable_and_order_sensitive():
    assert vs.gallery_hash(["a", "b"]) == vs.gallery_hash(["a", "b"])
    assert vs.gallery_hash(["a", "b"]) != vs.gallery_hash(["b", "a"])
    # Known-answer: must equal the vision service's image_set_hash(["u1","u2"]).
    assert vs.gallery_hash(["u1", "u2"]) == (
        "c9abf63c8b58c51cc0c51b6f08269fd967546364f57033de39723f9d52c41f78"
    )


# ── _build_request (pure) ─────────────────────────────────────────────────────


def test_build_request_maps_fields():
    row = {
        "property_id": 42,
        "source": "sreality",
        "images": ["a.jpg", "b.jpg"],
        "layout": "2+kk",
        "floor_area": 55,
        "district": "Praha 5",
        "snapshot_id": 99,
    }
    req = vs._build_request(row, max_images=50)
    assert req["property_id"] == "42"        # stringified for the vision schema
    assert req["snapshot_id"] == "99"
    assert req["source"] == "sreality"
    assert req["image_urls"] == ["a.jpg", "b.jpg"]
    assert req["metadata"] == {"layout": "2+kk", "floor_area": 55.0, "district": "Praha 5"}


def test_build_request_unknown_source_becomes_other():
    row = {"property_id": 1, "source": "idnes", "images": ["a.jpg"],
           "layout": None, "floor_area": None, "district": None, "snapshot_id": None}
    req = vs._build_request(row, max_images=50)
    assert req["source"] == "other"
    assert req["snapshot_id"] == "0"          # no snapshot → placeholder
    assert req["metadata"] == {}              # all-None metadata dropped


def test_build_request_caps_image_count():
    row = {"property_id": 1, "source": "sreality", "images": [f"{i}.jpg" for i in range(60)],
           "layout": None, "floor_area": None, "district": None, "snapshot_id": 1}
    req = vs._build_request(row, max_images=50)
    assert len(req["image_urls"]) == 50


# ── _select_pending (hash-based skip) ─────────────────────────────────────────


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return [dict(r) for r in self._rows]


def _candidate(pid, images, stored_hash=None):
    return {
        "property_id": pid, "source": "sreality", "images": images,
        "layout": None, "floor_area": None, "district": None,
        "snapshot_id": None, "stored_hash": stored_hash,
        "stored_model_version": "0.2.0" if stored_hash else None,
        "stored_gallery_size": 2 if stored_hash else None,
        "stored_image_count": 2 if stored_hash else None,
    }


def test_select_pending_skips_unchanged_galleries():
    images = ["a.jpg", "b.jpg"]
    rows = [
        _candidate(1, images, stored_hash=vs.gallery_hash(images)),  # unchanged
        _candidate(2, images, stored_hash=None),                     # never scored
        _candidate(3, images, stored_hash="stale-hash"),             # gallery changed
    ]
    pending = vs._select_pending(_FakeCursor(rows), limit=10, rescore=False, max_images=50)
    assert [r["property_id"] for r in pending] == [2, 3]
    assert all(r["current_hash"] == vs.gallery_hash(images) for r in pending)


def test_select_pending_rescores_outdated_scoring_version():
    # Same gallery hash, but the stored row was produced by an older scoring
    # version than the service's active one → must re-score.
    images = ["a.jpg", "b.jpg"]
    rows = [_candidate(1, images, stored_hash=vs.gallery_hash(images))]  # version 0.2.0

    pending = vs._select_pending(_FakeCursor(rows), limit=10, rescore=False,
                                 max_images=50, active_version="0.3.0")
    assert [r["property_id"] for r in pending] == [1]

    # Matching version (or unknown → hash-only fallback) still skips.
    assert vs._select_pending(_FakeCursor(rows), limit=10, rescore=False,
                              max_images=50, active_version="0.2.0") == []
    assert vs._select_pending(_FakeCursor(rows), limit=10, rescore=False,
                              max_images=50, active_version=None) == []


def test_select_pending_respects_empty_attempt_cooldown():
    from datetime import datetime, timedelta, timezone

    images = ["dead.jpg"]
    h = vs.gallery_hash(images)
    now = datetime.now(timezone.utc)

    fresh = {**_candidate(1, images, stored_hash=None),
             "empty_attempt_hash": h, "empty_attempted_at": now - timedelta(days=1)}
    aged = {**_candidate(2, images, stored_hash=None),
            "empty_attempt_hash": h, "empty_attempted_at": now - timedelta(days=30)}
    changed = {**_candidate(3, ["new.jpg"], stored_hash=None),
               "empty_attempt_hash": h, "empty_attempted_at": now - timedelta(days=1)}

    pending = vs._select_pending(_FakeCursor([fresh, aged, changed]),
                                 limit=10, rescore=False, max_images=50)
    # Fresh failure rests; an aged-out attempt and a changed gallery retry.
    assert [r["property_id"] for r in pending] == [2, 3]

    # --rescore ignores the cool-down entirely.
    pending = vs._select_pending(_FakeCursor([fresh]), limit=10, rescore=True, max_images=50)
    assert [r["property_id"] for r in pending] == [1]


def test_select_pending_rescore_includes_everything():
    images = ["a.jpg"]
    rows = [_candidate(1, images, stored_hash=vs.gallery_hash(images))]
    pending = vs._select_pending(_FakeCursor(rows), limit=10, rescore=True, max_images=50)
    assert [r["property_id"] for r in pending] == [1]


def test_select_pending_applies_limit_after_filtering():
    images = ["a.jpg"]
    done = vs.gallery_hash(images)
    rows = [_candidate(1, images, done)] + [
        _candidate(i, images) for i in range(2, 6)
    ]
    pending = vs._select_pending(_FakeCursor(rows), limit=2, rescore=False, max_images=50)
    assert [r["property_id"] for r in pending] == [2, 3]


def test_select_pending_hashes_truncated_gallery():
    # The hash must cover exactly the URL list that gets sent (max_images cap).
    images = [f"{i}.jpg" for i in range(10)]
    stored = vs.gallery_hash(images[:3])
    rows = [_candidate(1, images, stored)]
    pending = vs._select_pending(_FakeCursor(rows), limit=10, rescore=False, max_images=3)
    assert pending == []  # truncated gallery unchanged → skip


# ── score_one (HTTP, faked session) ──────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self._response

    def get(self, url, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        return self._response


def test_fetch_active_model_version_reads_models_endpoint():
    body = {"providers": [
        {"provider": "mock", "model_version": "2.0.0", "active": False},
        {"provider": "heuristic", "model_version": "0.2.0", "active": True},
    ], "active_provider": "heuristic"}
    session = _FakeSession(_FakeResponse(body))

    version = vs.fetch_active_model_version("http://vision:8000/", timeout=5, session=session)

    assert version == "0.2.0"
    assert session.calls[0]["url"] == "http://vision:8000/models"


def test_fetch_active_model_version_none_on_error():
    session = _FakeSession(_FakeResponse({}, status=500))
    assert vs.fetch_active_model_version("http://vision:8000", timeout=5, session=session) is None


def test_score_one_posts_and_returns_json():
    payload = {"property_id": "1", "image_urls": ["a.jpg"], "source": "sreality",
               "snapshot_id": "1", "metadata": {}}
    response_body = _service_result()
    session = _FakeSession(_FakeResponse(response_body))

    out = vs.score_one(payload, base_url="http://vision:8000/", timeout=30, session=session)

    assert out == response_body
    assert session.calls[0]["url"] == "http://vision:8000/score"   # trailing slash trimmed
    assert session.calls[0]["json"] == payload


def test_score_one_raises_on_http_error():
    session = _FakeSession(_FakeResponse({}, status=500))
    with pytest.raises(requests.HTTPError):
        vs.score_one({}, base_url="http://vision:8000", timeout=5, session=session)


# ── run (batch): empty results never clobber stored rows ─────────────────────


class _NullCursorCtx:
    """Stand-in for `get_cursor()` — the fake `upsert` never touches it."""

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def test_run_does_not_persist_empty_results(monkeypatch):
    pending = [_candidate(1, ["a.jpg"], stored_hash="old")]
    empty_result = _service_result(
        quality={**SAMPLE_QUALITY, "gallery_size": 0},
        warnings=["no_images_provided"],
        confidence=0.0,
    )
    marked = {}

    def fail_upsert(cur, **kwargs):
        raise AssertionError("empty result must not be persisted")

    monkeypatch.setattr(vs, "get_cursor", lambda: _NullCursorCtx())
    monkeypatch.setattr(vs, "fetch_active_model_version", lambda *a, **kw: "0.2.0")
    monkeypatch.setattr(vs, "_select_pending", lambda cur, **kw: pending)
    monkeypatch.setattr(vs, "score_one", lambda *a, **kw: empty_result)
    monkeypatch.setattr(vision_scores, "upsert", fail_upsert)
    monkeypatch.setattr(vision_scores, "mark_empty_attempt",
                        lambda cur, **kwargs: marked.update(kwargs) or True)

    stats = vs.run(limit=10, base_url="http://vision:8000", timeout=5, max_images=50)
    assert stats == {"scored": 0, "failed": 0, "empty": 1, "pending": 1}
    # The failed attempt is recorded (back-off marker), keyed by gallery hash.
    assert marked == {"property_id": 1, "image_set_hash": vs.gallery_hash(["a.jpg"])}


def test_run_persists_valid_results_with_hash(monkeypatch):
    pending = [_candidate(1, ["a.jpg", "b.jpg"])]
    upserted = {}

    monkeypatch.setattr(vs, "get_cursor", lambda: _NullCursorCtx())
    monkeypatch.setattr(vs, "fetch_active_model_version", lambda *a, **kw: "0.2.0")
    monkeypatch.setattr(vs, "_select_pending", lambda cur, **kw: pending)
    monkeypatch.setattr(vs, "score_one", lambda *a, **kw: _service_result())
    monkeypatch.setattr(vision_scores, "upsert",
                        lambda cur, **kwargs: upserted.update(kwargs) or 1)

    stats = vs.run(limit=10, base_url="http://vision:8000", timeout=5, max_images=50)
    assert stats["scored"] == 1
    assert upserted["quality"]["image_quality"] == SAMPLE_QUALITY["image_quality"]
    assert upserted["image_set_hash"] == vs.gallery_hash(["a.jpg", "b.jpg"])
    assert upserted["model_version"] == "0.2.0"
    assert upserted["warnings"] == []


# ── repository upsert (DB) ───────────────────────────────────────────────────


def _insert_property(db) -> int:
    db.execute(
        """
        INSERT INTO properties (source, source_listing_id, deal_type, images)
        VALUES ('sreality', '_vis_test_1', 'buy', '["a.jpg"]'::jsonb)
        RETURNING id
        """
    )
    return db.fetchone()["id"]


def test_vision_scores_upsert_roundtrip(db):
    pid = _insert_property(db)

    vid = vision_scores.upsert(
        db, property_id=pid, snapshot_id=None,
        model_provider="heuristic", model_name="heuristic-cv", model_version="0.2.0",
        scores=SAMPLE_SCORES, quality=SAMPLE_QUALITY,
        image_set_hash=vs.gallery_hash(["a.jpg"]), warnings=["small_gallery"],
        confidence=0.8, image_count=2, scored_at=SCORED_AT,
    )
    assert vid is not None

    db.execute("SELECT * FROM vision_scores WHERE id = %s", (vid,))
    row = db.fetchone()
    assert row["property_id"] == pid
    assert row["overall_condition"] is None            # deprecated → NULL
    assert float(row["brightness"]) == 0.68
    assert float(row["image_quality"]) == 0.53
    assert row["gallery_size"] == 2
    assert row["image_set_hash"] == vs.gallery_hash(["a.jpg"])
    assert row["warnings"] == ["small_gallery"]
    assert row["image_count"] == 2
    assert row["model_provider"] == "heuristic"


def test_vision_scores_upsert_is_idempotent(db):
    pid = _insert_property(db)
    first = vision_scores.upsert(
        db, property_id=pid, snapshot_id=None,
        model_provider="heuristic", model_name="heuristic-cv", model_version="0.2.0",
        scores=SAMPLE_SCORES, quality=SAMPLE_QUALITY,
        image_set_hash="h1", confidence=0.8, image_count=2, scored_at=SCORED_AT,
    )
    # Re-score the same property: overwrites in place, same row id, new values.
    second = vision_scores.upsert(
        db, property_id=pid, snapshot_id=None,
        model_provider="heuristic", model_name="heuristic-cv", model_version="0.3.0",
        scores=SAMPLE_SCORES, quality={**SAMPLE_QUALITY, "brightness": 0.11},
        image_set_hash="h2", confidence=0.9, image_count=5, scored_at=SCORED_AT,
    )
    assert first == second                      # unique on property_id

    db.execute("SELECT COUNT(*) AS n FROM vision_scores WHERE property_id = %s", (pid,))
    assert db.fetchone()["n"] == 1
    db.execute("SELECT brightness, model_version, image_set_hash FROM vision_scores WHERE id = %s",
               (first,))
    row = db.fetchone()
    assert float(row["brightness"]) == 0.11
    assert row["model_version"] == "0.3.0"
    assert row["image_set_hash"] == "h2"


def test_mark_empty_attempt_preserves_metrics(db):
    pid = _insert_property(db)
    vid = vision_scores.upsert(
        db, property_id=pid, snapshot_id=None,
        model_provider="heuristic", model_name="heuristic-cv", model_version="0.2.0",
        scores=SAMPLE_SCORES, quality=SAMPLE_QUALITY,
        image_set_hash="h1", warnings=[], confidence=0.8, image_count=2,
        scored_at=SCORED_AT,
    )

    assert vision_scores.mark_empty_attempt(db, property_id=pid, image_set_hash="h-dead")

    db.execute("SELECT brightness, image_set_hash, empty_attempt_hash, empty_attempted_at "
               "FROM vision_scores WHERE id = %s", (vid,))
    row = db.fetchone()
    # Attempt columns set; stored metrics and the valid-score hash untouched.
    assert row["empty_attempt_hash"] == "h-dead"
    assert row["empty_attempted_at"] is not None
    assert float(row["brightness"]) == 0.68
    assert row["image_set_hash"] == "h1"


def test_mark_empty_attempt_without_row_is_a_noop(db):
    pid = _insert_property(db)
    assert vision_scores.mark_empty_attempt(db, property_id=pid, image_set_hash="h") is False


def test_vision_scores_get_returns_quality_columns(db):
    pid = _insert_property(db)
    vision_scores.upsert(
        db, property_id=pid, snapshot_id=None,
        model_provider="heuristic", model_name="heuristic-cv", model_version="0.2.0",
        scores=SAMPLE_SCORES, quality=SAMPLE_QUALITY,
        image_set_hash="h1", warnings=[], confidence=0.8, image_count=2,
        scored_at=SCORED_AT,
    )
    row = vision_scores.get(db, pid)
    assert row is not None
    assert float(row["sharpness"]) == 0.44
    assert row["model_version"] == "0.2.0"
    assert row["kitchen_quality"] is None


# ── score_on_demand (report-generation path, no network/DB) ──────────────────


def test_score_on_demand_returns_none_without_images():
    row = {"id": 1, "source": "sreality", "images": [],
           "layout": None, "floor_area": None, "district": None}
    assert vs.score_on_demand(row) is None


def test_score_on_demand_returns_none_on_request_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("vision service down")

    monkeypatch.setattr(vs, "score_one", boom)
    row = {"id": 7, "source": "sreality", "images": ["a.jpg"],
           "layout": None, "floor_area": None, "district": None}
    assert vs.score_on_demand(row) is None


def test_score_on_demand_returns_none_and_skips_persist_on_empty(monkeypatch):
    empty_result = _service_result(
        quality={**SAMPLE_QUALITY, "gallery_size": 0},
        warnings=["no_images_provided"],
        confidence=0.0,
    )

    def fail_upsert(cur, **kwargs):
        raise AssertionError("empty result must not be persisted")

    monkeypatch.setattr(vs, "score_one", lambda *a, **kw: empty_result)
    monkeypatch.setattr(vs, "get_cursor", lambda: _NullCursorCtx())
    monkeypatch.setattr(vision_scores, "upsert", fail_upsert)

    row = {"id": 7, "source": "sreality", "images": ["a.jpg"],
           "layout": None, "floor_area": None, "district": None}
    assert vs.score_on_demand(row) is None


def test_score_on_demand_persists_and_returns_row_shape(monkeypatch):
    upserted = {}

    def fake_score_one(payload, *, base_url, timeout):
        assert payload["property_id"] == "42"
        return _service_result()

    def fake_upsert(cur, **kwargs):
        upserted.update(kwargs)
        return 123

    monkeypatch.setattr(vs, "score_one", fake_score_one)
    monkeypatch.setattr(vs, "get_cursor", lambda: _NullCursorCtx())
    monkeypatch.setattr(vision_scores, "upsert", fake_upsert)

    row = {
        "id": 42, "source": "sreality",
        "images": ["a.jpg", "b.jpg"], "layout": "2+kk",
        "floor_area": 55, "district": "Praha 5",
    }
    result = vs.score_on_demand(row)

    assert result["overall_condition"] is None          # deprecated stays null
    assert result["image_quality"] == SAMPLE_QUALITY["image_quality"]
    assert result["model_provider"] == "heuristic"
    assert result["confidence"] == 0.8
    assert result["image_count"] == 2
    assert upserted["property_id"] == 42
    assert upserted["quality"]["brightness"] == SAMPLE_QUALITY["brightness"]
    assert upserted["snapshot_id"] is None  # no lineage available on this path


def test_score_on_demand_caps_images_tighter_than_batch():
    row = {"id": 1, "property_id": 1, "source": "sreality",
           "images": [f"{i}.jpg" for i in range(60)],
           "layout": None, "floor_area": None, "district": None}
    payload = vs._build_request(row, max_images=vs.config.VISION_ON_DEMAND_MAX_IMAGES)
    assert len(payload["image_urls"]) == vs.config.VISION_ON_DEMAND_MAX_IMAGES
    assert vs.config.VISION_ON_DEMAND_MAX_IMAGES < vs.config.VISION_MAX_IMAGES
