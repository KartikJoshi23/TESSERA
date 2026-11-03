# ADR-0002: Only deterministic tools create evidence

- **Status:** accepted (3 Nov 2026)
- **Context:** Results must be evidence-linked, and the Verifier must be able to block
  unsupported conclusions. If models could write evidence, a fabricated citation would look
  exactly like a real one.
- **Decision:**
  - Evidence records are created only by deterministic tools. A record's ID is a content hash
    that includes the case ID, so it cannot be guessed.
  - Agents cite IDs but cannot create them.
  - A lookup that finds nothing creates a `no_match` record, so absence is checkable too.
  - Evidence from restricted sources stores only derived fields plus a reference to the
    restricted row.
- **Consequences:**
  - Verifier gate G1 can check every citation mechanically.
  - Text injected into an offer cannot produce evidence.
