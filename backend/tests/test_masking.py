import json

from tessera.governance.masking import MaskingGateway, RestrictedValue, classify_value

VALUES = [
    RestrictedValue("Lumen Crest Capital (DIFC) Limited", "firm_name", "dfsa_register:D-R-001"),
    RestrictedValue("lumencrest.example", "domain", "dfsa_register:D-R-001"),
    RestrictedValue("lumencrest-capital.example", "domain", "dfsa_alerts:D-A-007"),
    RestrictedValue("F000000", "reference", "dfsa_register:D-R-001"),
    RestrictedValue("+971 4 000 2000", "phone", "dfsa_register:D-R-001"),
    RestrictedValue("@lumencrest.example", "email", "dfsa_alerts:D-A-007"),
]
OFFER = (
    "I'm Sara from Lumen Crest Capital (DIFC) Limited, regulated by the DFSA (FRN F000000). "
    "Visit https://lumencrest-capital.example/login or www.lumencrest.example, email "
    "ops@lumencrest.example, call 04 000 2000 or +971-4-000-2000."
)


def test_masking_removes_every_restricted_value():
    gateway = MaskingGateway(VALUES)
    masked = gateway.mask(OFFER)
    assert gateway.leaked_values(masked) == []
    for fragment in ("Lumen", "lumencrest", "F000000", "000 2000", "000-2000"):
        assert fragment.lower() not in masked.lower()


def test_generic_name_parts_stay_visible():
    masked = MaskingGateway(VALUES).mask(OFFER)
    assert "(DIFC) Limited" in masked
    assert "regulated by the DFSA" in masked


def test_placeholders_are_deterministic_and_restorable():
    first = MaskingGateway(VALUES).mask(OFFER)
    second = MaskingGateway(list(reversed(VALUES))).mask(OFFER)
    assert first == second
    gateway = MaskingGateway(VALUES)
    assert gateway.unmask(gateway.mask("FRN F000000")) == "FRN F000000"


def test_nested_payloads_are_masked():
    gateway = MaskingGateway(VALUES)
    payload = {"messages": [{"role": "user", "content": OFFER}], "n": 1, "tools": ("x",)}
    masked = gateway.mask_payload(payload)
    assert gateway.leaked_values(json.dumps(masked, ensure_ascii=False)) == []
    assert masked["n"] == 1 and masked["tools"] == ("x",)


def test_short_generic_names_are_masked_only_in_full():
    gateway = MaskingGateway([RestrictedValue("Apex Ltd", "firm_name", "x")])
    masked = gateway.mask("The apex of the market. Apex Ltd is listed.")
    assert "apex of the market" in masked
    assert "Apex Ltd" not in masked


def test_an_empty_gateway_changes_nothing():
    assert MaskingGateway([]).mask(OFFER) == OFFER


def test_value_classification():
    assert classify_value("ops@desk.example") == "email"
    assert classify_value("@desk.example") == "domain"
    assert classify_value("+44 7700 900123") == "phone"
    assert classify_value("desk.example") == "domain"
