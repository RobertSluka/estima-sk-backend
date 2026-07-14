"""
Assemble a `ReportData` for a property_id from the live database.

This is the only module in the reports package that touches Postgres. It reads
the subject property, derives a market estimate from local comparables, pulls
any stored vision scores, and writes a plain-language recommendation — always
degrading gracefully (missing comparables, vision, or coordinates never raise;
the corresponding section just renders its fallback).

The heavy ML predictor is intentionally *not* required here: the estimate is
built from local comparables/medians, which is robust and always available. A
model-based estimate can be layered in later at the marked hook.
"""

from __future__ import annotations

import logging
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from src.db import get_cursor
from src.services import vision_scoring
from src.services.reports import geo, i18n
from src.services.reports.schema import (
    Comparable,
    DealType,
    LocationAnalysis,
    MarketAnalysis,
    MarketBenchmark,
    NearestFacility,
    Property,
    Recommendation,
    ReportData,
    ReportMeta,
    ValuationLabel,
    VisionAnalysis,
)
from src.repositories import location_scores, market_benchmarks, vision_scores

logger = logging.getLogger(__name__)

# How wide to cast the comparable net and how many "best" comps to show.
_MAX_COMPARABLES = 3
_CANDIDATE_LIMIT = 200
# Explicit user selections may exceed the auto cap, but keep the PDF bounded.
_MAX_PICKED_COMPARABLES = 20

# A comparable below this similarity is considered too weak to show, even if
# that leaves fewer than _MAX_COMPARABLES rows.
_SIMILARITY_FLOOR = 60.0
# If fewer district candidates clear the floor than this, widen to city-level.
_MIN_STRONG_COMPARABLES = 3


class PropertyNotFound(Exception):
    """Raised when no property row matches the requested id."""


# --------------------------------------------------------------------------- #
# Public entry point                                                            #
# --------------------------------------------------------------------------- #

def build_report(
    property_id: int, lang: str = "en", comparable_ids: Optional[list[int]] = None,
) -> ReportData:
    """Build a complete `ReportData` for one property. Raises PropertyNotFound.

    `lang` ("en" or "cs") controls the language of all generated prose
    (explanations, recommendation, vision summary) as well as the report's
    static metadata (disclaimer). It must match the `lang` later passed to
    `pdf.render_html`/`render_pdf` so the report is fully single-language.

    `comparable_ids` overrides the auto-picked "best comparable" rows with an
    explicit, ordered selection (the analyses UI lets users curate the set).
    None keeps the automatic ranking; an empty list shows no best-comp rows.
    Market statistics (median, estimate) always come from the full candidate
    pool so a hand-picked set can't skew the valuation.
    """
    lang = i18n.normalize_lang(lang)
    with get_cursor(commit=False) as cur:
        row = _fetch_property(cur, property_id)
        if row is None:
            raise PropertyNotFound(f"No property with id {property_id}")

        candidates, widened = _fetch_candidates(cur, row)
        picked = (
            _fetch_by_ids(cur, row, comparable_ids)
            if comparable_ids is not None else None
        )
        vision_row = _fetch_vision(cur, property_id)
        location_row = _fetch_location(cur, property_id)
        benchmark_row = _fetch_benchmark(cur, row)

    prop = _to_property(row, lang)
    market, comparables = _build_market(row, candidates, widened, lang, picked=picked)

    # Location (Overpass, when not already cached in location_scores) and
    # on-demand vision scoring are independent network calls; run them
    # concurrently so a cold report (neither cached yet) pays roughly
    # max(location, vision) instead of their sum. Each degrades to its own
    # fallback on failure/timeout — see geo.py and vision_scoring.score_on_demand.
    with ThreadPoolExecutor(max_workers=2) as pool:
        location_future = pool.submit(_build_location, property_id, prop, lang, location_row)
        vision_row_future = pool.submit(_ensure_vision_row, row, vision_row)
        location = location_future.result()
        vision_row = vision_row_future.result()

    vision = _build_vision(vision_row, market, prop, lang)
    recommendation = _build_recommendation(prop, market, vision, location, lang)

    return ReportData(
        meta=ReportMeta(
            report_id=f"EST-{property_id}",
            disclaimer=i18n.strings(lang)["disclaimer"],
        ),
        property=prop,
        market_analysis=market,
        benchmarks=_build_benchmarks(benchmark_row, row, lang),
        comparables=comparables,
        vision_analysis=vision,
        location_analysis=location,
        recommendation=recommendation,
    )


# --------------------------------------------------------------------------- #
# Data access                                                                   #
# --------------------------------------------------------------------------- #

def _fetch_property(cur, property_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT id, source, source_listing_id, url, deal_type, category,
               name, locality, city, district, layout,
               floor_area, land_area, lat, lon, image_url, images, currency,
               first_seen_at, last_seen_at, current_price, current_price_per_sqm
        FROM properties
        WHERE id = %s
        """,
        (property_id,),
    )
    return cur.fetchone()


def _fetch_candidates(cur, subject: dict) -> tuple[list[dict], bool]:
    """Active listings in the same district+category+deal_type (excluding self).

    Widens to city-level (merged in, not replacing the district rows) whenever
    the district pool has fewer than `_MIN_STRONG_COMPARABLES` listings that
    clear `_SIMILARITY_FLOOR` — i.e. a thin district is padded out with wider
    comparables instead of ranking in weak district-only matches. Returns
    ``(candidates, widened)`` so the caller can note the widening in the
    market explanation.
    """
    def _query(scope_col: str, scope_val) -> list[dict]:
        if scope_val is None:
            return []
        cur.execute(
            f"""
            SELECT id, locality, district, layout, floor_area,
                   current_price, current_price_per_sqm, url
            FROM properties
            WHERE active = TRUE
              AND id <> %(id)s
              AND current_price IS NOT NULL
              AND current_price_per_sqm IS NOT NULL
              AND {scope_col} = %(scope)s
              AND (%(category)s IS NULL OR category = %(category)s)
              AND (%(deal_type)s IS NULL OR deal_type = %(deal_type)s)
            LIMIT %(limit)s
            """,
            {
                "id": subject["id"],
                "scope": scope_val,
                "category": subject.get("category"),
                "deal_type": subject.get("deal_type"),
                "limit": _CANDIDATE_LIMIT,
            },
        )
        return cur.fetchall()

    district_rows = _query("district", subject.get("district"))
    strong = sum(1 for r in district_rows if _similarity(subject, r) >= _SIMILARITY_FLOOR)
    if strong >= _MIN_STRONG_COMPARABLES:
        return district_rows, False

    city_rows = _query("city", subject.get("city"))
    seen_ids = {r["id"] for r in district_rows}
    merged = district_rows + [r for r in city_rows if r["id"] not in seen_ids]
    return merged, len(merged) > len(district_rows)


def _fetch_by_ids(cur, subject: dict, ids: list[int]) -> list[dict]:
    """The user-picked comparable listings, in the order the ids were given.

    Mirrors the column set of `_fetch_candidates` but intentionally skips its
    active/price/scope filters — an explicitly chosen listing is shown even if
    it went inactive or sits in another district. Unknown ids and the subject
    itself are silently dropped.
    """
    ids = [i for i in ids if i != subject["id"]][:_MAX_PICKED_COMPARABLES]
    if not ids:
        return []
    cur.execute(
        """
        SELECT id, locality, district, layout, floor_area,
               current_price, current_price_per_sqm, url
        FROM properties
        WHERE id = ANY(%s)
        """,
        (ids,),
    )
    by_id = {r["id"]: r for r in cur.fetchall()}
    return [by_id[i] for i in ids if i in by_id]


def _fetch_vision(cur, property_id: int) -> Optional[dict]:
    return vision_scores.get(cur, property_id)


def _ensure_vision_row(row: dict, vrow: Optional[dict]) -> Optional[dict]:
    """Return a cached vision_scores row, or score this property on demand.

    Runs off the request thread (see build_report's ThreadPoolExecutor), so a
    slow/unreachable vision service only affects this section's fallback, not
    the rest of the report.
    """
    if vrow is not None:
        return vrow
    prop_row = {
        "id": row["id"],
        "source": row.get("source"),
        "images": row.get("images"),
        "layout": row.get("layout"),
        "floor_area": row.get("floor_area"),
        "district": row.get("district"),
    }
    return vision_scoring.score_on_demand(prop_row)


def _fetch_location(cur, property_id: int) -> Optional[dict]:
    return location_scores.get(cur, property_id)


def _fetch_benchmark(cur, row: dict) -> Optional[dict]:
    """Latest external index row for the subject's region (national fallback).

    SK: benchmark rows come from the NBS regional price index, which is
    kraj-level — resolve the subject's okres (properties.district) to its kraj
    and match the benchmark stored as "<Kraj> kraj". Unresolved districts fall
    back to the SR national row (granularity 'city'). NBS publishes sale prices
    only, so rent listings simply find no row and the section degrades.
    """
    metric = (
        "realized_rent_per_sqm_month"
        if _deal_type(row) == DealType.RENT
        else "realized_price_per_sqm"
    )
    from src.services import slovak_regions

    okres = row.get("district") or ""
    kraj = slovak_regions.kraj_of_okres(okres)
    district = f"{kraj} kraj" if kraj else okres
    return market_benchmarks.for_district(cur, district=district, metric=metric)


# --------------------------------------------------------------------------- #
# Section builders                                                              #
# --------------------------------------------------------------------------- #

def _build_benchmarks(
    bench: Optional[dict], row: dict, lang: str = "en"
) -> list[MarketBenchmark]:
    """Map a market_benchmarks row to the report's external-index entries.

    A single-country anchor: CZ properties only ever see the Czech index
    (the table holds nothing else); reports degrade to no section when the
    district has no benchmark row at all.
    """
    if not bench or bench.get("value_czk_per_sqm") is None:
        return []

    strings = i18n.strings(lang)
    metric = bench.get("metric") or ""
    unit = (
        strings["benchmark_unit_rent"]
        if metric.endswith("_month")
        else strings["benchmark_unit_sale"]
    )
    scope = (
        bench.get("district")
        if bench.get("granularity") == "district"
        else bench.get("city")
    )

    # "2024_Q3" → "Q3 2024" for display.
    period = bench.get("period") or ""
    m = re.match(r"^(\d{4})_Q(\d)$", period)
    if m:
        period = f"Q{m.group(2)} {m.group(1)}"

    return [
        MarketBenchmark(
            name=bench.get("source_name"),
            value_per_sqm=float(bench["value_czk_per_sqm"]),
            unit=unit,
            period=period,
            scope=scope,
        )
    ]


def _deal_type(row: dict) -> Optional[DealType]:
    dt = (row.get("deal_type") or "").lower()
    url = (row.get("url") or "").lower()
    if dt in ("buy", "sale", "prodej") or "prodej" in url:
        return DealType.SALE
    if dt in ("rent", "pronajem") or "pronajem" in url or "pronájem" in url:
        return DealType.RENT
    return None


def _to_property(row: dict, lang: str) -> Property:
    images = row.get("images") or []
    image_urls = [i for i in images if isinstance(i, str)]
    if row.get("image_url") and row["image_url"] not in image_urls:
        image_urls.insert(0, row["image_url"])

    days_on_market = None
    first, last = row.get("first_seen_at"), row.get("last_seen_at")
    if first:
        end = last or datetime.now(timezone.utc)
        try:
            days_on_market = max((end - first).days, 0)
        except TypeError:
            days_on_market = None

    return Property(
        id=str(row["id"]),
        title=row.get("name"),
        locality=row.get("locality"),
        address=row.get("locality"),
        property_type=i18n.category_word(lang, row.get("category")),
        deal_type=_deal_type(row),
        layout=row.get("layout"),
        floor_area=_f(row.get("floor_area")),
        land_area=_f(row.get("land_area")),
        price=_f(row.get("current_price")),
        price_per_sqm=_f(row.get("current_price_per_sqm")),
        currency=row.get("currency") or "CZK",
        source=row.get("source"),
        source_url=row.get("url"),
        image_urls=image_urls,
        lat=_f(row.get("lat")),
        lon=_f(row.get("lon")),
        first_seen_at=first,
        last_seen_at=last,
        days_on_market=days_on_market,
    )


def _similarity(subject: dict, cand: dict) -> float:
    """0–100 blend of layout match, floor-area proximity and price/m² proximity."""
    score, weight = 0.0, 0.0

    # Layout exact match (weight 40)
    weight += 40
    if subject.get("layout") and subject["layout"] == cand.get("layout"):
        score += 40

    # Floor-area proximity (weight 30)
    sa, ca = _f(subject.get("floor_area")), _f(cand.get("floor_area"))
    if sa and ca and sa > 0:
        weight += 30
        score += 30 * max(0.0, 1 - abs(sa - ca) / sa)

    # Price-per-m² proximity (weight 30)
    sp, cp = _f(subject.get("current_price_per_sqm")), _f(cand.get("current_price_per_sqm"))
    if sp and cp and sp > 0:
        weight += 30
        score += 30 * max(0.0, 1 - abs(sp - cp) / sp)

    return round((score / weight) * 100, 0) if weight else 0.0


def _build_market(
    subject: dict, candidates: list[dict], widened: bool, lang: str,
    picked: Optional[list[dict]] = None,
) -> tuple[MarketAnalysis, list[Comparable]]:
    P = i18n.prose(lang)
    asking = _f(subject.get("current_price"))
    area = _f(subject.get("floor_area"))

    prices = [_f(c["current_price"]) for c in candidates if _f(c.get("current_price"))]
    pps = [_f(c["current_price_per_sqm"]) for c in candidates if _f(c.get("current_price_per_sqm"))]
    median_price = round(statistics.median(prices)) if prices else None
    median_pps = round(statistics.median(pps)) if pps else None

    # Estimate: median price/m² × subject area (robust, always available).
    # HOOK: swap/blend in the ML predictor (src.services.prediction.predict) here.
    estimate = None
    if median_pps and area:
        estimate = round(median_pps * area)
    elif median_price:
        estimate = median_price
    est_low = round(estimate * 0.95) if estimate else None
    est_high = round(estimate * 1.05) if estimate else None

    diff = diff_pct = label = None
    if asking is not None and estimate:
        diff = asking - estimate
        diff_pct = round(diff / estimate * 100, 1)
        if diff_pct <= -5:
            label = ValuationLabel.UNDERVALUED
        elif diff_pct >= 5:
            label = ValuationLabel.OVERPRICED
        else:
            label = ValuationLabel.FAIR

    # An explicit user selection is shown as-is (their order, no similarity
    # floor — they chose it). Otherwise rank candidates by similarity and drop
    # anything below the floor rather than padding the "best" rows out with
    # weak matches (see _fetch_candidates).
    if picked is not None:
        ranked = [{**c, "_sim": _similarity(subject, c)} for c in picked]
    else:
        ranked = sorted(
            (c for c in ({**c, "_sim": _similarity(subject, c)} for c in candidates)
             if c["_sim"] >= _SIMILARITY_FLOOR),
            key=lambda c: c["_sim"], reverse=True,
        )
    comparables: list[Comparable] = [
        Comparable(
            label=P["comp_subject"], locality=subject.get("locality"),
            layout=subject.get("layout"), floor_area=area, price=asking,
            price_per_sqm=_f(subject.get("current_price_per_sqm")),
            similarity_score=100, is_subject=True,
        )
    ]
    if median_price is not None:
        median_area = (
            round(statistics.median([_f(c["floor_area"]) for c in candidates if _f(c.get("floor_area"))]))
            if any(_f(c.get("floor_area")) for c in candidates) else None
        )
        # Price/m² for this row must reconcile with its own price and area
        # columns (price ÷ area), not the independent cross-listing median of
        # price/m² (that figure is reported separately as local_median_price_per_sqm).
        median_row_pps = round(median_price / median_area) if median_area else median_pps
        comparables.append(Comparable(
            label=P["comp_median"], locality=subject.get("district") or subject.get("locality"),
            layout=subject.get("layout"),
            floor_area=median_area,
            price=median_price, price_per_sqm=median_row_pps,
            price_difference_vs_subject=(median_price - asking) if asking is not None else None,
            similarity_score=None, is_median=True,
        ))
    # Picked sets are already bounded by _MAX_PICKED_COMPARABLES at fetch time.
    best = ranked if picked is not None else ranked[:_MAX_COMPARABLES]
    for i, c in enumerate(best, start=1):
        cp = _f(c.get("current_price"))
        comparables.append(Comparable(
            label=P["comp_best"].format(i=i), locality=c.get("locality"), layout=c.get("layout"),
            floor_area=_f(c.get("floor_area")), price=cp,
            price_per_sqm=_f(c.get("current_price_per_sqm")),
            price_difference_vs_subject=(cp - asking) if (cp and asking is not None) else None,
            similarity_score=c["_sim"], source_url=c.get("url"),
        ))

    explanation = _market_explanation(
        diff_pct, median_pps, _f(subject.get("current_price_per_sqm")), widened, lang,
    )

    market = MarketAnalysis(
        estimated_value=estimate, estimated_low=est_low, estimated_high=est_high,
        local_median_price=median_price, local_median_price_per_sqm=median_pps,
        price_difference=diff, price_difference_percent=diff_pct,
        valuation_label=label, comparable_count=len(candidates), explanation=explanation,
    )
    return market, comparables


def _market_explanation(diff_pct, median_pps, subject_pps, widened: bool, lang: str) -> Optional[str]:
    P = i18n.prose(lang)
    if diff_pct is None:
        return P["expl_none"]
    parts = []
    if diff_pct <= -1:
        parts.append(P["expl_below"].format(pct=abs(diff_pct)))
    elif diff_pct >= 1:
        parts.append(P["expl_above"].format(pct=diff_pct))
    else:
        parts.append(P["expl_inline"])
    if median_pps and subject_pps:
        rel = (subject_pps - median_pps) / median_pps * 100
        if rel <= -1:
            parts.append(P["expl_pps_below"].format(rel=abs(rel)))
        elif rel >= 1:
            parts.append(P["expl_pps_above"].format(rel=rel))
        else:
            parts.append(P["expl_pps_close"])
    if widened:
        parts.append(P["expl_widened"])
    return " ".join(parts)


# --- vision ---------------------------------------------------------------- #

def _to_100(v) -> Optional[float]:
    """Normalise a stored score to 0–100.

    The vision service writes 0–10 scores (see vision_scores rows); 0–1 and
    0–100 inputs are tolerated for older/foreign rows. The scale is inferred
    from the magnitude, so a genuine 0–100 score below 10 would be stretched —
    acceptable, because no producer writes that scale today.
    """
    f = _f(v)
    if f is None:
        return None
    if f <= 1.0:
        f *= 100
    elif f <= 10.0:
        f *= 10
    return round(max(0.0, min(100.0, f)), 0)


def _build_vision(vrow: Optional[dict], market: MarketAnalysis, prop: Property, lang: str) -> VisionAnalysis:
    """Photo-quality section from a vision_scores row.

    Reports only what deterministic image analysis can measure — brightness,
    sharpness, exposure, resolution, gallery coverage. Never a condition
    label, never a price adjustment: photo quality is not evidence of
    property condition, and any valuation impact belongs to the trained
    model (vision_* features), not to hand-written percentage rules.
    """
    if not vrow:
        return VisionAnalysis(available=False)
    if vrow.get("model_provider") == "mock":
        # Mock rows are placeholder noise (hash-derived, see estima-vision's
        # mock provider) — render the honest "no photo analysis" fallback.
        return VisionAnalysis(available=False)

    # Quality metrics are stored 0..1; legacy 0.1.0 rows carried a measurable
    # photo_quality on the deprecated 0-10 scale — accept it as fallback.
    photo_quality = _to_100(vrow.get("image_quality"))
    if photo_quality is None:
        photo_quality = _to_100(vrow.get("photo_quality"))
    # Rows without a single measurable metric (dead-gallery legacy rows,
    # empty-attempt back-off markers) carry no evidence to present.
    if photo_quality is None and vrow.get("brightness") is None:
        return VisionAnalysis(available=False)
    brightness = _to_100(vrow.get("brightness"))
    sharpness = _to_100(vrow.get("sharpness"))
    exposure = _to_100(vrow.get("exposure_quality"))
    resolution = _to_100(vrow.get("resolution_quality"))
    blurry_ratio = _f(vrow.get("blurry_image_ratio"))
    dark_ratio = _f(vrow.get("dark_image_ratio"))
    gallery_size = vrow.get("gallery_size")
    confidence = _f(vrow.get("confidence"))

    P = i18n.prose(lang)
    observations: list[str] = []
    if brightness is not None and exposure is not None:
        if brightness >= 50 and exposure >= 70:
            observations.append(P["obs_bright_well_exposed"])
        elif brightness < 50:
            observations.append(P["obs_dim"])
        else:
            observations.append(P["obs_uneven_exposure"])
    if blurry_ratio is not None and blurry_ratio > 0:
        observations.append(
            P["obs_mostly_blurry"] if blurry_ratio >= 0.5 else P["obs_some_blurry"]
        )
    if resolution is not None:
        observations.append(
            P["obs_resolution_ok"] if resolution >= 60 else P["obs_resolution_low"]
        )
    if gallery_size is not None and gallery_size < 3:
        observations.append(P["obs_limited_coverage"])

    summary = (
        P["vision_summary"].format(n=gallery_size) if gallery_size is not None
        else P["vision_summary_no_count"]
    )

    return VisionAnalysis(
        available=True,
        visual_quality_score=photo_quality,
        brightness_score=brightness,
        sharpness_score=sharpness,
        gallery_size=gallery_size,
        blurry_image_ratio=blurry_ratio,
        dark_image_ratio=dark_ratio,
        confidence=confidence,
        observations=observations,
        summary=summary,
        images=[],  # per-image detail isn't persisted; aggregate metrics only
    )


# --- location -------------------------------------------------------------- #

def _build_location(
    property_id: int, prop: Property, lang: str, location_row: Optional[dict],
) -> LocationAnalysis:
    """Nearby-facility counts: from location_scores if cached, else live Overpass.

    A cache hit skips Overpass entirely (see location_scoring.py, the batch
    job that warms this table). A cache miss falls back to a live lookup and
    persists it for next time — an unreachable Overpass still degrades to the
    "not computed yet" wording, same as before this cache existed. The map
    image is separately disk-cached inside geo.static_map_data_uri.
    """
    if prop.lat is None or prop.lon is None:
        return LocationAnalysis(available=False)

    map_uri = geo.static_map_data_uri(prop.lat, prop.lon)
    nearest = _nearest_facilities(prop.lat, prop.lon)

    if location_row is not None:
        return LocationAnalysis(
            available=True,
            static_map_url=map_uri,
            **{field: location_row.get(field) for field in location_scores.COUNT_FIELDS},
            nearest_facilities=nearest,
            location_score=_f(location_row.get("location_score")),
            explanation=i18n.prose(lang)["location_ok"],
        )

    counts = geo.fetch_poi_counts(prop.lat, prop.lon)
    if counts is None:
        return LocationAnalysis(
            available=True,
            static_map_url=map_uri,
            nearest_facilities=nearest,
            explanation=i18n.prose(lang)["location_pending"],
        )

    score = geo.location_score(counts)
    fields = geo.poi_counts_to_location_fields(counts)
    with get_cursor() as write_cur:
        location_scores.upsert(write_cur, property_id=property_id, counts=fields, location_score=score)

    return LocationAnalysis(
        available=True,
        static_map_url=map_uri,
        **fields,
        nearest_facilities=nearest,
        location_score=score,
        explanation=i18n.prose(lang)["location_ok"],
    )


def _nearest_facilities(lat: float, lon: float) -> list[NearestFacility]:
    """geo.NearestPoi → schema objects; an unreachable Overpass means an
    empty showcase, never a failed report."""
    pois = geo.fetch_nearest_pois(lat, lon)
    return [
        NearestFacility(category=p.category, name=p.name, distance_m=p.distance_m)
        for p in pois or []
    ]


# --- recommendation -------------------------------------------------------- #

def _build_recommendation(
    prop: Property, market: MarketAnalysis, vision: VisionAnalysis, location: LocationAnalysis, lang: str,
) -> Recommendation:
    P = i18n.prose(lang)
    strengths, risks, steps = [], [], []

    label = market.valuation_label
    if label == ValuationLabel.UNDERVALUED and market.price_difference_percent is not None:
        strengths.append(P["str_below"].format(pct=abs(market.price_difference_percent)))
        verdict = P["verdict_undervalued"]
    elif label == ValuationLabel.OVERPRICED and market.price_difference_percent is not None:
        risks.append(P["risk_above"].format(pct=market.price_difference_percent))
        verdict = P["verdict_overpriced"]
    elif label == ValuationLabel.FAIR:
        strengths.append(P["str_inline"])
        verdict = P["verdict_fair"]
    else:
        verdict = P["verdict_none"]

    # Photo metrics never make the property itself a "strength" or "risk" —
    # they only qualify how much the listing photos can tell a buyer.
    if vision.available:
        risks.append(P["risk_photo_only"])
        if (vision.blurry_image_ratio or 0) >= 0.5 or (vision.dark_image_ratio or 0) >= 0.5:
            risks.append(P["risk_poor_photos"])
    else:
        risks.append(P["risk_no_vision"])

    if prop.days_on_market is not None:
        if prop.days_on_market >= 60:
            risks.append(P["risk_days"].format(days=prop.days_on_market))
        elif prop.days_on_market <= 14:
            strengths.append(P["str_recent"])

    steps = [P["step_viewing"], P["step_building"], P["step_benchmark"]]

    priced = {
        ValuationLabel.UNDERVALUED: P["priced_undervalued"],
        ValuationLabel.FAIR: P["priced_fair"],
        ValuationLabel.OVERPRICED: P["priced_overpriced"],
    }.get(label, P["priced_none"])

    ptype = (prop.property_type.lower() if prop.property_type else P["generic_property"])
    summary = P["rec_summary"].format(
        ptype=ptype,
        loc=prop.locality or P["the_area"],
        priced=priced,
        cond="",  # condition clause removed: photo metrics are not a condition read
    )

    return Recommendation(
        summary=summary, attractiveness=verdict,
        strengths=strengths, risks=risks, next_steps=steps,
    )


# --------------------------------------------------------------------------- #
# Small helpers                                                                 #
# --------------------------------------------------------------------------- #

def _f(value) -> Optional[float]:
    """Best-effort float; None-safe (handles Decimal/str/None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
