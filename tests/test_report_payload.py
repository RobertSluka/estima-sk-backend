"""Pure tests for the estima-report-service payload path — no DB needed.

Covers the NBS static series (region resolution, series shape, YoY math) and
the ReportData → EvaluationPayload mapping in payload.assemble().
"""

from __future__ import annotations

from decimal import Decimal

from src.services.reports import nbs, payload
from src.services.reports.schema import (
    Comparable,
    DealType,
    MarketAnalysis,
    Property,
    Recommendation,
    ReportData,
    VisionAnalysis,
)


# --------------------------------------------------------------------------- #
# NBS series
# --------------------------------------------------------------------------- #

def test_region_key_resolves_okres_to_nbs_region():
    assert nbs.region_key("Košice") == "KE"
    assert nbs.region_key("Malacky") == "BA"
    assert nbs.region_key("Poprad") == "PO"


def test_region_key_falls_back_to_city_then_national():
    assert nbs.region_key(None, "Bratislava") == "BA"
    assert nbs.region_key("Neverland", None) == "SR"
    assert nbs.region_key(None, None) == "SR"


def test_series_shape_and_order():
    pts = nbs.series("BA")
    assert len(pts) == 9
    assert pts[-1] == {"period": "1Q 2026", "value": 3845.0}
    values_ok = all({"period", "value"} <= set(p) for p in pts)
    assert values_ok
    # Oldest first — the chart draws left to right.
    assert pts[0]["period"] == "1Q 2024"


def test_block_computes_yoy_from_same_quarter_last_year():
    block = nbs.block("Bratislava")
    assert block["region"] == "Bratislava Region"
    assert block["average_price_per_sqm"] == 3845.0
    # 1Q 2026 vs 1Q 2025: (3845.0 - 3486.1) / 3486.1 * 100
    assert block["yoy_change"] == 10.3
    assert "National Bank of Slovakia" in block["source"]


# --------------------------------------------------------------------------- #
# Payload assembly
# --------------------------------------------------------------------------- #

def _report() -> ReportData:
    return ReportData(
        property=Property(
            id="7",
            title="3 izbový byt, Furča",
            locality="Košice",
            deal_type=DealType.SALE,
            layout="3-izb",
            floor_area=63.5,
            price=178000.0,
            price_per_sqm=2803.15,
            currency="EUR",
            source="bazos",
            source_url="https://example.com/listing/7",
        ),
        market_analysis=MarketAnalysis(
            estimated_value=185000.0,
            estimated_low=176000.0,
            estimated_high=194000.0,
            local_median_price=181000.0,
            local_median_price_per_sqm=2900.0,
            comparable_count=12,
            explanation="Based on 12 active comparables in Košice.",
        ),
        comparables=[
            Comparable(label="Subject property", price=178000.0, is_subject=True),
            Comparable(label="Best comparable 1", price=181000.0, similarity_score=88.0),
        ],
        vision_analysis=VisionAnalysis(available=False),
        recommendation=Recommendation(
            summary="Priced below the local median.",
            attractiveness="Fairly priced",
            strengths=["Below regional average price per m²"],
            risks=["Thin comparable sample"],
        ),
    )


def _row() -> dict:
    return {
        "id": 7,
        "district": "Košice",
        "city": "Košice",
        "deal_type": "buy",
        "category": "apartment",
    }


def test_assemble_maps_core_fields():
    doc = payload.assemble(_report(), _row(), distribution=None)

    assert doc["property"]["deal_type"] == "sale"
    assert doc["property"]["country"] == "Slovakia"
    assert doc["pricing"] == {
        "currency": "EUR",
        "list_price": 178000.0,
        "price_per_sqm": 2803.15,
    }
    assert doc["valuation"]["estimated_value"] == 185000.0
    assert doc["valuation"]["recommended_price_range"] == {
        "low": 176000.0,
        "mid": 185000.0,
        "high": 194000.0,
    }
    assert doc["valuation"]["estimated_price_per_sqm"] == round(185000.0 / 63.5)
    assert len(doc["comparables"]) == 2
    assert doc["comparables"][0]["is_subject"] is True
    assert doc["summary"]["headline"] == "Fairly priced"
    assert doc["options"] == {"template": "default", "language": "en"}


def test_assemble_market_statistics_uses_kosice_series_and_subject():
    doc = payload.assemble(_report(), _row(), distribution=None)
    ms = doc["market_statistics"]

    assert ms["region"] == "Košice Region"
    assert ms["subject_price_per_sqm"] == 2803.15
    assert ms["series"][-1] == {"period": "1Q 2026", "value": 2682.3}
    assert "distribution" not in ms


def test_assemble_distribution_converts_decimals():
    distribution = {
        "sample_size": 42,
        "min": Decimal("2100.50"),
        "p25": Decimal("2500"),
        "median": Decimal("2800"),
        "p75": Decimal("3100"),
        "max": Decimal("3900"),
    }
    ms = payload.assemble(_report(), _row(), distribution)["market_statistics"]

    dist = ms["distribution"]
    assert dist["min_price_per_sqm"] == 2100.5
    assert isinstance(dist["median_price_per_sqm"], float)
    assert dist["sample_size"] == 42
    assert "Košice" in dist["scope"]


def test_assemble_benchmarks_pair_local_median_with_nbs_index():
    doc = payload.assemble(_report(), _row(), distribution=None)
    benchmarks = doc["benchmarks"]

    assert [b["name"] for b in benchmarks] == [
        "Estima local listing median",
        "NBS index — Košice Region",
    ]
    assert benchmarks[0]["benchmark_type"] == "listing_asking"
    assert benchmarks[0]["value_per_sqm"] == 2900.0
    assert benchmarks[1]["benchmark_type"] == "realized_sale"
    assert benchmarks[1]["value_per_sqm"] == 2682.3
    assert "1Q 2026" in benchmarks[1]["source"]


def test_assemble_benchmarks_skip_nbs_sale_index_for_rent_listings():
    report = _report()
    report.property.deal_type = DealType.RENT
    benchmarks = payload.assemble(report, _row(), distribution=None)["benchmarks"]

    assert [b["name"] for b in benchmarks] == ["Estima local listing median"]


def test_assemble_vision_carries_photo_quality_signals_only():
    report = _report()
    report.vision_analysis = VisionAnalysis(
        available=True,
        visual_quality_score=74.0,
        overall_condition=None,
        summary="Photos are bright and sharp.",
    )
    doc = payload.assemble(report, _row(), distribution=None)

    vision = doc["vision_analysis"]
    assert vision["available"] is True
    assert vision["photo_quality"] == 74.0
    # No condition/renovation claims may leave this backend.
    assert "overall_condition_score" not in vision
    assert "renovation_score" not in vision
    assert "price_adjustment" not in vision
