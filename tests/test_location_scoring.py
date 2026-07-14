"""Tests for src/services/location_scoring.py — no network/DB, Overpass and the
cursor are faked so the batch orchestration logic (throttle, persist, count
scored/failed) can be verified in isolation."""

from __future__ import annotations

from src.repositories import location_scores
from src.services import location_scoring as ls
from src.services.reports.geo import PoiCounts


class _NullCursorCtx:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _patch_cursor(monkeypatch):
    monkeypatch.setattr(ls, "get_cursor", lambda: _NullCursorCtx())


def test_run_scores_and_persists_each_pending_property(monkeypatch):
    rows = [
        {"id": 1, "lat": 50.08, "lon": 14.43},
        {"id": 2, "lat": 50.09, "lon": 14.44},
    ]
    upserted = []

    monkeypatch.setattr(ls, "_select_pending", lambda cur, *, limit, rescore: rows)
    monkeypatch.setattr(
        ls.geo, "fetch_poi_counts",
        lambda lat, lon: PoiCounts(1, 1, 1, 1, 1, 1, 1, 1, 1),
    )
    monkeypatch.setattr(location_scores, "upsert", lambda cur, **kw: upserted.append(kw))
    monkeypatch.setattr(ls.time, "sleep", lambda s: None)
    _patch_cursor(monkeypatch)

    stats = ls.run(limit=10, rate=100.0)

    assert stats == {"scored": 2, "failed": 0, "pending": 2}
    assert [u["property_id"] for u in upserted] == [1, 2]
    assert upserted[0]["counts"]["nearby_transport_count_500m"] == 1
    assert upserted[0]["location_score"] == ls.geo.location_score(PoiCounts(1, 1, 1, 1, 1, 1, 1, 1, 1))


def test_run_counts_failures_without_aborting_the_batch(monkeypatch):
    rows = [
        {"id": 1, "lat": 50.08, "lon": 14.43},
        {"id": 2, "lat": 50.09, "lon": 14.44},
    ]
    upserted = []

    def fake_fetch(lat, lon):
        return None if lat == 50.08 else PoiCounts(2, 2, 2, 2, 2, 2, 2, 2, 2)

    monkeypatch.setattr(ls, "_select_pending", lambda cur, *, limit, rescore: rows)
    monkeypatch.setattr(ls.geo, "fetch_poi_counts", fake_fetch)
    monkeypatch.setattr(location_scores, "upsert", lambda cur, **kw: upserted.append(kw))
    monkeypatch.setattr(ls.time, "sleep", lambda s: None)
    _patch_cursor(monkeypatch)

    stats = ls.run(limit=10, rate=100.0)

    assert stats == {"scored": 1, "failed": 1, "pending": 2}
    assert len(upserted) == 1
    assert upserted[0]["property_id"] == 2


def test_run_throttles_between_requests(monkeypatch):
    rows = [{"id": i, "lat": 50.0, "lon": 14.0} for i in range(3)]
    sleeps = []

    monkeypatch.setattr(ls, "_select_pending", lambda cur, *, limit, rescore: rows)
    monkeypatch.setattr(
        ls.geo, "fetch_poi_counts",
        lambda lat, lon: PoiCounts(1, 1, 1, 1, 1, 1, 1, 1, 1),
    )
    monkeypatch.setattr(location_scores, "upsert", lambda cur, **kw: None)
    monkeypatch.setattr(ls.time, "sleep", lambda s: sleeps.append(s))
    _patch_cursor(monkeypatch)

    ls.run(limit=10, rate=2.0)  # 2/sec -> 0.5s delay

    # N properties -> N-1 gaps between requests, not before the first.
    assert sleeps == [0.5, 0.5]


def test_run_empty_pending_list(monkeypatch):
    monkeypatch.setattr(ls, "_select_pending", lambda cur, *, limit, rescore: [])
    _patch_cursor(monkeypatch)
    stats = ls.run(limit=10)
    assert stats == {"scored": 0, "failed": 0, "pending": 0}
