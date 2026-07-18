"""
Nominatim street geocoding with a once-ever on-disk cache.

OSM's Nominatim usage policy asks for ≤1 request/second, a descriptive
User-Agent and result caching. Every unique (street, town, number) query is
therefore looked up at most once ever: both matches and definitive "no match"
answers are persisted under GEOCODE_CACHE_DIR; only network errors are left
uncached so a transient outage doesn't poison the cache. Uncached lookups are
throttled to NOMINATIM_MIN_INTERVAL_SECONDS.

Results are sanity-checked: they must fall inside Slovakia and (when the town
centroid is known) within ~25 km of it, so a same-named street in another town
can't teleport a Košice listing to Bratislava.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from math import cos, radians, sqrt
from pathlib import Path

import requests

from src import config
from src.services.street_extraction import StreetMention

logger = logging.getLogger(__name__)

_USER_AGENT = "estima-sk-backend/0.1 (real-estate analytics; hello@estima.sk)"

# Slovakia bounding box — reject hits outside it outright.
_SK_LAT = (47.7, 49.65)
_SK_LON = (16.8, 22.6)
_MAX_TOWN_DISTANCE_KM = 25.0

_last_request_ts: float = 0.0


def _cache_path(query_key: str) -> Path:
    digest = hashlib.sha1(query_key.encode()).hexdigest()[:20]
    return Path(config.GEOCODE_CACHE_DIR) / f"{digest}.json"


def _plausible(lat: float, lon: float, town_lat: float | None, town_lon: float | None) -> bool:
    if not (_SK_LAT[0] <= lat <= _SK_LAT[1] and _SK_LON[0] <= lon <= _SK_LON[1]):
        return False
    if town_lat is None or town_lon is None:
        return True
    # Equirectangular approximation — plenty for a 25 km sanity radius.
    dlat = (lat - town_lat) * 111.0
    dlon = (lon - town_lon) * 111.0 * cos(radians(town_lat))
    return sqrt(dlat * dlat + dlon * dlon) <= _MAX_TOWN_DISTANCE_KM


def _query_nominatim(street_q: str, town: str) -> tuple[float, float] | None:
    """One rate-limited Nominatim request. Raises on network problems."""
    global _last_request_ts
    wait = config.NOMINATIM_MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()

    res = requests.get(
        config.NOMINATIM_URL,
        params={
            "street": street_q,
            "city": town,
            "country": "Slovakia",
            "format": "jsonv2",
            "limit": 1,
        },
        headers={"User-Agent": _USER_AGENT},
        timeout=config.NOMINATIM_TIMEOUT_SECONDS,
    )
    res.raise_for_status()
    hits = res.json()
    if not hits:
        return None
    return float(hits[0]["lat"]), float(hits[0]["lon"])


def geocode_street(
    street: str,
    town: str,
    house_number: str | None = None,
    town_lat: float | None = None,
    town_lon: float | None = None,
) -> tuple[float, float] | None:
    """Geocode one street spelling; cached once-ever. None = no (plausible) match."""
    street_q = f"{house_number} {street}" if house_number else street
    key = f"{street_q.lower()}|{town.lower()}"

    path = _cache_path(key)
    if path.exists():
        try:
            cached = json.loads(path.read_text())
            result = cached.get("result")
            return (result[0], result[1]) if result else None
        except (ValueError, OSError) as exc:
            logger.warning("Unreadable geocode cache %s: %s", path, exc)

    try:
        hit = _query_nominatim(street_q, town)
    except requests.RequestException as exc:
        # Network trouble: report "unknown", cache nothing.
        logger.warning("Nominatim request failed for %r, %r: %s", street_q, town, exc)
        return None

    if hit and not _plausible(hit[0], hit[1], town_lat, town_lon):
        logger.info("Discarding implausible hit %s for %r, %r", hit, street_q, town)
        hit = None

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"query": {"street": street_q, "city": town}, "result": hit}))
    except OSError as exc:
        logger.warning("Could not persist geocode cache %s: %s", path, exc)
    return hit


def geocode_mention(
    mention: StreetMention,
    town: str,
    town_lat: float | None = None,
    town_lon: float | None = None,
) -> tuple[str, float, float] | None:
    """
    Try the mention's candidate spellings in order; first plausible hit wins.
    Returns (matched street spelling, lat, lon) or None.
    """
    for candidate in mention.candidates:
        hit = geocode_street(candidate, town, mention.house_number, town_lat, town_lon)
        if hit:
            return candidate, hit[0], hit[1]
    return None
