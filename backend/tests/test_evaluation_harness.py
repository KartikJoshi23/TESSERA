"""The run harness and the reports, driven through the same code a real run uses."""

import argparse
import asyncio
import csv
import json
from datetime import date
from pathlib import Path

import pytest

from tessera.agents.crew import build_stack
from tessera.blackboard.store import EventStore
from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.errors import RestrictedValueLeak
from tessera.evaluation.cli import _sealed_problems, build_parser, main, restricted_home
from tessera.evaluation.freezing import (
    fingerprint,
    freeze_manifest,
    frozen_problems,
    pin_run,
)
from tessera.evaluation.harness import Harness, load_records, record_path
from tessera.evaluation.items import EvalItem, Level, Split, read_items
from tessera.evaluation.plan import Job, jobs_for, load_plan, plan_hash
from tessera.evaluation.report import (
    compare,
    evaluation_report,
    level_report,
    outcomes_by_condition,
    render_text,
    sampled_stability,
    stability,
    to_outcome,
)
from tessera.llm.config import load_models_policy
from tessera.llm.testing import ScriptedTransport
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import ResultCode

from .conftest import REPO_ROOT
from .scripted import in_loop

MODELS = load_models_policy(REPO_ROOT / "policies")
PLAN_PATH = REPO_ROOT / "eval" / "plan.yaml"
PLAN = load_plan(PLAN_PATH)
SMOKE = {case.id: case for case in load_smoke_cases(REPO_ROOT)}
RULES = SystemCondition.RULES_ONLY


def smoke_item(case_id, level=Level.MESSAGE):
    case = SMOKE[case_id]
    return EvalItem(
        item_id=case_id,
        level=level,
        text=case.offer().text,
        gold_label=case.gold_label,
        gold_reasons=tuple(case.gold_reasons),
        gold_relevant=tuple(case.gold_relevant),
        factors=tuple(case.factors),
        origin="template",
    )


@pytest.fixture
def stack(populated_settings):
    return build_stack(populated_settings, ScriptedTransport([]), EventStore(), MODELS)


@pytest.fixture
def harness(stack, tmp_path):
    return Harness(stack, tmp_path / "run", today=FICTION_DATE, plan_hash="abc")


def record(item_id, condition, result, run=0, **changes):
    return {
        "item_id": item_id,
        "condition": condition,
        "run": run,
        "result": result,
        "requests": 5,
        "tokens": 100,
        "seconds": 10.0,
        **changes,
    }


# ------------------------------------------------------------------ the plan


def test_the_registered_plan_loads_and_has_the_primary_comparison():
    assert SystemCondition.CREW_FULL in PLAN.primary and SystemCondition.SA_BASE in PLAN.primary
    assert {c.metric for c in PLAN.registered} == {"false_reassurance", "macro_f1"}
    assert PLAN.non_inferiority_margin == 0.02


def test_a_plan_has_a_stable_hash():
    assert plan_hash(PLAN_PATH) == plan_hash(PLAN_PATH)


def test_jobs_go_item_by_item_so_a_stopped_run_holds_complete_pairs():
    jobs = jobs_for([smoke_item("S01"), smoke_item("S02")], PLAN, stability=False)
    first = jobs[: len(PLAN.primary)]
    assert {job.item.item_id for job in first} == {"S01"}


def test_stability_runs_are_message_level_only():
    message = jobs_for([smoke_item("S01")], PLAN)
    entity = jobs_for([smoke_item("S01", Level.ENTITY)], PLAN)
    assert len(entity) == len(PLAN.primary)
    assert len(message) == len(PLAN.primary) + sum(PLAN.stability.runs.values())


def test_stability_runs_use_the_registered_temperature_and_their_own_numbers():
    jobs = [job for job in jobs_for([smoke_item("S01")], PLAN) if job.temperature is not None]
    assert {job.temperature for job in jobs} == {0.7}
    runs = sorted(job.run for job in jobs if job.condition is SystemCondition.CREW_FULL)
    assert runs == [1, 2, 3]


def test_an_optional_system_can_be_asked_for():
    jobs = jobs_for([smoke_item("S01")], PLAN, conditions=[SystemCondition.SA_LARGER])
    assert [job.condition for job in jobs] == [SystemCondition.SA_LARGER]


def test_a_part_of_the_plan_can_be_run():
    jobs = jobs_for([smoke_item("S01")], PLAN, conditions=[RULES])
    assert [job.condition for job in jobs] == [RULES]


# ------------------------------------------------------------------ the harness


@in_loop
async def test_a_record_holds_what_happened_and_no_gold(harness):
    job = Job(smoke_item("S09"), RULES)
    await harness.run([job])
    saved = json.loads(record_path(harness.run_dir, job).read_text("utf-8"))
    assert saved["result"] == "CONFLICTS" and saved["plan"] == "abc"
    assert saved["requests"] == 0 and saved["cited"] > 0
    assert saved["cited"] == saved["cited_valid"]
    assert not [key for key in saved if "gold" in key]
    assert "gold_" not in json.dumps(saved)


@in_loop
async def test_a_record_holds_no_restricted_value(harness):
    job = Job(smoke_item("S09"), RULES)
    await harness.run([job])
    text = record_path(harness.run_dir, job).read_text("utf-8")
    assert "2026-01-14" not in text and "Gate Village" not in text


@in_loop
async def test_a_second_run_skips_what_is_finished(harness):
    jobs = [Job(smoke_item("S09"), RULES), Job(smoke_item("S01"), RULES)]
    first = await harness.run(jobs[:1])
    second = await harness.run(jobs)
    assert first.done == 1
    assert second.skipped == 1 and second.done == 1


@in_loop
async def test_a_crash_midway_leaves_a_run_that_can_go_on(harness, monkeypatch):
    jobs = [Job(smoke_item("S09"), RULES), Job(smoke_item("S01"), RULES)]
    real = harness.run_job
    calls = []

    async def fail_once(job):
        calls.append(job.name)
        if len(calls) == 1:
            raise RuntimeError("the provider went away")
        return await real(job)

    monkeypatch.setattr(harness, "run_job", fail_once)
    progress = await harness.run(jobs)
    assert progress.failed == 1 and progress.done == 1
    assert not record_path(harness.run_dir, jobs[0]).exists()

    again = await harness.run(jobs)
    assert again.done == 1 and again.skipped == 1


@in_loop
async def test_a_case_cut_short_is_not_appended_to(harness, stack):
    job = Job(smoke_item("S09"), RULES)
    stack.open_case(job.name, job.item.offer(), condition=RULES)
    await harness.run([job])
    saved = json.loads(record_path(harness.run_dir, job).read_text("utf-8"))
    assert saved["case_id"] == f"{job.name}~retry1"


@in_loop
async def test_a_case_the_provider_cut_short_is_not_a_result(harness, monkeypatch):
    """An outage ends each case as "Could not verify", and that says nothing about a system."""
    real = harness.run_job
    broken = True

    async def outage(job):
        record = await real(job)
        return {**record, "failures": [{"code": "model_error"}]} if broken else record

    monkeypatch.setattr(harness, "run_job", outage)
    job = Job(smoke_item("S09"), RULES)
    first = await harness.run([job])
    assert first.done == 0 and first.failed == 1
    assert not record_path(harness.run_dir, job).exists()
    assert load_records(harness.run_dir)[0]["gave_no_result"] is True

    broken = False
    second = await harness.run([job])
    assert second.done == 1
    records = load_records(harness.run_dir)
    assert len(records) == 1 and "gave_no_result" not in records[0]


@in_loop
async def test_an_outage_stops_the_run(harness, monkeypatch):
    real = harness.run_job

    async def outage(job):
        return {**await real(job), "failures": [{"code": "model_error"}]}

    monkeypatch.setattr(harness, "run_job", outage)
    jobs = [Job(smoke_item(case), RULES) for case in ("S01", "S02", "S03", "S04", "S05")]
    progress = await harness.run(jobs)
    assert progress.failed == 3 and "failures in a row" in progress.stopped_because


@in_loop
async def test_a_rule_breaking_reply_is_how_a_system_behaved_so_it_stands(harness, monkeypatch):
    real = harness.run_job

    async def invalid(job):
        return {**await real(job), "failures": [{"code": "invalid_output"}]}

    monkeypatch.setattr(harness, "run_job", invalid)
    progress = await harness.run([Job(smoke_item("S01"), RULES)])
    assert progress.done == 1


@in_loop
async def test_a_leak_guard_ends_the_run(harness, monkeypatch):
    async def leak(job):
        raise RestrictedValueLeak("a value was about to leave")

    monkeypatch.setattr(harness, "run_job", leak)
    with pytest.raises(RestrictedValueLeak):
        await harness.run([Job(smoke_item("S01"), RULES), Job(smoke_item("S02"), RULES)])


def test_a_crash_is_scored_as_could_not_verify():
    item = smoke_item("S09")
    outcome = to_outcome(item, {"item_id": "S09", "result": "UNVERIFIED", "gave_no_result": True})
    assert outcome.predicted is ResultCode.UNVERIFIED and outcome.failed


def test_at_least_one_case_must_run_at_a_time(harness):
    with pytest.raises(ValueError, match="at least one"):
        asyncio.run(harness.run([], parallel=0))


@in_loop
async def test_a_stop_stays_a_stop_when_another_case_then_succeeds(harness, monkeypatch):
    real = harness.run_job
    calls = 0

    async def flaky(job):
        nonlocal calls
        calls += 1
        if calls <= 3:
            raise RuntimeError("down")
        return await real(job)

    monkeypatch.setattr(harness, "run_job", flaky)
    jobs = [Job(smoke_item(case), RULES) for case in ("S01", "S02", "S03", "S04", "S05", "S09")]
    progress = await harness.run(jobs, parallel=1)
    assert progress.stopped_because == "3 failures in a row" and calls == 3


@in_loop
async def test_a_run_stops_when_the_provider_keeps_failing(harness, monkeypatch):
    async def always(job):
        raise RuntimeError("down")

    monkeypatch.setattr(harness, "run_job", always)
    jobs = [Job(smoke_item(case), RULES) for case in ("S01", "S02", "S03", "S04", "S05")]
    progress = await harness.run(jobs)
    assert progress.failed == 3
    assert "failures in a row" in progress.stopped_because


@in_loop
async def test_a_request_budget_stops_a_run_between_cases(harness, monkeypatch):
    real = harness.run_job

    async def costly(job):
        return {**await real(job), "requests": 10}

    monkeypatch.setattr(harness, "run_job", costly)
    jobs = [Job(smoke_item(case), RULES) for case in ("S01", "S02", "S03")]
    progress = await harness.run(jobs, max_requests=15)
    assert progress.done == 2 and progress.stopped_because == "request budget"


@in_loop
async def test_a_time_limit_stops_a_run_between_cases(stack, tmp_path):
    ticks = iter(range(0, 100_000, 2_000))
    harness = Harness(stack, tmp_path / "run", today=FICTION_DATE, clock=lambda: next(ticks))
    jobs = [Job(smoke_item(case), RULES) for case in ("S01", "S02", "S03", "S04")]
    progress = await harness.run(jobs, hours=1)
    assert progress.stopped_because == "time limit"
    assert 0 < progress.done < 4


@in_loop
async def test_cases_can_run_side_by_side(harness):
    jobs = [Job(smoke_item(case), RULES) for case in ("S01", "S02", "S03", "S04", "S05", "S09")]
    progress = await harness.run(jobs, parallel=3)
    assert progress.done == 6
    assert {r["item_id"] for r in load_records(harness.run_dir)} == {j.item.item_id for j in jobs}


@in_loop
async def test_a_stop_reaches_every_worker(harness, monkeypatch):
    async def always(job):
        raise RuntimeError("down")

    monkeypatch.setattr(harness, "run_job", always)
    jobs = [Job(smoke_item(case), RULES) for case in ("S01", "S02", "S03", "S04", "S05", "S09")]
    progress = await harness.run(jobs, parallel=2)
    assert progress.failed == 3
    assert "failures in a row" in progress.stopped_because


@in_loop
async def test_progress_is_written_as_it_goes(harness):
    await harness.run([Job(smoke_item("S01"), RULES)])
    saved = json.loads((harness.run_dir / "progress.json").read_text("utf-8"))
    assert saved["done"] == 1 and saved["total"] == 1


def test_stability_runs_get_their_own_seed_and_temperature(harness):
    job = Job(smoke_item("S01"), SystemCondition.CREW_FULL, 2, 0.7)
    models = harness._models(job)
    assert models.decoding.temperature == 0.7
    assert models.decoding.seed == MODELS.decoding.seed + 2


def test_a_primary_run_keeps_the_registered_decoding(harness):
    models = harness._models(Job(smoke_item("S01"), SystemCondition.CREW_FULL))
    assert models.decoding == MODELS.decoding


# ------------------------------------------------------------------ the reports


def test_gold_joins_a_record_only_here():
    outcome = to_outcome(
        smoke_item("S09"), record("S09", "CREW-FULL", "CONSISTENT", hard_conflicts=["HC1"])
    )
    assert outcome.gold is ResultCode.CONFLICTS and outcome.predicted is ResultCode.CONSISTENT
    assert outcome.reasons == ("HC1",)


def items_and_records():
    items = [smoke_item(case) for case in ("S01", "S09", "S10", "S20", "S21", "S11")]
    records = [record(item.item_id, "CREW-FULL", item.gold_label.value) for item in items] + [
        record("S01", "SA-BASE", "CONSISTENT"),
        record("S09", "SA-BASE", "CONSISTENT"),
        record("S10", "SA-BASE", "CONSISTENT"),
        record("S20", "SA-BASE", "UNVERIFIED"),
        record("S21", "SA-BASE", "UNVERIFIED"),
        record("S11", "SA-BASE", "CONFLICTS"),
    ]
    return items, records


def test_a_comparison_uses_only_items_both_systems_answered():
    items, records = items_and_records()
    table = outcomes_by_condition(
        items, [r for r in records if r["item_id"] != "S11" or r["condition"] == "CREW-FULL"]
    )
    result = compare(table, PLAN.registered[0])
    assert result["pairs"] == 5


def test_the_primary_comparison_measures_false_reassurance():
    items, records = items_and_records()
    table = outcomes_by_condition(items, records)
    result = compare(table, PLAN.registered[0])
    # The single agent falsely reassured on S09 and S10. The crew never did.
    assert result["only_first"] == 0 and result["only_second"] == 2
    assert result["difference"] == pytest.approx(-0.4)
    assert result["p_value"] == pytest.approx(0.5)


def test_usefulness_has_a_test_of_its_own_on_right_answers():
    items, records = items_and_records()
    result = compare(outcomes_by_condition(items, records), PLAN.registered[1])
    # The crew is right everywhere. The single agent is wrong on S09 and S10.
    assert result["only_first"] == 2 and result["only_second"] == 0
    assert result["p_value"] == pytest.approx(0.5)


def test_every_secondary_comparison_is_in_the_correction():
    items, records = items_and_records()
    extra = [
        record(item.item_id, name, item.gold_label.value)
        for item in items
        for name in ("CREW-SHARE", "CREW-SILO")
    ]
    report = level_report(items, records + extra, PLAN, Level.MESSAGE)
    sharing = [c for c in report["secondary"] if c.get("first") == "CREW-SHARE"]
    assert {c["metric"] for c in sharing} == {"false_reassurance", "macro_f1"}
    assert all("p_holm" in c for c in sharing)


def test_a_report_says_what_has_not_run_yet():
    items, records = items_and_records()
    partial = [r for r in records if not (r["condition"] == "SA-BASE" and r["item_id"] == "S11")]
    report = level_report(items, partial, PLAN, Level.MESSAGE)
    assert report["systems"]["SA-BASE"]["not_yet_run"] == 1
    assert report["systems"]["CREW-FULL"]["not_yet_run"] == 0


def test_the_baseline_s_stability_comes_from_its_five_samples():
    items = [smoke_item("S01"), smoke_item("S09")]
    records = [
        record("S01", "SA-SC5", "CONSISTENT", votes={"CONSISTENT": 5}),
        record("S09", "SA-SC5", "CONFLICTS", votes={"CONFLICTS": 3, "UNVERIFIED": 2}),
    ]
    result = sampled_stability(items, records)
    assert result["condition"] == "SA-BASE"
    assert result["items"] == 2 and result["flip_rate"] == 0.5


def test_a_missing_system_is_reported_as_no_pairs():
    items, records = items_and_records()
    table = outcomes_by_condition(items, records)
    result = compare(table, PLAN.secondary[0])
    assert result["pairs"] == 0


def test_levels_are_never_pooled():
    message = smoke_item("S01")
    entity = smoke_item("S09", Level.ENTITY)
    records = [record("S01", "CREW-FULL", "CONSISTENT"), record("S09", "CREW-FULL", "CONFLICTS")]
    report = evaluation_report([message, entity], records, PLAN)
    assert report["levels"]["message"]["systems"]["CREW-FULL"]["items"] == 1
    assert report["levels"]["entity"]["systems"]["CREW-FULL"]["items"] == 1


def test_non_inferiority_needs_the_whole_interval_above_the_margin():
    items, records = items_and_records()
    report = level_report(items, records, PLAN, Level.MESSAGE)
    assert report["non_inferiority"]["tested"] is True
    assert report["non_inferiority"]["margin"] == 0.02


def test_stability_needs_every_run_of_an_item():
    items = [smoke_item("S01"), smoke_item("S09")]
    records = (
        [record("S01", "CREW-FULL", "CONSISTENT", run=run) for run in (1, 2, 3)]
        + [
            record("S09", "CREW-FULL", result, run=run)
            for run, result in ((1, "CONFLICTS"), (2, "UNVERIFIED"), (3, "CONFLICTS"))
        ]
        + [record("S20", "CREW-FULL", "UNVERIFIED", run=1)]
    )
    result = stability(items, records, SystemCondition.CREW_FULL, 3)
    assert result["items"] == 2 and result["flip_rate"] == 0.5


def test_a_report_renders_to_plain_text():
    items, records = items_and_records()
    text = render_text(evaluation_report(items, records, PLAN))
    assert "MESSAGE LEVEL" in text and "CREW-FULL" in text and "H1 false reassurance" in text


# ------------------------------------------------------------------ the command


def test_the_pipeline_runs_from_records_to_a_report(monkeypatch, tmp_path, capsys):
    """Build a fictional set, probe it with no model, and score the result."""
    out = tmp_path / "messages"
    assert main(["messages", "--fiction", "--per-label", "6", "--out", str(out)]) == 0
    built = capsys.readouterr().out
    assert "items:" in built and "dropped" in built
    files = [str(path) for path in tmp_path.rglob("items.jsonl")]
    assert any("restricted" in path for path in files)
    run_dir = tmp_path / "probe"
    assert main(["probe", "--fiction", "--items", *files, "--run-dir", str(run_dir)]) == 0
    assert "RULES-ONLY matches" in capsys.readouterr().out
    report = tmp_path / "report.json"
    arguments = ["report", "--items", *files, "--run-dir", str(run_dir), "--out", str(report)]
    assert main(arguments) == 2, "dev and test must not pool by accident"
    assert "--split" in capsys.readouterr().out
    assert main([*arguments, "--split", "all"]) == 0
    assert "MESSAGE LEVEL" in capsys.readouterr().out
    saved = json.loads(report.read_text("utf-8"))
    assert "RULES-ONLY" in saved["levels"]["message"]["systems"]
    lab = tmp_path / "lab.json"
    arguments = ["lab", "--items", *files, "--run-dir", str(run_dir), "--out", str(lab)]
    assert main([*arguments, "--fiction"]) == 0
    capsys.readouterr()
    written = lab.read_text("utf-8")
    assert '"condition": "RULES-ONLY"' in written
    assert "Lumen Crest" not in written and "Falcon Ridge" not in written
    assert main(arguments) == 2


def test_the_power_command_answers(capsys):
    assert main(["power", "--baseline", "0.10", "--crew", "0.03"]) == 0
    assert "power" in capsys.readouterr().out


def test_no_prompt_or_rule_card_names_a_firm_in_the_records(populated_settings, tmp_path):
    from tessera.evaluation.firms import load_world
    from tessera.evaluation.leakage import names_in, scan
    from tessera.knowledge import load_activity_taxonomy

    stack = build_stack(populated_settings, ScriptedTransport([]), EventStore(), MODELS)
    taxonomy = load_activity_taxonomy(populated_settings.knowledge_dir)
    world = load_world(stack.registry, taxonomy)
    assert names_in(world)
    assert scan(world, [REPO_ROOT / "backend" / "prompts", REPO_ROOT / "knowledge"]) == []
    planted = tmp_path / "card.yaml"
    planted.write_text("Falcon Ridge Securities is a good example.", encoding="utf-8")
    assert scan(world, [tmp_path]) == ["card.yaml: Falcon Ridge Securities"]


def test_a_fingerprint_changes_when_what_a_system_is_given_changes(populated_settings):
    before = fingerprint(populated_settings, MODELS)
    assert fingerprint(populated_settings, MODELS) == before
    assert (
        fingerprint(populated_settings, MODELS.with_thinking(False))["models"] != before["models"]
    )
    assert (
        fingerprint(populated_settings, MODELS.with_decoding(seed=1))["models"] != before["models"]
    )


def test_the_pace_can_change_without_breaking_a_run(populated_settings):
    faster = MODELS.model_copy(
        update={"rate_limit": MODELS.rate_limit.model_copy(update={"requests_per_minute": 1.0})}
    )
    assert fingerprint(populated_settings, faster) == fingerprint(populated_settings, MODELS)


def test_a_frozen_set_must_still_match():
    items = [smoke_item("S01")]
    print_ = {"prompts": "a", "plan": "b"}
    manifest = freeze_manifest(items, print_)
    assert frozen_problems(manifest, items, print_) == []
    changed = [items[0].model_copy(update={"text": "Changed."})]
    assert frozen_problems(manifest, changed, print_) == ["the items differ from the frozen set"]
    assert frozen_problems(manifest, items, {**print_, "prompts": "z"}) == [
        "prompts changed since the freeze"
    ]


def _run_args(tmp_path, **changes):
    fields = {"fiction": False, "frozen": None}
    return argparse.Namespace(**{**fields, **changes})


def test_real_test_items_need_a_freeze(tmp_path):
    sealed = smoke_item("S01").model_copy(update={"split": Split.TEST})
    open_item = smoke_item("S02").model_copy(update={"split": Split.DEV})
    assert _sealed_problems(_run_args(tmp_path), [open_item], {}) == []
    assert "sealed" in _sealed_problems(_run_args(tmp_path), [sealed], {})[0]
    assert _sealed_problems(_run_args(tmp_path, fiction=True), [sealed], {}) == []


def test_a_run_keeps_its_date_and_refuses_a_change(tmp_path):
    first = date(2026, 11, 5)
    assert pin_run(tmp_path, {"prompts": "a"}, first) == (first, [])
    later = date(2026, 12, 1)
    assert pin_run(tmp_path, {"prompts": "a"}, later) == (first, [])
    assert pin_run(tmp_path, {"prompts": "b"}, later)[1] == ["prompts changed since this run began"]
    assert "not 2026-12-01" in pin_run(tmp_path, {"prompts": "a"}, later, stated=later)[1][0]


def test_restricted_work_goes_where_a_purge_will_find_it():
    home = restricted_home(Path("datasets/message_level"))
    assert home == Path("datasets/restricted/message_level")


def test_people_s_briefs_for_dfsa_scenarios_stay_restricted(tmp_path, capsys):
    out = tmp_path / "messages"
    assert main(["messages", "--fiction", "--per-label", "12", "--people", "--out", str(out)]) == 0
    capsys.readouterr()
    public = out / "briefs.csv"
    held = restricted_home(out) / "briefs.csv"
    assert public.exists() and held.exists()
    assert "Lumen Crest" not in public.read_text("utf-8")
    assert "Harbour Cedar" not in public.read_text("utf-8")


def test_what_people_wrote_comes_back_through_the_same_checks(tmp_path, capsys):
    out = tmp_path / "messages"
    assert main(["messages", "--fiction", "--per-label", "12", "--people", "--out", str(out)]) == 0
    capsys.readouterr()
    briefs = out / "briefs.csv"
    with briefs.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["text"] = (
            f"About {row['offer_about']}: {' '.join(row['must_appear_exactly'].split(' | '))}"
        )
    with briefs.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    before = sum(len(read_items(path)) for path in out.rglob("items.jsonl"))
    assert main(["written", "--fiction", "--briefs", str(briefs), "--out", str(out)]) == 0
    assert "added" in capsys.readouterr().out
    after = [item for path in out.rglob("items.jsonl") for item in read_items(path)]
    assert len(after) > before
    assert {"human"} <= {item.origin for item in after}


def test_settled_labels_can_be_applied(tmp_path, capsys):
    from tessera.evaluation.items import write_items

    path = tmp_path / "items.jsonl"
    write_items(path, [smoke_item("S01"), smoke_item("S09")])
    decisions = tmp_path / "decisions.csv"
    decisions.write_text("item_id,label\nS01,\nS09,unverified\n", encoding="utf-8")
    assert main(["settle", "--items", str(path), "--decisions", str(decisions)]) == 0
    kept = read_items(path)
    assert [i.item_id for i in kept] == ["S09"] and kept[0].gold_label is ResultCode.UNVERIFIED
    assert "dropped: S01" in capsys.readouterr().out


def test_probing_nothing_says_so(tmp_path, capsys):
    from tessera.evaluation.items import write_items

    path = tmp_path / "items.jsonl"
    write_items(path, [])
    arguments = ["probe", "--fiction", "--items", str(path), "--run-dir", str(tmp_path / "run")]
    assert main(arguments) == 2
    assert "no items" in capsys.readouterr().out


def test_every_command_parses():
    parser = build_parser()
    for words in (
        ["entities", "--out", "x"],
        ["messages", "--out", "x", "--per-label", "5"],
        ["sheet", "--items", "a", "--annotator", "A", "--out", "b"],
        ["agreement", "--items", "a", "--first", "b", "--second", "c"],
        ["probe", "--items", "a"],
        ["run", "--items", "a", "--run-dir", "b", "--hours", "2"],
        ["report", "--items", "a", "--run-dir", "b"],
        ["freeze", "--items", "a", "--out", "b"],
    ):
        assert parser.parse_args(words).command == words[0]


def test_a_set_can_be_frozen_and_probed_from_the_command_line(tmp_path, capsys, monkeypatch):
    from tessera.evaluation.items import write_items

    path = write_items(tmp_path / "items.jsonl", [smoke_item("S01")]) and tmp_path / "items.jsonl"
    assert main(["freeze", "--items", str(path), "--out", str(tmp_path / "manifest.json")]) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert manifest["items"] == 1 and len(manifest["hash"]) == 64
    assert "frozen: 1 items" in capsys.readouterr().out
    assert read_items(path)[0].item_id == "S01"
    assert load_records(tmp_path) == []
