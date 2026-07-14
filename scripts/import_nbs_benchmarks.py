"""
Import the embedded NBS regional price series → market_benchmarks.

The report's "external market index" section (and /benchmarks*) reads from
market_benchmarks; for Slovakia the reference source is the NBS residential
price index already embedded in src/services/reports/nbs.py (kraj-level
average transaction prices, EUR/m²). This script materializes that series:

  - one 'district'-granularity row per kraj per quarter, keyed
    "<Kraj> kraj" (matches builder._fetch_benchmark's okres→kraj lookup)
  - one 'city'-granularity SR national row per quarter (the fallback for
    properties whose okres can't be resolved)

Values land in value_czk_per_sqm — the column name is legacy from the CZ
schema; for this database the unit is EUR/m² (see i18n benchmark units).
Idempotent: re-running updates in place. Run after extending nbs.py each
quarter:

    docker compose run --rm ml-api python -m scripts.import_nbs_benchmarks
"""

from __future__ import annotations

import logging
import re

from src.db import get_cursor
from src.repositories import market_benchmarks
from src.services import slovak_regions
from src.services.reports import nbs

logger = logging.getLogger(__name__)

SOURCE = "nbs"
SOURCE_NAME = "NBS – ceny rezidenčných nehnuteľností"
SOURCE_URL = "https://nbs.sk/statisticke-udaje/vybrane-makroekonomicke-ukazovatele/ceny-nehnutelnosti-na-byvanie/"

# NBS series key → kraj adjective (inverse of nbs._KRAJ_TO_KEY, national aside).
_KEY_TO_KRAJ: dict[str, str] = {
    "BA": "Bratislavský", "TT": "Trnavský", "TN": "Trenčiansky",
    "NR": "Nitriansky", "ZA": "Žilinský", "BB": "Banskobystrický",
    "PO": "Prešovský", "KE": "Košický",
}


def _canonical_period(nbs_period: str) -> tuple[str, int, int]:
    """'1Q 2026' → ('2026_Q1', 2026, 1) — the CZ-style canonical period key."""
    m = re.match(r"^(\d)Q (\d{4})$", nbs_period)
    if not m:
        raise ValueError(f"Unexpected NBS period: {nbs_period!r}")
    quarter, year = int(m.group(1)), int(m.group(2))
    return f"{year}_Q{quarter}", year, quarter


def run() -> int:
    kraje = set(slovak_regions.KRAJE)
    count = 0
    with get_cursor() as cur:
        for key, kraj in _KEY_TO_KRAJ.items():
            assert kraj in kraje, f"unknown kraj {kraj!r}"
            for point in nbs.series(key, quarters=10_000):
                period, year, quarter = _canonical_period(point["period"])
                market_benchmarks.upsert(cur, {
                    "source": SOURCE,
                    "source_name": SOURCE_NAME,
                    "source_url": SOURCE_URL,
                    "period": period,
                    "year": year,
                    "quarter": quarter,
                    "country": "SK",
                    "city": None,
                    "district": f"{kraj} kraj",
                    "locality": None,
                    "property_type": "all",
                    "segment": "all",
                    "metric": "realized_price_per_sqm",
                    "value_czk_per_sqm": point["value"],  # EUR/m² (legacy column name)
                    "change_percent": None,
                    "transaction_count": None,
                    "transaction_volume_czk": None,
                    "granularity": "district",
                    "notes": "NBS kraj-level average transaction price, EUR/m²",
                })
                count += 1
        # SR national rows — the 'city' fallback for unresolved districts.
        for point in nbs.series("SR", quarters=10_000):
            period, year, quarter = _canonical_period(point["period"])
            market_benchmarks.upsert(cur, {
                "source": SOURCE,
                "source_name": SOURCE_NAME,
                "source_url": SOURCE_URL,
                "period": period,
                "year": year,
                "quarter": quarter,
                "country": "SK",
                "city": "Slovensko",
                "district": None,
                "locality": None,
                "property_type": "all",
                "segment": "all",
                "metric": "realized_price_per_sqm",
                "value_czk_per_sqm": point["value"],  # EUR/m²
                "change_percent": None,
                "transaction_count": None,
                "transaction_volume_czk": None,
                "granularity": "city",
                "notes": "NBS national average transaction price, EUR/m²",
            })
            count += 1
    logger.info("Imported/updated %d NBS benchmark rows", count)
    print(f"Imported/updated {count} NBS benchmark rows")
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
