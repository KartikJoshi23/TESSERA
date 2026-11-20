"""The write-up's figures: static SVG with a CSV beside each (§17.4)."""

import json
import xml.etree.ElementTree as ET

import pytest

from tessera.evaluation.cli import main
from tessera.evaluation.figures import (
    BLUES,
    FAMILIES,
    IMPROVES,
    WORSENS,
    ablation_figure,
    factors_figure,
    family,
    frontier_figure,
    nice_ticks,
    paper_figures,
    write_figures,
)
from tessera.evaluation.paper import FICTION_NOTE

SVG = "{http://www.w3.org/2000/svg}"


def system(rate, f1, requests, tokens, groups=None, interval=None):
    return {
        "items": 20,
        "false_reassurance_rate": rate,
        "macro_f1": f1,
        "compute": {"requests_per_case": requests, "tokens_per_case": tokens},
        "intervals": {
            "false_reassurance_rate": interval or [max(0.0, rate - 0.02), rate + 0.03],
            "macro_f1": [f1 - 0.05, f1 + 0.05],
        },
        "by_group": groups or {},
    }


def level(**systems):
    return {"level": "message", "items": 20, "systems": systems}


def full_crew():
    return level(
        **{
            "SA-BASE": system(0.06, 0.82, 5.0, 60_000),
            "CREW-SILO": system(0.11, 0.80, 11.0, 80_000),
            "CREW-SHARE": system(0.11, 0.78, 12.0, 88_000),
            "CREW-FULL": system(0.05, 0.83, 13.3, 96_000),
            "CREW-NV": system(0.10, 0.86, 10.5, 70_000),
        }
    )


def parsed(figure):
    return ET.fromstring(figure.svg)


def texts(figure):
    return [element.text for element in parsed(figure).iter(f"{SVG}text")]


def test_ticks_are_round_and_reach_past_the_top():
    assert nice_ticks(0.11, 4) == [0.0, 0.05, 0.1, 0.15]
    assert nice_ticks(330_000, 4) == [0, 100_000, 200_000, 300_000, 400_000]
    assert nice_ticks(0.0) == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def test_systems_fall_into_three_families():
    assert {family(n) for n in ("RULES-ONLY", "SA-MAX", "CREW-NV")} == set(FAMILIES)


def test_every_figure_is_well_formed_svg_with_a_title_and_a_description():
    for figure in paper_figures({"levels": {"message": full_crew()}}):
        root = parsed(figure)
        assert root.find(f"{SVG}title").text and root.find(f"{SVG}desc").text


def test_the_compute_figure_gives_each_system_a_row_and_a_hover_title_for_each_mark():
    figure = frontier_figure(full_crew())
    assert [row["system"] for row in figure.rows] == [
        "SA-BASE",
        "CREW-SILO",
        "CREW-SHARE",
        "CREW-FULL",
        "CREW-NV",
    ]
    marks = [g for g in parsed(figure).iter(f"{SVG}g") if g.find(f"{SVG}title") is not None]
    assert len(marks) == 5 * 3, "a dot and two bars for each system"
    assert "SA-BASE" in texts(figure) and "Crew" in texts(figure), "names and legend in ink"


def test_one_family_needs_no_legend():
    figure = frontier_figure(level(**{"SA-BASE": system(0.06, 0.8, 5, 60_000)}))
    assert "Single agent" not in texts(figure)


def test_text_never_wears_a_series_colour():
    figure = frontier_figure(full_crew())
    for element in parsed(figure).iter(f"{SVG}text"):
        assert element.get("fill") not in FAMILIES.values()


def test_the_waterfall_steps_add_one_mechanism_each_and_colour_by_better_or_worse():
    figure = ablation_figure(full_crew())
    frr = {
        row["step"]: row["value"]
        for row in figure.rows
        if row["metric"] == "false_reassurance_rate"
    }
    assert frr["+ sharing"] == 0.11 and frr["+ challenges"] == 0.05 and frr["− Verifier"] == 0.10
    shown = texts(figure)
    assert "−0.060" in shown, "challenges lowered false reassurance"
    assert "SA-BASE 0.060" in shown, "the baseline as a reference rule"
    fills = [path.get("fill") for path in parsed(figure).iter(f"{SVG}path")]
    assert IMPROVES in fills and WORSENS in fills


def test_the_waterfall_is_left_out_without_every_crew_condition():
    partial = level(**{"CREW-FULL": system(0.05, 0.8, 13, 96_000)})
    assert ablation_figure(partial) is None


def test_the_factor_grid_has_a_cell_for_each_system_and_group_and_darker_is_better():
    groups_a = {"F1": {"items": 8, "accuracy": 1.0, "false_reassurance": 0.0}}
    groups_b = {
        "F1": {"items": 8, "accuracy": 0.0, "false_reassurance": 0.5},
        "F10": {"items": 4, "accuracy": 0.5, "false_reassurance": 0.0},
    }
    figure = factors_figure(
        level(
            **{
                "SA-BASE": system(0.0, 0.9, 5, 1, groups=groups_a),
                "CREW-FULL": system(0.1, 0.7, 13, 1, groups=groups_b),
            }
        )
    )
    cells = {(row["group"], row["system"]): row["accuracy"] for row in figure.rows}
    assert cells == {("F1", "SA-BASE"): 1.0, ("F1", "CREW-FULL"): 0.0, ("F10", "CREW-FULL"): 0.5}
    fills = [r.get("fill") for r in parsed(figure).iter(f"{SVG}rect") if r.get("fill") in BLUES]
    assert BLUES[-1] in fills and BLUES[0] in fills
    assert any(text == "F1 Copied official identifiers (n=8)" for text in texts(figure))
    assert [t for t in texts(figure) if t and t.startswith("F")][:2] == [
        "F1 Copied official identifiers (n=8)",
        "F10 Secondary domain (n=4)",
    ]


def test_fictional_figures_say_so():
    for figure in paper_figures({"levels": {"message": full_crew()}}, fiction=True):
        assert FICTION_NOTE in texts(figure)


@pytest.mark.parametrize("key", ["frontier-message", "ablation-message"])
def test_each_figure_is_written_with_its_table_view(tmp_path, key):
    write_figures(paper_figures({"levels": {"message": full_crew()}}), tmp_path)
    assert (tmp_path / f"figure-{key}.svg").read_text(encoding="utf-8").startswith("<svg")
    assert (tmp_path / f"figure-{key}.csv").read_text(encoding="utf-8").count("\n") >= 5


def test_the_paper_command_writes_figures_too(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    full = full_crew()
    for found in full["systems"].values():
        found.update(
            {
                "unsupported_conflict_rate": 0.0,
                "coverage": 0.8,
                "decisive_accuracy": 0.9,
                "cost_weighted_error": 0.3,
                "coordination": {},
            }
        )
    full |= {"registered": [], "secondary": [], "non_inferiority": {"tested": False}}
    report_path.write_text(json.dumps({"levels": {"message": full}}), encoding="utf-8")
    assert main(["paper", "--report", str(report_path), "--out", str(tmp_path / "out")]) == 0
    assert "figure-ablation-message.svg" in capsys.readouterr().out
