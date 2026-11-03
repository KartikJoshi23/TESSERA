# ADR-0005: The public repository holds no real data

- **Status:** accepted (3 Nov 2026)
- **Context:**
  - The GitHub repository `KartikJoshi23/TESSERA` is public, and work is pushed to `main`.
  - `PS.md` quotes DFSA alerts.
  - VARA's terms bar redistribution.
  - Anything pushed publicly should be treated as published permanently.
- **Decision:**
  - **Commit:** code, documentation, policies, rule cards (our wording), empty templates and
    fictional test fixtures (reserved `.example` domains).
  - **Git-ignore:** `PS.md`, every real-data folder, datasets, run logs and `.env`.
  - **Enforce** with `scripts/check_restricted.py`, run by the pre-commit hook and in CI. It
    checks for restricted paths, the restricted-content marker, DFSA deep links and API keys.
- **Consequences:** Collaborators get a complete, runnable codebase with no regulated material in
  it. Real data is shared only privately, under the release checklist in
  `docs/data-governance.md`.
