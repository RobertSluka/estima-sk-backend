"""Tests for the showcase enrichment overlay in ``payload``.

Pure — no DB. The overlay reads the checked-in
``src/services/reports/showcase_enrichment/<id>.json`` data files.
"""

from __future__ import annotations

import copy

from src.services.reports import payload

# One URL that is present in showcase_enrichment/416.json — the overlay's
# staleness guard keys on evaluated∩live being non-empty.
EVALUATED_URL = "https://www.bazos.sk/img/1/291/193231291.jpg"


def _base_payload(images: list[str]) -> dict:
    return {
        "property": {"images": images},
        "vision_analysis": {"available": False},
    }


def test_enrichment_applied_when_gallery_matches():
    enriched = payload._apply_showcase_enrichment(_base_payload([EVALUATED_URL]), 416)

    metrics = enriched["vision_analysis"]["image_metrics"]
    assert len(metrics) == 13
    assert all({"url", "note"} <= set(m) for m in metrics)

    ca = enriched["condition_assessment"]
    assert ca["available"] is True
    assert ca["overall_score"] == 65
    assert ca["overall_label"] == "Čiastočne renovovaný"
    assert len(ca["items"]) == 7


def test_property_without_enrichment_file_is_unchanged():
    before = _base_payload([EVALUATED_URL])
    after = payload._apply_showcase_enrichment(copy.deepcopy(before), 999999)
    assert after == before


def test_stale_gallery_drops_enrichment():
    before = _base_payload(["https://www.bazos.sk/img/1/1/replaced-photo.jpg"])
    after = payload._apply_showcase_enrichment(copy.deepcopy(before), 416)
    assert after == before
