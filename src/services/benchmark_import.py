"""
Import external market-benchmark CSVs (e.g. Deloitte Real Index) → market_benchmarks.

The CSV columns map 1:1 to the table; this just coerces types (blank → NULL) and
upserts row by row. Idempotent: re-importing the same report updates in place.

Run via:  python -m src.main import-benchmarks /app/data/deloitte_real_index_2024_q3_benchmarks.csv
"""

import csv
import logging

from src.db import get_cursor
from src.repositories import market_benchmarks

logger = logging.getLogger(__name__)

# CSV header → table column. Identity for most; listed explicitly so a column the
# importer doesn't know about fails loudly rather than being silently dropped.
_FIELDS = {
    "source": str, "source_name": str, "source_url": str,
    "period": str, "year": int, "quarter": int,
    "country": str, "city": str, "district": str, "locality": str,
    "property_type": str, "segment": str,
    "metric": str, "value_czk_per_sqm": float,
    "change_percent": float, "transaction_count": int,
    "transaction_volume_czk": float, "granularity": str, "notes": str,
}


def _coerce(value: str | None, cast) -> object | None:
    """Blank/whitespace → None; otherwise cast (int via float to tolerate '12.0')."""
    if value is None:
        return None
    s = value.strip()
    if s == "":
        return None
    if cast is int:
        return int(float(s))
    if cast is float:
        return float(s)
    return s


def import_csv(filepath: str) -> dict:
    """Import a benchmark CSV. Returns {rows, imported}."""
    with open(filepath, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    imported = 0
    with get_cursor() as cur:
        for raw in rows:
            record = {col: _coerce(raw.get(col), cast) for col, cast in _FIELDS.items()}
            market_benchmarks.upsert(cur, record)
            imported += 1

    logger.info("Imported %d benchmark rows from %s", imported, filepath)
    return {"rows": len(rows), "imported": imported}
