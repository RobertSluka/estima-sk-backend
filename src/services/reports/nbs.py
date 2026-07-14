"""NBS residential property price statistics — static regional €/m² series.

Source: National Bank of Slovakia, "Development of residential property prices
in Slovakia" quarterly exports (the same dataset the estima-sk frontend embeds
in ``lib/nbs.ts``). Average transaction prices in EUR per m², all residential.
Do not hand-edit the numbers; extend by appending new quarters from the NBS
export when a new period is published.

Used by ``payload.py`` to fill the ``market_statistics`` block of an
estima-report-service payload: the property's okres resolves to a kraj via
``slovak_regions``, which selects the matching NBS regional series; unknown
geography falls back to the national (SR) series.
"""

from __future__ import annotations

from src.services import slovak_regions

SOURCE = "National Bank of Slovakia (NBS), residential property price statistics"

# Kraj (as named in slovak_regions.OKRES_TO_KRAJ) → NBS region column key.
_KRAJ_TO_KEY: dict[str, str] = {
    "Bratislavský": "BA",
    "Trnavský": "TT",
    "Trenčiansky": "TN",
    "Nitriansky": "NR",
    "Žilinský": "ZA",
    "Banskobystrický": "BB",
    "Prešovský": "PO",
    "Košický": "KE",
}

# English display labels for the report (report-service templates are English).
REGION_LABELS: dict[str, str] = {
    "SR": "Slovakia",
    "BA": "Bratislava Region",
    "TT": "Trnava Region",
    "TN": "Trenčín Region",
    "NR": "Nitra Region",
    "ZA": "Žilina Region",
    "BB": "Banská Bystrica Region",
    "PO": "Prešov Region",
    "KE": "Košice Region",
}

# Quarterly average price, EUR/m², oldest first. Columns: period, SR, BA, TT,
# TN, NR, ZA, BB, PO, KE — matching _SERIES_KEYS below.
_SERIES_KEYS = ("SR", "BA", "TT", "TN", "NR", "ZA", "BB", "PO", "KE")
_QUARTERS: tuple[tuple, ...] = (
    ("1Q 2023", 2556.1, 3202.8, 1868.8, 1654.4, 1435.3, 2034.6, 1760.0, 2015.9, 2219.6),
    ("2Q 2023", 2493.8, 3146.3, 1852.6, 1569.8, 1431.9, 1934.6, 1686.9, 1886.9, 2096.0),
    ("3Q 2023", 2438.0, 3096.1, 1799.3, 1540.9, 1375.4, 1891.2, 1598.7, 1794.7, 2016.1),
    ("4Q 2023", 2433.0, 3077.1, 1807.8, 1564.5, 1358.1, 1874.0, 1589.4, 1785.8, 2076.3),
    ("1Q 2024", 2423.0, 3087.3, 1795.2, 1549.4, 1404.5, 1826.9, 1474.8, 1767.1, 2011.4),
    ("2Q 2024", 2461.6, 3127.0, 1836.8, 1569.1, 1392.8, 1819.2, 1562.4, 1817.9, 2087.0),
    ("3Q 2024", 2520.3, 3228.7, 1859.4, 1579.5, 1354.2, 1891.2, 1511.4, 1898.8, 2087.1),
    ("4Q 2024", 2596.1, 3316.4, 1879.3, 1626.3, 1403.5, 1948.8, 1604.3, 1955.6, 2222.1),
    ("1Q 2025", 2700.0, 3486.1, 1920.1, 1658.8, 1389.3, 1929.9, 1604.7, 1985.4, 2348.9),
    ("2Q 2025", 2777.3, 3548.7, 1935.3, 1690.1, 1502.8, 2038.2, 1714.3, 2177.5, 2508.5),
    ("3Q 2025", 2814.1, 3627.7, 1943.6, 1743.4, 1521.9, 2046.5, 1708.1, 2179.4, 2410.6),
    ("4Q 2025", 2906.4, 3730.7, 1981.6, 1787.3, 1589.0, 2180.3, 1744.2, 2171.9, 2607.8),
    ("1Q 2026", 3005.2, 3845.0, 2014.5, 1878.2, 1627.2, 2282.5, 1864.7, 2411.8, 2682.3),
)

LATEST_PERIOD = _QUARTERS[-1][0]


def region_key(district: str | None, city: str | None = None) -> str:
    """NBS region key for a property's okres (trying ``city`` as a fallback).

    Unknown or missing geography degrades to "SR" (national series) rather
    than failing — every property gets *some* market context.
    """
    for name in (district, city):
        kraj = slovak_regions.kraj_of_okres(name) if name else None
        if kraj is None and name:
            # Not an okres name — maybe a town resolvable to one.
            okres = slovak_regions.resolve_okres(name)
            kraj = slovak_regions.kraj_of_okres(okres) if okres else None
        if kraj and kraj in _KRAJ_TO_KEY:
            return _KRAJ_TO_KEY[kraj]
    return "SR"


def series(key: str, quarters: int = 9) -> list[dict]:
    """Last ``quarters`` NBS points for one region, oldest first,
    as ``{"period", "value"}`` dicts (the report-service series shape)."""
    idx = _SERIES_KEYS.index(key)
    rows = _QUARTERS[-quarters:]
    return [{"period": r[0], "value": r[1 + idx]} for r in rows]


def block(district: str | None, city: str | None = None) -> dict:
    """The ``market_statistics`` payload block (without subject/distribution,
    which the caller adds from the property row and the live DB)."""
    key = region_key(district, city)
    pts = series(key)
    latest = pts[-1]["value"]

    # Year-on-year: latest quarter vs. the same quarter one year earlier.
    yoy = None
    full = series(key, quarters=len(_QUARTERS))
    if len(full) >= 5:
        prev = full[-5]["value"]
        if prev:
            yoy = round((latest - prev) / prev * 100, 1)

    return {
        "region": REGION_LABELS[key],
        "country": "Slovakia",
        "scope_note": "All residential, average transaction prices",
        "source": f"{SOURCE}, {LATEST_PERIOD}",
        "period": LATEST_PERIOD,
        "average_price_per_sqm": latest,
        "yoy_change": yoy,
        "series": pts,
    }
