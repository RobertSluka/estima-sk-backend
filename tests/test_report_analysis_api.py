"""GET /reports/properties/{id}/analysis — the real evaluation as JSON.

No DB: build_report is monkeypatched, so these cover the endpoint contract
(ReportData passthrough, lang forwarding, 404 mapping) rather than valuation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.read_api import app
from src.services.reports import builder
from src.services.reports.schema import MarketAnalysis, Property, ReportData

client = TestClient(app)


def _fake_report() -> ReportData:
    return ReportData(
        property=Property(id="7", title="3 izbový byt, Furča", locality="Košice"),
        market_analysis=MarketAnalysis(
            estimated_value=185000.0, estimated_low=176000.0, estimated_high=194000.0
        ),
    )


def test_analysis_returns_report_json(monkeypatch):
    seen: dict = {}

    def fake_build_report(property_id, lang="en", **kwargs):
        seen["args"] = (property_id, lang)
        return _fake_report()

    monkeypatch.setattr(builder, "build_report", fake_build_report)
    resp = client.get("/reports/properties/7/analysis?lang=sk")

    assert resp.status_code == 200
    assert seen["args"] == (7, "sk")
    body = resp.json()
    assert body["property"]["title"] == "3 izbový byt, Furča"
    assert body["market_analysis"]["estimated_value"] == 185000.0
    # Full ReportData shape, not a trimmed summary — the frontend picks fields.
    assert "recommendation" in body and "vision_analysis" in body


def test_analysis_missing_property_is_404(monkeypatch):
    def fake_build_report(property_id, lang="en", **kwargs):
        raise builder.PropertyNotFound(f"No property with id {property_id}")

    monkeypatch.setattr(builder, "build_report", fake_build_report)
    resp = client.get("/reports/properties/999999/analysis")
    assert resp.status_code == 404
