"""
Report localization — English (en) and Czech (cs).

Two kinds of strings live here:
  * `LABELS`  — static template chrome (section titles, field labels, table
    headers, fallback sentences). The template reads these as `T.<key>`.
  * `PROSE`   — format strings the builder fills with numbers to produce the
    generated market/vision/recommendation copy.

Everything is keyed by a two-letter language code; `strings(lang)` and
`prose(lang)` fall back to English for any unknown code. The template and the
builder both go through here, so a report is fully single-language.
"""

from __future__ import annotations

DEFAULT_LANG = "en"
SUPPORTED = ("en", "cs")


def normalize_lang(lang: str | None) -> str:
    """Map anything user-supplied to a supported code (en/cs), default en."""
    if not lang:
        return DEFAULT_LANG
    code = lang.strip().lower()[:2]
    if code in ("cs", "cz", "sk"):   # Czech UI (and Slovak) → Czech report
        return "cs"
    return "en"


# --------------------------------------------------------------------------- #
# Localized month abbreviations for the date filter.                            #
# --------------------------------------------------------------------------- #

_MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "cs": ["led", "úno", "bře", "dub", "kvě", "čvn",
           "čvc", "srp", "zář", "říj", "lis", "pro"],
}


def month_abbr(lang: str, month_1_to_12: int) -> str:
    table = _MONTHS.get(lang, _MONTHS["en"])
    return table[max(1, min(12, month_1_to_12)) - 1]


# --------------------------------------------------------------------------- #
# Static template chrome                                                        #
# --------------------------------------------------------------------------- #

LABELS = {
    "en": {
        # brand / cover
        "tagline": "Real Estate Intelligence",
        "report_title": "Property Valuation Report",
        "ref": "Ref",
        "fb_untitled": "Untitled property",
        "fb_no_locality": "Locality not specified",
        "assessment": "Assessment",
        "undervalued": "Undervalued",
        "fairly_priced": "Fairly priced",
        "overpriced": "Overpriced",
        "not_assessed": "Not assessed",
        "est_market_value": "Estimated market value",
        "vs_asking": "Vs. asking price",
        "asking_price": "Asking price",
        "source": "Source",
        # deal types
        "sale": "Sale",
        "rent": "Rent",
        # section titles
        "sec_details": "Property Details",
        "sec_market": "Market Analysis",
        "sec_vision": "Listing Photo Quality",
        "sec_location": "Location & Nearby Facilities",
        "sec_recommendation": "Final Recommendation",
        # metadata labels
        "m_address": "Address / Locality",
        "m_type": "Property type",
        "m_deal": "Deal type",
        "m_layout": "Layout",
        "m_floor_area": "Floor area",
        "m_land_area": "Land area",
        "m_floor": "Floor",
        "m_asking": "Asking price",
        "m_psqm": "Price per m²",
        "m_source": "Source",
        "m_first_seen": "First seen",
        "m_last_seen": "Last seen",
        "m_days": "Days on market",
        "m_reference": "Reference",
        "listing_link": "Listing link",
        # market
        "est_fair_value": "Estimated fair value",
        "range": "Range",
        "local_median": "Local median price",
        "median_psqm": "Median /m²",
        "asking_vs_est": "Asking vs. estimate",
        "benchmark_title": "External market index",
        "benchmark_note": (
            "Macro benchmark aggregated across the wider market — a realized-price "
            "reference, not a comparable listing for this specific property."
        ),
        "benchmark_unit_sale": "EUR/m²",
        "benchmark_unit_rent": "EUR/m²/month",
        "comparables": "Comparable listings",
        "th_property": "Property",
        "th_locality": "Locality",
        "th_layout": "Layout",
        "th_area": "Area",
        "th_price": "Price",
        "th_psqm": "Price/m²",
        "th_delta": "Δ vs subject",
        "th_similarity": "Similarity",
        "comp_footnote": (
            "Δ vs subject: a negative value means the comparable is cheaper than "
            "the subject property. Similarity blends layout, floor area and "
            "price-per-m² proximity."
        ),
        "fb_no_comparables": (
            "No sufficiently similar listings were found for this locality and "
            "layout. The estimate relies on market medians and property metadata."
        ),
        # vision (photo quality only — never property condition)
        "photo_quality": "Photo quality",
        "confidence": "Confidence",
        "brightness": "Brightness",
        "sharpness": "Sharpness",
        "contrast": "Contrast",
        "gallery_photos": "Photos analysed",
        "observations": "Observations",
        "room_unknown": "room: unknown",
        "fb_vision_summary": (
            "The technical quality of the listing photos was measured. These "
            "metrics describe the photographs, not the property's condition."
        ),
        "fb_condition_notes": (
            "Only measurable photo statistics are reported; the images do not "
            "support any claim about the property's condition."
        ),
        "vision_footnote": (
            "All figures in this section are measurements of the listing "
            "photography (brightness, sharpness, exposure, resolution). They say "
            "nothing about renovation state, materials or the property's actual "
            "condition — only an in-person inspection can assess those."
        ),
        "fb_no_vision": (
            "No photo analysis is available for this property. The valuation is "
            "based on market data, comparable listings and metadata only."
        ),
        # location
        "map_preview": "Map preview",
        "map_unavailable": "Map preview unavailable",
        "poi_transport": "Public transport",
        "poi_grocery": "Groceries",
        "poi_schools": "Schools",
        "poi_parks": "Parks",
        "poi_restaurants": "Restaurants",
        "poi_healthcare": "Doctors / pharmacies",
        "within_500m": "within 500 m",
        "within_1km": "within 1 km",
        "nearest_facilities": "Nearest facilities",
        "min_walk": "min walk",
        "location_score": "Location score",
        "fb_no_location": "Location context is unavailable",
        "fb_no_location_coords": " because coordinates were not provided for this property",
        "fb_no_location_tail": ". Nearby-facility counts could not be computed.",
        # recommendation
        "strengths": "Strengths",
        "risks": "Risks",
        "next_steps": "Recommended next steps",
        "none_identified": "None identified.",
        "fb_rec_summary": (
            "A full recommendation could not be generated from the available data. "
            "Please review the market and comparable sections above for context."
        ),
        "disclaimer": (
            "This report is an evidence-based estimate produced from market data, "
            "comparable listings, property metadata and visual indicators. It is "
            "not a certified appraisal and does not represent a guaranteed value."
        ),
        # condition words (for the vision chip)
        "cond_poor": "poor",
        "cond_average": "average",
        "cond_good": "good",
        "cond_renovated": "renovated",
        "cond_luxury": "luxury",
        "cond_unclear": "unclear",
        # room words
        "room_kitchen": "kitchen",
        "room_bathroom": "bathroom",
        "room_living room": "living room",
        "room_bedroom": "bedroom",
        "room_balcony": "balcony",
        "room_exterior": "exterior",
        "room_unknown_word": "unknown",
    },
    "cs": {
        "tagline": "Realitní inteligence",
        "report_title": "Odhad hodnoty nemovitosti",
        "ref": "Č.",
        "fb_untitled": "Nemovitost bez názvu",
        "fb_no_locality": "Lokalita neuvedena",
        "assessment": "Hodnocení ceny",
        "undervalued": "Podhodnoceno",
        "fairly_priced": "Přiměřená cena",
        "overpriced": "Nadhodnoceno",
        "not_assessed": "Neposouzeno",
        "est_market_value": "Odhadovaná tržní hodnota",
        "vs_asking": "Vůči nabídkové ceně",
        "asking_price": "Nabídková cena",
        "source": "Zdroj",
        "sale": "Prodej",
        "rent": "Pronájem",
        "sec_details": "Údaje o nemovitosti",
        "sec_market": "Analýza trhu",
        "sec_vision": "Kvalita fotografií inzerátu",
        "sec_location": "Lokalita a občanská vybavenost",
        "sec_recommendation": "Závěrečné doporučení",
        "m_address": "Adresa / Lokalita",
        "m_type": "Typ nemovitosti",
        "m_deal": "Typ nabídky",
        "m_layout": "Dispozice",
        "m_floor_area": "Užitná plocha",
        "m_land_area": "Plocha pozemku",
        "m_floor": "Podlaží",
        "m_asking": "Nabídková cena",
        "m_psqm": "Cena za m²",
        "m_source": "Zdroj",
        "m_first_seen": "Poprvé zaznamenáno",
        "m_last_seen": "Naposledy zaznamenáno",
        "m_days": "Dní na trhu",
        "m_reference": "Odkaz",
        "listing_link": "Odkaz na inzerát",
        "est_fair_value": "Odhadovaná přiměřená hodnota",
        "range": "Rozpětí",
        "local_median": "Místní medián ceny",
        "median_psqm": "Medián /m²",
        "asking_vs_est": "Nabídka vs. odhad",
        "benchmark_title": "Externí tržní index",
        "benchmark_note": (
            "Makro ukazatel agregovaný za širší trh — reference realizovaných cen, "
            "nikoli srovnatelný inzerát pro tuto konkrétní nemovitost."
        ),
        "benchmark_unit_sale": "EUR/m²",
        "benchmark_unit_rent": "EUR/m²/měsíc",
        "comparables": "Srovnatelné inzeráty",
        "th_property": "Nemovitost",
        "th_locality": "Lokalita",
        "th_layout": "Dispozice",
        "th_area": "Plocha",
        "th_price": "Cena",
        "th_psqm": "Cena/m²",
        "th_delta": "Δ vůči předmětu",
        "th_similarity": "Podobnost",
        "comp_footnote": (
            "Δ vůči předmětu: záporná hodnota znamená, že srovnatelný inzerát je "
            "levnější než hodnocená nemovitost. Podobnost zohledňuje dispozici, "
            "plochu a blízkost ceny za m²."
        ),
        "fb_no_comparables": (
            "Pro tuto lokalitu a dispozici nebyly nalezeny dostatečně podobné "
            "inzeráty. Odhad vychází z tržních mediánů a údajů o nemovitosti."
        ),
        "photo_quality": "Kvalita fotografií",
        "confidence": "Spolehlivost",
        "brightness": "Jas",
        "sharpness": "Ostrost",
        "contrast": "Kontrast",
        "gallery_photos": "Analyzované fotografie",
        "observations": "Pozorování",
        "room_unknown": "místnost: neurčeno",
        "fb_vision_summary": (
            "Byla změřena technická kvalita fotografií z inzerátu. Tyto metriky "
            "popisují fotografie, nikoli stav nemovitosti."
        ),
        "fb_condition_notes": (
            "Uvádíme pouze měřitelné statistiky fotografií; snímky neumožňují "
            "žádné tvrzení o stavu nemovitosti."
        ),
        "vision_footnote": (
            "Všechny údaje v této sekci jsou měření fotografií z inzerátu (jas, "
            "ostrost, expozice, rozlišení). Nevypovídají nic o rekonstrukci, "
            "materiálech ani skutečném stavu nemovitosti — ty lze posoudit pouze "
            "osobní prohlídkou."
        ),
        "fb_no_vision": (
            "Pro tuto nemovitost není k dispozici analýza fotografií. Ocenění "
            "vychází pouze z tržních dat, srovnatelných inzerátů a údajů o "
            "nemovitosti."
        ),
        "map_preview": "Náhled mapy",
        "map_unavailable": "Náhled mapy není k dispozici",
        "poi_transport": "MHD",
        "poi_grocery": "Obchody s potravinami",
        "poi_schools": "Školy",
        "poi_parks": "Parky",
        "poi_restaurants": "Restaurace",
        "poi_healthcare": "Lékaři / lékárny",
        "within_500m": "do 500 m",
        "within_1km": "do 1 km",
        "nearest_facilities": "Nejbližší v okolí",
        "min_walk": "min chůze",
        "location_score": "Skóre lokality",
        "fb_no_location": "Informace o lokalitě nejsou k dispozici",
        "fb_no_location_coords": ", protože pro tuto nemovitost nebyly uvedeny souřadnice",
        "fb_no_location_tail": ". Počty nedaleké vybavenosti nebylo možné vypočítat.",
        "strengths": "Silné stránky",
        "risks": "Rizika",
        "next_steps": "Doporučené další kroky",
        "none_identified": "Nebyly identifikovány.",
        "fb_rec_summary": (
            "Z dostupných dat nebylo možné vytvořit úplné doporučení. Kontext "
            "naleznete v sekcích trhu a srovnatelných inzerátů výše."
        ),
        "disclaimer": (
            "Tento report je odhad založený na datech z trhu, srovnatelných "
            "inzerátech, údajích o nemovitosti a vizuálních ukazatelích. Nejde o "
            "znalecký posudek a nepředstavuje garantovanou hodnotu."
        ),
        "cond_poor": "špatném",
        "cond_average": "průměrném",
        "cond_good": "dobrém",
        "cond_renovated": "zrekonstruovaném",
        "cond_luxury": "luxusním",
        "cond_unclear": "nejasném",
        "room_kitchen": "kuchyně",
        "room_bathroom": "koupelna",
        "room_living room": "obývací pokoj",
        "room_bedroom": "ložnice",
        "room_balcony": "balkon",
        "room_exterior": "exteriér",
        "room_unknown_word": "neurčeno",
    },
}


# Condition chip: the chip shows an adjective; in Czech we want the *nominative*
# form for the chip (the vision summary uses the locative form above).
CONDITION_CHIP = {
    "en": {"poor": "poor", "average": "average", "good": "good",
           "renovated": "renovated", "luxury": "luxury"},
    "cs": {"poor": "špatný", "average": "průměrný", "good": "dobrý",
           "renovated": "zrekonstruovaný", "luxury": "luxusní"},
}


# --------------------------------------------------------------------------- #
# Generated prose (format strings filled by the builder)                        #
# --------------------------------------------------------------------------- #

PROSE = {
    "en": {
        "comp_subject": "Subject property",
        "comp_median": "Median comparable",
        "comp_best": "Best comparable {i}",

        "expl_below": "This property appears about {pct:.1f}% below our estimated fair value for the area.",
        "expl_above": "This property appears about {pct:.1f}% above our estimated fair value for the area.",
        "expl_inline": "This property is priced broadly in line with our estimated fair value for the area.",
        "expl_pps_below": "Its price per m² is roughly {rel:.0f}% below the local median, i.e. below comparable properties in the same area.",
        "expl_pps_above": "Its price per m² is roughly {rel:.0f}% above the local median, i.e. above comparable properties in the same area.",
        "expl_pps_close": "Its price per m² is close to the local median for comparable properties.",
        "expl_widened": "Comparable listings in the immediate area were limited, so the benchmark was widened to the wider city.",
        "expl_none": "A market comparison could not be computed — there were not enough comparable active listings in this area to benchmark the price.",

        "vision_summary": "Automated analysis measured the technical quality of {n} listing photo(s) — brightness, sharpness, exposure and resolution. These metrics describe the photographs themselves; they are not an assessment of the property's condition, renovation state or materials.",
        "vision_summary_no_count": "Automated analysis measured the technical quality of the listing photos — brightness, sharpness, exposure and resolution. These metrics describe the photographs themselves; they are not an assessment of the property's condition, renovation state or materials.",
        "obs_bright_well_exposed": "The gallery is bright and generally well exposed.",
        "obs_dim": "The gallery is on the dark side, which limits what the photos can show.",
        "obs_uneven_exposure": "Several images appear unevenly exposed.",
        "obs_some_blurry": "Several images appear blurry.",
        "obs_mostly_blurry": "Most images appear blurry.",
        "obs_resolution_ok": "Image resolution is sufficient for presentation.",
        "obs_resolution_low": "Image resolution is low.",
        "obs_limited_coverage": "The gallery has limited visual coverage.",

        "location_pending": "Coordinates are available for this property, but nearby-facility counts have not been computed yet. Map context is shown for reference.",
        "location_ok": "Facility counts are derived from OpenStreetMap data around the property's coordinates. The location score summarises walkable access to transport, groceries, schools, parks, dining and healthcare — it is a convenience indicator, not a valuation input.",

        "verdict_undervalued": "Verdict: potentially attractive — priced below estimated fair value.",
        "verdict_overpriced": "Verdict: priced above the local benchmark — negotiate or compare further.",
        "verdict_fair": "Verdict: fairly priced for the area.",
        "verdict_none": "Verdict: insufficient market data for a firm pricing view.",

        "str_below": "Asking price ~{pct:.1f}% below estimated fair value.",
        "str_inline": "Priced broadly in line with the local benchmark.",
        "str_recent": "Recently listed — likely to attract competing interest.",
        "risk_above": "Asking price ~{pct:.1f}% above estimated fair value.",
        "risk_photo_only": "Photo analysis measures image quality only — it says nothing about the property's actual condition; inspect in person.",
        "risk_poor_photos": "Listing photos are low quality (blurry or dark), which limits any remote assessment.",
        "risk_no_vision": "No photo analysis available — inspect the property before deciding.",
        "risk_days": "{days} days on market — check why it has not sold.",

        "step_viewing": "Arrange an in-person viewing to assess the property's actual condition.",
        "step_building": "Request building ownership and reserve-fund details.",
        "step_benchmark": "Benchmark against live comparables before making an offer.",

        "priced_undervalued": "attractively priced, sitting below our estimated fair value",
        "priced_fair": "fairly priced relative to the local benchmark",
        "priced_overpriced": "priced above the local benchmark",
        "priced_none": "difficult to price precisely given limited comparable data",
        "rec_summary": "Overall, this {ptype} in {loc} appears {priced}{cond}. It should be assessed alongside an in-person viewing and current comparable listings before a final decision, as this report is an evidence-based estimate rather than a certified appraisal.",
        "the_area": "the selected area",
        "generic_property": "property",
    },
    "cs": {
        "comp_subject": "Hodnocená nemovitost",
        "comp_median": "Mediánový srovnatelný",
        "comp_best": "Nejlepší srovnatelný {i}",

        "expl_below": "Tato nemovitost je přibližně o {pct:.1f} % pod naším odhadem přiměřené hodnoty pro danou lokalitu.",
        "expl_above": "Tato nemovitost je přibližně o {pct:.1f} % nad naším odhadem přiměřené hodnoty pro danou lokalitu.",
        "expl_inline": "Cena této nemovitosti zhruba odpovídá našemu odhadu přiměřené hodnoty pro danou lokalitu.",
        "expl_pps_below": "Cena za m² je zhruba o {rel:.0f} % pod místním mediánem, tedy pod srovnatelnými nemovitostmi ve stejné lokalitě.",
        "expl_pps_above": "Cena za m² je zhruba o {rel:.0f} % nad místním mediánem, tedy nad srovnatelnými nemovitostmi ve stejné lokalitě.",
        "expl_pps_close": "Cena za m² se blíží místnímu mediánu srovnatelných nemovitostí.",
        "expl_widened": "Srovnatelných inzerátů v bezprostředním okolí bylo málo, proto byl srovnávací základ rozšířen na celé město.",
        "expl_none": "Srovnání s trhem nebylo možné vypočítat — v této lokalitě nebyl dostatek srovnatelných aktivních inzerátů pro stanovení srovnávací ceny.",

        "vision_summary": "Automatická analýza změřila technickou kvalitu {n} fotografií z inzerátu — jas, ostrost, expozici a rozlišení. Tyto metriky popisují samotné fotografie; nejsou hodnocením stavu nemovitosti, rekonstrukce ani materiálů.",
        "vision_summary_no_count": "Automatická analýza změřila technickou kvalitu fotografií z inzerátu — jas, ostrost, expozici a rozlišení. Tyto metriky popisují samotné fotografie; nejsou hodnocením stavu nemovitosti, rekonstrukce ani materiálů.",
        "obs_bright_well_exposed": "Galerie je světlá a celkově dobře exponovaná.",
        "obs_dim": "Galerie je spíše tmavá, což omezuje, co fotografie mohou ukázat.",
        "obs_uneven_exposure": "Několik snímků se jeví jako nerovnoměrně exponované.",
        "obs_some_blurry": "Několik snímků se jeví jako rozmazané.",
        "obs_mostly_blurry": "Většina snímků se jeví jako rozmazaná.",
        "obs_resolution_ok": "Rozlišení fotografií je pro prezentaci dostatečné.",
        "obs_resolution_low": "Rozlišení fotografií je nízké.",
        "obs_limited_coverage": "Galerie má omezené vizuální pokrytí.",

        "location_pending": "Pro tuto nemovitost jsou k dispozici souřadnice, ale počty nedaleké vybavenosti zatím nebyly vypočítány. Mapa je zobrazena pro orientaci.",
        "location_ok": "Počty vybavenosti vycházejí z dat OpenStreetMap v okolí souřadnic nemovitosti. Skóre lokality shrnuje pěší dostupnost dopravy, obchodů, škol, parků, restaurací a zdravotní péče — jde o ukazatel komfortu, nikoli o vstup do ocenění.",

        "verdict_undervalued": "Závěr: potenciálně zajímavé — cena pod odhadem přiměřené hodnoty.",
        "verdict_overpriced": "Závěr: cena nad místním srovnávacím základem — vyjednávejte nebo dále srovnávejte.",
        "verdict_fair": "Závěr: přiměřená cena pro danou lokalitu.",
        "verdict_none": "Závěr: nedostatek tržních dat pro jednoznačný cenový názor.",

        "str_below": "Nabídková cena ~{pct:.1f} % pod odhadem přiměřené hodnoty.",
        "str_inline": "Cena zhruba odpovídá místnímu srovnávacímu základu.",
        "str_recent": "Nedávno inzerováno — pravděpodobně přiláká konkurenční zájem.",
        "risk_above": "Nabídková cena ~{pct:.1f} % nad odhadem přiměřené hodnoty.",
        "risk_photo_only": "Analýza fotografií měří pouze kvalitu snímků — o skutečném stavu nemovitosti nic neříká; prohlédněte osobně.",
        "risk_poor_photos": "Fotografie v inzerátu mají nízkou kvalitu (rozmazané nebo tmavé), což omezuje posouzení na dálku.",
        "risk_no_vision": "Analýza fotografií není k dispozici — před rozhodnutím nemovitost prohlédněte.",
        "risk_days": "{days} dní na trhu — ověřte, proč se dosud neprodala.",

        "step_viewing": "Domluvte osobní prohlídku a posuďte skutečný stav nemovitosti.",
        "step_building": "Vyžádejte si informace o vlastnictví domu a fondu oprav.",
        "step_benchmark": "Před podáním nabídky porovnejte s aktuálními srovnatelnými inzeráty.",

        "priced_undervalued": "atraktivně oceněná, pod naším odhadem přiměřené hodnoty",
        "priced_fair": "přiměřeně oceněná vůči místnímu srovnávacímu základu",
        "priced_overpriced": "oceněná nad místním srovnávacím základem",
        "priced_none": "obtížně přesně ocenitelná vzhledem k omezeným srovnatelným datům",
        "rec_summary": "Celkově se tato {ptype} v lokalitě {loc} jeví jako {priced}{cond}. Před konečným rozhodnutím by měla být posouzena spolu s osobní prohlídkou a aktuálními srovnatelnými inzeráty, neboť tento report je odhad založený na datech, nikoli znalecký posudek.",
        "the_area": "vybrané lokalitě",
        "generic_property": "nemovitost",
    },
}


# Property-category words used in the metadata field and recommendation prose.
CATEGORY_WORDS = {
    "en": {"apartment": "Apartment", "house": "House", "land": "Land",
           "commercial": "Commercial", "office": "Office"},
    "cs": {"apartment": "Byt", "house": "Dům", "land": "Pozemek",
           "commercial": "Komerční prostor", "office": "Kancelář"},
}
# Lower-case form for mid-sentence use in the recommendation summary.
CATEGORY_WORDS_LOWER = {
    "en": {"apartment": "apartment", "house": "house", "land": "plot",
           "commercial": "commercial unit", "office": "office"},
    "cs": {"apartment": "byt", "house": "dům", "land": "pozemek",
           "commercial": "komerční prostor", "office": "kancelář"},
}


def strings(lang: str) -> dict:
    """Static template chrome for `lang` (falls back to English)."""
    return LABELS.get(lang, LABELS[DEFAULT_LANG])


def prose(lang: str) -> dict:
    """Generated-copy format strings for `lang` (falls back to English)."""
    return PROSE.get(lang, PROSE[DEFAULT_LANG])


def category_word(lang: str, category: str | None, *, lower: bool = False) -> str | None:
    """Localize a property category; unknown categories are title/again-cased."""
    if not category:
        return None
    key = category.strip().lower()
    table = (CATEGORY_WORDS_LOWER if lower else CATEGORY_WORDS).get(lang, {})
    if key in table:
        return table[key]
    return key if lower else key.capitalize()


def condition_chip(lang: str, condition: str | None) -> str | None:
    """Nominative adjective for the condition chip (distinct from the locative
    form `LABELS["cond_*"]` uses inside the vision-summary sentence)."""
    if not condition:
        return None
    return CONDITION_CHIP.get(lang, CONDITION_CHIP[DEFAULT_LANG]).get(condition, condition)
