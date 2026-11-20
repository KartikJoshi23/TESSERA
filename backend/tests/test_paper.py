"""The write-up's tables, built from a report and the item files (§17.4)."""

import json

from tessera.evaluation.cli import main
from tessera.evaluation.items import EvalItem, Level, Split, write_items
from tessera.evaluation.paper import (
    FICTION_NOTE,
    Table,
    comparisons_table,
    coordination_table,
    datasets_table,
    paper_tables,
    results_table,
    write_tables,
)
from tessera.evaluation.plan import load_plan
from tessera.evaluation.report import evaluation_report
from tessera.protocol.common import ResultCode

from .conftest import REPO_ROOT

PLAN = load_plan(REPO_ROOT / "eval" / "plan.yaml")
C, F, U = ResultCode.CONSISTENT, ResultCode.CONFLICTS, ResultCode.UNVERIFIED
TELEMETRY = {
    "challenges": {"sent": 2, "revisions": 1},
    "verifier": {"vetoes": 1},
    "conflicts": {"total": 2},
    "conformity_flags": 0,
    "repairs": 1,
}


def item(item_id, gold, **changes):
    return EvalItem(
        item_id=item_id,
        level=Level.MESSAGE,
        text="An invented offer at invented.example.",
        gold_label=gold,
        origin="template",
        split=Split.TEST,
        **changes,
    )


def a_run():
    items = [item("M1", C), item("M2", F), item("M3", U), item("M4", U, restricted=True)]
    answers = {
        "SA-BASE": ("CONSISTENT", "CONFLICTS", "CONSISTENT", "UNVERIFIED"),
        "CREW-FULL": ("CONSISTENT", "CONFLICTS", "UNVERIFIED", "UNVERIFIED"),
        "RULES-ONLY": ("UNVERIFIED", "CONFLICTS", "UNVERIFIED", "UNVERIFIED"),
    }
    records = [
        {
            "item_id": it.item_id,
            "condition": condition,
            "run": 0,
            "result": result,
            "requests": 5,
            "tokens": 1000,
            "seconds": 9.0,
            "telemetry": TELEMETRY,
            "proposals": [],
        }
        for condition, results in answers.items()
        for it, result in zip(items, results, strict=True)
    ]
    return items, evaluation_report(items, records, PLAN)


def test_a_table_renders_as_markdown_and_as_booktabs_latex():
    table = Table("x", "Rates & 50% of A_B", ("System", "Value"), (("CREW-FULL", "−0.1"),))
    markdown = table.markdown()
    assert "| System | Value |" in markdown and "|---|---|" in markdown
    latex = table.latex()
    assert "\\toprule" in latex and "\\bottomrule" in latex and "\\label{tab:x}" in latex
    assert "Rates \\& 50\\% of A\\_B" in latex and "$-$0.1" in latex


def test_systems_come_in_the_lab_s_order_with_intervals():
    _, report = a_run()
    table = results_table(report["levels"]["message"])
    assert [row[0] for row in table.rows] == ["RULES-ONLY", "SA-BASE", "CREW-FULL"]
    single = table.rows[1]
    # One false reassurance among the three items whose gold is not Consistent.
    assert single[2].startswith("0.333 [") and single[2].endswith("]"), "FRR with its interval"


def test_comparisons_show_paired_differences_and_holm_only_for_the_secondary_family():
    _, report = a_run()
    table = comparisons_table(report["levels"]["message"])
    names = [row[0] for row in table.rows]
    assert names == ["H1 false reassurance (registered)", "H2 usefulness (registered)"]
    assert table.rows[0][1] == "CREW-FULL − SA-BASE" and table.rows[0][6] == "–"
    assert table.rows[0][3].startswith("−0.333"), "the crew reassured once less, of three"
    assert any("H2 non-inferiority" in note for note in table.notes)


def test_only_systems_with_mechanisms_appear_in_the_coordination_table():
    _, report = a_run()
    table = coordination_table(report["levels"]["message"])
    assert [row[0] for row in table.rows] == ["CREW-FULL"]
    assert table.rows[0][1] == "2.00" and table.rows[0][3] == "0.50"


def test_the_datasets_table_counts_labels_origins_and_dfsa_derived_items():
    items, _ = a_run()
    (row,) = datasets_table(items).rows
    assert row == ("Message level", "test", "4", "1", "1", "2", "4", "0", "0", "0", "1")


def test_fictional_tables_say_so_in_caption_and_note():
    items, report = a_run()
    for table in paper_tables(report, items, fiction=True):
        assert "FICTIONAL" in table.caption and FICTION_NOTE in table.notes
    for table in paper_tables(report, items):
        assert "FICTIONAL" not in table.caption and FICTION_NOTE not in table.notes


def test_every_table_is_written_both_ways_and_together(tmp_path):
    items, report = a_run()
    written = write_tables(paper_tables(report, items), tmp_path)
    names = {path.name for path in written}
    assert {"datasets.md", "datasets.tex", "results-message.tex", "tables.md"} <= names
    assert "Coordination diagnostics" in (tmp_path / "tables.md").read_text(encoding="utf-8")


def test_the_paper_command_builds_tables_from_a_saved_report(tmp_path, capsys):
    items, report = a_run()
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    item_path = tmp_path / "restricted" / "items.jsonl"
    write_items(item_path, items)
    out = tmp_path / "tables"
    argv = ["paper", "--report", str(report_path), "--items", str(item_path), "--out", str(out)]
    assert main([*argv, "--fiction"]) == 0
    assert "FICTIONAL" in (out / "results-message.md").read_text(encoding="utf-8")
    assert "datasets.md" in capsys.readouterr().out


def test_an_empty_report_gives_no_tables(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"levels": {}}), encoding="utf-8")
    assert main(["paper", "--report", str(report_path), "--out", str(tmp_path / "t")]) == 2
    assert "no results" in capsys.readouterr().out
