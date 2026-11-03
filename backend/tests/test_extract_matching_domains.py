from tessera.protocol.contacts import ContactKind, ContactRole
from tessera.tools.domain_analysis import compare_domains
from tessera.tools.extract import extract_contact_points
from tessera.tools.matching import match_name

WORKED_EXAMPLE = (
    "Good evening! I'm Sara from Lumen Crest Capital (DIFC) Limited, regulated by the DFSA "
    "(FRN F000000). Our crypto desk offers BTC trading and USDT staking with 3% weekly returns. "
    "Office: Gate Village, DIFC, Dubai. Open your account at lumencrest-capital.example and "
    "message me on WhatsApp +44 7700 900123. Deposits in USDT (TRC20) to the wallet we send you."
)


def by_kind(text):
    groups: dict[ContactKind, list] = {}
    for cp in extract_contact_points(text):
        groups.setdefault(cp.kind, []).append(cp)
    return groups


# ------------------------------------------------------------------- extraction


def test_worked_example_contact_points():
    points = extract_contact_points(WORKED_EXAMPLE)
    groups = by_kind(WORKED_EXAMPLE)
    domain = groups[ContactKind.DOMAIN][0]
    assert domain.normalized == "lumencrest-capital.example"
    assert domain.role is ContactRole.DECIDING
    whatsapp = groups[ContactKind.WHATSAPP][0]
    assert whatsapp.normalized == "+447700900123" and whatsapp.role is ContactRole.DECIDING
    assert groups[ContactKind.LICENCE_REF][0].normalized == "F000000"
    address = groups[ContactKind.ADDRESS][0]
    assert address.detail["zone"] == "DIFC" and address.role is ContactRole.REPORTED
    assert [p.cp_id for p in points] == [f"cp{i}" for i in range(1, len(points) + 1)]
    for point in points:
        assert WORKED_EXAMPLE[point.start : point.end] == point.raw


def test_urls_emails_short_links_ibans_and_wallets():
    text = (
        "Visit https://www.falconridge.example/open, email info@falconridge.example, or tap "
        "bit.ly/3xYz12. Pay to IBAN AE07 0331 2345 6789 0123 456 or ETH 0x" + "a" * 40 + ". "
        "Telegram: t.me/falcon_desk"
    )
    groups = by_kind(text)
    assert groups[ContactKind.URL][0].normalized == "falconridge.example"
    assert groups[ContactKind.EMAIL][0].detail["domain"] == "falconridge.example"
    assert groups[ContactKind.SHORT_LINK][0].role is ContactRole.NOT_COMPARABLE
    iban = groups[ContactKind.IBAN][0]
    assert iban.normalized == "AE070331234567890123456" and iban.detail["valid"] == "true"
    assert groups[ContactKind.WALLET][0].detail["chain"] == "ETH"
    assert groups[ContactKind.TELEGRAM][0].role is ContactRole.REPORTED
    assert ContactKind.PHONE not in groups  # IBAN digits are not mistaken for a phone number


def test_ordinary_text_yields_no_domains():
    groups = by_kind("Returns of 3.5% e.g. weekly. Contact Mr.Smith at the office.")
    assert ContactKind.DOMAIN not in groups and ContactKind.URL not in groups


# ------------------------------------------------------------------- name matching

CANDIDATES = [
    ("R1", ["Falcon Ridge Securities L.L.C.", "فالكون ريدج للأوراق المالية ذ.م.م"]),
    ("R2", ["Oasis Bridge Financial Consultancy LLC"]),
    ("R3", ["Coral Ledger Exchange FZE", "Coral Ledger"]),
]


def match(query):
    return match_name(query, CANDIDATES, tau1=92, tau2=90, partial_min_length=6)


def test_exact_match_ignores_case_and_legal_form():
    best = match("FALCON RIDGE SECURITIES LLC")[0]
    assert (best.record_id, best.match_type) == ("R1", "exact")


def test_alias_and_arabic_matches():
    assert match("Coral Ledger")[0].match_type == "alias"
    arabic = match("فالكون ريدج للاوراق المالية")
    assert arabic and arabic[0].record_id == "R1"


def test_typos_match_fuzzily_and_unrelated_names_do_not():
    best = match("Falcon Rdge Securities")[0]
    assert best.record_id == "R1" and best.match_type in {"fuzzy", "partial"}
    assert match("Mirage Coin Hub") == []


# ------------------------------------------------------------------- look-alike domains

T = {"max_edit_distance": 2, "min_similarity": 0.85, "min_brand_length": 5}


def test_same_domain_is_not_a_lookalike():
    result = compare_domains("https://www.falconridge.example/x", "falconridge.example", **T)
    assert result.same_registrable and not result.lookalike


def test_added_word():
    result = compare_domains("lumencrest-capital.example", "lumencrest.example", **T)
    assert result.lookalike and "added_word" in result.patterns
    assert result.added_tokens == ("capital",)


def test_typo_transposition():
    result = compare_domains("falconrigde.example", "falconridge.example", **T)
    assert result.lookalike and result.edit_distance == 1


def test_homoglyph():
    result = compare_domains("falconrіdge.example", "falconridge.example", **T)  # Cyrillic "і"
    assert result.lookalike and "homoglyph" in result.patterns and result.offer_is_idn


def test_tld_swap():
    result = compare_domains("falconridge.test", "falconridge.example", **T)
    assert result.lookalike and "tld_swap" in result.patterns


def test_abbreviation():
    result = compare_domains("orbitcapltd.example", "orbitcapitalltd.example", **T)
    assert result.lookalike and "truncation_or_abbreviation" in result.patterns


def test_unrelated_and_non_domains():
    assert not compare_domains("coralledger.example", "falconridge.example", **T).lookalike
    result = compare_domains("not a domain", "falconridge.example", **T)
    assert not result.lookalike and result.patterns == ("not_comparable",)
