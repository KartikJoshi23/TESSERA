from tessera.normalize.domains import domain_parts, registrable_domain
from tessera.normalize.names import fold_arabic, normalize_name
from tessera.normalize.phones import is_reserved_fiction, normalize_phone


def test_legal_forms_and_zone_tags_are_separated():
    name = normalize_name("Lumen Crest Capital (DIFC) Limited")
    assert name.key == "lumen crest capital"
    assert name.legal_forms == ("LTD",)
    assert name.zone_tags == ("DIFC",)


def test_llc_spellings_share_one_key():
    keys = {
        normalize_name(n).key
        for n in (
            "Falcon Ridge Securities L.L.C.",
            "FALCON RIDGE SECURITIES LLC",
            "Falcon Ridge Securities",
        )
    }
    assert keys == {"falcon ridge securities"}


def test_arabic_names_are_folded():
    assert fold_arabic("أحمد") == "احمد"
    assert normalize_name("فالكون ريدج للأوراق المالية ذ.م.م").legal_forms == ("LLC",)


def test_registrable_domains():
    assert registrable_domain("https://www.Falconridge.example/path") == "falconridge.example"
    assert registrable_domain("info@sub.oasisbridge.example") == "oasisbridge.example"
    assert registrable_domain("www.example.co.uk") == "example.co.uk"
    assert registrable_domain("not a domain") is None


def test_internationalised_domains_are_converted():
    parts = domain_parts("lumencrеst.example")  # Cyrillic "е"
    assert parts is not None and parts.is_idn and parts.host.startswith("xn--")
    assert parts.sld_unicode == "lumencrеst"


def test_phone_numbers_normalise_to_e164():
    assert normalize_phone("04 000 2000").e164 == "+97140002000"
    assert normalize_phone("+44 7700 900123").e164 == "+447700900123"
    assert normalize_phone("hello") is None


def test_fiction_ranges():
    assert is_reserved_fiction("+447700900123")
    assert is_reserved_fiction("+12025550142")
    assert not is_reserved_fiction("+97140002000")
