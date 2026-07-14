"""
OpenStreetMap context for the report's location section: nearby-facility
(POI) counts, the nearest named facility per category, and a static map image.

Counts come from the Overpass API in a single request (one `out count;` per
category/radius, parsed by position); nearest named facilities are a second,
separately cached Overpass query. The map is stitched from standard OSM
raster tiles with a marker and the required attribution — no API key.
Network problems, timeouts, and malformed responses all return None — the
caller renders the section's fallback instead of failing the PDF.

No database access here; successful lookups are memoised in-process so
re-generating a report (e.g. the same property in both languages) does not
re-query OSM.
"""

from __future__ import annotations

import base64
import json
import logging
import math
from dataclasses import asdict, dataclass, fields
from io import BytesIO
from pathlib import Path

import requests

from src import config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoiCounts:
    """One value per LocationAnalysis count field, same radii/categories."""

    transport_500m: int
    grocery_500m: int
    schools_1km: int
    parks_1km: int
    restaurants_1km: int
    healthcare_1km: int
    transport_1km: int
    grocery_1km: int
    transport_3km: int


# PoiCounts uses short field names; the report schema (LocationAnalysis) and
# the location_scores table use the longer `nearby_*_count_*` names the
# template reads. Single source of truth for that mapping, used by both
# builder.py (live/cached lookups) and location_scoring.py (batch warmup).
_FIELD_TO_LOCATION_KEY = {
    "transport_500m": "nearby_transport_count_500m",
    "grocery_500m": "nearby_grocery_count_500m",
    "schools_1km": "nearby_schools_count_1km",
    "parks_1km": "nearby_parks_count_1km",
    "restaurants_1km": "nearby_restaurants_count_1km",
    "healthcare_1km": "nearby_healthcare_count_1km",
    "transport_1km": "nearby_transport_count_1km",
    "grocery_1km": "nearby_grocery_count_1km",
    "transport_3km": "nearby_transport_count_3km",
}


def poi_counts_to_location_fields(counts: PoiCounts) -> dict:
    """`PoiCounts` -> a dict keyed by the `nearby_*_count_*` names."""
    return {
        location_key: getattr(counts, field)
        for field, location_key in _FIELD_TO_LOCATION_KEY.items()
    }


# OSM tag filters per category (a category may match several tag selectors).
# Kept deliberately narrow so the counts stay recognisable to a reader
# ("8 supermarkets" beats "37 shop-like objects").
_TRANSPORT = [
    '["highway"="bus_stop"]',
    '["railway"~"^(tram_stop|station|halt|subway_entrance)$"]',
]
_GROCERY = ['["shop"~"^(supermarket|convenience|greengrocer)$"]']
_SCHOOLS = ['["amenity"~"^(school|kindergarten)$"]']
_PARKS = ['["leisure"="park"]']
_RESTAURANTS = ['["amenity"~"^(restaurant|cafe|fast_food)$"]']
_HEALTHCARE = ['["amenity"~"^(doctors|pharmacy|clinic|hospital)$"]']

# (filters, radius in metres) in the exact order of the PoiCounts fields —
# Overpass returns one `count` element per `out count;`, matched by position.
_CATEGORIES: list[tuple[list[str], int]] = [
    (_TRANSPORT, 500),
    (_GROCERY, 500),
    (_SCHOOLS, 1000),
    (_PARKS, 1000),
    (_RESTAURANTS, 1000),
    (_HEALTHCARE, 1000),
    (_TRANSPORT, 1000),
    (_GROCERY, 1000),
    (_TRANSPORT, 3000),
]

# Only successful lookups are cached: a transient Overpass failure must not
# pin the fallback for the process lifetime.
_cache: dict[tuple[float, float], PoiCounts] = {}
_CACHE_MAX = 512


def _build_query(lat: float, lon: float) -> str:
    parts = [f"[out:json][timeout:{config.OVERPASS_TIMEOUT_SECONDS}];"]
    for tag_filters, radius in _CATEGORIES:
        union = "".join(
            f"nwr(around:{radius},{lat},{lon}){selector};" for selector in tag_filters
        )
        parts.append(f"({union});out count;")
    return "".join(parts)


def _parse_counts(payload: dict) -> PoiCounts | None:
    elements = payload.get("elements", [])
    totals = [
        int(el["tags"]["total"])
        for el in elements
        if el.get("type") == "count" and "total" in el.get("tags", {})
    ]
    if len(totals) != len(_CATEGORIES):
        return None
    return PoiCounts(*totals)


def fetch_poi_counts(lat: float, lon: float) -> PoiCounts | None:
    """Facility counts around a coordinate, or None if Overpass is unavailable."""
    key = (round(lat, 4), round(lon, 4))  # ~11 m — same building, same counts
    cached = _cache.get(key)
    if cached is not None:
        return cached
    try:
        resp = requests.post(
            config.OVERPASS_URL,
            data={"data": _build_query(key[0], key[1])},
            timeout=config.OVERPASS_TIMEOUT_SECONDS + 5,  # allow for queueing + transfer
            # overpass-api.de rejects the default python-requests UA with 406.
            headers={"User-Agent": "estima-backend-reports/1.0 (property report location section)"},
        )
        resp.raise_for_status()
        counts = _parse_counts(resp.json())
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Overpass POI lookup failed for %s: %s", key, exc)
        return None
    if counts is None:
        logger.warning("Overpass returned an unexpected shape for %s", key)
        return None
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[key] = counts
    return counts


# Per-category weight and the count at which the category is "fully served".
# Walkable daily needs (transport, groceries) dominate the score.
_SCORE_WEIGHTS: list[tuple[str, float, int]] = [
    ("transport_500m", 0.30, 8),
    ("grocery_500m", 0.20, 5),
    ("schools_1km", 0.10, 5),
    ("parks_1km", 0.10, 3),
    ("restaurants_1km", 0.15, 15),
    ("healthcare_1km", 0.15, 8),
]

assert {name for name, _, _ in _SCORE_WEIGHTS} <= {f.name for f in fields(PoiCounts)}


def location_score(counts: PoiCounts) -> float:
    """0–100 amenity-access score: weighted saturation across categories."""
    total = sum(
        weight * min(getattr(counts, field) / saturation, 1.0)
        for field, weight, saturation in _SCORE_WEIGHTS
    )
    return round(100 * total / sum(w for _, w, _ in _SCORE_WEIGHTS), 1)


# --------------------------------------------------------------------------- #
# Nearest named facilities                                                      #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class NearestPoi:
    """The closest named facility of one category."""

    category: str  # transport | grocery | schools | parks | restaurants | healthcare
    name: str
    distance_m: int


# (category key, tag filters, radius in metres) — the six categories the
# template displays, same selectors and radii as the count query above.
_POI_CATEGORIES: list[tuple[str, list[str], int]] = [
    ("transport", _TRANSPORT, 500),
    ("grocery", _GROCERY, 500),
    ("schools", _SCHOOLS, 1000),
    ("parks", _PARKS, 1000),
    ("restaurants", _RESTAURANTS, 1000),
    ("healthcare", _HEALTHCARE, 1000),
]

# Overpass cannot sort by distance, so each category returns up to this many
# elements and the nearest is picked client-side. Dense categories (Prague
# restaurants) can exceed the cap, in which case "nearest" may be off by a
# block — acceptable for a convenience showcase, and it bounds the payload.
_POIS_PER_CATEGORY = 60

# Must accept exactly what the _TRANSPORT.._HEALTHCARE selectors match —
# _parse_nearest_pois assigns categories from tags, not response position.
_TRANSPORT_RAILWAY = {"tram_stop", "station", "halt", "subway_entrance"}
_GROCERY_SHOPS = {"supermarket", "convenience", "greengrocer"}
_SCHOOL_AMENITIES = {"school", "kindergarten"}
_RESTAURANT_AMENITIES = {"restaurant", "cafe", "fast_food"}
_HEALTHCARE_AMENITIES = {"doctors", "pharmacy", "clinic", "hospital"}


def _classify_poi(tags: dict) -> str | None:
    if tags.get("highway") == "bus_stop" or tags.get("railway") in _TRANSPORT_RAILWAY:
        return "transport"
    if tags.get("shop") in _GROCERY_SHOPS:
        return "grocery"
    if tags.get("leisure") == "park":
        return "parks"
    amenity = tags.get("amenity")
    if amenity in _SCHOOL_AMENITIES:
        return "schools"
    if amenity in _RESTAURANT_AMENITIES:
        return "restaurants"
    if amenity in _HEALTHCARE_AMENITIES:
        return "healthcare"
    return None


def _build_pois_query(lat: float, lon: float) -> str:
    parts = [f"[out:json][timeout:{config.OVERPASS_TIMEOUT_SECONDS}];"]
    for _category, tag_filters, radius in _POI_CATEGORIES:
        union = "".join(
            f'nwr(around:{radius},{lat},{lon}){selector}["name"];'
            for selector in tag_filters
        )
        parts.append(f"({union});out tags center {_POIS_PER_CATEGORY};")
    return "".join(parts)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def _parse_nearest_pois(payload: dict, lat: float, lon: float) -> list[NearestPoi]:
    """Nearest named element per category, in _POI_CATEGORIES display order."""
    best: dict[str, NearestPoi] = {}
    for el in payload.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name")
        category = _classify_poi(tags) if name else None
        if category is None:
            continue
        coords = el if "lat" in el else el.get("center") or {}
        if "lat" not in coords or "lon" not in coords:
            continue
        distance = round(_haversine_m(lat, lon, coords["lat"], coords["lon"]))
        current = best.get(category)
        if current is None or distance < current.distance_m:
            best[category] = NearestPoi(category=category, name=name, distance_m=distance)
    return [best[cat] for cat, _, _ in _POI_CATEGORIES if cat in best]


_pois_cache: dict[tuple[float, float], list[NearestPoi]] = {}


def _pois_cache_path(key: tuple[float, float]) -> Path:
    return Path(config.LOCATION_POI_CACHE_DIR) / f"{key[0]}_{key[1]}.json"


def fetch_nearest_pois(lat: float, lon: float) -> list[NearestPoi] | None:
    """Nearest named facility per category, or None if Overpass is unavailable.

    Separate from fetch_poi_counts because counts are usually served from the
    location_scores table (see builder.py) and never reach Overpass. Successful
    lookups are persisted to disk so each coordinate is queried at most once
    ever, mirroring the static-map cache. An empty list is a valid (cachable)
    answer: coordinates with no named facility in range.
    """
    key = (round(lat, 4), round(lon, 4))
    cached = _pois_cache.get(key)
    if cached is not None:
        return cached

    disk_path = _pois_cache_path(key)
    if disk_path.exists():
        try:
            pois = [NearestPoi(**record) for record in json.loads(disk_path.read_text())]
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not read cached POIs %s: %s", disk_path, exc)
        else:
            return _remember_pois(key, pois)

    try:
        resp = requests.post(
            config.OVERPASS_URL,
            data={"data": _build_pois_query(key[0], key[1])},
            timeout=config.OVERPASS_TIMEOUT_SECONDS + 5,  # allow for queueing + transfer
            headers=_UA,
        )
        resp.raise_for_status()
        pois = _parse_nearest_pois(resp.json(), key[0], key[1])
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Overpass nearest-POI lookup failed for %s: %s", key, exc)
        return None

    try:
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        disk_path.write_text(json.dumps([asdict(p) for p in pois]))
    except OSError as exc:
        logger.warning("Could not persist POI cache %s: %s", disk_path, exc)

    return _remember_pois(key, pois)


def _remember_pois(key: tuple[float, float], pois: list[NearestPoi]) -> list[NearestPoi]:
    if len(_pois_cache) >= _CACHE_MAX:
        _pois_cache.clear()
    _pois_cache[key] = pois
    return pois


# --------------------------------------------------------------------------- #
# Static map (stitched OSM raster tiles)                                       #
# --------------------------------------------------------------------------- #

_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_TILE_PX = 256
_TILE_TIMEOUT_SECONDS = 5
# Sized for the template's .map-box (~170mm × 55mm, object-fit: cover).
# Zoom 15 ≈ 3 m/px in Prague → the 360 px height spans roughly ±550 m, a good
# frame for the walkable-facility radii.
_MAP_W, _MAP_H, _MAP_ZOOM = 1100, 360, 15
_ATTRIBUTION = "© OpenStreetMap contributors"
_UA = {"User-Agent": "estima-backend-reports/1.0 (property report location section)"}

_map_cache: dict[tuple[float, float], str] = {}


def _tile_frac(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Fractional slippy-map tile coordinates (Web Mercator)."""
    n = 2**zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def _render_map(lat: float, lon: float, get) -> bytes:
    """Stitch tiles around the coordinate, add marker + attribution → PNG bytes.

    `get` is a requests-compatible GET callable, injected so tests can supply
    synthetic tiles.
    """
    # Pillow ships as a WeasyPrint dependency; imported lazily to keep the
    # counts path importable even where imaging libs are broken.
    from PIL import Image, ImageDraw

    xf, yf = _tile_frac(lat, lon, _MAP_ZOOM)
    cx, cy = xf * _TILE_PX, yf * _TILE_PX  # property in global pixel space
    left, top = int(cx - _MAP_W / 2), int(cy - _MAP_H / 2)
    tx0, ty0 = left // _TILE_PX, top // _TILE_PX
    tx1, ty1 = (left + _MAP_W) // _TILE_PX, (top + _MAP_H) // _TILE_PX

    canvas = Image.new("RGB", ((tx1 - tx0 + 1) * _TILE_PX, (ty1 - ty0 + 1) * _TILE_PX))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            resp = get(
                _TILE_URL.format(z=_MAP_ZOOM, x=tx, y=ty),
                timeout=_TILE_TIMEOUT_SECONDS,
                headers=_UA,
            )
            resp.raise_for_status()
            tile = Image.open(BytesIO(resp.content)).convert("RGB")
            canvas.paste(tile, ((tx - tx0) * _TILE_PX, (ty - ty0) * _TILE_PX))

    crop_x, crop_y = left - tx0 * _TILE_PX, top - ty0 * _TILE_PX
    img = canvas.crop((crop_x, crop_y, crop_x + _MAP_W, crop_y + _MAP_H))

    draw = ImageDraw.Draw(img)
    px, py = int(cx - left), int(cy - top)
    draw.ellipse((px - 12, py - 12, px + 12, py + 12), fill=(255, 255, 255))
    draw.ellipse((px - 9, py - 9, px + 9, py + 9), fill=(198, 40, 40))
    draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=(255, 255, 255))

    # OSM tile usage policy requires visible attribution on the rendered map.
    text_w = draw.textlength(_ATTRIBUTION)
    draw.rectangle(
        (_MAP_W - text_w - 10, _MAP_H - 16, _MAP_W, _MAP_H), fill=(255, 255, 255)
    )
    draw.text((_MAP_W - text_w - 5, _MAP_H - 14), _ATTRIBUTION, fill=(90, 100, 110))

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _map_cache_path(key: tuple[float, float]) -> Path:
    return Path(config.LOCATION_MAP_CACHE_DIR) / f"{key[0]}_{key[1]}.png"


def static_map_data_uri(lat: float, lon: float) -> str | None:
    """PNG data URI of a map centred on the coordinate, or None if OSM fails.

    Checked in order: in-process cache, on-disk cache, live render. A
    successful live render is written to disk so this coordinate's tiles are
    only ever fetched once — see LOCATION_MAP_CACHE_DIR's docstring in
    config.py for why (OSM's tile usage policy).
    """
    key = (round(lat, 4), round(lon, 4))
    cached = _map_cache.get(key)
    if cached is not None:
        return cached

    disk_path = _map_cache_path(key)
    if disk_path.exists():
        try:
            png = disk_path.read_bytes()
        except OSError as exc:
            logger.warning("Could not read cached map %s: %s", disk_path, exc)
        else:
            return _remember_map(key, png)

    try:
        png = _render_map(key[0], key[1], requests.get)
    except Exception as exc:  # tile fetch, decode, or imaging failure
        logger.warning("Static map render failed for %s: %s", key, exc)
        return None

    try:
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        disk_path.write_bytes(png)
    except OSError as exc:
        logger.warning("Could not persist map cache %s: %s", disk_path, exc)

    return _remember_map(key, png)


def _remember_map(key: tuple[float, float], png: bytes) -> str:
    uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    if len(_map_cache) >= _CACHE_MAX:
        _map_cache.clear()
    _map_cache[key] = uri
    return uri
