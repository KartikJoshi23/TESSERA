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
| 2 | Protocol, blackboard, LLM runner, the seven agents | Next |
| 3 | Crew orchestration, reconciliation, Verifier, streaming API | Planned |
| 4 | Single-agent baselines and ablations | Planned |
| 5 | Frontend (Orchestration Theater) | Planned |
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

Copy `.env.example` to `.env` to set the mode and, from Part 2, the NVIDIA API key.

## Adding data (manual only)

Nothing downloads regulator data automatically. A person collects it by hand, following
[docs/data-governance.md](docs/data-governance.md), then ingests it:

```bash
cd backend
uv run tessera-ingest cma_licensed ../data/inbox/cma_licensed/export.xlsx --retrieved-by KJ --retrieved-on 2026-11-05
```

## Free by design

- **Models:** every model call goes to NVIDIA's free API catalog, using open-weight models.
- **Software:** the rest of the stack is open source and runs locally.
- **CI:** runs on free GitHub Actions.

## Licence

No licence has been chosen yet, so all rights are reserved by the author.
