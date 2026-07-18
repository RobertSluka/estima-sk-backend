"""Unit tests for Bazoš gallery expansion (no network, no database)."""
from __future__ import annotations

from src.services import bazos_gallery as bg


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeSession:
    """Serves 200 for photo indexes <= photos, 404 beyond."""

    def __init__(self, photos: int):
        self.photos = photos
        self.calls: list[str] = []

    def head(self, url, **kwargs):
        self.calls.append(url)
        index = int(url.split("/img/")[1].split("/")[0])
        return _FakeResponse(200 if index <= self.photos else 404)


THUMB = "https://www.bazos.sk/img/1/194/193211194.jpg"


def test_candidate_url_derivation():
    assert bg.candidate_url(THUMB, 2) == "https://www.bazos.sk/img/2/194/193211194.jpg"
    assert bg.candidate_url(THUMB, 12) == "https://www.bazos.sk/img/12/194/193211194.jpg"
    # Non-thumbnail and foreign URLs are not expandable.
    assert bg.candidate_url("https://www.bazos.sk/img/3/194/193211194.jpg", 2) is None
    assert bg.candidate_url("https://example.com/img/1/194/1.jpg", 2) is None
    assert bg.candidate_url(None, 2) is None


def test_expand_gallery_stops_at_first_miss():
    session = _FakeSession(photos=5)
    gallery = bg.expand_gallery(THUMB, session=session)
    assert gallery == [THUMB] + [bg.candidate_url(THUMB, i) for i in range(2, 6)]
    # Probed 2..6 (miss at 6 ends the loop): five requests total.
    assert len(session.calls) == 5


def test_expand_gallery_caps_at_max_photos():
    session = _FakeSession(photos=50)
    gallery = bg.expand_gallery(THUMB, session=session)
    assert len(gallery) == bg.MAX_PHOTOS


def test_expand_gallery_single_photo_listing():
    session = _FakeSession(photos=1)
    assert bg.expand_gallery(THUMB, session=session) == [THUMB]


def test_expand_gallery_non_bazos_url_untouched():
    assert bg.expand_gallery("https://example.com/a.jpg") == ["https://example.com/a.jpg"]
    assert bg.expand_gallery(None) == []
