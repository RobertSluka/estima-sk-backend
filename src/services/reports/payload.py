"""Build an estima-report-service payload for one property.

Maps the internal ``ReportData`` (assembled by the untouched CZ-ported
``builder``) into the JSON contract of ``estima-report-service``'s
``POST /reports/generate`` (its ``EvaluationPayload`` model), and enriches it
with the Slovak ``market_statistics`` block: the NBS regional €/m² series for
the property's kraj plus the live price/m² distribution of the property's
district segment. The report service then renders the trend chart with the
subject property marked on it.

Only mapping lives here — no rendering, no new valuation logic. The vision
mapping deliberately carries photo-quality signals only (no condition or
renovation claims; report wording is estimates only).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.db import get_cursor
from src.repositories import properties as properties_repo
from src.services.reports import builder, nbs
from src.services.reports.schema import DealType, ReportData


def build_payload(property_id: int, lang: str = "en") -> dict:
    """Full report-service payload for one property. Raises
    ``builder.PropertyNotFound`` when the id doesn't exist."""
    report = builder.build_report(property_id, lang=lang)

    with get_cursor(commit=False) as cur:
        # district/category/city aren't part of ReportData.Property — re-read
        # the row (one indexed SELECT) instead of widening the report schema.
        row = builder._fetch_property(cur, property_id)
        if row is None:
            raise builder.PropertyNotFound(f"No property with id {property_id}")
        distribution = properties_repo.price_per_sqm_distribution(
            cur,
            district=row.get("district"),
            deal_type=row.get("deal_type"),
            category=row.get("category"),
        )

    return assemble(report, row, distribution, lang=lang)


def assemble(
    report: ReportData, row: dict, distribution: dict | None, lang: str = "en"
) -> dict:
    """Pure mapping of ``ReportData`` + property row (+ optional distribution)
    to the report-service payload dict. Split from ``build_payload`` so it can
    be tested without a database."""
    prop = report.property
    rec = report.recommendation

    payload: dict = {
        "report_title": "Property Valuation Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "property": _property_block(report, row),
        "pricing": {
            "currency": prop.currency or "EUR",
            "list_price": prop.price,
            "price_per_sqm": prop.price_per_sqm,
        },
        "valuation": _valuation_block(report),
        "comparables": [
            {
                "label": c.label,
                "locality": c.locality,
                "layout": c.layout,
                "floor_area": c.floor_area,
                "price": c.price,
                "price_per_sqm": c.price_per_sqm,
                "price_difference_vs_subject": c.price_difference_vs_subject,
                "similarity_score": c.similarity_score,
                "source_url": c.source_url,
                "is_subject": c.is_subject,
                "is_median": c.is_median,
            }
            for c in report.comparables
        ],
        "market_statistics": _market_statistics_block(report, row, distribution),
        "benchmarks": _benchmarks_block(report, row),
        "vision_analysis": _vision_block(report),
        "location_facilities": _location_block(report),
        "summary": {
            "headline": rec.attractiveness,
            "recommendation": rec.summary,
            "strengths": rec.strengths,
            "risks": rec.risks,
            "next_steps": rec.next_steps,
        },
        "methodology": {
            "valuation_date": report.meta.generated_at.isoformat(),
            "model_version": "estima-sk-comparables",
            "data_freshness_note": "Comparables read from the live listing database at generation time.",
        },
        # "estima" is the shared production design in estima-report-service;
        # pass the requested language through so sk payloads get sk templates.
        "options": {"template": "estima", "language": lang},
    }
    return payload


def _property_block(report: ReportData, row: dict) -> dict:
    prop = report.property
    return {
        "title": prop.title,
        "deal_type": prop.deal_type.value if prop.deal_type else None,
        "property_type": prop.property_type,
        "layout": prop.layout,
        "address": prop.address,
        "locality": prop.locality,
        "city": row.get("city"),
        "country": "Slovakia",
        "latitude": prop.lat,
        "longitude": prop.lon,
        "floor_area": prop.floor_area,
        "land_area": prop.land_area,
        "source": prop.source,
        "source_url": prop.source_url,
        "first_seen_at": prop.first_seen_at.date().isoformat() if prop.first_seen_at else None,
        "last_seen_at": prop.last_seen_at.date().isoformat() if prop.last_seen_at else None,
        "days_on_market": prop.days_on_market,
        "images": prop.image_urls,
    }


def _valuation_block(report: ReportData) -> dict:
    prop = report.property
    market = report.market_analysis
    per_sqm = None
    if market.estimated_value and prop.floor_area:
        per_sqm = round(market.estimated_value / prop.floor_area)
    return {
        "estimated_value": market.estimated_value,
        "estimated_price_per_sqm": per_sqm,
        "recommended_price_range": {
            "low": market.estimated_low,
            "mid": market.estimated_value,
            "high": market.estimated_high,
        },
        "local_median_price": market.local_median_price,
        "local_median_price_per_sqm": market.local_median_price_per_sqm,
        "sample_size": market.comparable_count,
        "why_this_estimate": [market.explanation] if market.explanation else [],
    }


def _market_statistics_block(
    report: ReportData, row: dict, distribution: dict | None
) -> dict:
    block = nbs.block(row.get("district"), row.get("city"))
    block["subject_price_per_sqm"] = report.property.price_per_sqm
    if distribution:
        segment = row.get("category") or "listings"
        block["distribution"] = {
            "scope": f"Active {segment} listings, {row.get('district') or 'local market'}",
            "min_price_per_sqm": _f(distribution.get("min")),
            "p25_price_per_sqm": _f(distribution.get("p25")),
            "median_price_per_sqm": _f(distribution.get("median")),
            "p75_price_per_sqm": _f(distribution.get("p75")),
            "max_price_per_sqm": _f(distribution.get("max")),
            "sample_size": distribution.get("sample_size"),
        }
    return block


def _benchmarks_block(report: ReportData, row: dict) -> list[dict]:
    """Slovak market-index entries for the report's "Market Benchmarks" section.

    Local listing median (asking) plus the NBS regional realized-price index.
    The NBS entry is a sale-price benchmark, so it is omitted for rent listings
    — mixing €/m² sale prices with €/m²/month rents on one bar scale would be
    meaningless.
    """
    market = report.market_analysis
    entries: list[dict] = []

    if market.local_median_price_per_sqm:
        entries.append(
            {
                "name": "Estima local listing median",
                "benchmark_type": "listing_asking",
                "value_per_sqm": market.local_median_price_per_sqm,
                "source": "Estima listing index",
            }
        )

    if report.property.deal_type != DealType.RENT:
        key = nbs.region_key(row.get("district"), row.get("city"))
        latest = nbs.series(key, quarters=1)[-1]
        entries.append(
            {
                "name": f"NBS index — {nbs.REGION_LABELS[key]}",
                "benchmark_type": "realized_sale",
                "value_per_sqm": latest["value"],
                "source": f"{nbs.SOURCE}, {nbs.LATEST_PERIOD}",
            }
        )

    return entries


def _vision_block(report: ReportData) -> dict:
    vision = report.vision_analysis
    if not vision.available:
        return {"available": False}
    images = [i for i in vision.images if i is not None]

    def _avg(field: str) -> float | None:
        vals = [getattr(i, field) for i in images if getattr(i, field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    # Photo-quality signals only — condition/renovation fields are deliberately
    # not forwarded (report wording: estimates, never condition claims).
    # `images` feeds the template's gallery; vision rows carry no URLs of
    # their own, so the listing photos (= the analysed gallery) are the source.
    return {
        "available": True,
        "summary": vision.summary,
        "photo_quality": vision.visual_quality_score,
        "brightness": _avg("brightness"),
        "sharpness": _avg("sharpness"),
        "gallery_size": vision.gallery_size,
        "images": report.property.image_urls[:3],
    }


def _location_block(report: ReportData) -> dict:
    loc = report.location_analysis
    if not loc.available:
        return {"available": False}
    counts = [
        ("Public transport (500 m)", loc.nearby_transport_count_500m),
        ("Groceries (500 m)", loc.nearby_grocery_count_500m),
        ("Schools (1 km)", loc.nearby_schools_count_1km),
        ("Parks (1 km)", loc.nearby_parks_count_1km),
        ("Restaurants (1 km)", loc.nearby_restaurants_count_1km),
        ("Healthcare (1 km)", loc.nearby_healthcare_count_1km),
    ]
    facilities = [
        {"category": label, "count": count}
        for label, count in counts
        if count is not None
    ]
    return {
        "available": bool(facilities),
        "map_image_url": loc.static_map_url,
        "facilities": facilities,
    }


def _f(value) -> float | None:
    """NUMERIC columns arrive as Decimal — the payload wants plain floats."""
    return float(value) if value is not None else None
