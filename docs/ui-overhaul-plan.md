# UI overhaul plan

Status: **proposed, waiting for approval.** No code has been written for it.

## Why the current interface misses

Every screen follows one template: a small label over a very large heading, a paragraph, rounded
glass cards and pill tabs. It is clean, but it is the generic look of an AI dashboard, and nothing
in it belongs to TESSERA alone. The signature view, the orchestration theater, is a flat drawing of
hexagons and dashed lines. It shows what happened, but it does not make anyone want to watch.

## The idea: the tessera hospitalis

A *tessera hospitalis* was a Roman token broken in two. Each party kept one half, and when the
halves were brought together and fitted, they proved who you were. That is exactly what this tool
does: it holds the offer's half against the official record's half.

So the three results become what happens to the two halves:

- **Consistent with the official record:** the halves fuse along a seam of light.
- **Conflicts with the official record:** they fracture, and the break shows where.
- **Could not verify:** one half is missing, and only its outline is there.

The seam is the motif that runs through the whole interface. Pages open along a seam, the dossier
leads with the token itself, and the theater builds a mosaic of evidence tile by tile. The design
then says something true about the system, rather than decorating it.

## Visual language

- **Palette, "mineral":** ink-black ground, basalt surfaces, vellum text. The result colours come
  from mosaic stones: malachite for Consistent, ochre for Conflicts, lapis for Could not verify,
  and a thin gold for the seam. Every colour pair goes through the palette validator for contrast
  and colour-blind safety before use.
- **Type:** a characterful variable serif for display (Fraunces, free under the OFL), Geist for
  the interface and Geist Mono for data and identifiers. IBM Plex Sans Arabic stays for Arabic.
- **Layout:** an editorial grid with hairline rules instead of cards in cards. Cases are numbered
  like catalogue entries. A slim left rail replaces the top bar, and a command palette (Ctrl+K)
  reaches every case and screen.
- **Material:** real light in a few places, not glass everywhere. The token and the mosaic tiles
  are rendered in WebGL, with a soft sheen and fine grain. Glass is kept for overlays, so it means
  something when it appears.
- **Motion:** purposeful and choreographed. Every animation shows a real event: a finding arriving,
  a conflict, a ruling, a veto. Nothing moves only to look busy.

## Technology (all free)

- **WebGL:** three.js with React Three Fiber and drei, all MIT: the mosaic field on the home page,
  the token, and the theater's mosaic table, with instanced tiles and small shaders.
- **GSAP:** free since 2025, including ScrollTrigger, SplitText, Flip and DrawSVG. Used for
  choreographed sequences, such as an agent's turn or a seam transition, and for the Lab's
  scroll-driven narrative.
- **Motion** (Framer Motion, already in use): state, layout and shared-element transitions in
  components.
- **Lenis:** smooth scrolling for the long reading pages.
- Everything heavy loads lazily, so the first paint never waits for WebGL.

## Guardrails

- **Performance:** the target machine has a 2 GB MX450, so the budget is a steady 60 fps there.
  The pixel ratio is capped at 1.5, tiles are instanced, frames render only when something changes,
  and rendering pauses when a canvas is off screen or the tab is hidden.
- **Fallbacks:** with reduced motion asked for, or no WebGL, every view has a still version that
  carries the same information, with the token drawn in SVG.
- **Accessibility:** everything drawn in a canvas also exists as text. The ledger is a live region,
  every action works from the keyboard, contrast meets AA, and the axe checks in the browser tests
  stay green.
- **Governance does not change:** internal research framing on every screen, no DFSA deep links,
  masked values as stored, `RESTRICTED_DEMO` for screenshots, local only.
- **The data layer does not change:** the event reducer, API client, schemas and their tests stay
  as they are. Only presentation is rebuilt.

## Screens

1. **Shell:** left rail with glyphs, command palette, mode badge, seam transitions between pages.
2. **Console:** a living mosaic field that gathers into the token, recent cases as a numbered
   catalogue with each result's seam, and system status as one quiet strip.
3. **Intake:** the offer shown as a specimen. Contact points light up in the text as they are
   found, and each system to choose from is drawn as a small diagram of how it works.
4. **Theater, the signature view:** the mosaic table. Agents sit around it. Each finding flies in as
   a tile and is set into the mosaic. A conflict cracks tiles and draws a thread between the agents
   who disagree. The Reconciler's ruling repairs or lifts them, and the Verifier's gate seals the
   mosaic or rejects it. A ledger narrates in words, and a timeline lets you scrub and replay.
5. **Dossier:** the token at the top, fusing, fracturing or missing a half. The reasons follow as
   an engraved list, then the evidence as provenance cards with sources and dates, and what was not
   checked.
6. **Arena:** crew and single agent side by side on synchronised clocks, with requests and tokens
   counting up as they work.
7. **Lab:** a scroll-driven reading. Each chart stays pinned while its explanation scrolls past,
   and the charts keep the project's data-visualisation rules.
8. **Governance:** an animated map of what may leave the machine, and how masking stops the rest.

## Parts

Each part ends with a short report and a stop for "continue".

| Part | What it delivers | Size |
|---|---|---|
| **U1. Foundation** | Tokens, fonts and palette; the shell with rail, command palette and seam transitions; motion and WebGL plumbing with fallbacks and performance controls; the Console rebuilt as the first showcase | L |
| **U2. Theater** | The mosaic table, tile choreography, conflict threads, Verifier gate, ledger and scrubbable timeline | L |
| **U3. Dossier and Intake** | The token and the evidence layout; the specimen-style intake | M |
| **U4. Arena and Lab** | The synchronised race; the scroll-driven Lab with the charts restyled | M |
| **U5. Governance and finish** | The governance map; a performance and accessibility audit; browser tests updated; a visual review in `RESTRICTED_DEMO` | M |

The evaluation runs are independent of this work and carry on alongside it.
