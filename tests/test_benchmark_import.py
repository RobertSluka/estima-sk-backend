"""Market-benchmark import tests.

Pure type coercion is tested without a database. The repository upsert (and its
district→city fallback) runs against Postgres inside the rolled-back `db` fixture
(skipped if Postgres is unavailable).
"""

from src.repositories import market_benchmarks
from src.services import benchmark_import as bi


# ── _coerce (pure) ────────────────────────────────────────────────────────────


def test_coerce_blank_becomes_none():
    assert bi._coerce("", str) is None
    assert bi._coerce("   ", float) is None
    assert bi._coerce(None, int) is None


def test_coerce_numeric_types():
    assert bi._coerce("137900", float) == 137900.0
    assert bi._coerce("2024", int) == 2024
    assert bi._coerce("12.0", int) == 12          # int via float tolerates "12.0"
    assert bi._coerce("Praha 1", str) == "Praha 1"


# ── repository upsert (DB) ────────────────────────────────────────────────────


def _row(**overrides) -> dict:
    base = {
        "source": "deloitte_real_index", "source_name": "Deloitte Real Index",
        "source_url": "https://example.com", "period": "2024_Q3", "year": 2024,
        "quarter": 3, "country": "CZ", "city": "Praha", "district": None,
        "locality": None, "property_type": "apartment", "segment": "all",
        "metric": "realized_price_per_sqm", "value_czk_per_sqm": 137900.0,
        "change_percent": 4.5, "transaction_count": None,
        "transaction_volume_czk": None, "granularity": "city", "notes": None,
    }
    base.update(overrides)
    return base


def test_upsert_is_idempotent_including_null_district(db):
    # City-level row has NULL district; the COALESCE unique index must still treat
    # a re-insert as the same key (no duplicate).
    first = market_benchmarks.upsert(db, _row())
    second = market_benchmarks.upsert(db, _row(value_czk_per_sqm=140000.0, change_percent=5.0))
    assert first == second

    db.execute(
        "SELECT COUNT(*) AS n, MAX(value_czk_per_sqm) AS v FROM market_benchmarks "
        "WHERE source = 'deloitte_real_index' AND period = '2024_Q3' AND granularity = 'city'"
    )
    row = db.fetchone()
    assert row["n"] == 1
    assert float(row["v"]) == 140000.0          # updated in place


def test_for_district_prefers_district_over_city(db):
    market_benchmarks.upsert(db, _row(granularity="city", value_czk_per_sqm=137900.0))
    market_benchmarks.upsert(
        db, _row(granularity="district", district="Praha 5", value_czk_per_sqm=140700.0),
    )
    hit = market_benchmarks.for_district(db, district="Praha 5", period="2024_Q3")
    assert hit["granularity"] == "district"
    assert float(hit["value_czk_per_sqm"]) == 140700.0


def test_for_district_falls_back_to_city(db):
    market_benchmarks.upsert(db, _row(granularity="city", value_czk_per_sqm=137900.0))
    hit = market_benchmarks.for_district(db, district="Praha - Karlín", period="2024_Q3")
    assert hit["granularity"] == "city"          # no district row → city fallback
