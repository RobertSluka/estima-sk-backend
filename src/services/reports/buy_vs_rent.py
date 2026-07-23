"""Buy-vs-rent wealth projection for the report's market section.

Mirror of the estima-sk frontend simulation (``lib/buyVsRent.ts``, occupier
framing) so the Analyses preview and the PDF tell the same story: both sides
spend the same total each month — the buyer pays the mortgage, the renter pays
rent and invests the down payment plus the monthly difference at a fixed
return. Buyer wealth = property value − remaining loan + invested surplus;
renter wealth = invested portfolio. Rent grows with inflation; the property
appreciates at the NBS long-run regional rate.

Only deterministic arithmetic on numbers already in the payload path lives
here — no new data sources, no valuation logic. The rent estimate comes from
the district's active rent-listing median (€/m²/month × floor area); when that
segment is empty the whole block is omitted and the template skips the
section.
"""

from __future__ import annotations

from src.services.reports import nbs

HORIZON_YEARS = 30

# Fixed, disclosed assumptions (kept identical to the frontend calculator's
# defaults so preview and PDF agree).
MORTGAGE_RATE_PCT = 4.0
LTV_PCT = 80.0
TERM_YEARS = 30
INFLATION_PCT = 2.5
INVESTMENT_RETURN_PCT = 5.0

# Long-run average annual property price growth by NBS region key, computed
# from the NBS regional €/m² series: 2002 annual value → 4Q 2025 (~23.5
# years). Same figures as estima-sk ``lib/buyVsRent.ts`` REGION_GROWTH. The
# window includes the 2005–2008 convergence boom, so these are optimistic
# long-run rates; the report labels the source and period.
GROWTH_PERIOD = "2002–2025"
REGION_GROWTH_PCT: dict[str, float] = {
    "SR": 7.0,
    "BA": 6.9,
    "TT": 7.4,
    "TN": 6.0,
    "NR": 6.5,
    "ZA": 7.4,
    "BB": 7.0,
    "KE": 7.6,
    "PO": 8.0,
}


def simulate(
    property_price: float, monthly_rent: float, property_growth_pct: float
) -> dict:
    """Monthly-step occupier simulation over the fixed 30-year horizon.

    Returns yearly wealth points for both sides plus the derived summary
    numbers. Pure function of its inputs and the module assumptions.
    """
    price = max(0.0, property_price)
    loan = price * LTV_PCT / 100.0
    down_payment = price - loan
    term_months = TERM_YEARS * 12
    monthly_rate = MORTGAGE_RATE_PCT / 100.0 / 12.0
    monthly_payment = (
        loan / term_months
        if monthly_rate == 0
        else (loan * monthly_rate) / (1 - (1 + monthly_rate) ** -term_months)
    )
    monthly_inflation = (1 + INFLATION_PCT / 100.0) ** (1 / 12)
    monthly_appreciation = (1 + property_growth_pct / 100.0) ** (1 / 12)
    monthly_return = (1 + INVESTMENT_RETURN_PCT / 100.0) ** (1 / 12)

    balance = loan
    rent = max(0.0, monthly_rent)
    value = price
    renter_portfolio = down_payment
    buyer_portfolio = 0.0
    breakeven_year: int | None = None
    points = [{"year": 0, "buyer": round(value - balance), "renter": round(renter_portfolio)}]

    for month in range(1, HORIZON_YEARS * 12 + 1):
        renter_portfolio *= monthly_return
        buyer_portfolio *= monthly_return
        buyer_cost = monthly_payment if month <= term_months else 0.0
        diff = buyer_cost - rent
        if diff > 0:
            renter_portfolio += diff
        else:
            buyer_portfolio -= diff
        if month <= term_months:
            balance = max(0.0, balance * (1 + monthly_rate) - monthly_payment)
        value *= monthly_appreciation
        rent *= monthly_inflation

        if month % 12 == 0:
            year = month // 12
            buyer = round(value - balance + buyer_portfolio)
            renter = round(renter_portfolio)
            points.append({"year": year, "buyer": buyer, "renter": renter})
            if breakeven_year is None and buyer >= renter:
                breakeven_year = year

    return {
        "down_payment": round(down_payment),
        "monthly_payment": round(monthly_payment),
        "series": points,
        "buyer_final": points[-1]["buyer"],
        "renter_final": points[-1]["renter"],
        "breakeven_year": breakeven_year,
    }


def block(
    *,
    property_price: float | None,
    floor_area: float | None,
    district: str | None,
    city: str | None,
    rent_distribution: dict | None,
) -> dict | None:
    """The payload's ``buy_vs_rent`` block, or None when it can't be built
    honestly (no price, no floor area, or no rent listings to estimate from).
    Callers gate on deal type — this projection only makes sense for sales.
    """
    if not property_price or not floor_area:
        return None
    rent_median = (rent_distribution or {}).get("median")
    if not rent_median:
        return None

    monthly_rent = round(float(rent_median) * float(floor_area))
    if monthly_rent <= 0:
        return None

    region = nbs.region_key(district, city)
    growth_pct = REGION_GROWTH_PCT[region]
    result = simulate(float(property_price), float(monthly_rent), growth_pct)

    return {
        "horizon_years": HORIZON_YEARS,
        "assumptions": {
            "property_price": float(property_price),
            "monthly_rent": float(monthly_rent),
            "rent_source": f"Active rent-listing median, {district or 'local market'}",
            "mortgage_rate_pct": MORTGAGE_RATE_PCT,
            "ltv_pct": LTV_PCT,
            "term_years": TERM_YEARS,
            "inflation_pct": INFLATION_PCT,
            "investment_return_pct": INVESTMENT_RETURN_PCT,
            "property_growth_pct": growth_pct,
            "growth_source": (
                f"NBS regional price series, {nbs.REGION_LABELS[region]}, "
                f"{GROWTH_PERIOD} average"
            ),
        },
        **result,
    }
