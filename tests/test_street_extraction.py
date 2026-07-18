"""Street extraction tests — patterns taken from real Bazoš titles/descriptions."""

from src.services.street_extraction import extract_street


def test_prefix_ul_dot():
    m = extract_street("Terasa - Štýlový 3 izb. byt ul. Gudernova. ZARIADENÝ. LOGGIA")
    assert m and m.candidates[0] == "Gudernova"


def test_prefix_with_house_number():
    m = extract_street("Priestor na prenájom na ul. Moyzesova 46, Košice")
    assert m and m.candidates[0] == "Moyzesova"
    assert m.house_number == "46"


def test_prefix_initials():
    m = extract_street("Veľký 2-izbový byt blízko stanice na ul. T.G. Masaryka, Nové")
    assert m and m.candidates[0] == "T.G. Masaryka"


def test_prefix_ulica_word():
    m = extract_street("Na predaj 4 izbový byt na ulica SNP, Sečovce")
    assert m and m.candidates[0] == "SNP"


def test_prefix_genitive_name_kept_verbatim():
    m = extract_street("Nadštandartný 3-izbový byt na ulici Boženy Nemcovej")
    assert m and m.candidates[0] == "Boženy Nemcovej"


def test_prefix_two_word_name():
    m = extract_street("…trojizbový byt na ulici Stará Baštová v historickej časti Košíc")
    assert m and m.candidates[0] == "Stará Baštová"


def test_suffix_plain_nominative():
    m = extract_street("NOVÁ REKONŠTRUKCIA: 3-izbový byt s loggiou, Zupkova ulica")
    assert m and m.candidates[0] == "Zupkova"


def test_suffix_ul_dot():
    m = extract_street("2-izb. byt 41m2 Ždiarska ul., Košice Nad Jazerom, investícia")
    assert m and m.candidates[0] == "Ždiarska"


def test_suffix_locative_skej_gets_nominative_candidates():
    m = extract_street("3 izbový byt na prenájom na Sibírskej ulici")
    assert m is not None
    assert "Sibírská" in m.candidates or "Sibírska" in m.candidates
    assert m.raw == "Sibírskej"


def test_suffix_locative_ovej():
    m = extract_street("Izba na prenájom v 3-izbovom byte na Budovateľskej ulici")
    assert m and ("Budovateľská" in m.candidates or "Budovateľska" in m.candidates)


def test_title_wins_over_content():
    m = extract_street(
        "Byt ul. Hlavná",
        "…na Vedľajšej ulici…",
    )
    assert m and m.candidates[0] == "Hlavná"


def test_content_used_when_title_has_nothing():
    m = extract_street(
        "REZERVOVANÉ veľký 2 izbový byt s loggiou na Ťahanovciach",
        "byt po kompletnej rekonštrukcii na Helsinskej ulici na sídlisku Ťahanovce.",
    )
    assert m and ("Helsinská" in m.candidates or "Helsinska" in m.candidates)


def test_no_mention_returns_none():
    assert extract_street("Prenájom 3i byt Námestovo 85 m2 pekný výhľad") is None
    assert extract_street(None, "") is None
    assert extract_street("2izbovy byt v centre, ihneď voľný") is None
