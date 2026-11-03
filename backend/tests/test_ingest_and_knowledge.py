from datetime import date
from pathlib import Path

import pytest

from tessera.config.settings import Mode
from tessera.data.adapters import read_cma_excel, read_handrecord_csv
from tessera.data.ingest import ingest_file, main
from tessera.data.schemas import VaraRegisterRecord
from tessera.data.snapshots import SnapshotStore
from tessera.errors import IngestError, RestrictedDataUnavailable
from tessera.governance.network import uninstall_network_guard
from tessera.knowledge import load_activity_taxonomy, load_rule_cards
from tessera.protocol.evidence import EvidenceKind, mint_evidence

from .conftest import REPO_ROOT, make_settings, write_cma_workbook, write_csv

VARA_HEADER = [
    "record_id",
    "entity_name",
    "status",
    "licence_ref",
    "activities",
    "website",
    "aliases",
    "page_url",
    "recorded_by",
    "recorded_on",
]
DFSA_HEADER = [
    "record_id",
    "firm_name",
    "frn",
    "status",
    "permitted_services",
    "address",
    "website",
    "phone",
    "email_domains",
    "aliases",
    "recorded_by",
    "recorded_on",
]
DFSA_ROW = [
    "D-R-001",
    "Lumen Crest Capital (DIFC) Limited",
    "F000000",
    "authorised",
    "Advising",
    "",
    "lumencrest.example",
    "",
    "",
    "",
    "TEST",
    "2026-11-04",
]


def test_cma_excel_header_detection_with_title_rows_and_arabic(tmp_path: Path):
    records, warnings = read_cma_excel(write_cma_workbook(tmp_path / "export.xlsx"))
    assert [r.record_id for r in records] == ["CMA-L-1001", "CMA-L-1002", "CMA-L-1003"]
    first = records[0]
    assert first.name_ar and first.category == "Category 1"
    assert first.activities == [
        "Trading broker in OTC derivatives and currencies in the spot market",
        "Securities dealing",
    ]
    assert first.raw["Company Name"] == "Falcon Ridge Securities L.L.C."
    assert warnings == []


def test_csv_rows_are_validated_with_line_numbers(tmp_path: Path):
    bad = write_csv(
        tmp_path / "vara.csv",
        VARA_HEADER,
        [["V1", "X", "MAYBE", "", "", "", "", "", "T", "2026-11-04"]],
    )
    with pytest.raises(IngestError, match="line 2"):
        read_handrecord_csv(bad, VaraRegisterRecord)


def test_unknown_columns_are_rejected(tmp_path: Path):
    bad = write_csv(tmp_path / "vara.csv", [*VARA_HEADER, "surprise"], [])
    with pytest.raises(IngestError, match="unknown columns"):
        read_handrecord_csv(bad, VaraRegisterRecord)


def test_snapshots_are_immutable_and_carry_provenance(tmp_path: Path):
    settings = make_settings(tmp_path / "data")
    workbook = write_cma_workbook(tmp_path / "data" / "inbox" / "cma_licensed" / "export.xlsx")
    report = ingest_file(
        "cma_licensed",
        workbook,
        settings=settings,
        retrieved_by="KJ",
        retrieved_on=date(2026, 11, 5),
    )
    manifest = report.manifest
    assert manifest.row_count == 3 and len(manifest.input_sha256) == 64
    assert manifest.source_url == "https://www.uaecma.gov.ae/en/open-data/licensed-companies.aspx"
    assert manifest.snapshot_id.startswith("cma_licensed-20261105-")
    with pytest.raises(IngestError, match="immutable"):
        ingest_file(
            "cma_licensed",
            workbook,
            settings=settings,
            retrieved_by="KJ",
            retrieved_on=date(2026, 11, 5),
        )
    store = SnapshotStore(settings.data_path, restricted_allowed=True)
    assert store.latest("cma_licensed", restricted=False) == manifest


def test_dfsa_files_must_live_in_the_restricted_folder(tmp_path: Path):
    settings = make_settings(tmp_path / "data")
    outside = write_csv(
        tmp_path / "data" / "handrecords" / "register_facts.csv", DFSA_HEADER, [DFSA_ROW]
    )
    with pytest.raises(IngestError, match="must be stored under"):
        ingest_file(
            "dfsa_register",
            outside,
            settings=settings,
            retrieved_by="KJ",
            retrieved_on=date(2026, 11, 6),
        )


def test_dfsa_ingest_is_refused_in_demo_mode(tmp_path: Path):
    settings = make_settings(tmp_path / "data", Mode.RESTRICTED_DEMO)
    inside = write_csv(
        tmp_path / "data" / "restricted" / "dfsa" / "register_facts.csv", DFSA_HEADER, [DFSA_ROW]
    )
    with pytest.raises(RestrictedDataUnavailable):
        ingest_file(
            "dfsa_register",
            inside,
            settings=settings,
            retrieved_by="KJ",
            retrieved_on=date(2026, 11, 6),
        )


def test_dfsa_manifest_records_the_homepage_only(tmp_path: Path):
    settings = make_settings(tmp_path / "data")
    inside = write_csv(
        tmp_path / "data" / "restricted" / "dfsa" / "register_facts.csv", DFSA_HEADER, [DFSA_ROW]
    )
    report = ingest_file(
        "dfsa_register",
        inside,
        settings=settings,
        retrieved_by="KJ",
        retrieved_on=date(2026, 11, 6),
    )
    assert report.manifest.restricted and report.manifest.source_url == "https://www.dfsa.ae/"
    assert "restricted" in report.path.parts
    with pytest.raises(IngestError, match="homepage"):
        ingest_file(
            "dfsa_register",
            inside,
            settings=settings,
            retrieved_by="KJ",
            retrieved_on=date(2026, 11, 7),
            source_url="https://www.dfsa." + "ae/public-register/firms",
        )


def test_cli_ingests_a_file_and_reports_errors(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("TESSERA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TESSERA_MODE", "RESTRICTED_DEMO")
    workbook = write_cma_workbook(tmp_path / "data" / "inbox" / "cma_licensed" / "export.xlsx")
    try:
        assert (
            main(
                [
                    "cma_licensed",
                    str(workbook),
                    "--retrieved-by",
                    "KJ",
                    "--retrieved-on",
                    "2026-11-05",
                ]
            )
            == 0
        )
        assert "Created snapshot cma_licensed-20261105-" in capsys.readouterr().out
        assert (
            main(
                [
                    "vara_register",
                    str(workbook),
                    "--retrieved-by",
                    "KJ",
                    "--retrieved-on",
                    "2026-11-05",
                ]
            )
            == 2
        )
        assert "expects a CSV" in capsys.readouterr().err
    finally:
        uninstall_network_guard()


def test_rule_cards_load_and_cite_dfsa_by_homepage_only():
    cards = load_rule_cards(REPO_ROOT / "knowledge")
    assert {"JUR-01", "JUR-04", "SCOPE-CMA-01", "SCOPE-VARA-01", "CLONE-01"} <= set(cards)
    for card in cards.values():
        for source in card.sources:
            if source.url and "dfsa.ae" in source.url:
                assert source.url == "https://www.dfsa.ae/"


def test_activity_taxonomy_loads():
    taxonomy = load_activity_taxonomy(REPO_ROOT / "knowledge")
    codes = {a.code for a in taxonomy.activities}
    assert {"VA.EXCHANGE", "DER.FX_CFD", "LOAN.CREDIT", "OTHER"} <= codes


def test_restricted_evidence_cannot_hold_identifying_fields():
    with pytest.raises(ValueError, match="derived fields only"):
        mint_evidence(
            case_id="c",
            source_id="dfsa_register",
            kind=EvidenceKind.REGISTER_ENTRY,
            locator="D-R-001",
            fields={"firm_name": "X"},
            minted_by="test",
            restricted=True,
            restricted_ref="dfsa_register:D-R-001",
        )
