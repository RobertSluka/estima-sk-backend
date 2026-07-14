"""
Prague cadastral-area → administrative-district resolver.

The scraped `properties.district` holds a *cadastral area* (katastrální území),
e.g. "Praha - Žižkov" or "Praha - Libeň". External benchmarks (Deloitte Real
Index, etc.) are published by *administrative district* — Praha 1…Praha 10.
This module maps one to the other so a listing can be matched to its benchmark.

IMPORTANT: this is an approximation. Several cadastral areas straddle two
administrative districts (Vinohrady spans Praha 2/3/10, Libeň spans Praha 8/9,
…); each is assigned to its *predominant* administrative district. That is good
enough precisely because the benchmark is a district-level market reference, not
an exact valuation of a specific address — which is exactly how the UI frames it.
"""

import unicodedata

# Cadastral area (lower-cased, diacritics stripped) → "Praha N".
# Built from the katastrální území present in the live dataset.
_CADASTRAL_TO_DISTRICT: dict[str, str] = {
    # Praha 1
    "stare mesto": "Praha 1",
    "josefov": "Praha 1",
    "mala strana": "Praha 1",
    "hradcany": "Praha 1",
    "nove mesto": "Praha 1",
    # Praha 2
    "vinohrady": "Praha 2",
    "vysehrad": "Praha 2",
    # Praha 3
    "zizkov": "Praha 3",
    # Praha 4
    "nusle": "Praha 4",
    "podoli": "Praha 4",
    "branik": "Praha 4",
    "krc": "Praha 4",
    "michle": "Praha 4",
    "lhotka": "Praha 4",
    "hodkovicky": "Praha 4",
    "kamyk": "Praha 4",
    "haje": "Praha 4",
    "chodov": "Praha 4",
    "kunratice": "Praha 4",
    "seberov": "Praha 4",
    "ujezd u pruhonic": "Praha 4",
    "libus": "Praha 4",
    "pisnice": "Praha 4",
    "modrany": "Praha 4",
    "tocna": "Praha 4",
    "kreslice": "Praha 4",
    # Praha 5
    "smichov": "Praha 5",
    "kosire": "Praha 5",
    "motol": "Praha 5",
    "radlice": "Praha 5",
    "hlubocepy": "Praha 5",
    "jinonice": "Praha 5",
    "mala chuchle": "Praha 5",
    "velka chuchle": "Praha 5",
    "slivenec": "Praha 5",
    "lochkov": "Praha 5",
    "lipence": "Praha 5",
    "zbraslav": "Praha 5",
    "radotin": "Praha 5",
    "reporyje": "Praha 5",
    "trebonice": "Praha 5",
    "zlicin": "Praha 5",
    "stodulky": "Praha 5",
    # Praha 6
    "dejvice": "Praha 6",
    "brevnov": "Praha 6",
    "stresovice": "Praha 6",
    "veleslavin": "Praha 6",
    "vokovice": "Praha 6",
    "liboc": "Praha 6",
    "ruzyne": "Praha 6",
    "sedlec": "Praha 6",
    "nebusice": "Praha 6",
    "suchdol": "Praha 6",
    "repy": "Praha 6",
    # Praha 7
    "holesovice": "Praha 7",
    "bubenec": "Praha 7",
    "troja": "Praha 7",
    # Praha 8
    "liben": "Praha 8",
    "kobylisy": "Praha 8",
    "bohnice": "Praha 8",
    "karlin": "Praha 8",
    "cimice": "Praha 8",
    "dablice": "Praha 8",
    "dolni chabry": "Praha 8",
    "brezineves": "Praha 8",
    # Praha 9
    "vysocany": "Praha 9",
    "prosek": "Praha 9",
    "strizkov": "Praha 9",
    "hloubetin": "Praha 9",
    "hrdlorezy": "Praha 9",
    "kbely": "Praha 9",
    "letnany": "Praha 9",
    "cakovice": "Praha 9",
    "miskovice": "Praha 9",
    "satalice": "Praha 9",
    "vinor": "Praha 9",
    "kyje": "Praha 9",
    "hostavice": "Praha 9",
    "cerny most": "Praha 9",
    "horni pocernice": "Praha 9",
    "dolni pocernice": "Praha 9",
    "bechovice": "Praha 9",
    "ujezd nad lesy": "Praha 9",
    # Praha 10
    "vrsovice": "Praha 10",
    "strasnice": "Praha 10",
    "zabehlice": "Praha 10",
    "malesice": "Praha 10",
    "hostivar": "Praha 10",
    "petrovice": "Praha 10",
    "horni mecholupy": "Praha 10",
    "dolni mecholupy": "Praha 10",
    "sterboholy": "Praha 10",
    "dubec": "Praha 10",
    "kolovraty": "Praha 10",
    "uhrineves": "Praha 10",
    "pitkovice": "Praha 10",
    "nedvezi u rican": "Praha 10",
}


def _normalize(text: str) -> str:
    """Lower-case and strip diacritics so 'Žižkov' and 'zizkov' compare equal."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.lower().strip()


def cadastral_area(district: str | None, locality: str | None = None) -> str | None:
    """Extract the bare cadastral-area name from a 'Praha - Žižkov' style string.

    Falls back to `locality` if `district` carries no usable area. Returns None
    when nothing identifiable is present.
    """
    for raw in (district, locality):
        if not raw:
            continue
        # Split on the dash that separates city from area: "Praha - Žižkov".
        parts = [p.strip() for p in raw.replace("–", "-").split("-")]
        candidate = parts[-1] if len(parts) > 1 else parts[0]
        candidate = candidate.strip()
        if candidate and _normalize(candidate) not in ("praha", ""):
            return candidate
    return None


def administrative_district(district: str | None, locality: str | None = None) -> str | None:
    """Resolve a cadastral area to its predominant administrative district.

    Returns e.g. "Praha 8", or None if the area is unknown / not resolvable.
    Accepts an already-administrative value too: "Praha 8" maps to itself.
    """
    # Already an administrative district? ("Praha 8")
    for raw in (district, locality):
        if raw and _is_administrative(raw):
            return _canonical_administrative(raw)

    area = cadastral_area(district, locality)
    if area is None:
        return None
    return _CADASTRAL_TO_DISTRICT.get(_normalize(area))


def _is_administrative(raw: str) -> bool:
    norm = _normalize(raw)
    # "praha 8", "praha 10" — "praha" followed by a 1–2 digit number.
    if not norm.startswith("praha"):
        return False
    rest = norm[len("praha"):].strip()
    return rest.isdigit() and 1 <= int(rest) <= 22


def _canonical_administrative(raw: str) -> str:
    norm = _normalize(raw)
    num = norm[len("praha"):].strip()
    return f"Praha {int(num)}"
