"""
Lightweight read-only HTTP API for the byteval frontend.

Why this exists separately from app/api:
  The app/ FastAPI service (ORM models + ML predictor) targets a DIFFERENT
  schema generation than the live database. This module talks to the LIVE
  schema directly through src.db (the same connection the ingest pipeline
  uses), so it always matches whatever is actually in Postgres.

Run it:
    # locally (DB port 5432 is published by docker compose)
    uvicorn src.read_api:app --reload --port 8000

    # or inside the existing image, on the compose network
    docker compose run --rm --service-ports ml-api \
        uvicorn src.read_api:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /health
    GET  /listings       → canonical properties, shaped for the frontend
    GET  /raw-listings   → append-only verbatim scraper items
    POST /predict        → model valuation for ad-hoc property attributes
"""

import csv
import hmac
import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src import config
from src.db import get_cursor
from src.repositories import market_benchmarks, market_index, market_statistics, price_changes
from src.repositories import users as users_repo
from src.services import accounts, slovak_regions

logger = logging.getLogger(__name__)

app = FastAPI(
    title="estima-sk read API",
    description="Read-only access to the live Slovak real-estate database.",
    version="0.1.0",
)

# The frontend runs on localhost:3000 in dev. Open in dev; tighten for prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _deal_type_from_url(url: Optional[str]) -> Optional[str]:
    """Derive sale/rent from the listing URL slug (fallback when the stored
    deal_type is missing). CZ slugs: `prodej`=sale, `pronajem`=rent.
    SK (bazos) slugs: `predaj`=sale, `prenajom`=rent. Returns "sale"/"rent"/None.
    """
    if not url:
        return None
    u = url.lower()
    if "pronajem" in u or "pronájem" in u or "prenajom" in u or "prenájom" in u:
        return "rent"
    if "prodej" in u or "predaj" in u:
        return "sale"
    return None


def _deal_type(row: dict) -> Optional[str]:
    """Prefer the stored deal_type column (normalizer uses buy/rent), map to the
    frontend's sale/rent vocab, and fall back to the URL slug when it's null."""
    dt = (row.get("deal_type") or "").lower()
    if dt in ("buy", "sale"):
        return "sale"
    if dt == "rent":
        return "rent"
    return _deal_type_from_url(row.get("url"))


def _listing_from_row(row: dict) -> dict:
    """Map a live `properties` row to the JSON shape the frontend consumes."""
    price = row["current_price"]
    area = float(row["floor_area"]) if row["floor_area"] is not None else None
    pps = row["current_price_per_sqm"]
    # Prefer the street-level geocoded position over the town centroid.
    precise = row.get("geo_lat") is not None and row.get("geo_lon") is not None
    return {
        "id": str(row["id"]),
        "source": row["source"],
        "sourceListingId": row["source_listing_id"],
        "dealType": _deal_type(row),
        "category": row["category"],
        "name": row["name"],
        "locality": row["locality"],
        "district": row["district"],          # Slovak okres
        "region": slovak_regions.kraj_of_okres(row["district"]),   # kraj
        "layout": row["layout"],
        "floorArea": area,
        "landArea": float(row["land_area"]) if row["land_area"] is not None else None,
        "price": int(price) if price is not None else None,
        "pricePerSqm": float(pps) if pps is not None else None,
        "lat": row["geo_lat"] if precise else row["lat"],
        "lon": row["geo_lon"] if precise else row["lon"],
        "street": row.get("street"),
        "geoPrecision": "street" if precise else "town",
        "imageUrl": row["image_url"],
        "images": row.get("images") or [],
        "url": row["url"],
        "active": row["active"],
        "firstSeenAt": row["first_seen_at"].isoformat() if row["first_seen_at"] else None,
        "lastSeenAt": row["last_seen_at"].isoformat() if row["last_seen_at"] else None,
    }


@app.get("/health")
def health() -> dict:
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM properties")
        n = cur.fetchone()["n"]
    return {"status": "ok", "properties": n}


@app.get("/listings")
def listings(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: Optional[str] = None,
    category: Optional[str] = None,
    deal_type: Optional[str] = Query(None, pattern="^(sale|rent)$"),
    region: Optional[str] = Query(None, description="Slovak kraj, e.g. 'Košický'"),
    district: Optional[str] = Query(None, description="Slovak okres, e.g. 'Košice'"),
    active: Optional[bool] = None,
    min_price: Optional[int] = Query(None, ge=0),
    max_price: Optional[int] = Query(None, ge=0),
) -> dict:
    """Canonical, current-state listings from the `properties` table."""
    where = ["current_price IS NOT NULL"]
    params: list = []
    if source is not None:
        where.append("source = %s")
        params.append(source)
    if category is not None:
        where.append("category = %s")
        params.append(category)
    if district is not None:
        where.append("district = %s")
        params.append(district)
    if region is not None:
        # kraj → its okresy; an unknown kraj yields no rows rather than erroring.
        okresy = slovak_regions.okresy_of_kraj(region)
        where.append("district = ANY(%s)")
        params.append(okresy)
    if deal_type == "sale":
        # Stored deal_type uses buy/sale; fall back to the URL slug when null.
        where.append(
            "(deal_type IN ('buy', 'sale') OR "
            "(deal_type IS NULL AND (url ILIKE '%%prodej%%' OR url ILIKE '%%predaj%%')))"
        )
    elif deal_type == "rent":
        where.append(
            "(deal_type = 'rent' OR (deal_type IS NULL AND "
            "(url ILIKE '%%pronajem%%' OR url ILIKE '%%pronájem%%' OR url ILIKE '%%prenajom%%')))"
        )
    if active is not None:
        where.append("active = %s")
        params.append(active)
    if min_price is not None:
        where.append("current_price >= %s")
        params.append(min_price)
    if max_price is not None:
        where.append("current_price <= %s")
        params.append(max_price)

    where_sql = " AND ".join(where)

    with get_cursor(commit=False) as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM properties WHERE {where_sql}", params)
        total = cur.fetchone()["n"]
        cur.execute(
            f"""
            SELECT id, source, source_listing_id, url, deal_type, category, name, locality,
                   district, layout, floor_area, land_area, lat, lon,
                   street, geo_lat, geo_lon, geo_precision, image_url, images,
                   first_seen_at, last_seen_at, current_price,
                   current_price_per_sqm, active
            FROM properties
            WHERE {where_sql}
            ORDER BY last_seen_at DESC NULLS LAST, id DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_listing_from_row(r) for r in rows],
    }


def _benchmark_from_row(row: dict) -> dict:
    """Map a `market_benchmarks` row to the frontend JSON shape (camelCase)."""
    def num(v):
        return float(v) if v is not None else None
    return {
        "id": str(row["id"]),
        "source": row["source"],
        "sourceName": row["source_name"],
        "sourceUrl": row["source_url"],
        "period": row["period"],
        "year": row["year"],
        "quarter": row["quarter"],
        "country": row["country"],
        "city": row["city"],
        "district": row["district"],
        "locality": row["locality"],
        "propertyType": row["property_type"],
        "segment": row["segment"],
        "metric": row["metric"],
        "valueCzkPerSqm": num(row["value_czk_per_sqm"]),
        "changePercent": num(row["change_percent"]),
        "transactionCount": row["transaction_count"],
        "transactionVolumeCzk": num(row["transaction_volume_czk"]),
        "granularity": row["granularity"],
        "notes": row["notes"],
    }


@app.get("/benchmarks")
def benchmarks(
    period: Optional[str] = None,
    city: Optional[str] = None,
    granularity: Optional[str] = Query(None, pattern="^(city|district|locality|city_segment)$"),
    segment: Optional[str] = None,
    metric: str = "realized_price_per_sqm",
) -> dict:
    """External market benchmarks (realized prices) for a period (default latest)."""
    with get_cursor(commit=False) as cur:
        resolved = period or market_benchmarks.latest_period(cur, metric=metric)
        rows = market_benchmarks.list_benchmarks(
            cur, period=resolved, granularity=granularity, segment=segment, metric=metric, city=city,
        )
    return {
        "period": resolved,
        "metric": metric,
        "items": [_benchmark_from_row(r) for r in rows],
    }


@app.get("/benchmarks/summary")
def benchmarks_summary(
    period: Optional[str] = None,
    city: Optional[str] = None,
    metric: str = "realized_price_per_sqm",
) -> dict:
    """City total + per-district benchmarks for a period — for the dashboard/benchmarks page.

    `city` restricts both the headline and district rows to one city; omit it to
    fall back to whichever city sorts first for the period (legacy behavior).
    """
    with get_cursor(commit=False) as cur:
        resolved = period or market_benchmarks.latest_period(cur, metric=metric)
        if resolved is None:
            return {"period": None, "metric": metric, "city": None, "districts": []}
        city_rows = market_benchmarks.list_benchmarks(
            cur, period=resolved, granularity="city", segment="all", metric=metric, city=city,
        )
        district_rows = market_benchmarks.list_benchmarks(
            cur, period=resolved, granularity="district", segment="all", metric=metric, city=city,
        )
    return {
        "period": resolved,
        "metric": metric,
        "city": _benchmark_from_row(city_rows[0]) if city_rows else None,
        "districts": [_benchmark_from_row(r) for r in district_rows],
    }


@app.get("/benchmarks/district/{district}")
def benchmark_for_district(
    district: str,
    period: Optional[str] = None,
    metric: str = "realized_price_per_sqm",
) -> dict:
    """Best benchmark for one district (district match, else city fallback) — listing detail page."""
    with get_cursor(commit=False) as cur:
        row = market_benchmarks.for_district(cur, district=district, period=period, metric=metric)
    return {"district": district, "benchmark": _benchmark_from_row(row) if row else None}


def _index_point_from_row(row: dict) -> dict:
    """Map a market_index series row to the frontend JSON shape (camelCase)."""
    def num(v):
        return float(v) if v is not None else None
    return {
        "date": row["snapshot_date"].isoformat(),
        "medianPrice": num(row["median_price"]),
        "medianPricePerSqm": num(row["median_price_per_sqm"]),
        "propertyCount": row["property_count"],
    }


@app.get("/market-index")
def market_index_series(
    deal_type: str = Query("sale", pattern="^(sale|rent)$"),
    category: str = Query("apartment", pattern="^(apartment|house)$"),
    district: Optional[str] = None,
    format: str = Query("json", pattern="^(json|csv)$"),
):  # returns Response (csv) or dict (json) — no annotation, FastAPI can't model the union
    """Estima INDEX — daily median asking prices over time.

    Asking (offer) prices from snapshots, not realized prices — the
    /benchmarks endpoints carry the external realized references. `sale`
    maps to the pipeline's "buy" deal_type, same as /predict.
    `format=csv` returns the series as a downloadable CSV.
    """
    db_deal_type = "buy" if deal_type == "sale" else "rent"
    with get_cursor(commit=False) as cur:
        rows = market_index.series(
            cur, deal_type=db_deal_type, category=category, district=district,
        )
    points = [_index_point_from_row(r) for r in rows]

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["date", "median_price", "median_price_per_sqm", "property_count"])
        for p in points:
            writer.writerow(
                [p["date"], p["medianPrice"], p["medianPricePerSqm"], p["propertyCount"]]
            )
        # District names carry spaces/diacritics — slugify to a safe ASCII filename.
        slug_parts = ["estima-index", deal_type, category]
        if district:
            slug_parts.append(re.sub(r"[^A-Za-z0-9]+", "-", district).strip("-").lower() or "district")
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{"-".join(slug_parts)}.csv"'},
        )

    return {
        "dealType": deal_type,
        "category": category,
        "district": district,
        "series": points,
    }


@app.get("/market-index/districts")
def market_index_districts(
    deal_type: str = Query("sale", pattern="^(sale|rent)$"),
    category: str = Query("apartment", pattern="^(apartment|house)$"),
) -> dict:
    """Districts with snapshot coverage — options for the index district filter."""
    db_deal_type = "buy" if deal_type == "sale" else "rent"
    with get_cursor(commit=False) as cur:
        rows = market_index.districts(cur, deal_type=db_deal_type, category=category)
    return {
        "districts": [
            {"district": r["district"], "propertyCount": r["property_count"]} for r in rows
        ],
    }


def _price_drop_from_row(row: dict) -> dict:
    """Map a price_changes⨝properties row to the frontend JSON shape (camelCase)."""
    def num(v):
        return float(v) if v is not None else None
    return {
        "id": str(row["id"]),
        "propertyId": str(row["property_id"]),
        "changedAt": row["changed_at"].isoformat() if row["changed_at"] else None,
        "oldPrice": int(row["old_price"]),
        "newPrice": int(row["new_price"]),
        "absoluteChange": int(row["absolute_change"]),   # negative = reduction
        "percentChange": num(row["percent_change"]),
        "source": row["source"],
        "dealType": _deal_type(row),
        "category": row["category"],
        "name": row["name"],
        "locality": row["locality"],
        "district": row["district"],          # Slovak okres
        "region": slovak_regions.kraj_of_okres(row["district"]),   # kraj
        "layout": row["layout"],
        "floorArea": num(row["floor_area"]),
        "imageUrl": row["image_url"],
        "url": row["url"],
        "currentPrice": int(row["current_price"]) if row["current_price"] is not None else None,
        "pricePerSqm": num(row["current_price_per_sqm"]),
        "active": row["active"],
    }


@app.get("/price-drops")
def price_drops(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    category: Optional[str] = None,
    district: Optional[str] = None,
    deal_type: Optional[str] = Query(None, pattern="^(sale|rent)$"),
    since_days: Optional[int] = Query(None, ge=1, le=365),
    active: bool = True,
) -> dict:
    """Recent price reductions from the `price_changes` table, joined to their listing.

    Only reductions (the listing got cheaper); newest first. `deal_type` filters
    on the URL slug like /listings. `since_days` limits to changes in the last N
    days; `active=false` includes drops on listings that have since been delisted.
    """
    with get_cursor(commit=False) as cur:
        total, rows = price_changes.recent_drops(
            cur,
            deal_type=deal_type,
            category=category,
            district=district,
            since_days=since_days,
            active_only=active,
            limit=limit,
            offset=offset,
        )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_price_drop_from_row(r) for r in rows],
    }


@app.get(
    "/reports/properties/{property_id}/pdf",
    responses={200: {"content": {"application/pdf": {}}}},
)
def property_report_pdf(
    property_id: int,
    lang: str = Query("en", description="Report language: 'en', 'cs' or 'sk'"),
) -> Response:
    """Generate a client-ready valuation PDF for one property.

    Assembles the structured report (metadata, market analysis, comparables,
    vision, location, recommendation) from the live DB and renders it to PDF.
    With ``REPORT_SERVICE_URL`` set, rendering is delegated to the standalone
    estima-report-service (whose payload additionally carries the NBS
    market-statistics section); any failure there falls back to the internal
    pipeline, so the endpoint's contract is identical either way.
    Returns 404 if the property doesn't exist, 503 if the PDF engine (WeasyPrint
    and its native libs) isn't available in this environment.
    """
    # Imported lazily so the rest of the read API loads even where the PDF
    # engine's native dependencies (Pango/Cairo) aren't installed.
    from src.services.reports.builder import PropertyNotFound, build_report
    from src.services.reports.pdf import render_pdf

    filename = f"estima-report-{property_id}.pdf"

    if config.REPORT_SERVICE_URL:
        try:
            pdf_bytes = _render_via_report_service(property_id, lang)
        except PropertyNotFound:
            raise HTTPException(status_code=404, detail=f"Property {property_id} not found")
        if pdf_bytes is not None:
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{filename}"'},
            )
        logger.warning(
            "report service at %s failed for property %s; falling back to the internal renderer",
            config.REPORT_SERVICE_URL, property_id,
        )

    try:
        report = build_report(property_id, lang=lang)
    except PropertyNotFound:
        raise HTTPException(status_code=404, detail=f"Property {property_id} not found")

    try:
        pdf_bytes = render_pdf(report, lang=lang)
    except ImportError as exc:
        logger.exception("PDF engine unavailable")
        raise HTTPException(
            status_code=503,
            detail=f"PDF generation is unavailable in this environment: {exc}",
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _render_via_report_service(property_id: int, lang: str) -> bytes | None:
    """Render one property's PDF through estima-report-service.

    Returns the PDF bytes, or None on any service/transport failure so the
    caller can fall back to the internal pipeline. ``PropertyNotFound``
    propagates — a missing property is a 404 regardless of the render path.
    The download URL is built from our own config rather than the URLs in the
    generate response, which are minted for the service's public host and may
    not be reachable from this container.
    """
    import requests

    from src.services.reports.payload import build_payload

    payload = build_payload(property_id, lang=lang)
    base = config.REPORT_SERVICE_URL.rstrip("/")
    try:
        resp = requests.post(
            f"{base}/reports/generate",
            json=payload,
            timeout=config.REPORT_SERVICE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        report_id = resp.json()["report_id"]
        pdf = requests.get(
            f"{base}/reports/{report_id}/download",
            timeout=config.REPORT_SERVICE_TIMEOUT_SECONDS,
        )
        pdf.raise_for_status()
        return pdf.content
    except (requests.RequestException, KeyError, ValueError):
        logger.exception("estima-report-service render failed for property %s", property_id)
        return None


class PredictRequest(BaseModel):
    """Ad-hoc valuation request — the attributes a user can type into a form.

    Market context fields are optional; when all three are omitted they are
    filled from the latest `market_statistics` aggregate for the property's
    group, so address-level attributes alone are enough for an estimate.
    """

    target: str = Field(
        "sale_price",
        pattern="^(sale_price|rent_price|sale_price_per_sqm|rent_price_per_sqm)$",
    )
    source: Optional[str] = None
    category: Optional[str] = None
    locality: Optional[str] = None
    district: Optional[str] = None
    layout: Optional[str] = None
    floor_area: Optional[float] = Field(None, gt=0)
    land_area: Optional[float] = Field(None, ge=0)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    market_median_price: Optional[float] = None
    market_median_price_per_sqm: Optional[float] = None
    market_property_count: Optional[int] = None


@app.post("/predict")
def predict_valuation(body: PredictRequest) -> dict:
    """Value a property from its attributes using the active model for `target`.

    Returns the prediction plus the (possibly auto-filled) market context.
    503 if no model has been trained/activated for the requested target.
    """
    # Imported lazily so the read API loads even where the ML stack
    # (numpy/pandas/joblib) isn't installed.
    from src.services import prediction

    request = body.model_dump(exclude={"target"})
    # Same target→deal_type mapping as feature generation (sale_* trains on buy).
    request["deal_type"] = "buy" if body.target.startswith("sale") else "rent"

    market_filled = False
    if (
        body.market_median_price is None
        and body.market_median_price_per_sqm is None
        and body.market_property_count is None
    ):
        with get_cursor(commit=False) as cur:
            stats = market_statistics.latest_context(
                cur,
                deal_type=request["deal_type"],
                category=body.category,
                locality=body.locality,
                layout=body.layout,
            )
            if not stats and (body.district or body.locality):
                # Locality groups are street-level; district is what forms send.
                stats = market_statistics.district_context(
                    cur,
                    deal_type=request["deal_type"],
                    category=body.category,
                    district=body.district or body.locality,
                    layout=body.layout,
                )
        if stats:
            request["market_median_price"] = (
                float(stats["median_price"]) if stats["median_price"] is not None else None
            )
            request["market_median_price_per_sqm"] = (
                float(stats["median_price_per_sqm"])
                if stats["median_price_per_sqm"] is not None else None
            )
            request["market_property_count"] = stats["property_count"]
            market_filled = True

    try:
        result = prediction.predict(request, target=body.target)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except FileNotFoundError as exc:
        # Registry row exists but the artifact isn't on this host's ARTIFACTS_DIR.
        logger.exception("Active model artifact missing")
        raise HTTPException(
            status_code=503,
            detail=f"Active model artifact is missing in this environment: {exc}",
        )

    result["market_context"] = {
        "auto_filled": market_filled,
        "market_median_price": request.get("market_median_price"),
        "market_median_price_per_sqm": request.get("market_median_price_per_sqm"),
        "market_property_count": request.get("market_property_count"),
    }
    return result


@app.get("/raw-listings")
def raw_listings(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: Optional[str] = None,
) -> dict:
    """Append-only verbatim scraper items from the `raw_listings` table."""
    where = []
    params: list = []
    if source is not None:
        where.append("source = %s")
        params.append(source)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with get_cursor(commit=False) as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM raw_listings {where_sql}", params)
        total = cur.fetchone()["n"]
        cur.execute(
            f"""
            SELECT id, source, source_listing_id, url, scraped_at, raw_json
            FROM raw_listings
            {where_sql}
            ORDER BY scraped_at DESC NULLS LAST, id DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    items = [
        {
            "id": str(r["id"]),
            "source": r["source"],
            "sourceListingId": r["source_listing_id"],
            "url": r["url"],
            "scrapedAt": r["scraped_at"].isoformat() if r["scraped_at"] else None,
            "raw": r["raw_json"],
        }
        for r in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------------------
# Internal account & billing API (consumed by the estima-sk Next.js server).
#
# Guarded by the INTERNAL_API_KEY shared secret — these endpoints are never
# called from browsers, only server-to-server. With no key configured they
# return 503 (fail closed) so a misconfigured deploy can't expose accounts.
# ---------------------------------------------------------------------------


def _require_internal_key(x_internal_key: str = Header(default="")) -> None:
    if not config.INTERNAL_API_KEY:
        raise HTTPException(status_code=503, detail="internal_api_not_configured")
    if not hmac.compare_digest(x_internal_key, config.INTERNAL_API_KEY):
        raise HTTPException(status_code=401, detail="invalid_internal_key")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    name: Optional[str] = Field(default=None, max_length=200)


class VerifyRequest(BaseModel):
    email: str
    password: str


class GoogleSignInRequest(BaseModel):
    sub: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    name: Optional[str] = Field(default=None, max_length=200)
    picture: Optional[str] = Field(default=None, max_length=1000)


class SubscriptionUpdate(BaseModel):
    user_id: Optional[int] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    current_period_end: Optional[int] = None  # unix seconds, as Stripe sends it
    cancel_at_period_end: Optional[bool] = None


@app.post("/internal/auth/register", dependencies=[Depends(_require_internal_key)])
def internal_register(body: RegisterRequest) -> dict:
    with get_cursor() as cur:
        try:
            user = accounts.register(cur, body.email, body.password, body.name)
        except accounts.EmailTaken:
            raise HTTPException(status_code=409, detail="email_taken")
        return {"user": accounts.public_user(cur, user)}


@app.post("/internal/auth/verify", dependencies=[Depends(_require_internal_key)])
def internal_verify(body: VerifyRequest) -> dict:
    with get_cursor(commit=False) as cur:
        user = accounts.verify_login(cur, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    with get_cursor(commit=False) as cur:
        return {"user": accounts.public_user(cur, user)}


@app.post("/internal/auth/google", dependencies=[Depends(_require_internal_key)])
def internal_google_sign_in(body: GoogleSignInRequest) -> dict:
    with get_cursor() as cur:
        user = accounts.google_sign_in(cur, body.sub, body.email, body.name, body.picture)
        return {"user": accounts.public_user(cur, user)}


@app.get("/internal/auth/users/{user_id}", dependencies=[Depends(_require_internal_key)])
def internal_get_user(user_id: int) -> dict:
    with get_cursor(commit=False) as cur:
        user = users_repo.get_by_id(cur, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        return {"user": accounts.public_user(cur, user)}


@app.post("/internal/billing/subscription", dependencies=[Depends(_require_internal_key)])
def internal_update_subscription(body: SubscriptionUpdate) -> dict:
    """
    Upsert subscription state from Stripe webhook/checkout data. Identifies the
    user by user_id when known (checkout) or by stripe_customer_id (webhooks).
    """
    period_end = (
        datetime.fromtimestamp(body.current_period_end, tz=timezone.utc)
        if body.current_period_end
        else None
    )
    with get_cursor() as cur:
        user_id = body.user_id
        if user_id is None:
            if not body.stripe_customer_id:
                raise HTTPException(status_code=422, detail="user_id_or_customer_required")
            sub = users_repo.get_subscription_by_customer(cur, body.stripe_customer_id)
            if not sub:
                raise HTTPException(status_code=404, detail="customer_not_found")
            user_id = sub["user_id"]
        elif not users_repo.get_by_id(cur, user_id):
            raise HTTPException(status_code=404, detail="user_not_found")

        updated = users_repo.upsert_subscription(
            cur,
            user_id,
            stripe_customer_id=body.stripe_customer_id,
            stripe_subscription_id=body.stripe_subscription_id,
            plan=body.plan,
            status=body.status,
            current_period_end=period_end,
            cancel_at_period_end=body.cancel_at_period_end,
        )
        return {
            "user_id": user_id,
            "plan": accounts.effective_plan(updated),
            "subscription": updated and {
                "status": updated["status"],
                "plan": updated["plan"],
                "stripe_customer_id": updated["stripe_customer_id"],
                "cancel_at_period_end": updated["cancel_at_period_end"],
            },
        }
