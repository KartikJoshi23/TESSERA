"""Coding failures with MAST, the multi-agent failure taxonomy of Cemri et al. (2025) (§11.3).

A failure is an item a system got wrong. A seeded sample of them goes on a sheet, one row each,
with a short trace from the event log and the signals the log shows for certain. People code each
row with one or more failure modes, as the MAST paper's own examples do.

Nothing here sets a code. A signal is a fact about the trace, and a few facts suggest a mode, which
a person may accept or reject. MAST's modes describe failures of a multi-agent system, and many
failures here are plain mistakes inside one agent or a wrong label, so a few codes outside MAST keep
those from being forced into it. Definitions are in our own words; the names and numbers are the
paper's (arXiv 2503.13657, v3, Appendix A).
"""

from __future__ import annotations

import csv
import random
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessera.blackboard.store import Event
from tessera.errors import PolicyError
from tessera.evaluation.items import EvalItem, guard_restricted
from tessera.evaluation.metrics import Outcome
from tessera.evaluation.statistics import cohen_kappa

#: The plan's minimum sample (§11.3). With fewer failures than this, every one is coded.
SAMPLE_SIZE = 50
#: A trace on a sheet stops here. A person who needs more opens the case in the replay view.
TRACE_LINES = 60
_CLIP = 160


@dataclass(frozen=True)
class Mode:
    code: str
    category: str
    name: str
    meaning: str


CATEGORIES = {
    "FC1": "System design issues",
    "FC2": "Inter-agent misalignment",
    "FC3": "Task verification",
    "NM": "Outside MAST",
}

MODES = (
    Mode(
        "FM-1.1",
        "FC1",
        "Disobey task specification",
        "An agent breaks a stated requirement of its task, such as its output shape or a rule.",
    ),
    Mode(
        "FM-1.2",
        "FC1",
        "Disobey role specification",
        "An agent does another role's job, or leaves its own undone.",
    ),
    Mode("FM-1.3", "FC1", "Step repetition", "An agent repeats work it has already done."),
    Mode(
        "FM-1.4",
        "FC1",
        "Loss of conversation history",
        "An agent loses context it had, and acts as if from an earlier point.",
    ),
    Mode(
        "FM-1.5",
        "FC1",
        "Unaware of termination conditions",
        "An agent does not see when to stop, and carries on until a limit stops it.",
    ),
    Mode(
        "FM-2.1",
        "FC2",
        "Conversation reset",
        "An exchange starts over for no reason, and its progress is lost.",
    ),
    Mode(
        "FM-2.2",
        "FC2",
        "Fail to ask for clarification",
        "An agent acts on a guess where it could have asked another agent.",
    ),
    Mode(
        "FM-2.3",
        "FC2",
        "Task derailment",
        "Agents drift from the question into work that does not answer it.",
    ),
    Mode(
        "FM-2.4",
        "FC2",
        "Information withholding",
        "An agent keeps back a finding that would have changed another agent's work.",
    ),
    Mode(
        "FM-2.5",
        "FC2",
        "Ignored other agent's input",
        "An agent passes over a finding, challenge or reply that bears on its work.",
    ),
    Mode(
        "FM-2.6",
        "FC2",
        "Reasoning-action mismatch",
        "What an agent posts does not follow from its own stated reasoning.",
    ),
    Mode(
        "FM-3.1",
        "FC3",
        "Premature termination",
        "The case ends before the checks or exchanges it needs are done.",
    ),
    Mode(
        "FM-3.2",
        "FC3",
        "No or incomplete verification",
        "A check that would have caught the error was missing or partial.",
    ),
    Mode(
        "FM-3.3",
        "FC3",
        "Incorrect verification",
        "A check ran but reached the wrong verdict, passing an error or blocking a sound result.",
    ),
    Mode(
        "NM-READING",
        "NM",
        "Reading error",
        "One agent misread the offer or a record: an activity, a zone, a claim or a match.",
    ),
    Mode(
        "NM-KNOWLEDGE",
        "NM",
        "Knowledge gap",
        "A rule card or guidance file was missing or wrong.",
    ),
    Mode("NM-TOOL", "NM", "Tool or data fault", "A tool or a snapshot gave a wrong answer."),
    Mode(
        "NM-PROVIDER",
        "NM",
        "Provider fault",
        "The model provider refused, timed out or returned an unusable reply.",
    ),
    Mode("NM-LABEL", "NM", "Label problem", "The gold label is wrong, or the item is ambiguous."),
)
BY_CODE = {mode.code: mode for mode in MODES}

SHEET_COLUMNS = (
    "item_id",
    "condition",
    "gold",
    "predicted",
    "reasons",
    "signals",
    "trace",
    "codes",
    "note",
)
#: Agent failures whose cause the log states plainly.
_FAILURE_MODES = {
    "invalid_output": "FM-1.1",
    "budget_exceeded": "FM-1.5",
    "model_error": "NM-PROVIDER",
    "refused": "NM-PROVIDER",
}
_REPLIES = {"REBUT", "REVISE", "CONCEDE"}


@dataclass(frozen=True)
class Signal:
    """Something the log shows for certain, and the mode it suggests, if any."""

    fact: str
    suggests: str | None = None

    def __str__(self) -> str:
        return f"{self.fact} (suggests {self.suggests})" if self.suggests else self.fact


@dataclass(frozen=True)
class FailureRow:
    item: EvalItem
    outcome: Outcome
    condition: str
    signals: tuple[Signal, ...]
    trace: str


# ------------------------------------------------------------------------------------ sampling


def failures_of(outcomes: Mapping[str, Outcome]) -> list[Outcome]:
    """Every item answered wrongly, a job that gave no result included."""
    return sorted(
        (o for o in outcomes.values() if o.predicted is not o.gold), key=lambda o: o.item_id
    )


def sample_failures(
    outcomes: Mapping[str, Outcome], size: int = SAMPLE_SIZE, *, seed: int
) -> list[Outcome]:
    """A sample that keeps each kind of error in proportion, by gold and predicted result.

    Every kind of error that occurred is represented at least once, so a rare but serious one,
    such as a false reassurance, is never left out. The order is shuffled, so coders do not meet
    all of one kind together.
    """
    wrong = failures_of(outcomes)
    rng = random.Random(seed)
    if len(wrong) <= size:
        rng.shuffle(wrong)
        return wrong
    kinds: dict[tuple[str, str], list[Outcome]] = defaultdict(list)
    for outcome in wrong:
        kinds[(outcome.gold.value, outcome.predicted.value)].append(outcome)
    quotas = {kind: max(1, len(group) * size // len(wrong)) for kind, group in kinds.items()}
    # Largest remainders take what rounding down left over.
    order = sorted(kinds, key=lambda kind: -(len(kinds[kind]) * size % len(wrong)))
    for kind in order:
        if sum(quotas.values()) >= size:
            break
        if quotas[kind] < len(kinds[kind]):
            quotas[kind] += 1
    chosen = [o for kind in sorted(kinds) for o in rng.sample(kinds[kind], quotas[kind])]
    rng.shuffle(chosen)
    return chosen


# ------------------------------------------------------------------------------------- signals


def signals_of(events: Sequence[Event], outcome: Outcome) -> list[Signal]:
    """The facts a coder should not have to dig for. Each one is certain from the log."""
    found: list[Signal] = []
    if not events:
        return [Signal("the job gave no result and left no events", "NM-PROVIDER")]
    repeated = Counter(str(e.payload.get("tool")) for e in events if e.type == "tool.repeated")
    if repeated:
        listed = ", ".join(f"{tool} x{count}" for tool, count in sorted(repeated.items()))
        found.append(Signal(f"repeated identical tool calls: {listed}", "FM-1.3"))
    for event in events:
        if event.type == "agent.failed":
            code = str(event.payload.get("code"))
            found.append(Signal(f"{event.actor} failed: {code}", _FAILURE_MODES.get(code)))
    cut = [e.actor for e in events if e.type == "agent.repair" and e.payload.get("cut_off")]
    if cut:
        found.append(Signal(f"replies cut off at the output limit: {', '.join(cut)}"))
    found += _unanswered(events)
    found += _verification(events, outcome)
    found += _relevance(outcome)
    return found


def _unanswered(events: Sequence[Event]) -> list[Signal]:
    sent = [e.payload for e in events if e.type == "message.sent"]
    answered = {m.get("in_reply_to") for m in sent if m.get("performative") in _REPLIES}
    challenges = [m for m in sent if m.get("performative") == "CHALLENGE"]
    open_ = [m for m in challenges if m.get("msg_id") not in answered]
    revised = sum(e.type == "finding.revised" for e in events)
    found = []
    if challenges:
        found.append(Signal(f"{len(challenges)} challenges, {revised} findings revised"))
    for message in open_:
        recipients = ", ".join(message.get("recipients", ()))
        found.append(
            Signal(
                f"a challenge from {message.get('sender')} to {recipients} got no reply", "FM-2.5"
            )
        )
    return found


def _verification(events: Sequence[Event], outcome: Outcome) -> list[Signal]:
    decisions = [e.payload for e in events if e.type == "verifier.decision"]
    proposals = [e.payload for e in events if e.type == "proposal.created"]
    policies = [e.payload for e in events if e.type == "policy.derived"]
    found = []
    if decisions and decisions[-1].get("decision") == "APPROVE":
        found.append(
            Signal(
                "the Verifier approved the final proposal, which differs from the gold label",
                "FM-3.3",
            )
        )
    if "U6" in outcome.reasons and proposals and proposals[-1].get("result") == outcome.gold.value:
        found.append(
            Signal("a veto stood against a proposal that matched the gold label", "FM-3.3")
        )
    if proposals and policies and proposals[-1].get("result") != policies[-1].get("result"):
        found.append(
            Signal(
                f"the last proposal said {proposals[-1].get('result')}, "
                f"the policy derived {policies[-1].get('result')}"
            )
        )
    return found


def _relevance(outcome: Outcome) -> list[Signal]:
    if not outcome.gold_relevant:
        return []
    gold, found = set(outcome.gold_relevant), set(outcome.relevant)
    if gold == found:
        return []
    if not found:
        # A case that failed before its result has no list, whatever its agents said.
        return [Signal("the result names no relevant regulators")]
    parts = []
    if gold - found:
        parts.append(f"missing {', '.join(sorted(gold - found))}")
    if found - gold:
        parts.append(f"extra {', '.join(sorted(found - gold))}")
    return [
        Signal(f"the result's relevant regulators differ from the gold list: {'; '.join(parts)}")
    ]


# --------------------------------------------------------------------------------------- traces


def _clip(text: Any) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= _CLIP else f"{flat[: _CLIP - 3]}..."


def _assertion(payload: Mapping[str, Any]) -> str:
    assertion = dict(payload.get("assertion") or {})
    kind = assertion.pop("type", "?")
    assertion.pop("rationale", None)
    shown = ", ".join(f"{k}={v}" for k, v in assertion.items() if v not in (None, "", [], ()))
    return f"{kind}({_clip(shown)})"


def _reasons(payload: Mapping[str, Any]) -> list[str]:
    return [*payload.get("hard_conflicts", ()), *payload.get("unverified_reasons", ())]


def trace_lines(events: Sequence[Event], limit: int = TRACE_LINES) -> list[str]:
    """A case in a few dozen lines: what each agent posted and said, and how it ended.

    Events are masked as stored, so a restricted value appears only as its placeholder.
    """
    lines: list[str] = []
    for event in events:
        p = event.payload
        if event.type == "round.started":
            lines.append(f"-- {p.get('phase')}")
        elif event.type in ("finding.posted", "finding.revised"):
            verb = "revised" if event.type == "finding.revised" else "posted"
            lines.append(f"{p.get('author')} {verb} {p.get('finding_id')} {_assertion(p)}")
        elif event.type == "conflict.detected":
            found = p.get("finding_ids")
            lines.append(f"conflict {p.get('type')} on {found}: {_clip(p.get('summary'))}")
        elif event.type == "conflict.resolved":
            how = f"{p.get('outcome')} ({p.get('precedence_rule')})"
            lines.append(f"resolved {how}: {_clip(p.get('rationale'))}")
        elif event.type == "message.sent" and p.get("performative") not in ("INFORM", "RESOLVE"):
            route = f"{p.get('sender')} -> {', '.join(p.get('recipients', ()))}"
            said = _clip(p.get("rationale") or p.get("body"))
            lines.append(f"{route} {p.get('performative')}: {said}")
        elif event.type == "proposal.created":
            lines.append(f"proposal v{p.get('version')}: {p.get('result')} {_reasons(p)}")
        elif event.type == "policy.derived":
            lines.append(f"policy: {p.get('result')} {_reasons(p)}")
        elif event.type == "verifier.decision":
            failed = [g.get("gate") for g in p.get("gates", ()) if not g.get("passed")]
            lines.append(f"verifier {p.get('decision')}, failed gates {failed}")
        elif event.type in ("agent.failed", "agent.repair", "tool.failed", "budget.exceeded"):
            lines.append(f"! {event.type} {event.actor}: {_clip(p)}")
        elif event.type == "result.finalized":
            lines.append(f"final: {p.get('result')}")
    if len(lines) > limit:
        hidden = len(lines) - limit + 1
        lines = [*lines[: limit - 2], f"... {hidden} lines not shown ...", lines[-1]]
    return lines


# ---------------------------------------------------------------------------------------- sheets


def failure_rows(
    sample: Sequence[Outcome],
    items: Mapping[str, EvalItem],
    events_for: Mapping[str, Sequence[Event]],
    condition: str,
) -> list[FailureRow]:
    return [
        FailureRow(
            item=items[outcome.item_id],
            outcome=outcome,
            condition=condition,
            signals=tuple(signals_of(events_for.get(outcome.item_id, ()), outcome)),
            trace="\n".join(trace_lines(events_for.get(outcome.item_id, ()))),
        )
        for outcome in sample
    ]


def write_failure_sheet(rows: Sequence[FailureRow], path: Path) -> Path:
    """One sheet per coder. A row holding a DFSA value may only be written under ``restricted``."""
    guard_restricted(path, [row.item for row in rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        for row in rows:
            writer.writerow(
                (
                    row.item.item_id,
                    row.condition,
                    row.outcome.gold.value,
                    row.outcome.predicted.value,
                    " ".join(row.outcome.reasons),
                    "\n".join(str(signal) for signal in row.signals),
                    row.trace,
                    "",
                    "",
                )
            )
    return path


def read_codes(path: Path) -> dict[str, frozenset[str]]:
    """The codes on a filled sheet. A row with no code, or an unknown one, stops the import."""
    codes: dict[str, frozenset[str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            given = {c.upper() for c in re.split(r"[;,\s]+", row.get("codes") or "") if c}
            if not given:
                raise PolicyError(f"item {row['item_id']}: no code given")
            if unknown := sorted(given - set(BY_CODE)):
                raise PolicyError(f"item {row['item_id']}: unknown codes {unknown}")
            codes[row["item_id"]] = frozenset(given)
    return codes


# --------------------------------------------------------------------------------------- summary


def summarize_codes(codes: Mapping[str, frozenset[str]]) -> dict[str, Any]:
    """How often each mode and category was coded. An item can carry several, so shares overlap."""
    total = len(codes)

    def share(count: int) -> float | None:
        return count / total if total else None

    modes = Counter(code for given in codes.values() for code in given)
    categories = Counter(
        category
        for given in codes.values()
        for category in {BY_CODE[code].category for code in given}
    )
    outside_only = sum(all(BY_CODE[c].category == "NM" for c in given) for given in codes.values())
    return {
        "failures": total,
        "modes": {
            mode.code: {
                "name": mode.name,
                "count": modes[mode.code],
                "share": share(modes[mode.code]),
            }
            for mode in MODES
        },
        "categories": {
            key: {"name": name, "count": categories[key], "share": share(categories[key])}
            for key, name in CATEGORIES.items()
        },
        "outside_mast_only": {"count": outside_only, "share": share(outside_only)},
    }


def code_agreement(
    first: Mapping[str, frozenset[str]], second: Mapping[str, frozenset[str]]
) -> dict[str, Any]:
    """Agreement between two coders: Cohen's kappa on each mode coded as present or absent.

    MAST reports kappa between its annotators, 0.88 in its final rounds, so ours is comparable in
    kind. Kappa is undefined for a mode neither coder used, which counts here as full agreement.
    """
    shared = sorted(set(first) & set(second))
    if not shared:
        raise PolicyError("the two sheets share no items")
    per_mode = {}
    pooled_a: list[str] = []
    pooled_b: list[str] = []
    for mode in MODES:
        a = ["yes" if mode.code in first[i] else "no" for i in shared]
        b = ["yes" if mode.code in second[i] else "no" for i in shared]
        per_mode[mode.code] = cohen_kappa(a, b)
        pooled_a += a
        pooled_b += b
    return {
        "items": len(shared),
        "same_codes": sum(first[i] == second[i] for i in shared) / len(shared),
        "kappa_pooled": cohen_kappa(pooled_a, pooled_b),
        "kappa_by_mode": per_mode,
        "to_discuss": [i for i in shared if first[i] != second[i]],
    }
