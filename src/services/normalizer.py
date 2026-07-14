"""
Raw scraper item → canonical listing dict (pure, no DB).

The canonical dict is consumed by both the properties upsert and the snapshot
insert. One dict shape for every source; `source`/`deal_type` are always set.

Sources & formats (auto-detected per item):
  sreality         — keys: listingId, url, dealType, propertyType, title,
                     locality, city, district, rooms, areaSqm, latitude,
                     longitude, price, currency, images, scrapedAt
  bezrealitky flat — keys: source, url, category, name, locality, layout,
                     floorArea, landArea, lat, lon, imageUrl, price, pricePerSqm
  bezrealitky API  — the richer bezrealitky-task export. Nested/renamed keys:
                     estateType→category, offerType→deal_type,
                     disposition→layout, address→locality, surface→floor_area,
                     surfaceLand→land_area, coordinates.{lat,lng}→lat/lon,
                     mainImage.url→image_url, scrapedAt. Distinguished from the
                     flat format by the presence of estateType/disposition/
                     coordinates.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from src.services import slovak_regions

# ── Scalar helpers ──────────────────────────────────────────────────────────


def _to_float(val: Any) -> float | None:
    try:
        return float(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_int(val: Any) -> int | None:
    f = _to_float(val)
    return int(f) if f is not None else None


def nullify_zero(coord: float | None) -> float | None:
    """Treat 0.0 coordinates as missing (bezrealitky uses 0 for unknown)."""
    if coord is None or coord == 0:
        return None
    return coord


def price_per_sqm(price: int | None, area: float | None) -> float | None:
    if price and area:
        return round(price / area, 2)
    return None


def image_list(*candidates: Any) -> list[str]:
    """Flatten image sources into an ordered, de-duplicated list of URL strings.

    Accepts bare URL strings, dicts shaped like ``{"url": ...}``, and lists of
    either; falsy/duplicate entries are skipped. The first surviving URL is the
    main image (``image_url``); the whole list is the gallery (``images``).
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(item: Any) -> None:
        url = item.get("url") if isinstance(item, dict) else item
        if isinstance(url, str) and url and url not in seen:
            seen.add(url)
            out.append(url)

    for cand in candidates:
        if isinstance(cand, (list, tuple)):
            for item in cand:
                add(item)
        else:
            add(cand)
    return out


# ── Deal type ─────────────────────────────────────────────────────────────────

_DEAL_BUY = {"buy", "sale", "prodej"}
_DEAL_RENT = {"rent", "pronajem", "pronájem"}


def normalize_deal_type(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if v in _DEAL_BUY:
        return "buy"
    if v in _DEAL_RENT:
        return "rent"
    return None


def deal_type_from_url(url: str | None) -> str | None:
    """Derive buy/rent from a listing URL (bezrealitky has no deal-type field)."""
    if not url:
        return None
    u = url.lower()
    if "pronajem" in u or "pronájem" in u:
        return "rent"
    if "prodej" in u:
        return "buy"
    return None


# ── Category ──────────────────────────────────────────────────────────────────

_CATEGORY_MAP = {
    "byty": "apartment", "byt": "apartment", "apartment": "apartment",
    "domy": "house", "dum": "house", "house": "house",
    "pozemky": "land", "pozemek": "land", "land": "land",
    "komercni": "commercial", "commercial": "commercial",
}


def normalize_category(value: str | None) -> str | None:
    if not value:
        return None
    return _CATEGORY_MAP.get(value.strip().lower(), value.strip().lower())


# ── Layout ────────────────────────────────────────────────────────────────────

_LAYOUT_SPECIAL = {
    "GARSONIERA": "1+kk",
    "DISP_STUDIO": "1+kk",
    "DISP_ATYPICAL": "atypical",
    "ATYPICAL": "atypical",
    "UNDEFINED": None,
    "OSTATNI": None,
    "": None,
}
_DISP_RE = re.compile(r"^DISP_(\d+)_(KK|1)$")


def normalize_layout(value: str | None) -> str | None:
    """
    Canonicalize a layout code.
      DISP_6_1 -> 6+1, DISP_6_KK -> 6+kk, GARSONIERA -> 1+kk,
      UNDEFINED / OSTATNI -> None. Values already like '2+kk' pass through.
    """
    if value is None:
        return None
    raw = value.strip()
    upper = raw.upper()
    if upper in _LAYOUT_SPECIAL:
        return _LAYOUT_SPECIAL[upper]
    m = _DISP_RE.match(upper)
    if m:
        n, suffix = m.group(1), m.group(2)
        return f"{n}+kk" if suffix == "KK" else f"{n}+1"
    return raw  # already human-readable, e.g. "2+kk", "3+1"


# ── Location ──────────────────────────────────────────────────────────────────

_DISTRICT_NAMED = re.compile(
    r"Praha\s*[-–]\s*([A-Za-záčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\wáčďéěíňóřšťúůýž -]+)",
    re.UNICODE,
)


def prague_to_praha(locality: str | None) -> str | None:
    """Normalize the English exonym 'Prague' to 'Praha', for consistency with
    the rest of the dataset and the frontend region filter. The new bezrealitky
    scraper emits addresses like 'U Sluncové, Prague - Karlín'."""
    if not locality:
        return locality
    return re.sub(r"\bPrague\b", "Praha", locality)


def extract_prague_district(locality: str | None) -> str | None:
    if not locality:
        return None
    locality = prague_to_praha(locality)
    m = re.search(r"Praha\s+(\d{1,2})\b", locality)
    if m:
        return f"Praha {m.group(1)}"
    m = _DISTRICT_NAMED.search(locality)
    if m:
        return f"Praha - {m.group(1).strip()}"
    return "Praha" if "Praha" in locality else None


# ── URL fixes ─────────────────────────────────────────────────────────────────

_BEZ_HOST = "bezrealitky.cz/"
_BEZ_SEGMENT = "nemovitosti-byty-domy/"


def fix_bezrealitky_url(url: str | None) -> str | None:
    """
    Insert the missing '/nemovitosti-byty-domy/' path segment.

    The scraper emits e.g. https://www.bezrealitky.cz/1033493-nabidka-... which
    404s; the real URL is https://www.bezrealitky.cz/nemovitosti-byty-domy/1033493-...
    Idempotent: URLs that already contain the segment are returned unchanged.
    """
    if not url:
        return url
    idx = url.find(_BEZ_HOST)
    if idx == -1:
        return url
    rest_start = idx + len(_BEZ_HOST)
    if url[rest_start:].startswith(_BEZ_SEGMENT):
        return url
    return url[:rest_start] + _BEZ_SEGMENT + url[rest_start:]


def extract_bezrealitky_id(url: str | None) -> str | None:
    """
    Pull the numeric listing id from a bezrealitky URL.
      https://www.bezrealitky.cz/1035298-nabidka-pronajem-... -> 1035298
    Works whether or not the URL contains the nemovitosti-byty-domy segment.
    """
    if not url:
        return None
    m = re.search(r"/(\d+)-", url)
    return m.group(1) if m else None


# ── scraped_at parsing ──────────────────────────────────────────────────────


def _parse_scraped_at(value: Any, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return fallback


# ── Source normalizers ────────────────────────────────────────────────────────


def normalize_sreality(raw: dict, run_time: datetime) -> dict:
    price = _to_int(raw.get("price"))
    area = _to_float(raw.get("areaSqm"))
    gallery = image_list(raw.get("images"))
    return {
        "source": "sreality",
        "source_listing_id": str(raw.get("listingId")),
        "url": raw.get("url"),
        "deal_type": normalize_deal_type(raw.get("dealType")) or "buy",
        "category": normalize_category(raw.get("propertyType")),
        "source_category": raw.get("propertyType"),
        "name": raw.get("title"),
        "locality": raw.get("locality"),
        "city": raw.get("city"),
        "district": raw.get("district") or extract_prague_district(raw.get("locality")),
        "layout": normalize_layout(raw.get("rooms")),
        "floor_area": area,
        "land_area": None,
        "lat": nullify_zero(_to_float(raw.get("latitude"))),
        "lon": nullify_zero(_to_float(raw.get("longitude"))),
        "image_url": gallery[0] if gallery else None,
        "images": gallery,
        "currency": raw.get("currency"),
        "price": price,
        "price_per_sqm": price_per_sqm(price, area),
        "scraped_at": _parse_scraped_at(raw.get("scrapedAt"), run_time),
        "raw_json": raw,
    }


def normalize_bezrealitky(raw: dict, run_time: datetime) -> dict:
    url = raw.get("url")
    price = _to_int(raw.get("price"))
    area = _to_float(raw.get("floorArea"))
    locality = raw.get("locality") or raw.get("name")
    return {
        "source": raw.get("source") or "bezrealitky",
        "source_listing_id": extract_bezrealitky_id(url) or str(raw.get("id") or ""),
        "url": fix_bezrealitky_url(url),
        "deal_type": deal_type_from_url(url) or "buy",
        "category": normalize_category(raw.get("category")),
        "source_category": raw.get("category"),
        "name": raw.get("name"),
        "locality": locality,
        "city": None,
        "district": extract_prague_district(locality),
        "layout": normalize_layout(raw.get("layout")),
        "floor_area": area,
        "land_area": _to_float(raw.get("landArea")),
        "lat": nullify_zero(_to_float(raw.get("lat"))),
        "lon": nullify_zero(_to_float(raw.get("lon"))),
        "image_url": raw.get("imageUrl"),
        "images": image_list(raw.get("imageUrl")),
        "currency": "CZK",
        "price": price,
        "price_per_sqm": _to_float(raw.get("pricePerSqm")) or price_per_sqm(price, area),
        "scraped_at": run_time,
        "raw_json": raw,
    }


def normalize_bezrealitky_api(raw: dict, run_time: datetime) -> dict:
    """
    Normalize the richer bezrealitky scraper format (the bezrealitky-task
    actor), which nests location/images and uses different field names than the
    older flat export:
        estateType→category, offerType→deal_type, disposition→layout,
        address→locality, surface→floor_area, surfaceLand→land_area,
        coordinates.{lat,lng}→lat/lon, mainImage.url→image_url.
    """
    url = raw.get("url")
    price = _to_int(raw.get("price"))
    area = nullify_zero(_to_float(raw.get("surface")))
    locality = prague_to_praha(raw.get("address"))

    coords = raw.get("coordinates") or {}
    lat = nullify_zero(_to_float(coords.get("lat")))
    lon = nullify_zero(_to_float(coords.get("lng") if coords.get("lng") is not None
                                 else coords.get("lon")))

    # publicImages is the full-res gallery; mainImage is a smaller (record_thumb)
    # copy of the first photo at a *different* URL, so it can't be de-duped by
    # string match. Keep it only as the card thumbnail / fallback — otherwise the
    # first photo shows twice (slides 1 and 2 identical). Fall back to mainImage
    # for the gallery only when there are no publicImages.
    main_image = raw.get("mainImage") or {}
    gallery = image_list(raw.get("publicImages")) or image_list(main_image)
    image_url = (main_image.get("url") if isinstance(main_image, dict) else None) \
        or (gallery[0] if gallery else None)

    return {
        "source": "bezrealitky",
        "source_listing_id": extract_bezrealitky_id(url) or str(raw.get("id") or ""),
        "url": fix_bezrealitky_url(url),
        "deal_type": normalize_deal_type(raw.get("offerType"))
                     or deal_type_from_url(url) or "buy",
        "category": normalize_category(raw.get("estateType")),
        "source_category": raw.get("estateType"),
        "name": locality,
        "locality": locality,
        "city": None,
        "district": extract_prague_district(locality),
        "layout": normalize_layout(raw.get("disposition")),
        "floor_area": area,
        "land_area": nullify_zero(_to_float(raw.get("surfaceLand"))),
        "lat": lat,
        "lon": lon,
        "image_url": image_url,
        "images": gallery,
        "currency": raw.get("currency") or "CZK",
        "price": price,
        "price_per_sqm": price_per_sqm(price, area),
        "scraped_at": _parse_scraped_at(raw.get("scrapedAt"), run_time),
        "raw_json": raw,
    }


# ── Bazoš (SK) ────────────────────────────────────────────────────────────────
# Slovak classifieds (reality.bazos.sk). Free-text listings: structured area,
# layout, category and deal-type live inside the title/content, not in fields.

# Only the real-estate subsection is a property listing; a bazos keyword dump
# also pulls in furniture/auto/services sections, which must be skipped.
_BAZOS_REALITY_HOST = "reality.bazos.sk"

_BAZOS_PRICE_RE = re.compile(r"\d[\d\s  ]*")
# "63,5 m2", "63 m²", "45m2" — Slovak decimal comma; require an m² unit.
_BAZOS_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*[²2]", re.IGNORECASE)
# "1,5-izbový", "3 izbový", "2-izb.", "1-izbový garzón"
_BAZOS_ROOMS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*-?\s*izb", re.IGNORECASE)


def is_bazos(raw: dict) -> bool:
    return "bazos.sk" in (raw.get("url") or "").lower()


def is_bazos_reality(raw: dict) -> bool:
    return _BAZOS_REALITY_HOST in (raw.get("url") or "").lower()


# No real SK property (sale or rent) is priced below this; smaller values are
# placeholder/"inquiry" amounts like "6 €" or "1 €" and are treated as missing.
_BAZOS_MIN_PLAUSIBLE_PRICE = 100


def parse_bazos_price(price_raw: Any) -> int | None:
    """'161 000 €' -> 161000. Non-numeric ('Dohodou', 'V texte') and implausible
    placeholder prices (< 100 €) -> None."""
    if not price_raw:
        return None
    m = _BAZOS_PRICE_RE.search(str(price_raw))
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    if not digits:
        return None
    value = int(digits)
    return value if value >= _BAZOS_MIN_PLAUSIBLE_PRICE else None


def parse_bazos_area(content: str | None) -> float | None:
    """First plausible m² figure in the free-text content (8–2000 m²)."""
    if not content:
        return None
    for m in _BAZOS_AREA_RE.finditer(content):
        val = _to_float(m.group(1).replace(",", "."))
        if val is not None and 8 <= val <= 2000:
            return val
    return None


def parse_bazos_layout(title: str | None) -> str | None:
    """Room count from the title -> SK-style layout, e.g. '3-izb', '1.5-izb'.
    'garzón'/'garsónka' -> '1-izb'."""
    if not title:
        return None
    low = title.lower()
    if "garson" in low or "garzón" in low or "garzon" in low or "garsón" in low:
        return "1-izb"
    m = _BAZOS_ROOMS_RE.search(title)
    if not m:
        return None
    rooms = m.group(1).replace(",", ".")
    if rooms.endswith(".0"):
        rooms = rooms[:-2]
    return f"{rooms}-izb"


# Ordered category patterns. Commercial is checked first so "nebytový priestor"
# (non-residential) is not swallowed by a naive "byt" substring; apartment is
# checked before house so "bytový dom" (a flat in an apartment building) stays an
# apartment; land is last so "dom so záhradou" (house with a garden) stays a
# house. Word boundaries (\b) stop "byt" matching inside "nebytový".
_BAZOS_CATEGORY_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("commercial", re.compile(
        r"nebytov|kancelár|kancelar|obchodn|sklad|prevádzk|prevadzk|"
        r"komerč|komerc|reštaurác|restaurac|priemyseln", re.IGNORECASE)),
    ("apartment", re.compile(
        r"\bbyt\w*|\bizb|garzón|garzon|garsón|garson|apartmán|apartman|mezonet",
        re.IGNORECASE)),
    ("house", re.compile(
        r"rodinn\w*\s+dom|\bdom\b|domček|domcek|chat\w*|chalup|\bvila\b|novostavb",
        re.IGNORECASE)),
    ("land", re.compile(r"pozemok|pozemk|parcel|záhrad|zahrad|orn\w*\s+pôd", re.IGNORECASE)),
]


def _match_category(text: str) -> str | None:
    for canon, pattern in _BAZOS_CATEGORY_PATTERNS:
        if pattern.search(text):
            return canon
    return None


def bazos_category(title: str | None, content: str | None) -> str | None:
    """Property type from the title first — content is full of agency boilerplate
    ('obchodný register', 'kancelárie v okolí') that would mislabel flats as
    commercial — falling back to content only when the title is uninformative."""
    return _match_category(title or "") or _match_category(content or "")


def bazos_deal_type(raw: dict, price: int | None) -> str | None:
    """buy/rent for a Bazoš reality listing.

    The *title* carries the seller's intent ('Na predaj …' / 'Prenájom …'); the
    *content* often has agency boilerplate mentioning both ('predaj a prenájom
    nehnuteľností'), so it must not drive the decision. Order:
      1. unambiguous title keyword,
      2. price magnitude (a five-figure amount is a sale, not monthly rent),
      3. unambiguous content keyword.
    """
    title = (raw.get("title") or "").lower()
    has_rent_t = "prenaj" in title or "prenáj" in title
    has_buy_t = "predaj" in title or "predá" in title or "predam" in title
    if has_rent_t and not has_buy_t:
        return "rent"
    if has_buy_t and not has_rent_t:
        return "buy"

    if price is not None:
        if price >= 15000:   # never a monthly rent
            return "buy"
        if price <= 4000:    # never a sale price
            return "rent"

    content = (raw.get("content") or "").lower()
    has_rent_c = "prenaj" in content or "prenáj" in content
    has_buy_c = "predaj" in content or "predá" in content or "predam" in content
    if has_rent_c and not has_buy_c:
        return "rent"
    if has_buy_c and not has_rent_c:
        return "buy"
    return None


def normalize_bazos(raw: dict, run_time: datetime) -> dict:
    price = parse_bazos_price(raw.get("priceRaw"))
    area = parse_bazos_area(raw.get("content"))
    locality = raw.get("locationName")
    image = raw.get("imageUrl")
    okres = slovak_regions.resolve_okres(locality)
    lat, lon = slovak_regions.resolve_coords(locality)
    return {
        "source": "bazos",
        "source_listing_id": str(raw.get("id") or ""),
        "url": raw.get("url"),
        "deal_type": bazos_deal_type(raw, price) or "buy",
        "category": bazos_category(raw.get("title"), raw.get("content")),
        "source_category": None,
        "name": raw.get("title"),
        "locality": locality,
        "city": locality,
        # district holds the Slovak okres; kraj is derived from it (read_api).
        "district": okres,
        "layout": parse_bazos_layout(raw.get("title")),
        "floor_area": area,
        "land_area": None,
        # Town centroid — Bazoš has no per-listing coordinates; same-town
        # listings stack deliberately and the frontend map clusters them.
        "lat": lat,
        "lon": lon,
        "image_url": image,
        "images": image_list(image),
        "currency": "EUR",
        "price": price,
        "price_per_sqm": price_per_sqm(price, area),
        "scraped_at": run_time,
        "raw_json": raw,
    }


def _is_bezrealitky_api(raw: dict) -> bool:
    """The richer bezrealitky-task export — distinguished from the flat one by
    its nested/renamed fields."""
    return any(k in raw for k in ("estateType", "disposition", "coordinates"))


def detect_source(raw: dict) -> str:
    if is_bazos_reality(raw):
        return "bazos"
    if (raw.get("source") or "").lower() == "bezrealitky":
        return "bezrealitky"
    if raw.get("listingId"):
        return "sreality"
    if "bezrealitky.cz" in (raw.get("url") or ""):
        return "bezrealitky"
    raise ValueError(f"Cannot detect source for item: keys={list(raw.keys())}")


def normalize(raw: dict, run_time: datetime) -> dict:
    """Normalize one raw item, auto-detecting its source and format."""
    source = detect_source(raw)
    if source == "bazos":
        return normalize_bazos(raw, run_time)
    if source == "sreality":
        return normalize_sreality(raw, run_time)
    if _is_bezrealitky_api(raw):
        return normalize_bezrealitky_api(raw, run_time)
    return normalize_bezrealitky(raw, run_time)
