# ADR-0003: DFSA facts are restricted, local and masked

- **Status:** accepted (3 Nov 2026)
- **Context:** The DFSA Legal Disclaimer, as recorded in PS.md, does three things:
  - it limits extracts to personal or organisational use;
  - it bars storage in any public or private electronic retrieval system without written
    permission;
  - it bars caching and any link other than to the homepage.

  The DFSA register and alert pages are also bot-protected.
- **Decision:**
  - A person hand-records minimal facts into `data/restricted/dfsa/`, the only copy of DFSA
    values.
  - The data loads only in `RESEARCH_INTERNAL` mode.
  - Lookups are linear scans of a small table held in memory: no index, no embeddings.
  - Evidence keeps row IDs, not values.
  - Every DFSA link becomes the homepage.
  - Every identifying value is masked before any model call. Recorded services, addresses and
    alert dates are not sent at all: a model gets tool-computed relations instead.
  - The commit guard keeps all of this out of the public repository.
- **Consequences:**
  - Purging is one folder.
  - The system still runs without DFSA data, with those cases becoming "Could not verify".
  - A written permission request is drafted in `docs/dfsa-permission-request.md`.
