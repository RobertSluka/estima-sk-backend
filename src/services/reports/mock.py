"""
Fully-populated sample report — for local rendering, demos and tests.

`sample_report()` returns a realistic `ReportData` with every section filled in
(a Prague apartment). `sparse_report()` returns the same property with vision,
location and comparables stripped out, so you can eyeball the fallback states.

No database or network is required — image URLs point at real listings but the
renderer falls back to a placeholder if they can't be fetched, so this works
fully offline.
"""

from __future__ import annotations

from datetime import date, datetime

from src.services.reports.schema import (
    Comparable,
    DealType,
    LocationAnalysis,
    MarketAnalysis,
    NearestFacility,
    Property,
    Recommendation,
    ReportData,
    ReportMeta,
    ValuationLabel,
    VisionAnalysis,
)

_CURRENCY = "CZK"


def sample_report() -> ReportData:
    prop = Property(
        id="12345",
        title="Bright 2+kk apartment with balcony",
        locality="Praha 5 – Smíchov",
        address="Nádražní, Praha 5 – Smíchov",
        property_type="Apartment",
        deal_type=DealType.SALE,
        layout="2+kk",
        floor_area=58.0,
        land_area=None,
        floor="4th floor of 6",
        price=8_490_000,
        price_per_sqm=146_379,
        currency=_CURRENCY,
        source="bezrealitky",
        source_url="https://www.bezrealitky.cz/nemovitosti-byty-domy/909-nabidka-prodej-bytu",
        image_urls=[
            "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?w=1200",
            "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=1200",
            "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=1200",
        ],
        lat=50.0705,
        lon=14.4045,
        first_seen_at=datetime(2026, 5, 12),
        last_seen_at=datetime(2026, 7, 1),
        days_on_market=50,
    )

    market = MarketAnalysis(
        estimated_value=8_900_000,
        estimated_low=8_450_000,
        estimated_high=9_350_000,
        local_median_price=9_150_000,
        local_median_price_per_sqm=152_500,
        price_difference=8_490_000 - 8_900_000,          # asking - estimate = -410,000
        price_difference_percent=round((8_490_000 - 8_900_000) / 8_900_000 * 100, 1),
        valuation_label=ValuationLabel.UNDERVALUED,
        comparable_count=34,
        explanation=(
            "This property appears about 4.6% below our estimated fair value and "
            "roughly 4% under the local median price per m² for comparable 2+kk "
            "apartments in Praha 5 – Smíchov. The asking price sits below most "
            "comparable listings in the same area, suggesting modest room for "
            "value even before accounting for visual condition."
        ),
    )

    comparables = [
        Comparable(
            label="Subject property", locality="Praha 5 – Smíchov", layout="2+kk",
            floor_area=58.0, price=8_490_000, price_per_sqm=146_379,
            similarity_score=100, is_subject=True,
        ),
        Comparable(
            label="Median comparable", locality="Praha 5", layout="2+kk",
            floor_area=56.0, price=9_150_000, price_per_sqm=152_500,
            price_difference_vs_subject=9_150_000 - 8_490_000, similarity_score=88,
        ),
        Comparable(
            label="Best comparable 1", locality="Praha 5 – Smíchov", layout="2+kk",
            floor_area=60.0, price=8_990_000, price_per_sqm=149_833,
            price_difference_vs_subject=8_990_000 - 8_490_000, similarity_score=94,
            source_url="https://www.bezrealitky.cz/nemovitosti-byty-domy/001",
        ),
        Comparable(
            label="Best comparable 2", locality="Praha 5 – Smíchov", layout="2+kk",
            floor_area=55.0, price=8_600_000, price_per_sqm=156_364,
            price_difference_vs_subject=8_600_000 - 8_490_000, similarity_score=91,
            source_url="https://www.bezrealitky.cz/nemovitosti-byty-domy/002",
        ),
        Comparable(
            label="Best comparable 3", locality="Praha 5 – Anděl", layout="2+kk",
            floor_area=62.0, price=9_400_000, price_per_sqm=151_613,
            price_difference_vs_subject=9_400_000 - 8_490_000, similarity_score=86,
            source_url="https://www.bezrealitky.cz/nemovitosti-byty-domy/003",
        ),
    ]

    vision = VisionAnalysis(
        available=True,
        visual_quality_score=78,
        brightness_score=72,
        sharpness_score=64,
        gallery_size=8,
        blurry_image_ratio=0.13,
        dark_image_ratio=0.0,
        confidence=0.55,
        observations=[
            "The gallery is bright and generally well exposed.",
            "Several images appear blurry.",
            "Image resolution is sufficient for presentation.",
        ],
        summary=(
            "Automated analysis measured the technical quality of 8 listing "
            "photo(s) — brightness, sharpness, exposure and resolution. These "
            "metrics describe the photographs themselves; they are not an "
            "assessment of the property's condition, renovation state or "
            "materials."
        ),
    )

    location = LocationAnalysis(
        available=True,
        static_map_url=None,
        nearby_transport_count_500m=6,
        nearby_grocery_count_500m=4,
        nearby_schools_count_1km=7,
        nearby_parks_count_1km=3,
        nearby_restaurants_count_1km=41,
        nearby_healthcare_count_1km=9,
        nearby_transport_count_1km=14,
        nearby_transport_count_3km=52,
        nearest_facilities=[
            NearestFacility(category="transport", name="Anděl", distance_m=210),
            NearestFacility(category="grocery", name="Albert Supermarket", distance_m=170),
            NearestFacility(category="schools", name="ZŠ a MŠ Kořenského", distance_m=420),
            NearestFacility(category="parks", name="Sady Na Skalce", distance_m=380),
            NearestFacility(category="restaurants", name="Kavárna U Anděla", distance_m=150),
            NearestFacility(category="healthcare", name="Lékárna BENU Anděl", distance_m=260),
        ],
        location_score=86,
        explanation=(
            "The property has strong urban accessibility, with grocery stores, tram "
            "and metro connections, and everyday amenities within walking distance. "
            "Smíchov is a well-established, liquid Prague location with consistent "
            "buyer demand."
        ),
    )

    recommendation = Recommendation(
        summary=(
            "Overall, this property appears fairly-to-attractively priced, sitting "
            "just below our estimated fair value. It may suit buyers looking for a "
            "2+kk apartment in a liquid Prague location. Negotiation space may be "
            "limited given the already competitive asking price, unless comparable "
            "listings begin to show longer time on market."
        ),
        attractiveness="Verdict: attractive entry point, priced below fair value.",
        strengths=[
            "Asking price ~4.6% below estimated fair value.",
            "Excellent location score (86/100) with strong transport access.",
            "Liquid, established Praha 5 – Smíchov micro-market.",
        ],
        risks=[
            "50 days on market — verify why it has not yet sold.",
            "Photo analysis measures image quality only — it says nothing about "
            "the property's actual condition; inspect in person.",
            "Limited negotiation room given competitive pricing.",
        ],
        next_steps=[
            "Arrange an in-person viewing to assess the property's actual condition.",
            "Request the building's ownership and reserve-fund (fond oprav) details.",
            "Benchmark against 2–3 live comparables before making an offer.",
        ],
    )

    return ReportData(
        meta=ReportMeta(
            generated_at=date(2026, 7, 2),
            report_id="EST-2026-12345",
        ),
        property=prop,
        market_analysis=market,
        comparables=comparables,
        vision_analysis=vision,
        location_analysis=location,
        recommendation=recommendation,
    )


def sparse_report() -> ReportData:
    """Same subject property, but with vision / location / comparables missing.

    Useful for eyeballing the fallback states end-to-end.
    """
    full = sample_report()
    return ReportData(
        meta=full.meta,
        property=full.property,
        market_analysis=MarketAnalysis(
            estimated_value=full.market_analysis.estimated_value,
            estimated_low=full.market_analysis.estimated_low,
            estimated_high=full.market_analysis.estimated_high,
            local_median_price=full.market_analysis.local_median_price,
            local_median_price_per_sqm=full.market_analysis.local_median_price_per_sqm,
            price_difference=full.market_analysis.price_difference,
            price_difference_percent=full.market_analysis.price_difference_percent,
            valuation_label=full.market_analysis.valuation_label,
            explanation=full.market_analysis.explanation,
        ),
        comparables=[],                                  # no comparables
        vision_analysis=VisionAnalysis(available=False),  # no vision
        location_analysis=LocationAnalysis(available=False),  # no POIs
        recommendation=full.recommendation,
    )
