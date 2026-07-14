"""
Report data contract.

Everything the PDF template renders comes from a single `ReportData` object.
The template never talks to the database — it only reads these models. That
keeps rendering testable (feed it `mock.sample_report()`) and lets the report
degrade gracefully: almost every field is optional, and the template shows an
explicit fallback wherever data is missing.

Design principles baked into the models:
  * Nothing is required except the property id — a report can be produced from
    very thin data and simply shows "—" / fallback text for the gaps.
  * We never claim to *know* a property's value. `MarketAnalysis` carries an
    estimate with a low/high range and a plain-language explanation.
  * Vision output is deliberately hedged (see `VisionAnalysis.confidence` and
    the cautious wording the template applies).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enumerations (kept as str-enums so they serialise cleanly and read well in   #
# the template).                                                                #
# --------------------------------------------------------------------------- #

class ValuationLabel(str, Enum):
    UNDERVALUED = "undervalued"
    FAIR = "fair"
    OVERPRICED = "overpriced"


class DealType(str, Enum):
    SALE = "sale"
    RENT = "rent"


class Condition(str, Enum):
    POOR = "poor"
    AVERAGE = "average"
    GOOD = "good"
    RENOVATED = "renovated"
    LUXURY = "luxury"


class DetectedRoom(str, Enum):
    KITCHEN = "kitchen"
    BATHROOM = "bathroom"
    LIVING_ROOM = "living room"
    BEDROOM = "bedroom"
    BALCONY = "balcony"
    EXTERIOR = "exterior"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Sections                                                                      #
# --------------------------------------------------------------------------- #

class Property(BaseModel):
    """The subject property — metadata section + cover header."""

    id: str
    title: Optional[str] = None
    locality: Optional[str] = None
    address: Optional[str] = None
    property_type: Optional[str] = None
    deal_type: Optional[DealType] = None
    layout: Optional[str] = None
    floor_area: Optional[float] = None          # m²
    land_area: Optional[float] = None           # m²
    floor: Optional[str] = None
    price: Optional[float] = None               # asking price
    price_per_sqm: Optional[float] = None
    currency: str = "CZK"
    source: Optional[str] = None
    source_url: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list)
    lat: Optional[float] = None
    lon: Optional[float] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    days_on_market: Optional[int] = None


class MarketAnalysis(BaseModel):
    """Where the asking price sits versus the local market + our estimate."""

    estimated_value: Optional[float] = None
    estimated_low: Optional[float] = None
    estimated_high: Optional[float] = None
    local_median_price: Optional[float] = None
    local_median_price_per_sqm: Optional[float] = None
    price_difference: Optional[float] = None            # asking - estimate (CZK/EUR)
    price_difference_percent: Optional[float] = None    # signed %
    valuation_label: Optional[ValuationLabel] = None
    comparable_count: Optional[int] = None
    explanation: Optional[str] = None


class MarketBenchmark(BaseModel):
    """One external market-index reference (e.g. Deloitte Real Index) — a
    macro realized-price anchor, not a comparable listing."""

    name: Optional[str] = None                   # e.g. "Deloitte Real Index"
    value_per_sqm: Optional[float] = None
    unit: Optional[str] = None                   # "CZK/m²" or "CZK/m²/month"
    period: Optional[str] = None                 # display form, e.g. "Q3 2024"
    scope: Optional[str] = None                  # "Praha 4" or the city fallback


class Comparable(BaseModel):
    """One comparable listing (or the synthesised 'median comparable')."""

    label: Optional[str] = None                  # e.g. "Best comparable 1"
    locality: Optional[str] = None
    layout: Optional[str] = None
    floor_area: Optional[float] = None
    price: Optional[float] = None
    price_per_sqm: Optional[float] = None
    price_difference_vs_subject: Optional[float] = None    # signed CZK/EUR
    similarity_score: Optional[float] = None               # 0–100
    source_url: Optional[str] = None
    is_subject: bool = False
    is_median: bool = False


class VisionImage(BaseModel):
    """Per-image visual read. All analytic fields optional — often only the
    preview and an overall score are known."""

    image_url: Optional[str] = None
    detected_room: Optional[DetectedRoom] = None
    brightness: Optional[float] = None           # 0–100
    sharpness: Optional[float] = None            # 0–100
    contrast: Optional[float] = None             # 0–100
    condition_notes: Optional[str] = None
    score: Optional[float] = None                # 0–100


class VisionAnalysis(BaseModel):
    """Photo-quality read of the listing gallery.

    Local deterministic analysis measures the PHOTOGRAPHS, not the property:
    the report may say "bright, some blurry images", never "renovated
    kitchen". `available=False` means we render the honest "no photo
    analysis" fallback.

    Photo quality must not adjust the price estimate — a valuation impact is
    only legitimate once the trained model has empirically learned it from
    the vision_* features.
    """

    available: bool = True
    visual_quality_score: Optional[float] = None        # 0–100, PHOTO quality
    brightness_score: Optional[float] = None            # 0–100
    sharpness_score: Optional[float] = None             # 0–100
    gallery_size: Optional[int] = None                  # analysed images
    blurry_image_ratio: Optional[float] = None          # 0–1
    dark_image_ratio: Optional[float] = None            # 0–1
    confidence: Optional[float] = None                  # 0–1
    observations: List[str] = Field(default_factory=list)  # localized, measurable
    summary: Optional[str] = None
    images: List[VisionImage] = Field(default_factory=list)

    # DEPRECATED — semantic condition claims and vision-driven price
    # adjustments were removed (local analysis cannot support them). Kept
    # optional so historic payload consumers don't break; never populated.
    overall_condition: Optional[Condition] = None
    renovation_score: Optional[float] = None
    luxury_score: Optional[float] = None
    condition_adjustment_percent: Optional[float] = None
    renovation_adjustment_percent: Optional[float] = None
    base_estimate: Optional[float] = None
    adjusted_estimate: Optional[float] = None


class NearestFacility(BaseModel):
    """The closest named facility of one category, for the location showcase."""

    category: str  # transport | grocery | schools | parks | restaurants | healthcare
    name: str
    distance_m: int


class LocationAnalysis(BaseModel):
    """Neighbourhood context from POI counts around the coordinates."""

    available: bool = True
    static_map_url: Optional[str] = None
    nearby_transport_count_500m: Optional[int] = None
    nearby_grocery_count_500m: Optional[int] = None
    nearby_schools_count_1km: Optional[int] = None
    nearby_parks_count_1km: Optional[int] = None
    nearby_restaurants_count_1km: Optional[int] = None
    nearby_healthcare_count_1km: Optional[int] = None
    nearby_transport_count_1km: Optional[int] = None
    nearby_grocery_count_1km: Optional[int] = None
    nearby_transport_count_3km: Optional[int] = None
    nearest_facilities: List[NearestFacility] = Field(default_factory=list)
    location_score: Optional[float] = None              # 0–100
    explanation: Optional[str] = None


class Recommendation(BaseModel):
    """Executive summary — the part a non-technical reader jumps to."""

    summary: Optional[str] = None
    attractiveness: Optional[str] = None        # short verdict phrase
    strengths: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)


class ReportMeta(BaseModel):
    """Branding + generation metadata for the cover/footer."""

    brand: str = "Estima"
    tagline: str = "Real Estate Intelligence"
    generated_at: date = Field(default_factory=date.today)
    report_id: Optional[str] = None
    disclaimer: str = (
        "This report is an evidence-based estimate produced from market data, "
        "comparable listings, property metadata and visual indicators. It is "
        "not a certified appraisal and does not represent a guaranteed value."
    )


class ReportData(BaseModel):
    """The complete, self-contained payload the template renders."""

    meta: ReportMeta = Field(default_factory=ReportMeta)
    property: Property
    market_analysis: MarketAnalysis = Field(default_factory=MarketAnalysis)
    benchmarks: List[MarketBenchmark] = Field(default_factory=list)
    comparables: List[Comparable] = Field(default_factory=list)
    vision_analysis: VisionAnalysis = Field(default_factory=lambda: VisionAnalysis(available=False))
    location_analysis: LocationAnalysis = Field(default_factory=lambda: LocationAnalysis(available=False))
    recommendation: Recommendation = Field(default_factory=Recommendation)
