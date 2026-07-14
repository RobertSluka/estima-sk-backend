"""
Rendering: ReportData -> HTML -> PDF bytes.

No database or ML imports here — this module only depends on the schema, the
Jinja template and WeasyPrint. That keeps it runnable in any environment (the
local test script renders `mock.sample_report()` through here).

Two entry points:
    render_html(report) -> str        # the HTML, useful for previewing/debugging
    render_pdf(report)  -> bytes      # the finished A4 PDF

Robustness notes:
  * Every remote image is fetched once, size-checked and embedded as a base64
    data URI. A failed/oversized/missing image silently falls back to a neutral
    inline SVG placeholder, so a broken URL never breaks the PDF or leaks a
    network dependency into rendering.
  * All the numeric/date formatting lives in Jinja filters (`czk`, `num`,
    `pct`, …) so the template stays free of Python logic and every `None`
    renders as an em-dash rather than the word "None".
"""

from __future__ import annotations

import base64
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.services.reports import i18n
from src.services.reports.schema import ReportData

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "report.html"

# Cap on remotely-fetched images so a rogue URL can't bloat the PDF or hang it.
_IMAGE_TIMEOUT_SECONDS = 6
_IMAGE_MAX_BYTES = 6 * 1024 * 1024

# Neutral 4:3 placeholder used whenever an image can't be embedded.
_PLACEHOLDER_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='300'>"
    "<rect width='100%' height='100%' fill='#eef1f5'/>"
    "<text x='50%' y='50%' fill='#9aa5b1' font-family='sans-serif' "
    "font-size='18' text-anchor='middle' dominant-baseline='middle'>"
    "Image unavailable</text></svg>"
)
PLACEHOLDER_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(
    _PLACEHOLDER_SVG.encode("utf-8")
).decode("ascii")


# --------------------------------------------------------------------------- #
# Image embedding                                                               #
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=256)
def embed_image(url: Optional[str]) -> str:
    """Return a data URI for `url`, or the placeholder if it can't be embedded.

    Accepts http(s) URLs and existing data: URIs (returned unchanged). Never
    raises — any failure returns the placeholder.
    """
    if not url:
        return PLACEHOLDER_DATA_URI
    if url.startswith("data:"):
        return url
    if not url.startswith(("http://", "https://")):
        return PLACEHOLDER_DATA_URI

    try:
        import requests  # imported lazily so the template path has no hard dep

        resp = requests.get(url, timeout=_IMAGE_TIMEOUT_SECONDS, stream=True)
        resp.raise_for_status()
        content = resp.content
        if not content or len(content) > _IMAGE_MAX_BYTES:
            logger.warning("Skipping image (empty or too large): %s", url)
            return PLACEHOLDER_DATA_URI
        mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        b64 = base64.b64encode(content).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as exc:  # network error, DNS, timeout, bad payload …
        logger.warning("Could not embed image %s: %s", url, exc)
        return PLACEHOLDER_DATA_URI


# --------------------------------------------------------------------------- #
# Jinja filters                                                                 #
# --------------------------------------------------------------------------- #

_DASH = "—"


def _fmt_money(value, currency: str = "CZK") -> str:
    if value is None:
        return _DASH
    try:
        n = round(float(value))
    except (TypeError, ValueError):
        return _DASH
    grouped = f"{n:,}".replace(",", " ")  # narrow no-break space thousands
    return f"{grouped} {currency}"


def _fmt_num(value, decimals: int = 0, suffix: str = "") -> str:
    if value is None:
        return _DASH
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _DASH
    grouped = f"{f:,.{decimals}f}".replace(",", " ")
    return f"{grouped}{suffix}"


def _fmt_pct(value, decimals: int = 1, signed: bool = False) -> str:
    if value is None:
        return _DASH
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _DASH
    sign = "+" if (signed and f > 0) else ""
    return f"{sign}{f:.{decimals}f} %"


def _fmt_signed_money(value, currency: str = "CZK") -> str:
    if value is None:
        return _DASH
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _DASH
    sign = "+" if f > 0 else ("-" if f < 0 else "")
    return f"{sign}{_fmt_money(abs(f), currency)}"


def _fmt_date(value, lang: str = "en") -> str:
    """Localized `D Mon YYYY` (Czech month abbreviations when lang == 'cs')."""
    if value is None:
        return _DASH
    try:
        return f"{value.day} {i18n.month_abbr(lang, value.month)} {value.year}"
    except AttributeError:
        return str(value)


def _fmt_default(value, fallback: str = _DASH) -> str:
    """None/empty -> fallback; enums -> their value."""
    if value is None or value == "":
        return fallback
    enum_val = getattr(value, "value", None)
    return str(enum_val if enum_val is not None else value)


def _fmt_cond_chip(value, lang: str = "en") -> Optional[str]:
    return i18n.condition_chip(lang, value)


def _fmt_distance(value) -> str:
    """Metres -> `230 m` / `1.2 km`."""
    if value is None:
        return _DASH
    try:
        m = int(value)
    except (TypeError, ValueError):
        return _DASH
    return f"{m} m" if m < 1000 else f"{m / 1000:.1f} km"


def _walk_minutes(value) -> int:
    """Metres -> whole walking minutes (~4.8 km/h), never below 1."""
    try:
        return max(1, round(int(value) / 80))
    except (TypeError, ValueError):
        return 1


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["czk"] = _fmt_money
    env.filters["money"] = _fmt_money
    env.filters["signed_money"] = _fmt_signed_money
    env.filters["num"] = _fmt_num
    env.filters["pct"] = _fmt_pct
    env.filters["date"] = _fmt_date
    env.filters["dash"] = _fmt_default
    env.filters["cond_chip"] = _fmt_cond_chip
    env.filters["embed_image"] = embed_image
    env.filters["dist"] = _fmt_distance
    env.filters["walk_min"] = _walk_minutes
    return env


# --------------------------------------------------------------------------- #
# Public API                                                                    #
# --------------------------------------------------------------------------- #

def render_html(report: ReportData, lang: str = "en") -> str:
    """Render the report to a standalone HTML string (images embedded).

    `lang` selects the report language ("en" or "cs"); anything else falls back
    to English. Note this only localizes the static chrome + date formatting —
    the generated prose (explanations, recommendation) is produced in the chosen
    language by the builder, so pass the same `lang` there.
    """
    lang = i18n.normalize_lang(lang)
    template = _env().get_template(TEMPLATE_NAME)
    return template.render(r=report, T=i18n.strings(lang), lang=lang)


def render_pdf(report: ReportData, lang: str = "en") -> bytes:
    """Render the report to PDF bytes via WeasyPrint.

    WeasyPrint is imported lazily so importing this module (e.g. to call
    `render_html`) does not require the native Pango/Cairo stack.
    """
    from weasyprint import HTML  # lazy: needs system libs (pango/cairo)

    html = render_html(report, lang=lang)
    # base_url lets any relative asset references resolve against the template dir.
    return HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
