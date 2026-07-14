"""Pure normalization tests (no database)."""

from datetime import datetime, timezone

from src.services import normalizer as nz

RUN_TIME = datetime(2026, 6, 19, 6, 0, tzinfo=timezone.utc)


# ── helpers ───────────────────────────────────────────────────────────────────


def test_extract_bezrealitky_id():
    url = "https://www.bezrealitky.cz/1035298-nabidka-pronajem-domu-nyklickova-praha"
    assert nz.extract_bezrealitky_id(url) == "1035298"
    # also works with the corrected path segment
    url2 = "https://www.bezrealitky.cz/nemovitosti-byty-domy/981912-nabidka-prodej-bytu-praha"
    assert nz.extract_bezrealitky_id(url2) == "981912"
    assert nz.extract_bezrealitky_id(None) is None


def test_deal_type_from_url():
    assert nz.deal_type_from_url("https://www.bezrealitky.cz/123-nabidka-prodej-bytu") == "buy"
    assert nz.deal_type_from_url("https://www.bezrealitky.cz/123-nabidka-pronajem-bytu") == "rent"
    assert nz.deal_type_from_url("https://www.sreality.cz/detail/prodej/byt/praha/9") == "buy"
    assert nz.deal_type_from_url("https://example.com/x") is None


def test_normalize_layout():
    assert nz.normalize_layout("DISP_6_1") == "6+1"
    assert nz.normalize_layout("DISP_6_KK") == "6+kk"
    assert nz.normalize_layout("GARSONIERA") == "1+kk"
    assert nz.normalize_layout("UNDEFINED") is None
    assert nz.normalize_layout("OSTATNI") is None
    assert nz.normalize_layout("2+kk") == "2+kk"   # already human-readable
    assert nz.normalize_layout(None) is None


def test_normalize_category():
    assert nz.normalize_category("byty") == "apartment"
    assert nz.normalize_category("domy") == "house"
    assert nz.normalize_category("apartment") == "apartment"
    assert nz.normalize_category(None) is None


def test_price_per_sqm():
    assert nz.price_per_sqm(8000000, 50) == 160000.0
    assert nz.price_per_sqm(None, 50) is None
    assert nz.price_per_sqm(8000000, None) is None
    assert nz.price_per_sqm(8000000, 0) is None


def test_nullify_zero():
    assert nz.nullify_zero(0) is None
    assert nz.nullify_zero(0.0) is None
    assert nz.nullify_zero(50.07) == 50.07
    assert nz.nullify_zero(None) is None


def test_fix_bezrealitky_url():
    bad = "https://www.bezrealitky.cz/1033493-nabidka-pronajem-bytu-na-pankraci-praha"
    good = "https://www.bezrealitky.cz/nemovitosti-byty-domy/1033493-nabidka-pronajem-bytu-na-pankraci-praha"
    assert nz.fix_bezrealitky_url(bad) == good
    # idempotent
    assert nz.fix_bezrealitky_url(good) == good
    assert nz.fix_bezrealitky_url(None) is None


# ── source normalizers ─────────────────────────────────────────────────────────


def test_normalize_sreality():
    raw = {
        "listingId": "3929374796",
        "url": "https://www.sreality.cz/detail/prodej/byt/atypicky/praha/3929374796",
        "dealType": "buy",
        "propertyType": "apartment",
        "title": "Prodej bytu 2+kk 50 m²",
        "locality": "Holečkova, Košíře, Praha, Praha 5",
        "city": "Praha",
        "district": "Praha 5",
        "rooms": "2+kk",
        "areaSqm": 50,
        "latitude": None,
        "longitude": None,
        "price": 7990000,
        "currency": "CZK",
        "images": ["https://img/1.jpg", "https://img/2.jpg"],
        "scrapedAt": "2026-06-18T05:54:36.168Z",
    }
    n = nz.normalize_sreality(raw, RUN_TIME)
    assert n["source"] == "sreality"
    assert n["source_listing_id"] == "3929374796"
    assert n["deal_type"] == "buy"
    assert n["category"] == "apartment"
    assert n["layout"] == "2+kk"
    assert n["floor_area"] == 50
    assert n["price"] == 7990000
    assert n["price_per_sqm"] == 159800.0
    assert n["image_url"] == "https://img/1.jpg"
    assert n["district"] == "Praha 5"
    assert n["scraped_at"].year == 2026 and n["scraped_at"].month == 6 and n["scraped_at"].day == 18


def test_normalize_bezrealitky():
    raw = {
        "id": "bezrealitky_byty_1034600",
        "source": "bezrealitky",
        "category": "byty",
        "name": "Plzeňská, Praha - Košíře",
        "price": "18000",
        "pricePerSqm": "419",
        "locality": "Plzeňská, Praha - Košíře",
        "layout": "2+kk",
        "floorArea": "43",
        "landArea": None,
        "lat": "50.0721597",
        "lon": "0",                      # zero → should become None
        "imageUrl": "https://img/x.jpg",
        "url": "https://www.bezrealitky.cz/1034600-nabidka-pronajem-bytu-plzenska-praha",
    }
    n = nz.normalize_bezrealitky(raw, RUN_TIME)
    assert n["source"] == "bezrealitky"
    assert n["source_listing_id"] == "1034600"
    assert n["deal_type"] == "rent"            # from URL (pronajem)
    assert n["category"] == "apartment"        # byty → apartment
    assert n["source_category"] == "byty"
    assert n["currency"] == "CZK"
    assert n["price"] == 18000
    assert n["price_per_sqm"] == 419.0
    assert n["floor_area"] == 43
    assert n["lat"] == 50.0721597
    assert n["lon"] is None                    # zero coordinate nullified
    assert n["url"].startswith("https://www.bezrealitky.cz/nemovitosti-byty-domy/")
    assert n["scraped_at"] == RUN_TIME         # bezrealitky has no scrapedAt


BEZ_API_RAW = {
    "id": "1003681",
    "url": "https://www.bezrealitky.cz/nemovitosti-byty-domy/1003681-nabidka-pronajem-bytu-u-sluncove-praha",
    "estateType": "BYT",
    "offerType": "PRONAJEM",
    "disposition": "DISP_3_KK",
    "address": "U Sluncové, Prague - Karlín",
    "surface": 98,
    "surfaceLand": 0,
    "price": 42000,
    "totalPrice": 56000,
    "currency": "CZK",
    "coordinates": {"lat": 50.0981153, "lng": 14.4706657},
    "mainImage": {"id": "27055820", "url": "https://api.bezrealitky.cz/media/x.jpg"},
    "source": "bezrealitky",
    "scrapedAt": "2026-06-26T06:22:22.129Z",
}


def test_normalize_bezrealitky_api():
    n = nz.normalize_bezrealitky_api(BEZ_API_RAW, RUN_TIME)
    assert n["source"] == "bezrealitky"
    assert n["source_listing_id"] == "1003681"
    assert n["deal_type"] == "rent"            # offerType PRONAJEM → rent
    assert n["category"] == "apartment"        # BYT → apartment
    assert n["source_category"] == "BYT"
    assert n["layout"] == "3+kk"               # DISP_3_KK → 3+kk
    assert n["floor_area"] == 98.0
    assert n["land_area"] is None              # surfaceLand 0 → None
    assert n["price"] == 42000
    assert n["price_per_sqm"] == round(42000 / 98, 2)
    assert n["lat"] == 50.0981153
    assert n["lon"] == 14.4706657              # coordinates.lng → lon
    assert n["image_url"] == "https://api.bezrealitky.cz/media/x.jpg"
    assert n["locality"] == "U Sluncové, Praha - Karlín"   # Prague → Praha
    assert n["district"] == "Praha - Karlín"
    assert n["scraped_at"].day == 26 and n["scraped_at"].month == 6


def test_normalize_routes_bezrealitky_api():
    # The rich format must route to the new normalizer, not the flat one
    # (which would read surface/coordinates as missing → null area/coords).
    n = nz.normalize(BEZ_API_RAW, RUN_TIME)
    assert n["floor_area"] == 98.0
    assert n["lat"] == 50.0981153 and n["lon"] == 14.4706657


def test_detect_source():
    assert nz.detect_source({"listingId": "1"}) == "sreality"
    assert nz.detect_source({"source": "bezrealitky", "url": "x"}) == "bezrealitky"


# ── Image gallery ─────────────────────────────────────────────────────────────


def test_image_list_flattens_and_dedupes():
    assert nz.image_list("a", "b") == ["a", "b"]
    assert nz.image_list(["a", "b", "a"]) == ["a", "b"]          # de-duped, ordered
    assert nz.image_list({"url": "a"}, [{"url": "b"}]) == ["a", "b"]  # dict.url
    assert nz.image_list(None, "", {"url": None}, []) == []      # falsy skipped
    assert nz.image_list({"url": "a"}, ["a", "b"]) == ["a", "b"]  # thumbnail first


def test_sreality_gallery():
    raw = {"listingId": "1", "title": "x", "price": 100, "areaSqm": 10,
           "images": ["u1.jpg", "u2.jpg", "u1.jpg"]}
    n = nz.normalize_sreality(raw, RUN_TIME)
    assert n["images"] == ["u1.jpg", "u2.jpg"]   # de-duped
    assert n["image_url"] == "u1.jpg"            # first is the thumbnail


def test_sreality_no_images():
    n = nz.normalize_sreality({"listingId": "1", "price": 100, "areaSqm": 10}, RUN_TIME)
    assert n["images"] == [] and n["image_url"] is None


def test_bezrealitky_flat_gallery_is_single_image():
    n = nz.normalize_bezrealitky(
        {"source": "bezrealitky", "url": "https://www.bezrealitky.cz/1-x",
         "imageUrl": "main.jpg", "price": 100, "floorArea": 10}, RUN_TIME)
    assert n["images"] == ["main.jpg"]
    assert n["image_url"] == "main.jpg"


def test_bezrealitky_api_gallery_uses_publicimages_only():
    # mainImage is a record_thumb copy of the first publicImage (record_main) —
    # different URL, same photo. The gallery must be the publicImages only, so
    # the first photo doesn't appear twice; mainImage stays the card thumbnail.
    thumb = "https://api.bezrealitky.cz/media/cache/record_thumb/data/img-1.jpg"
    main1 = "https://api.bezrealitky.cz/media/cache/record_main/data/img-1.jpg"
    main2 = "https://api.bezrealitky.cz/media/cache/record_main/data/img-2.jpg"
    raw = {**BEZ_API_RAW, "mainImage": {"url": thumb},
           "publicImages": [{"url": main1}, {"url": main2}]}
    n = nz.normalize_bezrealitky_api(raw, RUN_TIME)
    assert n["images"] == [main1, main2]   # full-res gallery, no thumbnail dup
    assert n["image_url"] == thumb         # thumbnail for the card


def test_bezrealitky_api_gallery_falls_back_to_main_image():
    raw = {**BEZ_API_RAW, "mainImage": {"url": "only.jpg"}, "publicImages": []}
    n = nz.normalize_bezrealitky_api(raw, RUN_TIME)
    assert n["images"] == ["only.jpg"]
    assert n["image_url"] == "only.jpg"


# ── Bazoš (SK) ────────────────────────────────────────────────────────────────

BAZOS_RAW = {
    "id": 193292570,
    "title": "Ponúkame na predaj 3-izbový byt s loggiou na Furči",
    "priceRaw": "178 000 €",
    "locationName": "Košice",
    "locationPsc": "040 01",
    "url": "https://reality.bazos.sk/inzerat/193292570/na-predaj-3-izbovy-byt.php",
    "content": "Ponúkame na predaj 3-izbový byt ● Výmera: 63,5 m2 ● Poschodie: 8 z 12",
    "imageUrl": "https://www.bazos.sk/img/1/570/193292570.jpg",
}


def test_bazos_detection_reality_only():
    assert nz.is_bazos_reality({"url": "https://reality.bazos.sk/inzerat/1/x.php"})
    # non-real-estate bazos sections must NOT be treated as property listings
    assert not nz.is_bazos_reality({"url": "https://nabytok.bazos.sk/inzerat/2/y.php"})
    assert nz.detect_source(BAZOS_RAW) == "bazos"


def test_bazos_price_parsing_and_placeholder():
    assert nz.parse_bazos_price("178 000 €") == 178000
    assert nz.parse_bazos_price("1 199 €") == 1199
    assert nz.parse_bazos_price("Dohodou") is None
    assert nz.parse_bazos_price("V texte") is None
    # implausible placeholder/inquiry prices are dropped
    assert nz.parse_bazos_price("6 €") is None
    assert nz.parse_bazos_price("") is None


def test_bazos_area_slovak_decimal_comma():
    assert nz.parse_bazos_area("Výmera: 63,5 m2 ● Poschodie 8") == 63.5
    assert nz.parse_bazos_area("plocha 45 m²") == 45.0
    assert nz.parse_bazos_area("bez rozmerov") is None


def test_bazos_layout_from_title():
    assert nz.parse_bazos_layout("Na predaj 3-izbový byt") == "3-izb"
    assert nz.parse_bazos_layout("1,5-izbový byt po rekonštrukcii") == "1.5-izb"
    assert nz.parse_bazos_layout("Garzónka v centre") == "1-izb"


def test_bazos_deal_type_title_beats_boilerplate():
    # a five-figure sale whose content mentions agency 'prenájom' boilerplate
    raw = {"title": "Na predaj 2-izbový byt", "priceRaw": "161 000 €",
           "content": "Realitná kancelária ponúka predaj a prenájom nehnuteľností."}
    assert nz.bazos_deal_type(raw, 161000) == "buy"
    # a genuine rent
    rent = {"title": "Prenájom 2-izbového bytu v Púchove", "content": "..."}
    assert nz.bazos_deal_type(rent, 550) == "rent"


def test_bazos_category_nebytovy_is_commercial_not_apartment():
    # 'nebytový' contains the substring 'byt' but is non-residential
    assert nz.bazos_category("Na prenájom nebytový priestor – kancelária", None) == "commercial"
    assert nz.bazos_category("Predaj 3-izbového bytu", None) == "apartment"
    assert nz.bazos_category("Predaj rodinného domu", None) == "house"
    assert nz.bazos_category("Predaj pozemku 800 m2", None) == "land"


def test_normalize_bazos_full_item():
    n = nz.normalize(BAZOS_RAW, RUN_TIME)
    assert n["source"] == "bazos"
    assert n["source_listing_id"] == "193292570"
    assert n["deal_type"] == "buy"
    assert n["category"] == "apartment"
    assert n["layout"] == "3-izb"
    assert n["floor_area"] == 63.5
    assert n["price"] == 178000
    assert n["currency"] == "EUR"
    assert n["locality"] == "Košice"
    assert n["price_per_sqm"] == round(178000 / 63.5, 2)
