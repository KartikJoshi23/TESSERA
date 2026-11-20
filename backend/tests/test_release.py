"""The release check: the data-governance checklist, done by machine (§12.7, §17.5).

Keys and DFSA links are built from parts, so the commit guard does not flag this file.
"""

import json

from tessera.evaluation.cli import main
from tessera.evaluation.release import check_release
from tessera.governance.masking import RestrictedValue

from .conftest import REPO_ROOT

DFSA_VALUE = "Harbour Example (DIFC) Limited"
VARA_FACT = "examplevasp.example"


def check(*paths):
    return check_release(
        list(paths),
        root=REPO_ROOT,
        restricted=[RestrictedValue(DFSA_VALUE, "firm_name")],
        vara={VARA_FACT, "Example VASP FZE"},
    )


def test_clean_files_pass(tmp_path):
    (tmp_path / "tables.md").write_text("| System | FRR |\n| CREW-FULL | 0.03 |\n", "utf-8")
    result = check(tmp_path)
    assert result.passed and result.files == 1


def test_files_that_stay_local_fail_by_name_or_place(tmp_path):
    for name in ("restricted/x.md", ".env", "runs/events.sqlite", "data/snapshots/a.csv", "PS.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("plain\n", encoding="utf-8")
    problems = "\n".join(check(tmp_path).problems)
    for reason in ("restricted folder", "stays local", "run log", "register data"):
        assert reason in problems
    assert "PS.md: this file stays local" in problems


def test_a_dfsa_value_fails_and_is_never_printed(tmp_path):
    (tmp_path / "draft.md").write_text(f"We saw {DFSA_VALUE.upper()} in a case.\n", "utf-8")
    (problem,) = check(tmp_path).problems
    assert "a DFSA value" in problem and DFSA_VALUE.casefold() not in problem.casefold()


def test_a_vara_fact_fails(tmp_path):
    (tmp_path / "items.md").write_text(f"Sign up at {VARA_FACT}.\n", "utf-8")
    assert any("a VARA fact" in p for p in check(tmp_path).problems)


def test_the_commit_guard_s_content_rules_apply(tmp_path):
    link = "https://www." + "dfsa.ae" + "/alerts/one"
    key = "nvapi-" + "x" * 24
    (tmp_path / "notes.md").write_text(f"{link}\nkey {key}\n", "utf-8")
    problems = "\n".join(check(tmp_path).problems)
    assert "deep link" in problems and "NVIDIA API key" in problems
    assert key not in problems, "a key is never echoed"


def test_restricted_and_entity_level_items_fail(tmp_path):
    rows = [
        {"item_id": "M1", "level": "message", "synthetic": True, "restricted": True},
        {"item_id": "E1", "level": "entity", "synthetic": True, "restricted": False},
        {"item_id": "M2", "level": "message", "synthetic": True, "restricted": False},
    ]
    (tmp_path / "items.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    problems = "\n".join(check(tmp_path).problems)
    assert "line 1: an item built from DFSA facts" in problems
    assert "line 2: an entity-level item" in problems
    assert "line 3" not in problems


def test_a_file_that_is_not_text_is_left_to_a_person(tmp_path):
    (tmp_path / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
    result = check(tmp_path)
    assert result.passed and result.by_eye == ("shot.png",)


def test_the_command_passes_the_lab_s_committed_data(capsys):
    assert (
        main(["release-check", "--fiction", "--path", str(REPO_ROOT / "frontend" / "src" / "data")])
        == 0
    )
    assert "passed" in capsys.readouterr().out


def test_the_command_fails_a_fictional_dfsa_value(tmp_path, capsys):
    (tmp_path / "draft.md").write_text(
        "Lumen Crest Capital (DIFC) Limited, FRN F000000.\n", "utf-8"
    )
    assert main(["release-check", "--fiction", "--path", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "a DFSA value" in out and "F000000" not in out
