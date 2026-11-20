"""The write-up's tables (§17.4): datasets, main results with intervals, and coordination.

Every table is built from the item files and the report the harness writes, never typed by hand,
so each number in a draft can be traced to a run. Each comes as Markdown, for drafts, and as LaTeX
with booktabs, for the paper. Tables built from fictional data say so in their captions, so they
cannot pass for results.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessera.evaluation.items import EvalItem, Level, Split
from tessera.protocol.common import ResultCode

#: The order systems are shown in, from no model to the full crew, as in the Lab.
SYSTEM_ORDER = (
    "RULES-ONLY",
    "SA-BASE",
    "SA-VER",
    "SA-SC5",
    "SA-MAX",
    "SA-LARGER",
    "CREW-SILO",
    "CREW-SHARE",
    "CREW-FULL",
    "CREW-NV",
)
#: Systems with conflicts, challenges or a Verifier. For the rest, Table 3's zeros would mislead.
WITH_MECHANISMS = frozenset({"SA-VER", "CREW-SILO", "CREW-SHARE", "CREW-FULL", "CREW-NV"})
FICTION_NOTE = "Fictional development data. These numbers say nothing about final performance."
_DASH = "–"
_LABELS = (ResultCode.CONSISTENT, ResultCode.CONFLICTS, ResultCode.UNVERIFIED)
_ORIGINS: tuple[str, ...] = ("template", "paraphrase", "human", "entity_card")
_COORDINATION = (
    ("conflicts_per_case", "Conflicts / case", 2),
    ("challenges_per_case", "Challenges / case", 2),
    ("revision_rate", "Revision rate", 2),
    ("veto_rate", "Veto rate", 2),
    ("veto_precision", "Veto precision", 2),
    ("veto_recall", "Veto recall", 2),
    ("rescue_rate", "Rescue rate", 2),
    ("conformity_flags_per_case", "Conformity flags / case", 2),
    ("repairs_per_case", "Repairs / case", 2),
)


@dataclass(frozen=True)
class Table:
    key: str
    caption: str
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    notes: tuple[str, ...] = ()

    def markdown(self) -> str:
        lines = [f"**{self.caption}**", "", _md_row(self.header)]
        lines.append("|" + "|".join("---" for _ in self.header) + "|")
        lines += [_md_row(row) for row in self.rows]
        lines += ["", *(f"*{note}*" for note in self.notes)] if self.notes else []
        return "\n".join(lines) + "\n"

    def latex(self) -> str:
        columns = "l" + "r" * (len(self.header) - 1)
        body = [
            "\\begin{table}[t]",
            "\\centering",
            "\\small",
            f"\\caption{{{_tex(self.caption)}}}",
            f"\\label{{tab:{self.key}}}",
            f"\\begin{{tabular}}{{{columns}}}",
            "\\toprule",
            _tex_row(self.header),
            "\\midrule",
            *(_tex_row(row) for row in self.rows),
            "\\bottomrule",
            "\\end{tabular}",
        ]
        body += [f"\\par\\smallskip\\footnotesize {_tex(note)}" for note in self.notes]
        body.append("\\end{table}")
        return "\n".join(body) + "\n"


def _md_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


_TEX = {
    "\\": "\\textbackslash{}",
    "&": "\\&",
    "%": "\\%",
    "$": "\\$",
    "#": "\\#",
    "_": "\\_",
    "{": "\\{",
    "}": "\\}",
    "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
    _DASH: "--",
    "−": "$-$",
}


def _tex(text: str) -> str:
    return "".join(_TEX.get(char, char) for char in text)


def _tex_row(cells: Sequence[str]) -> str:
    return " & ".join(_tex(cell) for cell in cells) + " \\\\"


# ------------------------------------------------------------------------------- formatting


def _number(value: float | None, places: int = 3) -> str:
    return _DASH if value is None else f"{value:.{places}f}"


def _with_interval(value: float | None, interval: Sequence[float] | None, places: int = 3) -> str:
    if value is None:
        return _DASH
    if not interval:
        return _number(value, places)
    low, high = interval
    return f"{value:.{places}f} [{low:.{places}f}, {high:.{places}f}]"


def _signed(value: float) -> str:
    return f"{value:+.3f}".replace("-", "−")


def _p(value: float | None) -> str:
    if value is None:
        return _DASH
    return "<0.001" if value < 0.001 else f"{value:.3f}"


def _ordered(systems: dict[str, Any]) -> list[tuple[str, Any]]:
    def rank(name: str) -> tuple[int, str]:
        return (SYSTEM_ORDER.index(name) if name in SYSTEM_ORDER else len(SYSTEM_ORDER), name)

    return sorted(systems.items(), key=lambda pair: rank(pair[0]))


def _caption(text: str, fiction: bool) -> str:
    return f"{text} (FICTIONAL DEVELOPMENT DATA)" if fiction else text


def _notes(fiction: bool, *extra: str) -> tuple[str, ...]:
    return (*((FICTION_NOTE,) if fiction else ()), *extra)


# ----------------------------------------------------------------------------------- tables


def datasets_table(items: Sequence[EvalItem], *, fiction: bool = False) -> Table:
    """Table 1: each set and split, by label, by how the text was written, and DFSA-derived."""
    groups: dict[tuple[Level, str], list[EvalItem]] = {}
    for item in items:
        split = item.split.value if item.split else "unsplit"
        groups.setdefault((item.level, split), []).append(item)
    order = {Split.DEV.value: 0, Split.TEST.value: 1, "unsplit": 2}
    rows = []
    for (level, split), members in sorted(groups.items(), key=lambda g: (g[0][0], order[g[0][1]])):
        labels = Counter(item.gold_label for item in members)
        origins = Counter(str(item.origin) for item in members)
        rows.append(
            (
                f"{level.value.capitalize()} level",
                split,
                str(len(members)),
                *(str(labels[label]) for label in _LABELS),
                *(str(origins[origin]) for origin in _ORIGINS),
                str(sum(item.restricted for item in members)),
            )
        )
    return Table(
        "datasets",
        _caption("Datasets", fiction),
        (
            "Set",
            "Split",
            "Items",
            "Consistent",
            "Conflicts",
            "Could not verify",
            "Template",
            "Paraphrase",
            "Written by people",
            "Entity card",
            "From DFSA facts",
        ),
        tuple(rows),
        _notes(fiction, "Items built from DFSA facts are kept local and are never released."),
    )


def results_table(level: dict[str, Any], *, fiction: bool = False) -> Table:
    """Table 2: every system on one level, with 95% bootstrap intervals for the headline metrics."""
    rows = []
    for name, system in _ordered(level["systems"]):
        intervals = system.get("intervals", {})
        compute = system.get("compute", {})
        rows.append(
            (
                name,
                str(system["items"]),
                _with_interval(
                    system["false_reassurance_rate"], intervals.get("false_reassurance_rate")
                ),
                _with_interval(system["macro_f1"], intervals.get("macro_f1")),
                _number(system["coverage"]),
                _number(system["decisive_accuracy"]),
                _number(system["cost_weighted_error"]),
                _number(compute.get("requests_per_case"), 1),
                _number(compute.get("tokens_per_case"), 0),
            )
        )
    return Table(
        f"results-{level['level']}",
        _caption(f"Main results, {level['level']} level ({level['items']} items)", fiction),
        (
            "System",
            "n",
            "False reassurance [95% CI]",
            "Macro-F1 [95% CI]",
            "Coverage",
            "Decisive accuracy",
            "Cost-weighted error",
            "Requests / case",
            "Tokens / case",
        ),
        tuple(rows),
        _notes(
            fiction,
            "False reassurance is the primary safety metric: a Consistent answer when the record "
            "does not support one. Lower is better.",
        ),
    )


def comparisons_table(level: dict[str, Any], *, fiction: bool = False) -> Table:
    """The registered and secondary comparisons, with paired intervals and exact McNemar tests."""
    rows = []
    for kind, comparisons in (
        ("Registered", level["registered"]),
        ("Secondary", level["secondary"]),
    ):
        for comparison in comparisons:
            if not comparison.get("pairs"):
                continue
            rows.append(
                (
                    f"{comparison['name']} ({kind.lower()})",
                    f"{comparison['first']} − {comparison['second']}",
                    str(comparison["pairs"]),
                    f"{_signed(comparison['difference'])} "
                    f"[{_signed(comparison['ci_low'])}, {_signed(comparison['ci_high'])}]",
                    f"{comparison['only_first']} / {comparison['only_second']}",
                    _p(comparison.get("p_value")),
                    _p(comparison.get("p_holm")) if kind == "Secondary" else _DASH,
                )
            )
    held = level.get("non_inferiority", {})
    extra = []
    if held.get("tested"):
        verdict = "holds" if held["holds"] else "does not hold"
        extra.append(
            f"H2 non-inferiority at a margin of {held['margin']}: {verdict} "
            f"(interval's lower end {_signed(held['ci_low'])})."
        )
    return Table(
        f"comparisons-{level['level']}",
        _caption(f"Comparisons, {level['level']} level", fiction),
        (
            "Comparison",
            "Systems",
            "Pairs",
            "Difference [95% CI]",
            "Discordant (first / second)",
            "p",
            "p (Holm)",
        ),
        tuple(rows),
        _notes(
            fiction,
            "Discordant counts the items where only one system had the event; the exact McNemar "
            "test uses them. Holm's correction applies to the secondary family only.",
            *extra,
        ),
    )


def coordination_table(level: dict[str, Any], *, fiction: bool = False) -> Table:
    """Table 3: how the crew's mechanisms behaved, for every system that has them."""
    rows = [
        (
            name,
            *(_number(system["coordination"].get(key), places) for key, _, places in _COORDINATION),
        )
        for name, system in _ordered(level["systems"])
        if name in WITH_MECHANISMS and system.get("coordination")
    ]
    return Table(
        f"coordination-{level['level']}",
        _caption(f"Coordination diagnostics, {level['level']} level", fiction),
        ("System", *(title for _, title, _ in _COORDINATION)),
        tuple(rows),
        _notes(
            fiction,
            "Veto precision is the share of vetoed proposals that were wrong. Veto recall is the "
            "share of wrong Consistent proposals that were vetoed. Rescue is how often a wrong "
            "first proposal ended right.",
        ),
    )


def paper_tables(
    report: dict[str, Any], items: Sequence[EvalItem] = (), *, fiction: bool = False
) -> list[Table]:
    """Every table the report supports, in the order the paper uses them."""
    tables = [datasets_table(items, fiction=fiction)] if items else []
    builders: tuple[Callable[..., Table], ...] = (
        results_table,
        comparisons_table,
        coordination_table,
    )
    for build in builders:
        for level in report["levels"].values():
            table = build(level, fiction=fiction)
            if table.rows:
                tables.append(table)
    return tables


def write_tables(tables: Sequence[Table], folder: Path) -> list[Path]:
    """One Markdown and one LaTeX file per table, and all the Markdown together for reading."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for table in tables:
        for suffix, text in ((".md", table.markdown()), (".tex", table.latex())):
            path = folder / f"{table.key}{suffix}"
            path.write_text(text, encoding="utf-8")
            written.append(path)
    together = folder / "tables.md"
    together.write_text("\n".join(table.markdown() for table in tables), encoding="utf-8")
    return [*written, together]
