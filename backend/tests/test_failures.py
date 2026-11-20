"""Coding failures with MAST: the sample, the signals, the sheet and agreement (§11.3)."""

import csv
import json
from collections import Counter
from datetime import UTC, datetime

import pytest

from tessera.blackboard.store import Event, EventStore
from tessera.errors import PolicyError
from tessera.evaluation.cli import main
from tessera.evaluation.failures import (
    BY_CODE,
    CATEGORIES,
    MODES,
    code_agreement,
    failure_rows,
    failures_of,
    read_codes,
    sample_failures,
    signals_of,
    summarize_codes,
    trace_lines,
    write_failure_sheet,
)
from tessera.evaluation.items import EvalItem, Level, Split, write_items
from tessera.evaluation.metrics import Outcome
from tessera.protocol.common import ResultCode

C, F, U = ResultCode.CONSISTENT, ResultCode.CONFLICTS, ResultCode.UNVERIFIED
NOW = datetime(2026, 11, 4, tzinfo=UTC)


def event(kind, actor="REC", case="case", **payload):
    return Event(case_id=case, ts=NOW, actor=actor, type=kind, payload=payload)


def outcome(item_id, gold, predicted, **changes):
    return Outcome(item_id=item_id, gold=gold, predicted=predicted, **changes)


def item(item_id, gold=C, **changes):
    return EvalItem(
        item_id=item_id,
        level=Level.MESSAGE,
        text="An invented offer at invented.example.",
        gold_label=gold,
        origin="template",
        **changes,
    )


def suggested(signals):
    return {signal.suggests for signal in signals if signal.suggests}


# --------------------------------------------------------------------------------- taxonomy


def test_the_taxonomy_has_mast_s_fourteen_modes_in_three_categories():
    mast = [mode for mode in MODES if mode.category != "NM"]
    assert len(mast) == 14
    assert Counter(mode.category for mode in mast) == {"FC1": 5, "FC2": 6, "FC3": 3}
    assert [mode.code for mode in mast][:3] == ["FM-1.1", "FM-1.2", "FM-1.3"]
    assert BY_CODE["FM-3.3"].name == "Incorrect verification"
    assert set(CATEGORIES) == {mode.category for mode in MODES}


def test_codes_outside_mast_are_marked_as_such():
    """A wrong label or a misread offer is not a coordination failure, and is not coded as one."""
    outside = {mode.code for mode in MODES if mode.category == "NM"}
    assert {"NM-LABEL", "NM-READING", "NM-KNOWLEDGE"} <= outside
    assert all(code.startswith("NM-") for code in outside)


# --------------------------------------------------------------------------------- sampling


def wrong_answers():
    outcomes = {f"C{i:03d}": outcome(f"C{i:03d}", C, U) for i in range(80)}
    outcomes |= {f"F{i:03d}": outcome(f"F{i:03d}", F, U) for i in range(18)}
    outcomes |= {"R001": outcome("R001", U, C), "R002": outcome("R002", F, C)}
    outcomes |= {f"OK{i}": outcome(f"OK{i}", C, C) for i in range(30)}
    return outcomes


def test_only_wrong_answers_are_failures():
    assert len(failures_of(wrong_answers())) == 100


def test_a_sample_keeps_each_kind_of_error_and_never_drops_a_rare_one():
    sample = sample_failures(wrong_answers(), 50, seed=1)
    kinds = Counter((o.gold, o.predicted) for o in sample)
    assert 50 <= len(sample) <= 52
    assert kinds[(U, C)] == 1 and kinds[(F, C)] == 1, "every false reassurance is kept"
    assert kinds[(C, U)] == 40 and kinds[(F, U)] == 9


def test_the_same_seed_gives_the_same_sample():
    first = [o.item_id for o in sample_failures(wrong_answers(), 50, seed=3)]
    assert first == [o.item_id for o in sample_failures(wrong_answers(), 50, seed=3)]
    assert first != [o.item_id for o in sample_failures(wrong_answers(), 50, seed=4)]


def test_fewer_failures_than_the_sample_are_all_coded():
    few = {"A": outcome("A", C, U), "B": outcome("B", F, C), "C": outcome("C", C, C)}
    assert {o.item_id for o in sample_failures(few, 50, seed=1)} == {"A", "B"}


# ---------------------------------------------------------------------------------- signals


def test_repeated_calls_suggest_step_repetition():
    events = [event("tool.repeated", "SA", tool="cma_register_lookup")] * 3
    signals = signals_of(events, outcome("x", C, U))
    assert "cma_register_lookup x3" in str(signals[0]) and suggested(signals) == {"FM-1.3"}


def test_an_output_that_never_fit_its_shape_suggests_disobeying_the_task():
    events = [event("agent.failed", code="invalid_output", detail="no JSON")]
    assert suggested(signals_of(events, outcome("x", C, U))) == {"FM-1.1"}


def test_a_challenge_with_no_reply_suggests_ignored_input():
    events = [
        event(
            "message.sent", msg_id="M1", sender="REC", recipients=["CMA"], performative="CHALLENGE"
        ),
        event(
            "message.sent", msg_id="M2", sender="REC", recipients=["VARA"], performative="CHALLENGE"
        ),
        event(
            "message.sent",
            msg_id="M3",
            sender="CMA",
            recipients=["REC"],
            performative="REVISE",
            in_reply_to="M1",
        ),
    ]
    signals = signals_of(events, outcome("x", C, U))
    open_ = [s for s in signals if s.suggests == "FM-2.5"]
    assert len(open_) == 1 and "to VARA" in open_[0].fact


def test_an_approved_wrong_result_suggests_incorrect_verification():
    events = [
        event("proposal.created", version=1, result="UNVERIFIED"),
        event("verifier.decision", decision="APPROVE"),
    ]
    assert "FM-3.3" in suggested(signals_of(events, outcome("x", C, U)))


def test_a_veto_that_blocked_a_right_proposal_suggests_incorrect_verification():
    events = [
        event("proposal.created", version=1, result="CONSISTENT"),
        event("verifier.decision", decision="VETO"),
    ]
    signals = signals_of(events, outcome("x", C, U, reasons=("U6",)))
    assert any("veto stood" in s.fact and s.suggests == "FM-3.3" for s in signals)


def test_a_disagreement_with_the_policy_is_reported_without_a_mode():
    events = [
        event("proposal.created", version=1, result="UNVERIFIED"),
        event("policy.derived", result="CONSISTENT"),
    ]
    signals = signals_of(events, outcome("x", C, U))
    assert any("policy derived CONSISTENT" in s.fact and s.suggests is None for s in signals)


def test_relevance_against_the_gold_list_is_a_fact_not_a_mode():
    signals = signals_of(
        [event("round.started", phase="R0")],
        outcome("x", C, U, gold_relevant=("CMA",), relevant=("CMA", "FSRA")),
    )
    assert [s.fact for s in signals] == [
        "the result's relevant regulators differ from the gold list: extra FSRA"
    ]
    failed = signals_of(
        [event("round.started", phase="R0")], outcome("x", C, U, gold_relevant=("CMA",))
    )
    assert [s.fact for s in failed] == ["the result names no relevant regulators"]


def test_a_job_with_no_events_says_so():
    assert suggested(signals_of([], outcome("x", C, U, failed=True))) == {"NM-PROVIDER"}


# ----------------------------------------------------------------------------------- traces


def test_a_trace_keeps_what_agents_posted_and_said_and_how_it_ended():
    events = [
        event("round.started", phase="R0"),
        event(
            "finding.posted",
            author="JUR",
            finding_id="F-J1",
            assertion={"type": "activity", "code": "SEC.ADVICE", "rationale": "long words"},
        ),
        event("llm.response", round=0),
        event(
            "message.sent",
            sender="REC",
            recipients=["CMA"],
            performative="CHALLENGE",
            rationale="Which card?",
        ),
        event(
            "message.sent",
            sender="REC",
            recipients=["ORC"],
            performative="INFORM",
            rationale="noise",
        ),
        event("result.finalized", result="UNVERIFIED"),
    ]
    lines = trace_lines(events)
    assert lines == [
        "-- R0",
        "JUR posted F-J1 activity(code=SEC.ADVICE)",
        "REC -> CMA CHALLENGE: Which card?",
        "final: UNVERIFIED",
    ]


def test_a_long_trace_is_cut_in_the_middle_and_keeps_its_end():
    events = [event("round.started", phase=f"R{i}") for i in range(100)]
    events.append(event("result.finalized", result="CONFLICTS"))
    lines = trace_lines(events, limit=10)
    assert len(lines) == 10 and lines[-1] == "final: CONFLICTS" and "not shown" in lines[-2]


def test_a_trace_shows_a_restricted_value_only_as_its_placeholder():
    placeholder = "⟦R:FIRM-1⟧"
    events = [
        event(
            "finding.posted",
            author="DFSA",
            finding_id="F-D1",
            assertion={"type": "offer_claim", "value": placeholder},
        )
    ]
    assert placeholder in trace_lines(events)[0]


# ----------------------------------------------------------------------------------- sheets


def test_a_sheet_row_holding_a_dfsa_value_must_go_under_restricted(tmp_path):
    rows = failure_rows([outcome("D1", C, U)], {"D1": item("D1", restricted=True)}, {}, "CREW-FULL")
    with pytest.raises(PermissionError):
        write_failure_sheet(rows, tmp_path / "review" / "failures-A.csv")
    assert write_failure_sheet(
        rows, tmp_path / "restricted" / "review" / "failures-A.csv"
    ).is_file()


def test_codes_are_read_back_several_to_a_row(tmp_path):
    sheet = tmp_path / "A.csv"
    sheet.write_text("item_id,codes\nx,fm-1.3; FM-3.3\ny,NM-LABEL\n", encoding="utf-8")
    assert read_codes(sheet) == {"x": {"FM-1.3", "FM-3.3"}, "y": {"NM-LABEL"}}


@pytest.mark.parametrize("codes", ["", "FM-9.9", "FM-1.1 scam"])
def test_a_missing_or_unknown_code_stops_the_import(tmp_path, codes):
    sheet = tmp_path / "A.csv"
    sheet.write_text(f"item_id,codes\nx,{codes}\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="item x"):
        read_codes(sheet)


# ---------------------------------------------------------------------------------- summary


def test_counts_are_by_mode_and_by_category_and_overlap():
    codes = {
        "a": frozenset({"FM-1.3", "FM-3.3"}),
        "b": frozenset({"FM-3.3"}),
        "c": frozenset({"NM-LABEL"}),
    }
    summary = summarize_codes(codes)
    assert summary["failures"] == 3
    assert summary["modes"]["FM-3.3"]["count"] == 2
    assert summary["categories"]["FC3"]["count"] == 2 and summary["categories"]["FC1"]["count"] == 1
    assert summary["outside_mast_only"] == {"count": 1, "share": pytest.approx(1 / 3)}


def test_agreement_is_kappa_on_each_mode_and_lists_what_to_discuss():
    first = {"a": frozenset({"FM-1.3"}), "b": frozenset({"FM-3.3"}), "c": frozenset({"NM-LABEL"})}
    second = {"a": frozenset({"FM-1.3"}), "b": frozenset({"FM-3.2"}), "c": frozenset({"NM-LABEL"})}
    agreement = code_agreement(first, second)
    assert agreement["items"] == 3 and agreement["to_discuss"] == ["b"]
    assert agreement["kappa_by_mode"]["FM-1.3"] == 1.0
    assert agreement["kappa_by_mode"]["FM-2.1"] == 1.0, "a mode neither coder used"
    assert agreement["kappa_by_mode"]["FM-3.3"] < 1.0
    assert agreement["same_codes"] == pytest.approx(2 / 3)


def test_sheets_with_no_items_in_common_cannot_be_compared():
    with pytest.raises(PolicyError):
        code_agreement({"a": frozenset({"FM-1.1"})}, {"b": frozenset({"FM-1.1"})})


# -------------------------------------------------------------------------- the commands


def run_folder(tmp_path):
    """A finished run on three items: one right, one wrong, one wrong and restricted."""
    items = [
        item("M-1", C, split=Split.TEST),
        item("M-2", C, split=Split.TEST),
        item("M-3", F, split=Split.TEST, restricted=True),
    ]
    write_items(tmp_path / "restricted" / "items.jsonl", items)
    run = tmp_path / "run"
    for item_id, result in (("M-1", "CONSISTENT"), ("M-2", "UNVERIFIED"), ("M-3", "UNVERIFIED")):
        path = run / "records" / "CREW-FULL" / "0" / f"{item_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"item_id": item_id, "condition": "CREW-FULL", "run": 0, "result": result}
        path.write_text(json.dumps({**record, "case_id": f"{item_id}~CREW-FULL~0"}), "utf-8")
    store = EventStore(run / "events.sqlite")
    store.append(event("tool.repeated", "CMA", case="M-2~CREW-FULL~0", tool="cma_register_lookup"))
    store.append(event("result.finalized", case="M-2~CREW-FULL~0", result="UNVERIFIED"))
    store.close()
    return tmp_path / "restricted" / "items.jsonl", run


def test_the_failures_command_writes_public_and_restricted_sheets_apart(tmp_path, capsys):
    items, run = run_folder(tmp_path)
    out = tmp_path / "review"
    assert main(["failures", "--items", str(items), "--run-dir", str(run), "--out", str(out)]) == 0
    public = list(csv.DictReader((out / "failures-A.csv").open(encoding="utf-8", newline="")))
    assert [row["item_id"] for row in public] == ["M-2"]
    assert (
        "cma_register_lookup x1" in public[0]["signals"]
        and "final: UNVERIFIED" in public[0]["trace"]
    )
    hidden = tmp_path / "restricted" / "review" / "failures-A.csv"
    assert [
        row["item_id"] for row in csv.DictReader(hidden.open(encoding="utf-8", newline=""))
    ] == ["M-3"]
    assert "2 failures of 3 items" in capsys.readouterr().out


def test_the_codes_command_counts_and_compares(tmp_path, capsys):
    first, second = tmp_path / "A.csv", tmp_path / "B.csv"
    first.write_text("item_id,codes\nx,FM-1.3\ny,NM-LABEL\n", encoding="utf-8")
    second.write_text("item_id,codes\nx,FM-1.3\ny,FM-3.3\n", encoding="utf-8")
    out = tmp_path / "summary.json"
    assert (
        main(["failure-codes", "--codes", str(first), "--second", str(second), "--out", str(out)])
        == 0
    )
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["modes"]["FM-1.3"]["count"] == 1 and summary["agreement"]["to_discuss"] == ["y"]
    assert "to discuss: y" in capsys.readouterr().out


def test_a_bad_code_is_a_clear_error_not_a_crash(tmp_path, capsys):
    sheet = tmp_path / "A.csv"
    sheet.write_text("item_id,codes\nx,FM-7.7\n", encoding="utf-8")
    assert main(["failure-codes", "--codes", str(sheet)]) == 2
    assert "unknown codes" in capsys.readouterr().err
