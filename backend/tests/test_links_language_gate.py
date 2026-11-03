import pytest

from tessera.errors import SyntheticInputRejected
from tessera.governance.language import has_disclaimer, lint_text
from tessera.governance.links import DFSA_HOMEPAGE, find_dfsa_deep_links, sanitize_link
from tessera.governance.policies import load_language_policy, load_sources_policy
from tessera.governance.synthetic_gate import OfferInput, check_offer_input

from .conftest import REPO_ROOT

SOURCES = load_sources_policy(REPO_ROOT / "policies")
LANGUAGE = load_language_policy(REPO_ROOT / "policies")
# Built from parts so that this file never contains a DFSA deep link itself.
DFSA_DEEP = "https://www.dfsa." + "ae/alerts/some-alert"


# ------------------------------------------------------------------- links


def test_dfsa_links_always_become_the_homepage():
    assert sanitize_link("dfsa_alerts", DFSA_DEEP, SOURCES) == DFSA_HOMEPAGE
    assert sanitize_link("dfsa_register", None, SOURCES) == DFSA_HOMEPAGE


def test_cma_deep_links_are_kept_but_foreign_hosts_are_not():
    page = "https://www.uaecma.gov.ae/en/open-data/licensed-companies.aspx"
    assert sanitize_link("cma_licensed", page, SOURCES) == page
    assert sanitize_link("cma_licensed", "https://elsewhere.example/x", SOURCES) == page


def test_deep_link_detection():
    assert find_dfsa_deep_links(f"see {DFSA_DEEP} now")
    assert not find_dfsa_deep_links("see https://www.dfsa.ae/ or <https://www.dfsa.ae/>")


# ------------------------------------------------------------------- language


def test_verdict_and_advice_terms_are_flagged():
    text = (
        "This is a scam. The site was cloned and is fraudulent. "
        "You should invest now; returns are guaranteed."
    )
    terms = {v.term.lower() for v in lint_text(text, LANGUAGE)}
    assert {"scam", "cloned", "fraudulent", "you should invest", "guaranteed"} <= terms


def test_allowed_proper_nouns_pass():
    assert lint_text("Report it to the Dubai Police Anti-Fraud Center.", LANGUAGE) == []


def test_a_neutral_result_passes():
    text = (
        "Conflicts with the official record. The offer's website domain is named in a DFSA alert "
        "dated 14 January 2026 about impersonation of this firm, and it differs from the official "
        "website on the register."
    )
    assert lint_text(text, LANGUAGE) == []


def test_disclaimer_detection():
    assert has_disclaimer("Result.\n\n" + LANGUAGE.disclaimer, LANGUAGE)
    assert not has_disclaimer("Result only.", LANGUAGE)


# ------------------------------------------------------------------- synthetic gate


def test_real_messages_are_rejected():
    with pytest.raises(SyntheticInputRejected):
        check_offer_input(OfferInput(text="hello", synthetic=False, corpus_item_id="SYN-1"))


def test_synthetic_offers_need_a_corpus_id_or_attestation():
    with pytest.raises(SyntheticInputRejected):
        check_offer_input(OfferInput(text="hello", synthetic=True))


def test_real_looking_personal_data_is_flagged():
    text = (
        "ID 784-1990-1234567-1, card 4111 1111 1111 1111, write to someone@gmail.com, "
        "or call +971 50 000 0001."
    )
    warnings = check_offer_input(OfferInput(text=text, synthetic=True, synthetic_attestation=True))
    assert {"emirates_id", "payment_card", "personal_email", "phone"} <= {w.kind for w in warnings}
    assert all("1111 1111" not in w.excerpt for w in warnings)  # excerpts are redacted


def test_fiction_range_identifiers_pass_quietly():
    text = "WhatsApp +44 7700 900123 or write to desk@lumencrest-capital.example"
    assert check_offer_input(OfferInput(text=text, synthetic=True, corpus_item_id="SYN-2")) == []
