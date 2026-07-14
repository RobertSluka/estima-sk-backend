"""POST /predict endpoint tests (model mocked) + market_statistics repository (DB, rolled back)."""

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src import read_api
from src.read_api import app
from src.repositories import market_statistics, properties
from src.services import market_statistics as market_statistics_service
from src.services import prediction

client = TestClient(app)

# Market fields supplied explicitly so the endpoint skips the DB lookup.
FULL_BODY = {
    "target": "sale_price",
    "category": "apartment",
    "locality": "Praha 5",
    "district": "Praha 5",
    "layout": "2+kk",
    "floor_area": 50,
    "lat": 50.07,
    "lon": 14.39,
    "market_median_price": 8_000_000,
    "market_median_price_per_sqm": 160_000,
    "market_property_count": 120,
}


def test_predict_returns_model_output(monkeypatch):
    captured = {}

    def fake_predict(request, *, target, property_id=None):
        captured["request"] = request
        captured["target"] = target
        return {"prediction_id": 1, "model_version_id": 2, "target": target,
                "predicted_price": 8_500_000, "predicted_price_per_sqm": None,
                "confidence_low": None, "confidence_high": None}

    monkeypatch.setattr(prediction, "predict", fake_predict)
    resp = client.post("/predict", json=FULL_BODY)

    assert resp.status_code == 200
    body = resp.json()
    assert body["predicted_price"] == 8_500_000
    assert body["market_context"]["auto_filled"] is False
    assert captured["target"] == "sale_price"
    assert captured["request"]["deal_type"] == "buy"       # derived, not client-sent
    assert "target" not in captured["request"]             # not a model feature


def test_predict_rent_target_maps_to_rent_deal_type(monkeypatch):
    captured = {}

    def fake_predict(request, *, target, property_id=None):
        captured["request"] = request
        return {"target": target, "predicted_price": 25_000}

    monkeypatch.setattr(prediction, "predict", fake_predict)
    resp = client.post("/predict", json={**FULL_BODY, "target": "rent_price"})

    assert resp.status_code == 200
    assert captured["request"]["deal_type"] == "rent"


def test_predict_auto_fills_market_context(monkeypatch):
    captured = {}

    def fake_predict(request, *, target, property_id=None):
        captured["request"] = request
        return {"target": target, "predicted_price": 8_000_000}

    def fake_latest_context(cur, **kwargs):
        captured["lookup"] = kwargs
        return {"stat_date": date(2026, 7, 1), "median_price": 7_900_000,
                "median_price_per_sqm": 158_000.0, "property_count": 42}

    class FakeCursorCtx:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(prediction, "predict", fake_predict)
    monkeypatch.setattr(market_statistics, "latest_context", fake_latest_context)
    monkeypatch.setattr(read_api, "get_cursor", lambda **kw: FakeCursorCtx())

    body = {k: v for k, v in FULL_BODY.items() if not k.startswith("market_")}
    resp = client.post("/predict", json=body)

    assert resp.status_code == 200
    assert resp.json()["market_context"] == {
        "auto_filled": True,
        "market_median_price": 7_900_000.0,
        "market_median_price_per_sqm": 158_000.0,
        "market_property_count": 42,
    }
    assert captured["lookup"] == {"deal_type": "buy", "category": "apartment",
                                  "locality": "Praha 5", "layout": "2+kk"}
    assert captured["request"]["market_median_price"] == 7_900_000.0


def test_predict_falls_back_to_district_context(monkeypatch):
    captured = {}

    def fake_predict(request, *, target, property_id=None):
        captured["request"] = request
        return {"target": target, "predicted_price": 8_000_000}

    def fake_district_context(cur, **kwargs):
        captured["district_lookup"] = kwargs
        return {"median_price": 8_100_000, "median_price_per_sqm": 150_000.0,
                "property_count": 7}

    class FakeCursorCtx:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(prediction, "predict", fake_predict)
    monkeypatch.setattr(market_statistics, "latest_context", lambda cur, **kw: None)
    monkeypatch.setattr(market_statistics, "district_context", fake_district_context)
    monkeypatch.setattr(read_api, "get_cursor", lambda **kw: FakeCursorCtx())

    body = {k: v for k, v in FULL_BODY.items() if not k.startswith("market_")}
    resp = client.post("/predict", json=body)

    assert resp.status_code == 200
    assert resp.json()["market_context"]["auto_filled"] is True
    assert resp.json()["market_context"]["market_median_price"] == 8_100_000.0
    assert captured["district_lookup"]["district"] == "Praha 5"


def test_predict_no_active_model_is_503(monkeypatch):
    def fake_predict(request, *, target, property_id=None):
        raise ValueError(f"No active model for target '{target}'. Train one first.")

    monkeypatch.setattr(prediction, "predict", fake_predict)
    resp = client.post("/predict", json=FULL_BODY)

    assert resp.status_code == 503
    assert "No active model" in resp.json()["detail"]


def test_predict_rejects_unknown_target():
    resp = client.post("/predict", json={**FULL_BODY, "target": "avocado_price"})
    assert resp.status_code == 422


def test_predict_rejects_nonpositive_floor_area():
    resp = client.post("/predict", json={**FULL_BODY, "floor_area": 0})
    assert resp.status_code == 422


# --- repository, against the live schema (always rolled back) ---

pytestmark_db = pytest.mark.db


@pytest.mark.db
def test_latest_context_picks_latest_and_largest_sample(db):
    norm = {
        "source": "test_src", "source_listing_id": "mc1", "url": "https://x/mc1",
        "deal_type": "buy", "category": "apartment", "source_category": "byty",
        "name": "Test", "locality": "Testov", "city": "Praha", "district": "Testov",
        "layout": "2+kk", "floor_area": 50, "land_area": None, "lat": None, "lon": None,
        "image_url": None, "currency": "CZK", "price": 5_000_000, "price_per_sqm": 100_000,
    }
    properties.upsert(db, norm, datetime.now(timezone.utc))
    market_statistics_service.aggregate(db, date(2026, 7, 4))

    row = market_statistics.latest_context(
        db, deal_type="buy", category="apartment", locality="Testov", layout="2+kk",
    )
    assert row is not None
    assert row["stat_date"] == date(2026, 7, 4)
    assert float(row["median_price"]) == 5_000_000
    assert row["property_count"] == 1


@pytest.mark.db
def test_district_context_layout_fallback(db):
    norm = {
        "source": "test_src", "source_listing_id": "dc1", "url": "https://x/dc1",
        "deal_type": "buy", "category": "apartment", "source_category": "byty",
        "name": "Test", "locality": "Ulice 1, Testov", "city": "Praha",
        "district": "Praha - Testov", "layout": "3+kk", "floor_area": 70,
        "land_area": None, "lat": None, "lon": None, "image_url": None,
        "currency": "CZK", "price": 9_000_000, "price_per_sqm": 128_571,
    }
    properties.upsert(db, norm, datetime.now(timezone.utc))

    # Exact layout match
    row = market_statistics.district_context(
        db, deal_type="buy", category="apartment", district="Praha - Testov", layout="3+kk",
    )
    assert row is not None and float(row["median_price"]) == 9_000_000

    # No 2+kk in the district → falls back to layout-agnostic sample
    row = market_statistics.district_context(
        db, deal_type="buy", category="apartment", district="Praha - Testov", layout="2+kk",
    )
    assert row is not None and row["property_count"] == 1

    # Unknown district → None
    assert market_statistics.district_context(
        db, deal_type="buy", category="apartment", district="Atlantis", layout=None,
    ) is None


@pytest.mark.db
def test_latest_context_no_match_returns_none(db):
    row = market_statistics.latest_context(
        db, deal_type="buy", category="apartment", locality="Nowhereville", layout="9+kk",
    )
    assert row is None
