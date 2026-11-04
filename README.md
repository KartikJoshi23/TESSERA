# TESSERA

**A coordinated crew of AI agents that checks synthetic investment, trading and crypto offers
against UAE regulator records, with an honest test of whether the crew beats a single agent.**

> Internal research prototype. Not a public tool and not investment advice. It never gives a
> verdict on any firm or person.

## The problem

UAE authorities advise residents to check that an investment, trading or crypto offer comes from
a properly licensed firm before sending money. That check is split across five regulators: the
CMA, CBUAE, DFSA, ADGM FSRA and VARA. Each has its own register and alert list, and each covers a
different activity or zone. Impersonators copy real firms' names, addresses and reference
numbers, so finding a name on a register does not prove an offer is genuine.

TESSERA takes a clearly labelled **synthetic** offer and does four things:

1. works out which regulators could be relevant;
2. checks each register and alert list;
3. compares the offer's contact and payment details with the official record;
4. returns one of three results, *Consistent with the official record*, *Conflicts with the
   official record* or *Could not verify*, with every claim linked to evidence.

A single-agent baseline gets the same model, tools and knowledge, and the two are compared
under a pre-registered evaluation.

The full design is in [implementation-plan.md](implementation-plan.md).

## Status

| Part | Scope | State |
|---|---|---|
| 1 | Governance, data layer, deterministic tools | ✅ Done |
| 2 | Protocol, blackboard, LLM runner, the seven agents | ✅ Done |
| 3 | Crew orchestration, reconciliation, Verifier, streaming API | ✅ Done |
| 4 | Single-agent baselines and ablations | ✅ Done |
| 5 | Frontend (Orchestration Theater) | Next |
| 6 | Datasets, evaluation harness, pilot | Planned |
| 7 | Experiments and analysis | Planned |
| 8 | CBUAE and ADGM FSRA | Planned |

## What this repository contains, and what it never will

- **Contains:**
  - code, documentation and machine-readable policies (`policies/`);
  - rule cards in our own words (`knowledge/`);
  - empty data templates;
  - **fictional** test fixtures that use reserved `.example` domains.
- **Never contains:**
  - the problem-statement notes;
  - real register or alert data;
  - DFSA hand-recorded facts;
  - datasets, run logs or API keys.

  `.gitignore` excludes these, and a commit guard (`scripts/check_restricted.py`) blocks them in
  a pre-commit hook and in CI. See [docs/data-governance.md](docs/data-governance.md).

## Quick start (backend)

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
uv run pytest
```

Turn on the commit guard for your clone:

```bash
git config core.hooksPath .githooks
```

## Modes

| Mode | Behaviour |
|---|---|
| `RESTRICTED_DEMO` (default) | Restricted (DFSA) facts never load. Use it for anything shown to others |
| `RESEARCH_INTERNAL` | Local research. DFSA facts load from `data/restricted/` and are masked before any model call |

Copy `.env.example` to `.env` to set the mode and the NVIDIA API key.

## Adding data (manual only)

Nothing downloads regulator data automatically. A person collects it by hand, following
[docs/data-governance.md](docs/data-governance.md), then ingests it:

```bash
cd backend
uv run tessera-ingest cma_licensed ../data/inbox/cma_licensed/export.xlsx --retrieved-by KJ --retrieved-on 2026-11-05
```

## Running against a live model

Tests never need a key or a network. Live runs need one free key from
[build.nvidia.com](https://build.nvidia.com). You need one key, not one per model.

Copy `.env.example` to a new file named `.env` at the repository root, and put the key in that
copy. `.env.example` is public, so never paste a key there. The commit guard blocks it if you do.

Then, from `backend/`:

| Command | What it does |
|---|---|
| `uv run tessera-run --case S09` | Runs one fictional offer through the crew and prints its report |
| `uv run tessera-smoke --limit 3` | Runs fictional cases and compares them with their gold results |
| `uv run tessera-probe` | Measures tool calling and JSON output for the candidate models |
| `uv run tessera-api --fiction` | Starts the local API on `127.0.0.1:8000`, on the fictional world |

- Models listed by NVIDIA are not all served to every account. A `404 ... Not found for account`
  means this account cannot use that model. `tessera-probe` shows which ones work.
- `tessera-probe` writes its report to `runs/probe/` as it goes. With no arguments it runs 40
  trials on every candidate in `policies/models.yaml`, one request at a time, which takes a while.
- `tessera-smoke` works in its own folder under `runs/smoke/` and stops at a request cap (120 by
  default). `--condition` picks the system, for example `CREW-FULL`, `SA-BASE` or `RULES-ONLY`.
  Its results say nothing about final performance: the set is hand-written and easy, and plain
  rules alone match 21 of its 25 cases.
- `tessera-run --text "..." --attest-synthetic` runs your own synthetic text. Real messages are
  never allowed.

## The local API

`tessera-api` binds to `127.0.0.1` only, and has no sign-in because it serves this machine alone.
Without `--fiction` it uses the data in `data/`.

| Route | Purpose |
|---|---|
| `GET /api/status` | Mode, model, covered regulators and what data is loaded |
| `GET /api/examples` | The fictional offers |
| `POST /api/cases` | Starts a case. Anything not marked synthetic is refused |
| `GET /api/cases/{id}/events` | Every event of a case in order, live or replayed, as Server-Sent Events |
| `GET /api/cases/{id}/report` | The finished report |
| `GET /api/cases/{id}` | The full masked case state |
| `GET /api/cases/{id}/trace` | The whole case with its coordination telemetry, masked |

Interactive documentation is at `/api/docs`.

## Free by design

- **Models:** every model call goes to NVIDIA's free API catalog, using open-weight models.
- **Software:** the rest of the stack is open source and runs locally.
- **CI:** runs on free GitHub Actions.

## Licence

No licence has been chosen yet, so all rights are reserved by the author.
