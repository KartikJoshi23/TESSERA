"""Shared fixtures. Tests never touch the network and never use real data.

All fixture records are FICTIONAL. They use reserved ``.example`` domains and phone ranges reserved
for fiction, and they live only in temporary directories.
"""

from __future__ import annotations

import csv
import socket
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from tessera.config.settings import Mode, Settings, find_repo_root
from tessera.data.ingest import ingest_file
from tessera.tools.context import ToolContext

REPO_ROOT = find_repo_root(Path(__file__))
_LOCAL_HOSTS = {None, "localhost", "127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to resolve or connect to a non-local host."""
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host in _LOCAL_HOSTS:
            return real_getaddrinfo(host, *args, **kwargs)
        raise RuntimeError(f"network access attempted in tests: DNS lookup of {host!r}")

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOCAL_HOSTS:
            return real_connect(self, address)
        raise RuntimeError(f"network access attempted in tests: connect to {address!r}")

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


def make_settings(data_dir: Path, mode: Mode = Mode.RESEARCH_INTERNAL) -> Settings:
    return Settings(mode=mode, root=REPO_ROOT, data_dir=data_dir)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


CMA_HEADER = [
    "Company Name",
    "اسم الشركة",
    "License No",
    "Category",
    "Activities",
    "Status",
    "Emirate",
    "Website",
    "Phone",
    "Email",
]
CMA_ROWS = [
    [
        "Falcon Ridge Securities L.L.C.",
        "فالكون ريدج للأوراق المالية ذ.م.م",
        "CMA-L-1001",
        "Category 1",
        "Trading broker in OTC derivatives and currencies in the spot market; Securities dealing",
        "Active",
        "Dubai",
        "www.falconridge.example",
        "+971 4 000 1001",
        "info@falconridge.example",
    ],
    [
        "Oasis Bridge Financial Consultancy LLC",
        None,
        "CMA-L-1002",
        "Category 5",
        "Introduction; Promotion; Financial consultation",
        "Active",
        "Abu Dhabi",
        "https://oasisbridge.example",
        "+971 2 000 1002",
        None,
    ],
    [
        "Desert Lantern Capital PJSC",
        "",
        "CMA-L-1003",
        "Category 2",
        "Fund management",
        "Active",
        "Sharjah",
        "desertlantern.example",
        None,
        None,
    ],
]


def write_cma_workbook(path: Path) -> Path:
    """A fictional CMA-style export with title rows above the header, as real exports often have."""
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Licensed Companies (FICTIONAL TEST FIXTURE)"])
    sheet.append([])
    sheet.append(CMA_HEADER)
    for row in CMA_ROWS:
        sheet.append(row)
    workbook.save(path)
    return path


def populate(data_dir: Path) -> Settings:
    """Ingest fictional fixtures for every Phase 1 source, as a person would by hand."""
    settings = make_settings(data_dir)
    on = date(2026, 11, 4)

    def run(source_id: str, file_path: Path) -> None:
        ingest_file(source_id, file_path, settings=settings, retrieved_by="TEST", retrieved_on=on)

    run("cma_licensed", write_cma_workbook(data_dir / "inbox" / "cma_licensed" / "export.xlsx"))
    run(
        "cma_warnings",
        write_csv(
            data_dir / "handrecords" / "cma_warnings.csv",
            [
                "record_id",
                "entity_name",
                "warning_date",
                "domains",
                "phones",
                "emails",
                "notes",
                "page_url",
                "recorded_by",
                "recorded_on",
            ],
            [
                [
                    "CMA-W-0001",
                    "Golden Dune Trading Platform",
                    "2026-02-10",
                    "goldendune-fx.example",
                    "+44 7700 900456",
                    "support@goldendune-fx.example",
                    "Fictional fixture",
                    "",
                    "TEST",
                    "2026-11-04",
                ]
            ],
        ),
    )
    run(
        "vara_register",
        write_csv(
            data_dir / "handrecords" / "vara_register.csv",
            [
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
            ],
            [
                [
                    "VARA-R-0001",
                    "Coral Ledger Exchange FZE",
                    "LICENSED",
                    "VL/26/01/001",
                    "Exchange Services;Broker-Dealer Services",
                    "coralledger.example",
                    "Coral Ledger",
                    "",
                    "TEST",
                    "2026-11-04",
                ],
                [
                    "VARA-R-0002",
                    "Saffron Chain Custody FZCO",
                    "IPA",
                    "IPA/26/02/003",
                    "Custody Services",
                    "saffronchain.example",
                    "",
                    "",
                    "TEST",
                    "2026-11-04",
                ],
            ],
        ),
    )
    run(
        "vara_unlicensed",
        write_csv(
            data_dir / "handrecords" / "vara_unlicensed.csv",
            [
                "record_id",
                "entity_name",
                "domains",
                "date_listed",
                "page_url",
                "recorded_by",
                "recorded_on",
            ],
            [
                [
                    "VARA-U-0001",
                    "Mirage Coin Hub",
                    "miragecoinhub.example;mirage-coin.example",
                    "2026-01-13",
                    "",
                    "TEST",
                    "2026-11-04",
                ]
            ],
        ),
    )
    run(
        "dfsa_register",
        write_csv(
            data_dir / "restricted" / "dfsa" / "register_facts.csv",
            [
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
            ],
            [
                [
                    "D-R-001",
                    "Lumen Crest Capital (DIFC) Limited",
                    "F000000",
                    "authorised",
                    "Advising on Financial Products;Arranging Deals in Investments",
                    "Gate Village, DIFC, Dubai",
                    "lumencrest.example",
                    "+971 4 000 2000",
                    "lumencrest.example",
                    "",
                    "TEST",
                    "2026-11-04",
                ]
            ],
        ),
    )
    run(
        "dfsa_alerts",
        write_csv(
            data_dir / "restricted" / "dfsa" / "alert_facts.csv",
            [
                "record_id",
                "alert_date",
                "category",
                "firm_named",
                "frn_named",
                "contact_points_named",
                "legitimate_contacts_stated",
                "recorded_by",
                "recorded_on",
            ],
            [
                [
                    "D-A-007",
                    "2026-01-14",
                    "impersonated_authorised_firm",
                    "Lumen Crest Capital (DIFC) Limited",
                    "F000000",
                    "lumencrest-capital.example;+44 7700 900789",
                    "@lumencrest.example",
                    "TEST",
                    "2026-11-04",
                ]
            ],
        ),
    )
    return settings


@pytest.fixture
def populated_settings(tmp_path: Path) -> Settings:
    return populate(tmp_path / "data")


@pytest.fixture
def ctx(populated_settings: Settings) -> ToolContext:
    return ToolContext.create("case-0001", populated_settings)


@pytest.fixture
def demo_ctx(populated_settings: Settings) -> ToolContext:
    demo = make_settings(populated_settings.data_path, Mode.RESTRICTED_DEMO)
    return ToolContext.create("case-0001", demo)


@pytest.fixture
def empty_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext.create("case-empty", make_settings(tmp_path / "empty-data"))
