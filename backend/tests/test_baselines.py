"""The systems the crew is compared with: RULES-ONLY and the single-agent conditions."""

import asyncio
import json
from typing import Any

import pytest

from tessera.agents.crew import build_stack
from tessera.baseline.rules_only import RulesOnly, read_offer
from tessera.blackboard.board import Blackboard
from tessera.blackboard.store import EventStore
from tessera.config.settings import Mode
from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.errors import PolicyError
from tessera.experiment import (
    SC5_RUNS,
    SC5_TEMPERATURE,
    _Vote,
    _winner,
    model_for,
    models_for,
    open_condition,
    run_opened,
)
from tessera.governance.language import lint_text
from tessera.llm.config import load_models_policy
from tessera.llm.testing import ScriptedTransport, chat_reply, json_reply, tool_reply
from tessera.llm.types import PermanentLLMError
from tessera.protocol.case import SystemCondition
from tessera.protocol.claims import DECISIVE_TYPES
from tessera.protocol.common import REGULATORS, AgentId, ResultCode
from tessera.protocol.contacts import ContactRole
from tessera.protocol.findings import FindingStatus
from tessera.protocol.results import FinalResult
from tessera.reporting.report import render_report

from .conftest import REPO_ROOT, make_settings
from .scripted import agent_of, tool_results

CASES = {case.id: case for case in load_smoke_cases(REPO_ROOT)}
MODELS = load_models_policy(REPO_ROOT / "policies")
FIRM = "Falcon Ridge Securities L.L.C."
LOOKALIKE = "falconrigde.example"
OFFICIAL = "falconridge.example"


class Bench:
    """Every case opened and run the way the commands and the API do it."""

    def __init__(self, settings: Any, replies: Any = ()) -> None:
        self.transport = ScriptedTransport(replies)
        self.store = EventStore()
        self.stack = build_stack(settings, self.transport, self.store, MODELS)

    def run(self, key: str, condition: SystemCondition):
        offer = CASES[key].offer()
        env = open_condition(self.stack, key, offer, condition=condition)
        final = asyncio.run(run_opened(self.stack, env, offer, today=FICTION_DATE))
        return env, final


@pytest.fixture
def bench(populated_settings):
    def build(*replies: Any) -> Bench:
        return Bench(populated_settings, replies)

    return build


# ------------------------------------------------------------------- RULES-ONLY


@pytest.mark.parametrize("key", sorted(CASES))
def test_rules_only_finishes_every_case_with_no_model(bench, key):
    setup = bench()
    env, final = setup.run(key, SystemCondition.RULES_ONLY)
    assert setup.transport.payloads == []
    assert final.detail["requests"] == 0
    assert not lint_text(final.explanation, env.language)
    if final.result is ResultCode.UNVERIFIED:
        assert final.unverified_reasons
    # Rules read keywords, so they can miss things, but they must not reassure falsely.
    if final.result is ResultCode.CONSISTENT:
        assert CASES[key].gold_label is ResultCode.CONSISTENT


def test_rules_only_reads_an_offer_by_keyword_and_pattern(harness):
    reading = read_offer(harness(CASES["S09"].offer().text).env)
    assert {code for code, _ in reading.activities} >= {"VA.EXCHANGE", "VA.YIELD"}
    assert reading.firm == "Lumen Crest Capital (DIFC) Limited"
    assert reading.regulator[0] == "DFSA"
    assert reading.reference == "F000000"
    assert reading.payment == {"wallet_requested": True}
    assert reading.relevant["DFSA"] == "primary"


def test_rules_only_reads_a_licence_claim_written_either_way_round(harness):
    claim = read_offer(harness(CASES["S11"].offer().text).env).regulator
    assert claim == ("VARA", "licensed VARA")
    capitalised = read_offer(harness("Licensed by VARA. See azuredhow.example.").env)
    assert capitalised.regulator[0] == "VARA"


def test_rules_only_keeps_the_strongest_status_when_an_offer_spans_groups(harness):
    text = "Trade forex and crypto trading from Gate Village, DIFC."
    reading = read_offer(harness(text).env)
    assert reading.relevant == {"DFSA": "primary"}


def test_rules_only_keeps_an_unknown_regulators_name(harness):
    reading = read_offer(harness(CASES["S25"].offer().text).env)
    assert reading.regulator[0] == "UAE Financial Trade Authority"


def test_a_free_zone_regulator_needs_a_sign_of_its_zone(harness):
    """With no zone signal, nothing makes the DFSA or the FSRA relevant (F63)."""
    silent = read_offer(harness("Forex trading with Silver Palm at silverpalm.example.").env)
    assert set(silent.relevant) == {"CMA"}
    pointed = read_offer(harness("Forex trading from Al Maryah Island, ADGM.").env)
    assert pointed.relevant.get("FSRA") == "primary"


def test_rules_only_cites_a_card_that_fits_any_cma_category(harness):
    """Desert Lantern is Category 2, so a card about Category 5 says nothing about it (F64)."""
    env = harness("Desert Lantern Capital offers fund management.").env
    env.belt.execute(
        "cma_register_lookup",
        json.dumps({"name": "Desert Lantern Capital"}),
        allowed=("cma_register_lookup",),
        actor=AgentId.CMA,
        round=1,
    )
    entry = next(r for r in env.board.evidence.values() if r.fields.get("activities"))
    assert entry.fields["category"] == "Category 2"
    crew = RulesOnly(env, read_offer(env))
    assert crew.scope_of("CMA", "FUND.MGMT", entry) == ("yes", "SCOPE-CMA-03")
    assert crew.scope_of("CMA", "SEC.BROKERAGE", entry) == ("no", "SCOPE-CMA-03")


def test_rules_only_finds_a_beneficiary(harness):
    reading = read_offer(harness(CASES["S17"].offer().text).env)
    assert reading.payment["beneficiary"].startswith("XYZ General Trading")


def test_rules_only_is_most_useful_on_list_hits(bench):
    env, final = bench().run("S12", SystemCondition.RULES_ONLY)
    assert final.result is ResultCode.CONFLICTS
    assert {"HC1", "HC2"} <= set(final.hard_conflicts)
    assert render_report(env.board, env.ctx).claims


def test_rules_only_stops_at_what_a_model_is_needed_for(bench):
    """It sees no firm, so it cannot match one, and says so."""
    _, final = bench().run("S20", SystemCondition.RULES_ONLY)
    assert final.result is ResultCode.UNVERIFIED


def test_rules_only_loses_no_dfsa_detail(bench):
    setup = bench()
    env, _ = setup.run("S09", SystemCondition.RULES_ONLY)
    stored = json.dumps([e.payload for e in setup.store.read("S09")], ensure_ascii=False)
    assert env.board.gateway.leaked_values(stored) == []
    assert "2026-01-14" not in stored


def test_rules_only_in_demo_mode_reports_the_gap(populated_settings):
    demo = make_settings(populated_settings.data_path, Mode.RESTRICTED_DEMO)
    env, final = Bench(demo).run("S04", SystemCondition.RULES_ONLY)
    assert final.result is ResultCode.UNVERIFIED
    gaps = env.board.live_findings("coverage_gap")
    assert "DFSA" in {gap.assertion.regulator for gap in gaps}


# ------------------------------------------------------------------- one agent


def lookups() -> dict[str, Any]:
    return tool_reply(
        ("cma_register_lookup", {"name": FIRM}),
        ("cma_warnings_lookup", {"domain": LOOKALIKE}),
        ("vara_register_lookup", {"name": FIRM}),
        ("vara_unlicensed_lookup", {"domain": LOOKALIKE}),
        ("dfsa_facts_lookup", {"name": FIRM, "domain": LOOKALIKE}),
    )


def comparisons(payload: dict[str, Any]) -> dict[str, Any]:
    entry = tool_results(payload)[0]["matches"][0]["evidence_id"]
    return tool_reply(
        ("official_contacts_for", {"evidence_id": entry}),
        ("reverse_contact_lookup", {"value": LOOKALIKE}),
        (
            "compare_domain",
            {
                "offer_domain": LOOKALIKE,
                "official_domain": OFFICIAL,
                "official_evidence_id": entry,
            },
        ),
    )


def relevance() -> list[dict[str, Any]]:
    return [
        {
            "regulator": regulator,
            "status": "primary" if regulator == "CMA" else "not_indicated",
            "rule_ids": ["JUR-04"] if regulator == "CMA" else [],
        }
        for regulator in REGULATORS
    ]


def final_object(payload: dict[str, Any], **changes: Any) -> dict[str, Any]:
    results = tool_results(payload)
    cma, _, vara = results[:3]
    entry = cma["matches"][0]["evidence_id"]
    compared = results[7]
    return {
        "activities": [{"code": "DER.FX_CFD", "quote": "FX account"}],
        "zone_signals": [],
        "claims": [{"kind": "firm_name", "value": FIRM, "quote": FIRM}],
        "targets_uae_clients": "unclear",
        "relevance": relevance(),
        "regulators": [
            {
                "regulator": "CMA",
                "register_matches": [
                    {
                        "evidence_id": entry,
                        "match_type": cma["matches"][0]["match_type"],
                        "status": "active",
                        "rationale": "The CMA register lists this firm.",
                    }
                ],
                "scope": [
                    {
                        "entity_evidence_id": entry,
                        "activity": "DER.FX_CFD",
                        "covered": "yes",
                        "rule_id": "SCOPE-CMA-02",
                        "rationale": "The licence covers this activity.",
                    }
                ],
            },
            {"regulator": "VARA", "no_match_evidence_ids": [vara["no_match_evidence_id"]]},
        ],
        "contacts": [
            {
                "cp_id": "cp1",
                "status": "lookalike_of_official",
                "official_evidence_id": entry,
                "evidence_ids": [compared["evidence_id"]],
                "rationale": "The domain resembles the official one.",
            }
        ],
        "payment": None,
        "result": "CONFLICTS",
        "hard_conflicts": ["HC5"],
        "unverified_reasons": [],
        "explanation": "The offer's website domain resembles the firm's official domain.",
        **changes,
    }


def single_agent_replies(**changes: Any) -> list[Any]:
    return [lookups(), comparisons, lambda payload: json_reply(final_object(payload, **changes))]


def approve(payload: dict[str, Any]) -> dict[str, Any]:
    claims = json.loads(
        payload["messages"][1]["content"].split("<case_data>\n", 1)[1].split("\n</case_data>", 1)[0]
    )["claims"]
    return json_reply(
        {"entailment": [{"claim_index": c["claim_index"], "verdict": "supported"} for c in claims]}
    )


def test_one_agent_does_every_job_on_the_same_blackboard(bench):
    setup = bench(*single_agent_replies())
    env, final = setup.run("S15", SystemCondition.SA_BASE)
    board = env.board
    assert final.result is ResultCode.CONFLICTS and final.hard_conflicts == ("HC5",)
    assert final.detail["requests"] == 3
    assert {f.author for f in board.findings.values()} == {AgentId.SA}
    for kind in ("activity", "register_match", "licence_scope", "contact_assessment"):
        assert board.live_findings(kind), kind
    assert board.proposals[-1].author is AgentId.SA
    assert board.verifier_reports == []


def test_a_single_agent_turn_is_logged_like_any_other(bench):
    setup = bench(*single_agent_replies())
    env, _ = setup.run("S15", SystemCondition.SA_BASE)
    kinds = {event.type for event in setup.store.read("S15")}
    assert {"agent.activated", "llm.response", "tool.called", "evidence.minted"} <= kinds
    assert {"finding.posted", "proposal.created", "result.finalized"} <= kinds
    replayed = Blackboard.replay(setup.store, "S15", gateway=env.board.gateway)
    assert replayed.snapshot() == env.board.snapshot()


def test_the_agents_reasons_become_its_claims(bench):
    env, _ = bench(*single_agent_replies()).run("S15", SystemCondition.SA_BASE)
    claims = env.board.proposals[-1].claims
    texts = [claim.text for claim in claims]
    assert "The domain resembles the official one." in texts
    assert all(claim.evidence_ids for claim in claims)
    # A finding with no reason gets a plain sentence, and judgements are not claims.
    assert "The CMA entry has the status active." in texts
    assert {claim.assertion.type for claim in claims} <= DECISIVE_TYPES
    assert render_report(env.board, env.ctx).claims


def test_one_agent_skipping_a_regulators_lists_is_a_gap(bench):
    def skips_dfsa() -> dict[str, Any]:
        return tool_reply(
            ("cma_register_lookup", {"name": FIRM}),
            ("cma_warnings_lookup", {"domain": LOOKALIKE}),
        )

    def final(payload: dict[str, Any]) -> dict[str, Any]:
        return json_reply(
            {
                "targets_uae_clients": "unclear",
                "relevance": relevance(),
                "contacts": [{"cp_id": "cp1", "status": "not_comparable"}],
                "result": "UNVERIFIED",
                "unverified_reasons": ["U3"],
                "explanation": "The records were compared.",
            }
        )

    env, _ = bench(skips_dfsa(), final).run("S15", SystemCondition.SA_BASE)
    gaps = {f.assertion.regulator for f in env.board.live_findings("coverage_gap")}
    assert {"DFSA", "VARA"} <= gaps


def test_output_that_breaks_the_rules_gets_one_repair(bench):
    setup = bench(
        *single_agent_replies(result="CONFLICTS", hard_conflicts=[]),
        lambda payload: json_reply(final_object(payload)),
    )
    _, final = setup.run("S15", SystemCondition.SA_BASE)
    assert final.detail["requests"] == 4
    assert any(e.type == "agent.repair" for e in setup.store.read("S15"))
    assert final.result is ResultCode.CONFLICTS


def test_a_failed_turn_ends_as_could_not_verify(bench):
    _, final = bench(PermanentLLMError("HTTP 400")).run("S15", SystemCondition.SA_BASE)
    assert final.result is ResultCode.UNVERIFIED and "U7" in final.unverified_reasons


def test_without_a_verifier_nothing_stops_an_overconfident_result(bench):
    replies = single_agent_replies(result="CONSISTENT", hard_conflicts=[])
    _, final = bench(*replies).run("S15", SystemCondition.SA_BASE)
    assert final.result is ResultCode.CONSISTENT
    assert final.detail["policy_result"] == "CONFLICTS"  # the error stays visible for measuring


def test_the_linter_runs_on_a_single_agents_words_too(bench):
    replies = single_agent_replies(explanation="This firm is a scam.")
    env, final = bench(*replies).run("S15", SystemCondition.SA_BASE)
    assert not lint_text(final.explanation, env.language)


# ------------------------------------------------------------------- SA-VER


def test_the_verifier_can_veto_one_agent_and_it_can_try_again(bench):
    setup = bench(
        *single_agent_replies(explanation="The website is a clone of the official one."),
        lambda payload: json_reply(_again(payload)),
        approve,
    )
    env, final = setup.run("S15", SystemCondition.SA_VER)
    board = env.board
    assert [report.decision for report in board.verifier_reports] == ["VETO", "APPROVE"]
    assert [g.gate for g in board.verifier_reports[0].gates if not g.passed] == ["G5"]
    assert final.result is ResultCode.CONFLICTS and final.proposal_version == 2
    assert "clone" not in final.explanation
    statuses = {f.status for f in board.findings.values() if f.assertion.type == "activity"}
    assert FindingStatus.SUPERSEDED in {s for h in board.history.values() for s in _statuses(h)}
    assert FindingStatus.ACTIVE in statuses


def _statuses(history: list[Any]) -> list[FindingStatus]:
    return [finding.status for finding in history]


def _again(payload: dict[str, Any]) -> dict[str, Any]:
    """The second turn sees the veto and the evidence in its case data."""
    data = json.loads(
        payload["messages"][1]["content"].split("<case_data>\n", 1)[1].split("\n</case_data>", 1)[0]
    )
    assert data["veto_reasons"] and data["evidence"]
    findings = {f["assertion"]["type"]: f for f in data["your_findings"]}
    match = findings["register_match"]["assertion"]
    compare = next(e for e in data["evidence"] if e["fields"].get("lookalike") is not None)
    return {
        "activities": [{"code": "DER.FX_CFD", "quote": "FX account"}],
        "claims": [{"kind": "firm_name", "value": FIRM, "quote": FIRM}],
        "targets_uae_clients": "unclear",
        "relevance": relevance(),
        "regulators": [
            {
                "regulator": "CMA",
                "register_matches": [
                    {
                        "evidence_id": match["entity_evidence_id"],
                        "match_type": match["match_type"],
                        "status": "active",
                    }
                ],
            }
        ],
        "contacts": [
            {
                "cp_id": "cp1",
                "status": "lookalike_of_official",
                "official_evidence_id": match["entity_evidence_id"],
                "evidence_ids": [compare["evidence_id"]],
                "rationale": "The domain resembles the official one.",
            }
        ],
        "result": "CONFLICTS",
        "hard_conflicts": ["HC5"],
        "explanation": "The offer's website domain resembles the firm's official domain.",
    }


def test_a_veto_that_stands_ends_as_could_not_verify(bench):
    bad = "The website is a clone of the official one."
    setup = bench(
        *single_agent_replies(explanation=bad),
        lambda payload: json_reply({**_again(payload), "explanation": bad}),
    )
    _, final = setup.run("S15", SystemCondition.SA_VER)
    assert final.result is ResultCode.UNVERIFIED and "U6" in final.unverified_reasons


def test_the_verifier_stops_an_overconfident_single_agent(bench):
    replies = single_agent_replies(result="CONSISTENT", hard_conflicts=[])
    setup = bench(*replies, chat_reply("no"), chat_reply("still no"))
    env, final = setup.run("S15", SystemCondition.SA_VER)
    failed = {g.gate for g in env.board.verifier_reports[0].gates if not g.passed}
    assert {"G3", "G8"} <= failed
    assert final.result is not ResultCode.CONSISTENT


def test_sa_ver_uses_the_verifier_the_crew_uses(bench):
    setup = bench(*single_agent_replies(), approve)
    setup.run("S15", SystemCondition.SA_VER)
    assert [agent_of(p) for p in setup.transport.payloads] == ["SA", "SA", "SA", "VER"]


# ------------------------------------------------------------------- SA-SC5


def sampled(payload: dict[str, Any]) -> dict[str, Any]:
    """A stateless single agent, so that parallel runs can interleave. The seed sets its vote."""
    done = tool_results(payload)
    if not done:
        return lookups()
    if len(done) == 5:
        return comparisons(payload)
    vote = payload["seed"] % 5
    if vote < 3:
        return json_reply(final_object(payload))
    return json_reply(
        final_object(payload, result="UNVERIFIED", hard_conflicts=[], unverified_reasons=["U3"])
    )


def test_sc5_votes_over_sampled_runs(bench):
    setup = bench(*[sampled] * (SC5_RUNS * 3))
    env, final = setup.run("S15", SystemCondition.SA_SC5)
    payloads = setup.transport.payloads
    assert {p["temperature"] for p in payloads} == {SC5_TEMPERATURE}
    assert len({p["seed"] for p in payloads}) == SC5_RUNS
    votes = final.detail["votes"]
    assert sum(votes.values()) == SC5_RUNS and max(votes.values()) == 3
    winner = max(votes, key=votes.get)
    assert final.result.value == winner
    assert final.detail["requests"] == SC5_RUNS * 3
    assert env.board.final == final
    assert render_report(env.board, env.ctx).claims
    assert len(setup.store.case_ids()) == SC5_RUNS + 1
    assert any(e.type == "votes.counted" for e in setup.store.read("S15"))
    assert all("#" not in case_id for case_id in setup.store.case_ids())


def _final(result: ResultCode) -> _Vote:
    final = FinalResult(result=result, wording="", explanation="")
    return _Vote(env=None, final=final)


@pytest.mark.parametrize(
    ("codes", "winner"),
    [
        ("CCCUU", ResultCode.CONFLICTS),
        ("OOCUU", ResultCode.UNVERIFIED),  # a tie goes to the cautious side
        ("OOCCU", ResultCode.CONFLICTS),
    ],
)
def test_a_tied_vote_goes_to_the_more_cautious_result(codes, winner):
    names = {
        "O": ResultCode.CONSISTENT,
        "C": ResultCode.CONFLICTS,
        "U": ResultCode.UNVERIFIED,
    }
    assert _winner([_final(names[code]) for code in codes]).final.result is winner


# ------------------------------------------------------------------- the other controls


def test_sa_max_thinks_at_full_and_writes_more():
    models = models_for(MODELS, SystemCondition.SA_MAX)
    options = models.options_for(MODELS.roles["primary"])
    assert options["chat_template_kwargs"] == {"enable_thinking": True}
    assert models.decoding.max_tokens == MODELS.decoding.max_tokens * 2


def test_sa_larger_runs_on_the_larger_model(bench):
    setup = bench(chat_reply("no"), chat_reply("no"))
    env, _ = setup.run("S15", SystemCondition.SA_LARGER)
    assert model_for(MODELS, SystemCondition.SA_LARGER) == MODELS.roles["larger_single"]
    assert setup.transport.payloads[0]["model"] == MODELS.roles["larger_single"]
    assert env.board.case.config["model"] == MODELS.roles["larger_single"]


def test_every_condition_can_be_opened(bench):
    setup = bench()
    offer = CASES["S01"].offer()
    for condition in SystemCondition:
        open_condition(setup.stack, f"open-{condition.value}", offer, condition=condition)


def test_a_condition_that_cannot_run_is_refused(bench, monkeypatch):
    setup = bench()
    monkeypatch.setattr("tessera.experiment.SINGLE", {})
    with pytest.raises(PolicyError, match="not a system"):
        open_condition(setup.stack, "x", CASES["S01"].offer(), condition=SystemCondition.SA_BASE)


def test_contact_points_the_agent_must_assess_come_from_intake(bench):
    setup = bench(chat_reply("no"), chat_reply("no"))
    env, _ = setup.run("S15", SystemCondition.SA_BASE)
    deciding = [p for p in env.board.case.contact_points if p.role is ContactRole.DECIDING]
    assert [p.cp_id for p in deciding] == ["cp1"]
    assert "cp1" in setup.transport.payloads[0]["messages"][1]["content"]
