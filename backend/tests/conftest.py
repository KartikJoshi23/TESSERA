"""Shared fixtures. Tests never touch the network and never use real data.

All fixture records are FICTIONAL. They use reserved ``.example`` domains and phone ranges reserved
for fiction, and they live only in temporary directories.
"""

from __future__ import annotations

import asyncio
import csv
import json
import socket
from pathlib import Path

import pytest
from openpyxl import Workbook

from tessera.agents.base import Task
from tessera.agents.crew import build_crew, open_case_env
from tessera.blackboard.store import EventStore
from tessera.config.settings import Mode, Settings, find_repo_root
from tessera.data.registry import DataRegistry
from tessera.devdata import install_world
from tessera.governance.masking import MaskingGateway
from tessera.governance.policies import load_sources_policy
from tessera.governance.synthetic_gate import OfferInput
from tessera.llm.client import GuardedLLM
from tessera.llm.testing import ScriptedTransport
from tessera.protocol.common import AgentId
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
    """Ingest the fictional world, through the same path a person would use by hand."""
    settings = make_settings(data_dir)
    install_world(settings)
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


# ---------------------------------------------------------------------- crew helpers


class CrewHarness:
    """One case on an in-memory store, with a scripted model behind the real guarded stack."""

    def __init__(self, settings: Settings, offer_text: str, *replies, case_id: str = "case-1"):
        self.settings = settings
        self.registry = DataRegistry(settings, load_sources_policy(settings.policies_dir))
        self.gateway = MaskingGateway(self.registry.restricted_values())
        self.transport = ScriptedTransport(replies)
        self.store = EventStore()
        self.env = open_case_env(
            store=self.store,
            settings=settings,
            registry=self.registry,
            gateway=self.gateway,
            llm=GuardedLLM(self.transport, self.gateway),
            case_id=case_id,
            offer=OfferInput(text=offer_text, synthetic=True, corpus_item_id="TEST"),
        )
        self.board = self.env.board
        self.crew = build_crew()

    def turn(self, agent: AgentId, kind: str = "initial", round: int = 0):
        return asyncio.run(self.crew[agent].activate(self.env, Task(kind, round=round)))

    def outgoing_text(self) -> str:
        """Everything that left the machine, as one string."""
        return json.dumps(self.transport.payloads, ensure_ascii=False)

    def assert_no_leaks(self) -> None:
        assert self.gateway.leaked_values(self.outgoing_text()) == []


@pytest.fixture
def harness(populated_settings: Settings):
    def build(offer_text: str, *replies, **kwargs) -> CrewHarness:
        return CrewHarness(populated_settings, offer_text, *replies, **kwargs)

    return build
