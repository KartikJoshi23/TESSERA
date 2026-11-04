"""Prompts agree with the schemas and the knowledge base; the smoke set is sound and fictional."""

import json
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from tessera.agents.base import Task
from tessera.agents.crew import prompt_library
from tessera.agents.schemas import (
    CloneCheckOutput,
    JurisdictionOutput,
    ReconcilerRoundOutput,
    ReconcilerSynthesisOutput,
    RegulatorOutput,
    SingleAgentOutput,
    VerifierOutput,
)
from tessera.agents.smoke import main as smoke_main
from tessera.agents.smoke import select_cases
from tessera.config.settings import Settings
from tessera.devdata import install_world, load_smoke_cases
from tessera.errors import PolicyError
from tessera.governance.policies import load_decision_policy
from tessera.knowledge import load_activity_taxonomy, load_rule_cards
from tessera.llm.client import CachingTransport
from tessera.llm.prompts import PromptLibrary
from tessera.llm.testing import ScriptedTransport, chat_reply
from tessera.protocol.case import strip_gold
from tessera.protocol.common import REGULATORS, AgentId, ResultCode

from .conftest import REPO_ROOT, make_settings

PROMPTS = REPO_ROOT / "backend" / "prompts" / "v1"
OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "jurisdiction": JurisdictionOutput,
    "regulator": RegulatorOutput,
    "clone_check": CloneCheckOutput,
    "reconciler_round": ReconcilerRoundOutput,
    "reconciler_synthesis": ReconcilerSynthesisOutput,
    "verifier": VerifierOutput,
    "single_agent": SingleAgentOutput,
}
ALL_PROMPTS = sorted(path.stem for path in PROMPTS.glob("*.md"))
CASES = load_smoke_cases(REPO_ROOT)


def json_example(name: str) -> dict:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    block = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    assert block, f"{name}.md has no output-shape example"
    return json.loads(block.group(1))


@pytest.mark.parametrize(("name", "model"), OUTPUT_MODELS.items())
def test_every_example_is_valid_for_its_schema(name, model):
    example = json_example(name)
    model.model_validate(example)
    # Output models ignore unknown fields, so a misspelt field would otherwise pass unnoticed.
    assert set(example) <= set(model.model_fields)


@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_prompts_cite_only_rules_that_exist(name):
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    known = load_rule_cards(REPO_ROOT / "knowledge")
    cited = set(re.findall(r"\b(?:JUR|CLONE|SCOPE-[A-Z]+)-\d{2}\b", text))
    assert cited <= set(known)


@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_prompts_use_only_activity_codes_that_exist(name):
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    known = {a.code for a in load_activity_taxonomy(REPO_ROOT / "knowledge").activities}
    assert set(re.findall(r"\b(?:VA|SEC|DER|FUND|BANK|LOAN|PAY)\.[A-Z_]+\b", text)) <= known


@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_prompts_hold_no_case_data_or_links(name):
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    assert "http" not in text and "gold_" not in text


def test_a_missing_prompt_is_a_clear_error(tmp_path):
    with pytest.raises(PolicyError, match="missing prompt file"):
        PromptLibrary(tmp_path).read("nothing")


@pytest.mark.parametrize(
    ("agent", "kind"),
    [
        (AgentId.JUR, "initial"),
        (AgentId.CMA, "initial"),
        (AgentId.DFSA, "initial"),
        (AgentId.VARA, "initial"),
        (AgentId.CLN, "initial"),
        (AgentId.REC, "challenge_round"),
        (AgentId.REC, "synthesis"),
    ],
)
def test_system_prompts_are_byte_identical_across_cases(harness, agent, kind):
    first = harness("Trade FX with Falcon Ridge Securities at falconridge.example.")
    second = harness("Earn with Coral Ledger Exchange: coralledger.example.", case_id="case-2")
    task = Task(kind)
    one = first.crew[agent].spec(first.env, task).system
    other = second.crew[agent].spec(second.env, task).system
    assert one.text == other.text and one.sha256 == other.sha256


def test_each_agent_gets_its_own_system_prompt(harness):
    setup = harness("An offer at falconridge.example.")
    hashes = {
        setup.crew[agent].spec(setup.env, Task("initial")).system.sha256
        for agent in (AgentId.JUR, AgentId.CMA, AgentId.DFSA, AgentId.VARA, AgentId.CLN)
    }
    assert len(hashes) == 5


def test_regulators_get_only_their_own_scope_cards(harness):
    setup = harness("An offer at falconridge.example.")
    text = setup.crew[AgentId.VARA].spec(setup.env, Task("initial")).system.text
    assert "SCOPE-VARA-01" in text and "SCOPE-CMA-01" not in text
    # The Reconciler and Verifier need every card to check the others' work.
    full = setup.crew[AgentId.REC].spec(setup.env, Task("synthesis")).system.text
    assert "SCOPE-VARA-01" in full and "SCOPE-CMA-01" in full


def test_only_the_agents_with_lookups_hold_tools(harness):
    setup = harness("An offer at falconridge.example.")
    assert setup.crew[AgentId.REC].tool_names == ()
    assert setup.crew[AgentId.VER].tool_names == ()
    assert setup.crew[AgentId.JUR].tool_names == ()
    assert "dfsa_facts_lookup" not in setup.crew[AgentId.CMA].tool_names
    assert "cma_register_lookup" not in setup.crew[AgentId.DFSA].tool_names


def test_the_library_is_tied_to_the_repository(populated_settings):
    library = prompt_library(populated_settings)
    assert library.version == "v1" and library.directory == PROMPTS


# ------------------------------------------------------------------- the smoke set


def test_the_smoke_set_has_all_three_results():
    counts = {code: sum(c.gold_label is code for c in CASES) for code in ResultCode}
    assert len(CASES) == 25 and all(counts.values())
    assert len({case.id for case in CASES}) == 25


def test_gold_reasons_exist_in_the_policy_and_fit_the_label():
    policy = load_decision_policy(REPO_ROOT / "policies")
    hard = {rule.id for rule in policy.hard_conflicts}
    unverified = {rule.id for rule in policy.unverified_reasons}
    for case in CASES:
        allowed = {
            ResultCode.CONFLICTS: hard,
            ResultCode.UNVERIFIED: unverified,
            ResultCode.CONSISTENT: set(),
        }[case.gold_label]
        assert set(case.gold_reasons) <= allowed, case.id
        assert bool(case.gold_reasons) == (case.gold_label is not ResultCode.CONSISTENT), case.id
        assert set(case.gold_relevant) <= set(REGULATORS), case.id


def test_every_domain_in_the_smoke_set_is_reserved_for_fiction():
    """The one exception is a short link, which is never opened: its target is the unknown."""
    domain = re.compile(r"\b[a-z0-9][a-z0-9.-]*\.[a-z]{2,}\b", re.IGNORECASE)
    for case in CASES:
        for found in domain.findall(case.text):
            assert found.endswith(".example") or found == "bit.ly", (case.id, found)


def test_gold_never_reaches_an_offer():
    item = {"id": "S", "text": "x", "gold_label": "CONFLICTS", "gold_reasons": ["HC1"]}
    assert strip_gold(item) == {"id": "S", "text": "x"}
    offer = CASES[0].offer()
    assert offer.synthetic and "CONSISTENT" not in offer.model_dump_json()


def test_cases_can_be_selected():
    assert [c.id for c in select_cases(CASES, "S09, S01", None)] == ["S01", "S09"]
    assert [c.id for c in select_cases(CASES, None, 2)] == ["S01", "S02"]


# ------------------------------------------------------------------- installing the world


def test_the_fictional_world_cannot_be_installed_into_the_real_data_folder():
    with pytest.raises(ValueError, match="separate data folder"):
        install_world(Settings(root=REPO_ROOT))


def test_installing_twice_keeps_the_same_snapshots(tmp_path):
    settings = make_settings(tmp_path / "data")
    first = install_world(settings)
    second = install_world(settings)
    assert [m.snapshot_id for m in first] == [m.snapshot_id for m in second]


# ------------------------------------------------------------------- tessera-smoke


class _FakeHttp:
    closed = False

    async def aclose(self) -> None:
        self.closed = True


def stub_stack(monkeypatch, replies):
    """Run the smoke command against scripted replies, with no key and no network."""
    http = _FakeHttp()
    transport = ScriptedTransport(replies)
    built = {}

    def fake_build(settings, models, *, cache_path=None, notify=None):
        built.update(cache=cache_path, mode=settings.mode, data=settings.data_path)
        return (CachingTransport(transport, cache_path) if cache_path else transport), http

    monkeypatch.setattr("tessera.agents.smoke.build_live_transport", fake_build)
    return transport, http, built


def test_smoke_runs_in_its_own_folder_and_reports_what_failed(monkeypatch, tmp_path, capsys):
    _, http, built = stub_stack(monkeypatch, [chat_reply("no")] * 20)
    code = smoke_main(["--cases", "S01", "--run-dir", str(tmp_path), "--no-cache"])
    assert code == 0 and http.closed
    assert Path(built["data"]) == (tmp_path / "data").resolve()
    output = capsys.readouterr().out
    assert "JUR failed: invalid_output" in output and "matches gold: 0/1" in output
    assert "say nothing about final performance" in output


def test_smoke_stops_at_its_request_cap(monkeypatch, tmp_path, capsys):
    stub_stack(monkeypatch, [chat_reply("no")] * 40)
    args = ["--limit", "3", "--max-requests", "1", "--run-dir", str(tmp_path), "--no-cache"]
    assert smoke_main(args) == 0
    assert "request cap reached after 1 case(s)" in capsys.readouterr().out


def test_smoke_can_run_a_condition_with_no_model(monkeypatch, tmp_path, capsys):
    transport, _, _ = stub_stack(monkeypatch, [])
    code = smoke_main(
        ["--cases", "S15", "--condition", "RULES-ONLY", "--run-dir", str(tmp_path), "--no-cache"]
    )
    assert code == 0 and transport.payloads == []
    assert "S15" in capsys.readouterr().out


def test_smoke_explains_a_missing_key(monkeypatch, tmp_path, capsys):
    def no_key(*args, **kwargs):
        raise PolicyError("NVIDIA_API_KEY is not set.")

    monkeypatch.setattr("tessera.agents.smoke.build_live_transport", no_key)
    assert smoke_main(["--run-dir", str(tmp_path)]) == 2
    assert "NVIDIA_API_KEY is not set" in capsys.readouterr().err
