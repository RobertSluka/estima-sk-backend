"""
Geocoding tests: cache-once-ever behaviour, plausibility checks and candidate
order (all with a stubbed Nominatim), plus DB round-trips for the new columns.
"""

import pytest
import requests

from src import config
from src.repositories import properties
from src.services import geocoding
from src.services.street_extraction import StreetMention, extract_street


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def geo_env(tmp_path, monkeypatch):
    """Isolated cache dir + no throttle sleeping + call-recording stub."""
    monkeypatch.setattr(config, "GEOCODE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "NOMINATIM_MIN_INTERVAL_SECONDS", 0.0)
    calls = []

    def install(payloads):
        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(params)
            if isinstance(payloads, Exception):
                raise payloads
            return _FakeResponse(payloads)
        monkeypatch.setattr(geocoding.requests, "get", fake_get)

    return calls, install


KOSICE = (48.716, 21.261)
HIT_KOSICE = [{"lat": "48.7300", "lon": "21.2500"}]


def test_hit_is_cached_once_ever(geo_env):
    calls, install = geo_env
    install(HIT_KOSICE)
    first = geocoding.geocode_street("Fibichova", "Košice", town_lat=KOSICE[0], town_lon=KOSICE[1])
    second = geocoding.geocode_street("Fibichova", "Košice", town_lat=KOSICE[0], town_lon=KOSICE[1])
    assert first == (48.73, 21.25)
    assert second == first
    assert len(calls) == 1  # second answer came from the disk cache


def test_no_match_is_cached(geo_env):
    calls, install = geo_env
    install([])
    assert geocoding.geocode_street("Neexistujúca", "Košice") is None
    assert geocoding.geocode_street("Neexistujúca", "Košice") is None
    assert len(calls) == 1


def test_network_error_not_cached(geo_env):
    calls, install = geo_env
    install(requests.ConnectionError("down"))
    assert geocoding.geocode_street("Hlavná", "Košice") is None
    install(HIT_KOSICE)
    assert geocoding.geocode_street(
        "Hlavná", "Košice", town_lat=KOSICE[0], town_lon=KOSICE[1]
    ) == (48.73, 21.25)


def test_implausible_hits_rejected(geo_env):
    _, install = geo_env
    # Vienna — outside Slovakia.
    install([{"lat": "48.2082", "lon": "16.3738"}])
    assert geocoding.geocode_street("Hlavná", "Košice") is None


def test_far_from_town_rejected(geo_env):
    _, install = geo_env
    # Inside Slovakia but ~370 km from Košice (Bratislava).
    install([{"lat": "48.1486", "lon": "17.1077"}])
    assert (
        geocoding.geocode_street("Hlavná", "Košice", town_lat=KOSICE[0], town_lon=KOSICE[1])
        is None
    )


def test_mention_candidates_tried_in_order(geo_env, monkeypatch):
    _, install = geo_env
    seen = []

    def fake(street, town, house_number=None, town_lat=None, town_lon=None):
        seen.append(street)
        return (48.73, 21.25) if street == "Sibírska" else None

    monkeypatch.setattr(geocoding, "geocode_street", fake)
    mention = StreetMention(raw="Sibírskej", candidates=["Sibírská", "Sibírska"])
    result = geocoding.geocode_mention(mention, "Košice")
    assert result == ("Sibírska", 48.73, 21.25)
    assert seen == ["Sibírská", "Sibírska"]


def test_house_number_in_query(geo_env):
    calls, install = geo_env
    install(HIT_KOSICE)
    geocoding.geocode_street("Moyzesova", "Košice", house_number="46",
                             town_lat=KOSICE[0], town_lon=KOSICE[1])
    assert calls[0]["street"] == "46 Moyzesova"
    assert calls[0]["country"] == "Slovakia"


# --- DB round-trip (rolled back) --------------------------------------------

@pytest.mark.db
def test_geocode_result_roundtrip(db):
    db.execute(
        """
        INSERT INTO properties (source, source_listing_id, deal_type, name, city, locality)
        VALUES ('test', 'geo-1', 'buy', 'Byt ul. Hlavná 12', 'Košice', 'Košice')
        RETURNING id
        """
    )
    pid = db.fetchone()["id"]

    pending = properties.list_geocode_pending(db, limit=10_000)
    assert any(r["id"] == pid for r in pending)

    mention = extract_street("Byt ul. Hlavná 12")
    assert mention and mention.candidates[0] == "Hlavná" and mention.house_number == "12"

    properties.set_geocode_result(db, pid, "Hlavná", 48.73, 21.25, "street")
    db.execute("SELECT street, geo_lat, geo_lon, geo_precision, geocoded_at FROM properties WHERE id = %s", (pid,))
    row = db.fetchone()
    assert row["street"] == "Hlavná"
    assert row["geo_precision"] == "street"
    assert row["geocoded_at"] is not None

    # Attempted properties leave the pending queue.
    assert not any(r["id"] == pid for r in properties.list_geocode_pending(db, limit=10_000))
