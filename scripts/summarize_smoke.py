#!/usr/bin/env python3
"""Turn smoke-run reports into the development comparison the Evaluation Lab shows.

Reads ``runs/compare/*.txt`` and writes ``frontend/src/data/smoke-comparison.json``. A report that
has no closing summary is still running, and is left out. Only counts and result codes for the
fictional development set are written, so the output is safe to commit.

These numbers say how the system behaves while it is built. They are not evaluation results.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs" / "compare"
TARGET = ROOT / "frontend" / "src" / "data" / "smoke-comparison.json"

_ROW = re.compile(
    r"^(?P<case>S\d+)\s+(?P<gold>[A-Z]+)\s+(?P<result>[A-Z]+|-+)\s+"
    r"(?P<requests>\d+)\s+(?P<tokens>\d+)\s+(?P<seconds>\d+)"
)
_CONDITION = re.compile(r"condition:\s*(\S+)")
_RATE_LIMITED = re.compile(r"rate limited:\s*(\d+)")


def parse(path: Path) -> dict[str, object] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "matches gold:" not in text:
        return None
    condition = _CONDITION.search(text)
    limited = _RATE_LIMITED.search(text)
    cases = []
    for line in text.splitlines():
        row = _ROW.match(line.strip())
        if row:
            cases.append(
                {
                    "case": row["case"],
                    "gold": row["gold"],
                    "result": row["result"],
                    "requests": int(row["requests"]),
                    "tokens": int(row["tokens"]),
                    "seconds": int(row["seconds"]),
                }
            )
    return {
        "run": path.stem,
        "condition": condition[1] if condition else path.stem,
        "rate_limited": int(limited[1]) if limited else 0,
        "cases": cases,
    }


def main() -> int:
    rows = [row for path in sorted(RUNS.glob("*.txt")) if (row := parse(path))]
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps({"runs": rows}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} runs to {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
