"""The write-up's figures (§17.4): Figure 3, 4 and 5, as static SVG with a CSV beside each.

Figure 3 puts false reassurance against requests and against tokens per case, in two panels with
one axis each. Figure 4 is the ablation waterfall: what sharing, challenges and the Verifier each
change. Figure 5 is accuracy on each scenario factor or stratum, for every system.

The figures follow the project's data-visualisation rules: thin marks, one axis per panel, a
legend whenever two or more series share a plot, text in ink and never in a series colour, and one
hue for magnitude. Colours were checked with the palette validator: the three family colours pass
every check with all pairs compared, and the one below 3:1 contrast is always labelled. A paper
cannot hover, so each mark carries a native SVG title for screen readers and browsers, and the CSV
beside each figure is its table view.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from tessera.evaluation.paper import FICTION_NOTE, SYSTEM_ORDER

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
SURFACE = "#ffffff"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
#: Categorical slots 1 to 3 of the reference palette: the only three that pass with all pairs.
FAMILIES = {"Single agent": "#2a78d6", "Crew": "#eb6834", "Rules only": "#1baf7a"}
#: The diverging pair, read as better and worse for whichever metric a panel shows.
IMPROVES = "#2a78d6"
WORSENS = "#e34948"
LEVEL = MUTED
#: The reference blue ramp, step 100 to 700, for magnitude.
BLUES = (
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
)
#: Short names in our own words for the plan's factors and strata (§11.2 A and B).
GROUP_NAMES = {
    "F1": "Copied official identifiers",
    "F2": "Look-alike domain",
    "F3": "Unrelated domain",
    "F4": "Off-platform contact",
    "F5": "Payment to a third party",
    "F6": "Mixed jurisdiction signals",
    "F7": "Outside the licence",
    "F8": "Regulator impersonation",
    "F9": "Genuine, full details",
    "F10": "Secondary domain",
    "F11": "Outside coverage",
    "F12": "Variant names",
    "F13": "Several firm names",
    "F14": "Pressure or polish",
    "F15": "Prompt injection",
    "E1": "Impersonated firm, listed contact",
    "E2": "Same firms, official contact",
    "E3": "False DFSA claims",
    "E4": "VARA unlicensed",
    "E5": "VARA licensed, in scope",
    "E6": "VARA IPA holders",
    "E7": "CMA licensed, in scope",
    "E8": "CMA Category 5 with FX",
    "E9": "CMA warnings",
    "E10": "CBUAE only",
    "E11": "Near-miss names",
}
_TEXT = 11
_CHAR = 0.56  # average character width as a share of the font size, for laying out labels


@dataclass(frozen=True)
class Figure:
    key: str
    svg: str
    rows: tuple[dict[str, Any], ...]

    def csv(self) -> str:
        if not self.rows:
            return ""
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(self.rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        return buffer.getvalue()


def family(system: str) -> str:
    if system == "RULES-ONLY":
        return "Rules only"
    return "Crew" if system.startswith("CREW-") else "Single agent"


def _ordered(names: Sequence[str]) -> list[str]:
    rank = {name: index for index, name in enumerate(SYSTEM_ORDER)}
    return sorted(names, key=lambda name: (rank.get(name, len(rank)), name))


def _width(text: str, size: int = _TEXT) -> float:
    return len(text) * size * _CHAR


def _text(x: float, y: float, text: str, **attrs: Any) -> str:
    extra = " ".join(f'{key.replace("_", "-")}="{value}"' for key, value in attrs.items())
    return f'<text x="{x:.1f}" y="{y:.1f}" {extra}>{escape(text)}</text>'


def nice_ticks(high: float, count: int = 5) -> list[float]:
    """Round ticks from zero to just past ``high``: 1, 2, 2.5 or 5 times a power of ten."""
    high = high if high > 0 else 1.0
    power = 10 ** math.floor(math.log10(high / count))
    step = power
    for multiple in (1, 2, 2.5, 5, 10):
        step = multiple * power
        if high / step <= count:
            break
    top = math.ceil(high / step - 1e-9)
    return [round(index * step, 10) for index in range(top + 1)]


def _tick_label(value: float) -> str:
    if value >= 10_000:
        return f"{value / 1000:g}K"
    return f"{value:,.0f}" if value >= 1000 else f"{value:g}"


def _svg(width: int, height: int, title: str, description: str, body: list[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" role="img" aria-labelledby="t d">',
            f'<title id="t">{escape(title)}</title>',
            f'<desc id="d">{escape(description)}</desc>',
            f"<style>text {{ font-family: {escape(FONT)}; font-size: {_TEXT}px; "
            f"fill: {INK_2}; }} .tick {{ font-variant-numeric: tabular-nums; fill: {MUTED}; }} "
            f".title {{ font-size: 13px; font-weight: 600; fill: {INK}; }} "
            f".note {{ font-size: 10px; fill: {MUTED}; }}</style>",
            f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
            *body,
            "</svg>",
        ]
    )


def _heading(title: str, fiction: bool, width: int) -> list[str]:
    lines = [_text(16, 22, title, **{"class": "title"})]
    if fiction:
        lines.append(_text(16, 38, FICTION_NOTE, **{"class": "note"}))
    return lines


def _legend(entries: Sequence[tuple[str, str]], x: float, y: float) -> list[str]:
    """Swatches beside ink labels, right to left from ``x``. Identity never rests on colour."""
    parts = []
    for name, colour in reversed(entries):
        x -= _width(name) + 22
        parts.append(
            f'<rect x="{x:.1f}" y="{y - 8:.1f}" width="10" height="10" rx="2" fill="{colour}"/>'
        )
        parts.append(_text(x + 14, y + 1, name))
    return parts


@dataclass(frozen=True)
class _Panel:
    left: float
    top: float
    width: float
    height: float

    def x(self, value: float, high: float) -> float:
        return self.left + self.width * (value / high if high else 0)

    def y(self, value: float, high: float, low: float = 0.0) -> float:
        span = high - low
        return self.top + self.height * (1 - ((value - low) / span if span else 0))


def _axes(
    panel: _Panel,
    x_ticks: Sequence[float] | None,
    y_ticks: Sequence[float],
    *,
    y_low: float = 0.0,
    x_title: str = "",
    y_title: str = "",
) -> list[str]:
    """Hairline grid and axes, solid and recessive, with round ticks."""
    parts = []
    y_high = y_ticks[-1]
    for tick in y_ticks:
        y = panel.y(tick, y_high, y_low)
        colour = AXIS if tick == y_low else GRID
        parts.append(
            f'<line x1="{panel.left:.1f}" x2="{panel.left + panel.width:.1f}" y1="{y:.1f}" '
            f'y2="{y:.1f}" stroke="{colour}" stroke-width="1"/>'
        )
        parts.append(
            _text(panel.left - 6, y + 4, _tick_label(tick), text_anchor="end", **{"class": "tick"})
        )
    if x_ticks:
        x_high = x_ticks[-1]
        base = panel.top + panel.height
        for tick in x_ticks:
            x = panel.x(tick, x_high)
            parts.append(
                _text(x, base + 16, _tick_label(tick), text_anchor="middle", **{"class": "tick"})
            )
    if x_title:
        parts.append(
            _text(
                panel.left + panel.width / 2,
                panel.top + panel.height + 34,
                x_title,
                text_anchor="middle",
            )
        )
    if y_title:
        parts.append(_text(panel.left, panel.top - 10, y_title))
    return parts


# ------------------------------------------------------------------------------- Figure 3

_FRR = "false_reassurance_rate"


def _hbar(x0: float, x1: float, y: float, thickness: float, colour: str) -> str:
    """A horizontal bar, square at the baseline ``x0`` and rounded at its data end."""
    if x1 - x0 < 1:
        return ""
    r = min(4.0, (x1 - x0) / 2, thickness / 2)
    top, bottom = y - thickness / 2, y + thickness / 2
    return (
        f'<path d="M{x0:.1f},{top:.1f} L{x1 - r:.1f},{top:.1f} Q{x1:.1f},{top:.1f} '
        f"{x1:.1f},{top + r:.1f} L{x1:.1f},{bottom - r:.1f} Q{x1:.1f},{bottom:.1f} "
        f'{x1 - r:.1f},{bottom:.1f} L{x0:.1f},{bottom:.1f} Z" fill="{colour}"/>'
    )


def frontier_figure(level: dict[str, Any], *, fiction: bool = False) -> Figure | None:
    """Figure 3: each system's false reassurance beside what it spends, one row per system.

    Ten systems on one scatter plot crowd their labels into each other, so each system gets a
    row, and each measure a panel with its own axis. Nothing is plotted against a second scale.
    """
    points = []
    for name in _ordered(list(level["systems"])):
        system = level["systems"][name]
        rate = system.get(_FRR)
        compute = system.get("compute") or {}
        if rate is None or compute.get("requests_per_case") is None:
            continue
        low, high = (system.get("intervals") or {}).get(_FRR, (rate, rate))
        points.append(
            {
                "system": name,
                "family": family(name),
                _FRR: rate,
                "ci_low": low,
                "ci_high": high,
                "requests_per_case": compute["requests_per_case"],
                "tokens_per_case": compute.get("tokens_per_case") or 0.0,
            }
        )
    if not points:
        return None
    width, label_w, row_h = 720, 110, 26
    top = (74 if fiction else 60) + 26
    rows_h = row_h * len(points)
    height = int(top + rows_h + 60)
    panels = (
        (_FRR, "False reassurance, 95% interval", _Panel(label_w, top, 250, rows_h)),
        ("requests_per_case", "Requests per case", _Panel(label_w + 280, top, 140, rows_h)),
        ("tokens_per_case", "Tokens per case", _Panel(label_w + 450, top, 140, rows_h)),
    )
    title = f"False reassurance and what it costs, {level['level']} level"
    body = _heading(title, fiction, width)
    present = [
        (name, colour)
        for name, colour in FAMILIES.items()
        if any(p["family"] == name for p in points)
    ]
    if len(present) >= 2:
        body += _legend(present, width - 16, 22)
    for index, point in enumerate(points):
        y = top + row_h * index + row_h / 2
        body.append(_text(label_w - 12, y + 4, point["system"], text_anchor="end"))
    for key, heading, panel in panels:
        largest = max(p["ci_high"] for p in points) if key == _FRR else max(p[key] for p in points)
        ticks = nice_ticks(max(largest, 0.1 if key == _FRR else 1.0) * 1.1, 4)
        for tick in ticks:
            x = panel.x(tick, ticks[-1])
            body.append(
                f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top - 4:.1f}" y2="{top + rows_h:.1f}" '
                f'stroke="{AXIS if tick == 0 else GRID}" stroke-width="1"/>'
            )
            body.append(
                _text(
                    x,
                    top + rows_h + 16,
                    _tick_label(tick),
                    text_anchor="middle",
                    **{"class": "tick"},
                )
            )
        body.append(_text(panel.left, top - 12, heading))
        for index, point in enumerate(points):
            y = top + row_h * index + row_h / 2
            colour = FAMILIES[point["family"]]
            if key == _FRR:
                tip = (
                    f"{point['system']}: false reassurance {point[_FRR]:.3f} "
                    f"[{point['ci_low']:.3f}, {point['ci_high']:.3f}]"
                )
                x_low = panel.x(point["ci_low"], ticks[-1])
                x_high = panel.x(point["ci_high"], ticks[-1])
                mark = (
                    f'<line x1="{x_low:.1f}" x2="{x_high:.1f}" y1="{y:.1f}" y2="{y:.1f}" '
                    f'stroke="{colour}" stroke-width="2" stroke-linecap="round" opacity="0.55"/>'
                    if x_high - x_low > 1
                    else ""
                )
                mark += (
                    f'<circle cx="{panel.x(point[_FRR], ticks[-1]):.1f}" cy="{y:.1f}" r="4.5" '
                    f'fill="{colour}" stroke="{SURFACE}" stroke-width="2"/>'
                )
            else:
                tip = f"{point['system']}: {point[key]:,.1f} {heading.lower()}"
                mark = _hbar(panel.left, panel.x(point[key], ticks[-1]), y, 10, colour)
            body.append(f"<g><title>{escape(tip)}</title>{mark}</g>")
    body.append(
        _text(
            16,
            height - 12,
            "Lower false reassurance is safer. Each system is one row, and each measure has its "
            "own axis.",
            **{"class": "note"},
        )
    )
    svg = _svg(
        width,
        height,
        title,
        "For each system: its false-reassurance rate with a 95% interval, its requests per case, "
        "and its tokens per case.",
        body,
    )
    return Figure(f"frontier-{level['level']}", svg, tuple(points))


# ------------------------------------------------------------------------------- Figure 4

#: Each step adds one mechanism, as the conditions define them (§10.2).
ABLATION = (
    ("level", "CREW-SILO", "CREW-SILO"),
    ("step", "+ sharing", "CREW-SHARE"),
    ("step", "+ challenges", "CREW-FULL"),
    ("level", "CREW-FULL", "CREW-FULL"),
    ("step", "− Verifier", "CREW-NV"),
    ("level", "CREW-NV", "CREW-NV"),
)
_METRICS = (
    ("false_reassurance_rate", "False reassurance rate", True),
    ("macro_f1", "Macro-F1", False),
)


def _bar(x: float, start: float, end: float, width: float, colour: str, radius: float = 4) -> str:
    """A bar square at ``start`` and rounded at its data end, ``end``."""
    if abs(end - start) < 2:
        return (
            f'<line x1="{x:.1f}" x2="{x + width:.1f}" y1="{end:.1f}" y2="{end:.1f}" '
            f'stroke="{colour}" stroke-width="2" stroke-linecap="round"/>'
        )
    r = min(radius, abs(end - start) / 2, width / 2)
    sign = -1 if end < start else 1
    return (
        f'<path d="M{x:.1f},{start:.1f} L{x:.1f},{end - sign * r:.1f} '
        f"Q{x:.1f},{end:.1f} {x + r:.1f},{end:.1f} L{x + width - r:.1f},{end:.1f} "
        f"Q{x + width:.1f},{end:.1f} {x + width:.1f},{end - sign * r:.1f} "
        f'L{x + width:.1f},{start:.1f} Z" fill="{colour}"/>'
    )


def ablation_figure(level: dict[str, Any], *, fiction: bool = False) -> Figure | None:
    """Figure 4: the ablation waterfall, from CREW-SILO to CREW-FULL, and without the Verifier."""
    systems = level["systems"]
    needed = {name for _, _, name in ABLATION}
    if not needed <= set(systems):
        return None
    width, panel_h, gap = 720, 180, 74
    top = (78 if fiction else 64) + 24
    height = int(top + 2 * (panel_h + gap))
    rows: list[dict[str, Any]] = []
    body = _heading(f"What each mechanism changes, {level['level']} level", fiction, width)
    body += _legend(
        (("Level", LEVEL), ("Improves", IMPROVES), ("Worsens", WORSENS)), width - 16, 22
    )
    for index, (metric, title, lower_is_better) in enumerate(_METRICS):
        panel = _Panel(70, top + index * (panel_h + gap), 540, panel_h)
        values = {name: systems[name].get(metric) for name in needed}
        if any(value is None for value in values.values()):
            continue
        reference = systems.get("SA-BASE", {}).get(metric)
        highest = max([*values.values(), reference or 0.0])
        y_ticks = (
            [0.0, 0.25, 0.5, 0.75, 1.0]
            if metric == "macro_f1"
            else nice_ticks(max(highest, 0.05) * 1.15)
        )
        body += _axes(panel, None, y_ticks, y_title=title)
        slot = panel.width / len(ABLATION)
        bar = min(24.0, slot * 0.5)
        previous = 0.0
        for position, (kind, label, name) in enumerate(ABLATION):
            value = values[name]
            x = panel.left + slot * position + (slot - bar) / 2
            if kind == "level":
                start, end, colour, shown = 0.0, value, LEVEL, f"{value:.3f}"
            else:
                start, end = previous, value
                better = (end < start) == lower_is_better if end != start else None
                colour = MUTED if better is None else IMPROVES if better else WORSENS
                shown = f"{end - start:+.3f}".replace("-", "−")
            y_start = panel.y(start, y_ticks[-1])
            y_end = panel.y(end, y_ticks[-1])
            body.append(f"<g><title>{escape(f'{label}: {shown} ({title.lower()})')}</title>")
            body.append(_bar(x, y_start, y_end, bar, colour))
            body.append("</g>")
            label_y = min(y_start, y_end) - 6
            body.append(_text(x + bar / 2, label_y, shown, text_anchor="middle"))
            body.append(
                _text(
                    x + bar / 2,
                    panel.top + panel.height + 16,
                    label,
                    text_anchor="middle",
                    **{"class": "tick"},
                )
            )
            if position + 1 < len(ABLATION):
                y_line = panel.y(value, y_ticks[-1])
                body.append(
                    f'<line x1="{x + bar:.1f}" x2="{x + slot:.1f}" y1="{y_line:.1f}" '
                    f'y2="{y_line:.1f}" stroke="{AXIS}" stroke-width="1"/>'
                )
            previous = value
            rows.append(
                {"metric": metric, "step": label, "system": name, "kind": kind, "value": value}
            )
        if reference is not None:
            y_ref = panel.y(reference, y_ticks[-1])
            body.append(
                f'<line x1="{panel.left:.1f}" x2="{panel.left + panel.width:.1f}" y1="{y_ref:.1f}" '
                f'y2="{y_ref:.1f}" stroke="{INK_2}" stroke-width="1"/>'
            )
            # In the margin, so it can never sit on a bar.
            body.append(_text(panel.left + panel.width + 8, y_ref + 4, f"SA-BASE {reference:.3f}"))
            rows.append(
                {
                    "metric": metric,
                    "step": "reference",
                    "system": "SA-BASE",
                    "kind": "reference",
                    "value": reference,
                }
            )
    if not rows:
        return None
    body.append(
        _text(
            16,
            height - 12,
            "Each step adds or removes one mechanism. Paired intervals for each step are in the "
            "comparisons table.",
            **{"class": "note"},
        )
    )
    svg = _svg(
        width,
        height,
        f"What each mechanism changes, {level['level']} level",
        "A waterfall from CREW-SILO, adding sharing and challenges to reach CREW-FULL, then "
        "removing the Verifier to reach CREW-NV, for false reassurance and macro-F1.",
        body,
    )
    return Figure(f"ablation-{level['level']}", svg, tuple(rows))


# ------------------------------------------------------------------------------- Figure 5


def _blue(share: float) -> str:
    """A step of the blue ramp: light for low accuracy, dark for high."""
    index = round(max(0.0, min(1.0, share)) * (len(BLUES) - 1))
    return BLUES[index]


def _group_key(group: str) -> tuple[str, int]:
    digits = "".join(char for char in group if char.isdigit())
    return (group.rstrip("0123456789"), int(digits) if digits else 0)


def factors_figure(level: dict[str, Any], *, fiction: bool = False) -> Figure | None:
    """Figure 5: accuracy on each factor or stratum, one column per system."""
    systems = _ordered([name for name, s in level["systems"].items() if s.get("by_group")])
    groups = sorted(
        {g for name in systems for g in level["systems"][name]["by_group"]}, key=_group_key
    )
    if not systems or not groups:
        return None
    label_width = 230
    cell_w = max(34.0, min(56.0, (720 - label_width - 32) / len(systems)))
    cell_h = 22
    top = 128 if fiction else 114
    width = int(label_width + cell_w * len(systems) + 32)
    height = int(top + cell_h * len(groups) + 70)
    kind = "factor" if groups[0].startswith("F") else "stratum"
    body = _heading(
        f"Accuracy on each scenario {kind}, {level['level']} level",
        fiction,
        width,
    )
    rows: list[dict[str, Any]] = []
    for column, name in enumerate(systems):
        x = label_width + column * cell_w + cell_w / 2
        body.append(
            f'<text x="{x:.1f}" y="{top - 8:.1f}" transform="rotate(-40 {x:.1f} {top - 8:.1f})" '
            f'class="tick" style="fill: {INK_2}">{escape(name)}</text>'
        )
    for row, group in enumerate(groups):
        y = top + row * cell_h
        counts = [
            level["systems"][name]["by_group"].get(group, {}).get("items", 0) for name in systems
        ]
        named = f"{group} {GROUP_NAMES.get(group, '')} (n={max(counts)})".replace("  ", " ")
        body.append(_text(label_width - 10, y + cell_h / 2 + 4, named, text_anchor="end"))
        for column, name in enumerate(systems):
            found = level["systems"][name]["by_group"].get(group)
            if not found or found.get("accuracy") is None:
                continue
            accuracy = found["accuracy"]
            x = label_width + column * cell_w
            tip = (
                f"{name}, {group} {GROUP_NAMES.get(group, '')}: accuracy {accuracy:.2f} "
                f"on {found['items']} items"
            )
            body.append(
                f'<g><title>{escape(tip)}</title><rect x="{x + 1:.1f}" y="{y + 1:.1f}" '
                f'width="{cell_w - 2:.1f}" height="{cell_h - 2}" rx="2" '
                f'fill="{_blue(accuracy)}"/></g>'
            )
            rows.append(
                {
                    "group": group,
                    "name": GROUP_NAMES.get(group, ""),
                    "system": name,
                    "items": found["items"],
                    "accuracy": accuracy,
                    "false_reassurance": found.get("false_reassurance"),
                }
            )
    scale_y = top + cell_h * len(groups) + 26
    scale_x = label_width
    scale_w = min(240.0, cell_w * len(systems))
    body.append(
        '<defs><linearGradient id="ramp" x1="0" x2="1" y1="0" y2="0">'
        + "".join(
            f'<stop offset="{i / (len(BLUES) - 1):.3f}" stop-color="{colour}"/>'
            for i, colour in enumerate(BLUES)
        )
        + "</linearGradient></defs>"
    )
    body.append(
        f'<rect x="{scale_x:.1f}" y="{scale_y:.1f}" width="{scale_w:.1f}" height="8" rx="4" '
        'fill="url(#ramp)"/>'
    )
    for share in (0.0, 0.5, 1.0):
        body.append(
            _text(
                scale_x + scale_w * share,
                scale_y + 22,
                f"{share:g}",
                text_anchor="middle",
                **{"class": "tick"},
            )
        )
    body.append(_text(scale_x - 10, scale_y + 8, "Accuracy", text_anchor="end"))
    svg = _svg(
        width,
        height,
        f"Accuracy on each scenario factor, {level['level']} level",
        "A grid of accuracy for every system on each factor or stratum. Darker is more accurate. "
        "An item with several factors counts under each.",
        body,
    )
    return Figure(f"factors-{level['level']}", svg, tuple(rows))


# ---------------------------------------------------------------------------------- output


def paper_figures(report: dict[str, Any], *, fiction: bool = False) -> list[Figure]:
    """Every figure the report supports. One that lacks its systems is left out, not faked."""
    builders: tuple[Callable[..., Figure | None], ...] = (
        frontier_figure,
        ablation_figure,
        factors_figure,
    )
    figures = []
    for build in builders:
        for level in report["levels"].values():
            figure = build(level, fiction=fiction)
            if figure is not None:
                figures.append(figure)
    return figures


def write_figures(figures: Sequence[Figure], folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for figure in figures:
        svg = folder / f"figure-{figure.key}.svg"
        svg.write_text(figure.svg, encoding="utf-8")
        table = folder / f"figure-{figure.key}.csv"
        table.write_text(figure.csv(), encoding="utf-8")
        written += [svg, table]
    return written
