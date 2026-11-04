"""Join finished runs into one event log, so the frontend can replay and compare them.

Every condition of a comparison uses the same case IDs, in a file of its own. Here each case takes
its condition as a suffix, such as ``S09~CREW-FULL``. The events themselves are copied as stored, so
they stay masked. The output belongs in ``runs/``, which is never committed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from tessera.blackboard.store import EventStore

_Row = tuple[str, str, str, str, str, str | None, int | None]


def _rows(path: Path) -> list[_Row]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT case_id, ts, actor, type, payload, usage, latency_ms FROM events ORDER BY seq"
        ).fetchall()
    finally:
        connection.close()


def _renamed(rows: list[_Row]) -> list[_Row]:
    """The events of every case that has a record, each case named by its condition."""
    conditions = {
        row[0]: json.loads(row[4])["condition"] for row in rows if row[3] == "case.created"
    }
    renamed: list[_Row] = []
    for case_id, ts, actor, kind, payload, usage, latency in rows:
        if case_id not in conditions:
            continue
        name = f"{case_id}~{conditions[case_id]}"
        data = json.loads(payload)
        if data.get("case_id") == case_id:
            data["case_id"] = name
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        renamed.append((name, ts, actor, kind, text, usage, latency))
    return renamed


def merge_logs(sources: list[Path], target: Path) -> int:
    """Copy every event of ``sources`` into a new log at ``target``. Returns the number of cases."""
    if target.exists():
        raise FileExistsError(target)
    EventStore(target).close()
    connection = sqlite3.connect(target)
    cases: set[str] = set()
    try:
        for source in sources:
            rows = _renamed(_rows(source))
            connection.executemany(
                "INSERT INTO events (case_id, ts, actor, type, payload, usage, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            cases.update(row[0] for row in rows)
        connection.commit()
    finally:
        connection.close()
    return len(cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tessera-replay", description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="event logs to join")
    parser.add_argument("--out", type=Path, required=True, help="the new event log")
    args = parser.parse_args(argv)
    print(f"joined {merge_logs(args.sources, args.out)} cases into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
