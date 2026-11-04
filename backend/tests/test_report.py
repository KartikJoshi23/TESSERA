"""The report: the output contract, and where DFSA values are allowed to appear (§12.1, §9.3)."""

import asyncio
import json

from tessera.config.settings import Mode
from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.governance.language import has_disclaimer
from tessera.governance.links import DFSA_HOMEPAGE, find_dfsa_deep_links
from tessera.llm.testing import chat_reply
from tessera.orchestration.graph import run_crew
from tessera.protocol.common import AgentId, ResultCode
from tessera.reporting.report import _chip, render_report

from .conftest import REPO_ROOT, CrewHarness, make_settings
from .scripted import FIRM, Routed, worked_example

CASES = {case.id: case for case in load_smoke_cases(REPO_ROOT)}


def finished_case(harness):
    script = Routed()
    setup = harness(CASES["S09"].offer().text, *[script] * 60, case_id="S09")
    script.queues = worked_example(setup)
    asyncio.run(run_crew(setup.env, today=FICTION_DATE))
    return setup, render_report(setup.board, setup.env.ctx)


def stored_text(setup):
    return json.dumps(
        [e.model_dump(mode="json") for e in setup.store.read("S09")], ensure_ascii=False
    )


def test_a_report_holds_everything_the_output_contract_requires(harness):
    setup, report = finished_case(harness)
    assert report.wording == "Conflicts with the official record"
    assert len(report.explanation.split()) <= 120
    assert [rule.id for rule in report.hard_conflicts] == ["HC1", "HC4", "HC5"]
    assert all(rule.text for rule in report.hard_conflicts)
    assert report.claims and all(claim.evidence for claim in report.claims)
    assert {c.regulator for c in report.regulators} == {"CMA", "DFSA", "VARA"}
    assert {s.source for s in report.sources} >= {"CMA Licensed Companies"}
    assert all(source.as_of == FICTION_DATE for source in report.sources)
    assert report.how_to_verify
    assert has_disclaimer(report.disclaimer, setup.env.language)
    assert report.synthetic is True
    assert report.case_id == "S09" and report.condition == "CREW-FULL"


def test_dfsa_evidence_links_only_to_the_homepage(harness):
    _, report = finished_case(harness)
    chips = [chip for claim in report.claims for chip in claim.evidence]
    dfsa = [chip for chip in chips if chip.source.startswith("DFSA")]
    assert dfsa and all(chip.link == DFSA_HOMEPAGE for chip in dfsa)
    assert not find_dfsa_deep_links(report.model_dump_json())
    verify = {link.regulator: link.link for link in report.how_to_verify}
    assert verify["DFSA"] == DFSA_HOMEPAGE


def test_a_report_restores_masked_values_locally(harness):
    setup = harness(CASES["S09"].offer().text, *[chat_reply("no")] * 40, case_id="S09")
    asyncio.run(run_crew(setup.env, today=FICTION_DATE))
    placeholder = setup.gateway.mask(FIRM)
    assert placeholder != FIRM
    final = setup.board.final.model_copy(update={"explanation": f"About {placeholder}."})
    setup.board.final = final
    report = render_report(setup.board, setup.env.ctx)
    assert report.explanation == f"About {FIRM}."


def test_a_dfsa_alert_date_appears_in_the_report_and_never_in_the_log(harness):
    setup, report = finished_case(harness)
    alerts = [
        chip
        for claim in report.claims
        for chip in claim.evidence
        if chip.kind == "alert_entry" and chip.source.startswith("DFSA")
    ]
    assert alerts and all(chip.dated.isoformat() == "2026-01-14" for chip in alerts)
    assert "2026-01-14" not in stored_text(setup)


def test_the_stored_result_stays_masked(harness):
    setup, _ = finished_case(harness)
    stored = setup.board.final.model_dump_json()
    assert setup.gateway.leaked_values(stored) == []
    assert FIRM not in stored_text(setup)


def test_a_report_needs_a_finished_case(harness):
    setup = harness("An offer at falconridge.example.")
    try:
        render_report(setup.board, setup.env.ctx)
    except ValueError as exc:
        assert "not finished" in str(exc)
    else:
        raise AssertionError("expected a refusal")


def test_a_case_with_no_proposal_still_gets_a_full_report(harness):
    setup = harness(CASES["S09"].offer().text, *[chat_reply("no")] * 40, case_id="S09")
    asyncio.run(run_crew(setup.env, today=FICTION_DATE))
    report = render_report(setup.board, setup.env.ctx)
    assert report.result is ResultCode.UNVERIFIED
    assert report.wording == "Could not verify"
    assert "U7" in {rule.id for rule in report.unverified_reasons}
    assert report.explanation and report.disclaimer


def test_a_public_list_shows_its_own_date(harness):
    setup = harness("Register at goldendune-fx.example today.", *[chat_reply("no")] * 40)
    setup.env.belt.execute(
        "reverse_contact_lookup",
        '{"value": "goldendune-fx.example"}',
        allowed=("reverse_contact_lookup",),
        actor=AgentId.CLN,
    )
    record = next(e for e in setup.board.evidence.values() if e.kind.value == "warning_entry")
    assert _chip(setup.env.ctx, record).dated.isoformat() == "2026-02-10"


def test_demo_mode_reports_contain_no_dfsa_values(populated_settings):
    demo = make_settings(populated_settings.data_path, mode=Mode.RESTRICTED_DEMO)
    setup = CrewHarness(demo, CASES["S09"].offer().text, *[chat_reply("no")] * 40, case_id="S09")
    asyncio.run(run_crew(setup.env, today=FICTION_DATE))
    report = render_report(setup.board, setup.env.ctx)
    assert report.mode == "RESTRICTED_DEMO"
    assert all(chip.dated is None for claim in report.claims for chip in claim.evidence)
