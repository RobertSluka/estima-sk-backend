"""
Slovak administrative geography — resolve a listing's town/PSČ to its okres
(district) and kraj (region). The SK analogue of `prague_districts.py`.

Slovakia has 8 kraje and 79 okresy; here the 5 Bratislava and 4 Košice city
okresy are consolidated to single "Bratislava"/"Košice" districts (72 entries),
which is the granularity Bazoš listings actually carry (a town name, not a city
district). Resolution is by town name — every okres seat maps to itself; a small
alias table covers non-seat towns and dataset spellings. PSČ is currently only a
presence signal; a precise PSČ→okres table (from the Slovenská pošta dataset) is
a future improvement — see resolve().
"""

from __future__ import annotations

import unicodedata

# Canonical kraj names (without the trailing " kraj").
KRAJE: tuple[str, ...] = (
    "Bratislavský", "Trnavský", "Trenčiansky", "Nitriansky",
    "Žilinský", "Banskobystrický", "Prešovský", "Košický",
)

# okres (district) → kraj (region). Bratislava/Košice consolidated.
OKRES_TO_KRAJ: dict[str, str] = {
    # Bratislavský
    "Bratislava": "Bratislavský", "Malacky": "Bratislavský",
    "Pezinok": "Bratislavský", "Senec": "Bratislavský",
    # Trnavský
    "Dunajská Streda": "Trnavský", "Galanta": "Trnavský", "Hlohovec": "Trnavský",
    "Piešťany": "Trnavský", "Senica": "Trnavský", "Skalica": "Trnavský",
    "Trnava": "Trnavský",
    # Trenčiansky
    "Bánovce nad Bebravou": "Trenčiansky", "Ilava": "Trenčiansky",
    "Myjava": "Trenčiansky", "Nové Mesto nad Váhom": "Trenčiansky",
    "Partizánske": "Trenčiansky", "Považská Bystrica": "Trenčiansky",
    "Prievidza": "Trenčiansky", "Púchov": "Trenčiansky", "Trenčín": "Trenčiansky",
    # Nitriansky
    "Komárno": "Nitriansky", "Levice": "Nitriansky", "Nitra": "Nitriansky",
    "Nové Zámky": "Nitriansky", "Šaľa": "Nitriansky", "Topoľčany": "Nitriansky",
    "Zlaté Moravce": "Nitriansky",
    # Žilinský
    "Bytča": "Žilinský", "Čadca": "Žilinský", "Dolný Kubín": "Žilinský",
    "Kysucké Nové Mesto": "Žilinský", "Liptovský Mikuláš": "Žilinský",
    "Martin": "Žilinský", "Námestovo": "Žilinský", "Ružomberok": "Žilinský",
    "Turčianske Teplice": "Žilinský", "Tvrdošín": "Žilinský", "Žilina": "Žilinský",
    # Banskobystrický
    "Banská Bystrica": "Banskobystrický", "Banská Štiavnica": "Banskobystrický",
    "Brezno": "Banskobystrický", "Detva": "Banskobystrický",
    "Krupina": "Banskobystrický", "Lučenec": "Banskobystrický",
    "Poltár": "Banskobystrický", "Revúca": "Banskobystrický",
    "Rimavská Sobota": "Banskobystrický", "Veľký Krtíš": "Banskobystrický",
    "Zvolen": "Banskobystrický", "Žarnovica": "Banskobystrický",
    "Žiar nad Hronom": "Banskobystrický",
    # Prešovský
    "Bardejov": "Prešovský", "Humenné": "Prešovský", "Kežmarok": "Prešovský",
    "Levoča": "Prešovský", "Medzilaborce": "Prešovský", "Poprad": "Prešovský",
    "Prešov": "Prešovský", "Sabinov": "Prešovský", "Snina": "Prešovský",
    "Stará Ľubovňa": "Prešovský", "Stropkov": "Prešovský", "Svidník": "Prešovský",
    "Vranov nad Topľou": "Prešovský",
    # Košický
    "Košice": "Košický", "Košice-okolie": "Košický", "Gelnica": "Košický",
    "Michalovce": "Košický", "Rožňava": "Košický", "Sobrance": "Košický",
    "Spišská Nová Ves": "Košický", "Trebišov": "Košický",
}

# Non-seat towns and dataset-specific spellings → okres. Keys are matched after
# accent/case-insensitive normalization (see _norm), so only the mapping needs
# listing, not every casing.
_TOWN_ALIASES: dict[str, str | None] = {
    "nove mesto n.vahom": "Nové Mesto nad Váhom",
    "nove mesto nad vahom": "Nové Mesto nad Váhom",
    "sturovo": "Nové Zámky",       # Štúrovo lies in okres Nové Zámky
    "zahranicie": None,            # "abroad" — not resolvable to an okres
}

# Accent/case-folded lookup of okres names, so "kosice" resolves "Košice".
_OKRES_NORM: dict[str, str] = {}


def _norm(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return stripped.strip().lower()


for _okres in OKRES_TO_KRAJ:
    _OKRES_NORM[_norm(_okres)] = _okres


def resolve_okres(town: str | None) -> str | None:
    """Town name → okres (None if unknown/foreign)."""
    if not town:
        return None
    key = _norm(town)
    if key in _TOWN_ALIASES:
        return _TOWN_ALIASES[key]
    return _OKRES_NORM.get(key)


def kraj_of_okres(okres: str | None) -> str | None:
    return OKRES_TO_KRAJ.get(okres) if okres else None


def resolve(town: str | None, psc: str | None = None) -> tuple[str | None, str | None]:
    """Return (okres, kraj) for a listing. PSČ is accepted for a future
    PSČ→okres fallback (needs the official postal dataset); today resolution is
    by town name only, which covers all okres-seat towns."""
    okres = resolve_okres(town)
    return okres, kraj_of_okres(okres)


def okresy_of_kraj(kraj: str) -> list[str]:
    """All okresy in a kraj — used to filter listings by region in SQL."""
    return [o for o, k in OKRES_TO_KRAJ.items() if k == kraj]


# ── Town centroids ────────────────────────────────────────────────────────────
# Bazoš gives only a town name, so town-centroid coordinates are the honest
# granularity for map pins (listings in one town deliberately stack; the
# frontend clusters them). Keyed by town, not okres, so a non-seat town like
# Štúrovo gets its own point rather than its okres seat's. Covers every okres
# seat plus the non-seat towns seen in the data.
_TOWN_COORDS: dict[str, tuple[float, float]] = {
    "Banská Bystrica": (48.7363, 19.1462),
    "Banská Štiavnica": (48.4587, 18.8935),
    "Bardejov": (49.2920, 21.2725),
    "Bratislava": (48.1486, 17.1077),
    "Brezno": (48.8043, 19.6417),
    "Bánovce nad Bebravou": (48.7186, 18.2581),
    "Bytča": (49.2233, 18.5583),
    "Čadca": (49.4387, 18.7887),
    "Detva": (48.5608, 19.4183),
    "Dolný Kubín": (49.2097, 19.2964),
    "Dunajská Streda": (47.9924, 17.6191),
    "Galanta": (48.1901, 17.7273),
    "Gelnica": (48.8557, 20.9358),
    "Hlohovec": (48.4319, 17.8031),
    "Humenné": (48.9370, 21.9165),
    "Ilava": (48.9990, 18.2340),
    "Kežmarok": (49.1387, 20.4292),
    "Komárno": (47.7633, 18.1284),
    "Košice": (48.7164, 21.2611),
    # okres around the city — approximate district centroid, not the city itself
    "Košice-okolie": (48.6800, 21.3300),
    "Krupina": (48.3573, 19.0648),
    "Kysucké Nové Mesto": (49.3000, 18.7833),
    "Levice": (48.2153, 18.6069),
    "Levoča": (49.0261, 20.5889),
    "Liptovský Mikuláš": (49.0842, 19.6136),
    "Lučenec": (48.3312, 19.6708),
    "Malacky": (48.4360, 17.0203),
    "Martin": (49.0664, 18.9217),
    "Medzilaborce": (49.2719, 21.9048),
    "Michalovce": (48.7570, 21.9195),
    "Myjava": (48.7560, 17.5687),
    "Námestovo": (49.4072, 19.4805),
    "Nitra": (48.3069, 18.0864),
    "Nové Mesto nad Váhom": (48.7570, 17.8309),
    "Nové Zámky": (47.9855, 18.1590),
    "Partizánske": (48.6274, 18.3723),
    "Pezinok": (48.2897, 17.2665),
    "Piešťany": (48.5949, 17.8252),
    "Poltár": (48.4306, 19.7955),
    "Poprad": (49.0511, 20.2988),
    "Považská Bystrica": (49.1218, 18.4451),
    "Prešov": (48.9984, 21.2339),
    "Prievidza": (48.7746, 18.6273),
    "Púchov": (49.1205, 18.3305),
    "Revúca": (48.6832, 20.1123),
    "Rimavská Sobota": (48.3829, 20.0201),
    "Rožňava": (48.6604, 20.5333),
    "Ružomberok": (49.0748, 19.3080),
    "Sabinov": (49.1030, 21.0988),
    "Šaľa": (48.1518, 17.8748),
    "Senec": (48.2195, 17.4007),
    "Senica": (48.6805, 17.3665),
    "Skalica": (48.8449, 17.2265),
    "Snina": (48.9880, 22.1567),
    "Sobrance": (48.7450, 22.1800),
    "Spišská Nová Ves": (48.9445, 20.5615),
    "Stará Ľubovňa": (49.2984, 20.6893),
    "Stropkov": (49.2024, 21.6511),
    "Svidník": (49.3055, 21.5677),
    "Štúrovo": (47.7995, 18.7178),
    "Topoľčany": (48.5646, 18.1701),
    "Trebišov": (48.6284, 21.7191),
    "Trenčín": (48.8945, 18.0444),
    "Trnava": (48.3774, 17.5883),
    "Turčianske Teplice": (48.8624, 18.8620),
    "Tvrdošín": (49.3339, 19.5561),
    "Veľký Krtíš": (48.2126, 19.3346),
    "Vranov nad Topľou": (48.8886, 21.6845),
    "Zlaté Moravce": (48.3855, 18.4013),
    "Zvolen": (48.5744, 19.1531),
    "Žarnovica": (48.4818, 18.7169),
    "Žiar nad Hronom": (48.5906, 18.8496),
    "Žilina": (49.2231, 18.7394),
}

# Dataset abbreviations that must hit the coords of their full town name.
_COORD_ALIASES: dict[str, str] = {
    "nove mesto n.vahom": "Nové Mesto nad Váhom",
}

_COORDS_NORM: dict[str, tuple[float, float]] = {
    _norm(town): coords for town, coords in _TOWN_COORDS.items()
}


def resolve_coords(town: str | None) -> tuple[float | None, float | None]:
    """Town name → (lat, lon) centroid; (None, None) if unknown/foreign."""
    if not town:
        return None, None
    key = _norm(town)
    key = _norm(_COORD_ALIASES.get(key, town))
    coords = _COORDS_NORM.get(key)
    return coords if coords else (None, None)
