"""Slovak geography resolution tests (pure, no database)."""

from src.services import slovak_regions as G


def test_okres_seat_resolves_to_itself_and_kraj():
    assert G.resolve("Košice") == ("Košice", "Košický")
    assert G.resolve("Bratislava") == ("Bratislava", "Bratislavský")
    assert G.resolve("Prešov") == ("Prešov", "Prešovský")
    assert G.resolve("Banská Bystrica") == ("Banská Bystrica", "Banskobystrický")


def test_accent_and_case_insensitive():
    assert G.resolve_okres("kosice") == "Košice"
    assert G.resolve_okres("ZILINA") == "Žilina"


def test_aliases_and_non_seat_towns():
    # Štúrovo is not an okres seat — it lies in okres Nové Zámky
    assert G.resolve("Štúrovo") == ("Nové Zámky", "Nitriansky")
    # dataset abbreviation
    assert G.resolve("Nové Mesto n.Váhom") == ("Nové Mesto nad Váhom", "Trenčiansky")


def test_unknown_and_foreign_return_none():
    assert G.resolve("Zahraničie") == (None, None)
    assert G.resolve("Praha") == (None, None)
    assert G.resolve(None) == (None, None)


def test_every_okres_has_a_valid_kraj():
    assert set(G.OKRES_TO_KRAJ.values()) == set(G.KRAJE)


def test_okresy_of_kraj_roundtrip():
    for kraj in G.KRAJE:
        okresy = G.okresy_of_kraj(kraj)
        assert okresy, f"{kraj} has no okresy"
        assert all(G.kraj_of_okres(o) == kraj for o in okresy)


def test_resolve_coords_town_centroids():
    lat, lon = G.resolve_coords("Košice")
    assert (lat, lon) == (48.7164, 21.2611)
    # accent/case-insensitive
    assert G.resolve_coords("kosice") == (48.7164, 21.2611)
    # non-seat town gets ITS OWN point, not its okres seat's
    assert G.resolve_coords("Štúrovo") == (47.7995, 18.7178)
    assert G.resolve_coords("Štúrovo") != G.resolve_coords("Nové Zámky")
    # dataset abbreviation hits the full name's coords
    assert G.resolve_coords("Nové Mesto n.Váhom") == G.resolve_coords("Nové Mesto nad Váhom")
    # unknown/foreign
    assert G.resolve_coords("Zahraničie") == (None, None)
    assert G.resolve_coords(None) == (None, None)


def test_every_okres_seat_has_coords():
    # Every okres must resolve to a map point so choropleth/pins never gap.
    for okres in G.OKRES_TO_KRAJ:
        lat, lon = G.resolve_coords(okres)
        assert lat is not None and lon is not None, f"{okres} missing coords"
        # sanity: inside Slovakia's bounding box
        assert 47.7 <= lat <= 49.7 and 16.8 <= lon <= 22.6, f"{okres} out of bounds"
