# TESSERA — Implementation Plan

**A coordinated crew of AI agents that checks investment, trading and crypto offers against UAE regulator records, compared with a single-agent baseline**

| | |
|---|---|
| **Version** | 2. Audited and revised on 3 November 2026; Appendix E lists every finding and fix. |
| **Status** | Approved to proceed on 3 Nov 2026. Part 1 (foundations) is delivered. Parts 2 (protocol, blackboard, runner, the seven agents), 3 (crew orchestration, Verifier, streaming API) and 4 (baselines) are delivered. Parts 5–8 are pending, and each starts only after your "continue". |
| **Budget** | **$0.** Every model, service and tool is free (§1.4). |
| **Repository** | <https://github.com/KartikJoshi23/TESSERA> (public). Real data and `PS.md` never leave this machine (§12.7). |
| **Problem** | `PS.md`, Problem 1 (finalized). Problem 2, the Part B audit logs and the dropped candidates are used only where they constrain Problem 1. |
| **Codename** | TESSERA. A tessera is one glass tile of a mosaic, and in ancient Rome a tessera was also a token used to prove identity. The system builds one picture from five separate registers. |
| **Nature** | Internal research and evaluation system. Not a public tool and not a consumer product. |

> `PS.md` was not in the project root. The copy in the Downloads folder (saved 3 Nov 2026, 18:31) matched the described problem, so it was copied unchanged into the root. It stays **local only** because it quotes DFSA alerts (§12.7).

---

## Contents

0. [Executive summary](#0-executive-summary)
1. [Scope and constraints](#1-scope-and-constraints)
2. [Requirements and constraints traceability](#2-requirements-and-constraints-traceability)
3. [System architecture](#3-system-architecture)
4. [Outcome semantics and decision policy](#4-outcome-semantics-and-decision-policy)
5. [The agent crew](#5-the-agent-crew)
6. [Inter-agent communication, shared context and reconciliation](#6-inter-agent-communication-shared-context-and-reconciliation)
7. [Deterministic tools](#7-deterministic-tools)
8. [Data sources and legal access (Phase 1)](#8-data-sources-and-legal-access-phase-1)
9. [DFSA compliance architecture](#9-dfsa-compliance-architecture)
10. [Baselines, ablations and the fairness contract](#10-baselines-ablations-and-the-fairness-contract)
11. [Evaluation methodology](#11-evaluation-methodology)
12. [Ethics and legal safeguards built into outputs](#12-ethics-and-legal-safeguards-built-into-outputs)
13. [Tech stack](#13-tech-stack)
14. [File and folder structure](#14-file-and-folder-structure)
15. [Frontend design](#15-frontend-design)
16. [Phased build roadmap](#16-phased-build-roadmap)
17. [Research-paper potential](#17-research-paper-potential)
18. [Risks and resolved decisions](#18-risks-and-resolved-decisions)
- [Appendix A: Seed rule cards and jurisdiction matrix](#appendix-a-seed-rule-cards-and-jurisdiction-matrix)
- [Appendix B: Activity taxonomy (seed)](#appendix-b-activity-taxonomy-seed)
- [Appendix C: Glossary](#appendix-c-glossary)
- [Appendix D: Sources and research log](#appendix-d-sources-and-research-log)
- [Appendix E: Audit log (version 1 → version 2)](#appendix-e-audit-log-version-1--version-2)
- [Appendix F: Changes made during the build](#appendix-f-changes-made-during-the-build)

---

## 0. Executive summary

1. **What we build.** A crew of seven LLM agents: Jurisdiction, three regulator agents (CMA, DFSA, VARA), Clone-check, Reconciler and Verifier. The crew takes a clearly labelled synthetic offer and returns exactly one of three results: **"Consistent with the official record"**, **"Conflicts with the official record"** or **"Could not verify"**. Every claim links to an evidence record created by a deterministic tool.
2. **Why a crew, and how we make that claim testable.** PS.md justifies a crew on two grounds only: conflicting jurisdiction and scope reasoning, and an independent check against false reassurance. Both become real mechanisms that can be inspected:
   - a typed challenge → response → resolution protocol on a shared, event-sourced blackboard;
   - a Verifier whose veto can only make a result more cautious.
3. **The comparison is the research.**
   - The single agent gets the same model, decoding settings, tools, rule knowledge, output contract and runner code as the crew.
   - Further baselines spend extra compute in other ways: majority vote over five runs, the model's highest reasoning setting, and optionally a larger free model.
   - Ablations switch off sharing, challenges and the Verifier one at a time.
   - Work from 2025–26 finds that single agents often match multi-agent systems at equal compute. A tie is a valid, publishable outcome, and the design is built to detect a tie, not to hide one.
4. **Zero budget.**
   - All models run on NVIDIA's free API catalog, which uses the OpenAI request format. Its stated limit is about 40 requests per minute, but about 8 per minute were measured on this key (§11.5).
   - The whole stack is open source, everything runs on this machine, and CI uses free GitHub Actions on the public repository.
   - Because the models are open-weight, anyone can repeat the experiments at no cost.
5. **Legal design.**
   - No component may access a regulator website automatically. Network calls to regulator domains are blocked in code.
   - DFSA material is never scraped, cached, indexed, stored as pages or deep-linked. The only DFSA data is a set of minimal facts recorded by hand, kept in one restricted, git-ignored store and used only in internal research mode.
   - **DFSA values never reach a model provider.** A masking gateway replaces them with placeholders before any request leaves the machine.
   - CMA data comes from the manual "Export To Excel" button. VARA data is copied by hand at a low rate.
   - Nothing real is published: the public repository holds code, documentation and fictional test data only.
6. **Output ethics.** Results state register and alert facts with dates and links, and they say what was not checked. They never call a firm a scam or a site a clone, never recommend an investment, and run only on synthetic inputs.
7. **Evaluation.**
   - Entity-level checks run on real register and alert records; message-level checks run on labelled synthetic offers built from alert facts. The two are reported separately and never pooled.
   - The main safety metric is the **false-reassurance rate**.
   - We use paired statistics, hypotheses registered in advance, and a request budget that fits the free tier: about 95K model calls, or about 45 hours of background running.
8. **Delivery.** Eight build parts, each ending at a stop point for your approval. Part 1 (foundations) is built. Four human tasks are on the critical path: the CMA export, the VARA transcription, the DFSA hand-recording and the annotation.

---

## 1. Scope and constraints

### 1.1 In scope (Phase 1)

- **Regulators:**
  - CMA: federal, formerly the SCA; the legacy name still appears on its pages.
  - DFSA: the DIFC.
  - VARA: Dubai outside the DIFC.
- **Offer types:** investment, trading (securities, FX and CFDs, commodities) and crypto or virtual assets. Loan, deposit and payment offers are *recognised* as CBUAE matters and reported as "not checked in this phase" until Part 8.
- **Inputs:** synthetic offer messages (text), plus entity queries built from real records.
- **Outputs:** the three-way result, a plain-language explanation, evidence, which regulators are relevant and why, a list of what was and wasn't checked, and a standard disclaimer.
- **Users:** the internal research team only.

### 1.2 Later (Part 8 and optional)

- CBUAE and ADGM FSRA agents and data.
- The IOSCO I-SCAN API: free, but you would need to sign its terms.
- Domain context (RDAP, Certificate Transparency) as context that never decides a result.

### 1.3 Non-goals

- No public release or hosting, and no consumer interface.
- No real user messages, ever (UAE data-protection law; PS.md B1 #12).
- No verdicts about firms or people, such as "scam", "fraud", "clone" or "fake" used as conclusions.
- No investment advice, rankings or suitability judgements. The CMA licenses advice and finfluencers.
- No scraping, crawling or headless browsing of regulator sites.
- No computer vision (PS.md B1 #11).
- Problem 2 (firms finding their own clones) is not built. Its alert-listed fake domains may serve as test facts, under the same DFSA limits.

### 1.4 Constraints added after the first review (3 November 2026)

| Constraint | Consequence for the design |
|---|---|
| **No capital.** Everything must be free | Models come from NVIDIA's free API catalog (trial terms permit research use). The stack is open source and hosted locally; CI runs on free GitHub Actions. A **request budget** replaces the dollar budget (§11.5) |
| **Public GitHub repository**, with updates pushed to `main` | Only code, docs, policies, rule cards, empty templates and **fictional** fixtures are committed. `PS.md`, real data, snapshots, datasets, run logs and secrets are git-ignored. A commit guard and CI enforce this, also blocking DFSA deep links and API keys (§12.7) |
| **This machine:** Windows 11, Python 3.11, Node 22, 2 GB GPU | The backend targets Python ≥ 3.11. Running models locally is not practical, so the hosted free API is the main path |
| **Free model endpoints may log what is sent to them** (sources disagree) | Restricted-value masking gateway (§9.4). Only synthetic text and public CMA/VARA facts leave the machine; no personal data at all |

---

## 2. Requirements and constraints traceability

Each requirement from PS.md, the brief and your later instructions maps to a design response, the component that enforces it and the test that proves it.

| # | Requirement or constraint | Source | Design response | Enforced in | Verified by |
|---|---|---|---|---|---|
| R1 | Exactly three results, worded as in PS.md | PS.md, official statement | Fixed outcome set and exact display strings | `policies/decision_policy.yaml`, `reporting/` | Renderer snapshot tests |
| R2 | Results are evidence-linked | PS.md | Only tools create evidence; every claim cites evidence IDs (§6.3) | `protocol/`, Verifier G1–G2 | Protocol invariant tests |
| R3 | Verifier blocks unsupported "consistent" results | PS.md crew roles | Gates G1–G8; a veto can only downgrade (§6.8) | `agents/verifier`, `orchestration/` | "Veto never upgrades" property test |
| R4 | Register lookups are tools, not agents | PS.md | Deterministic lookups that create evidence (§7) | `tools/` | Unit tests |
| R5 | Mandatory single-agent baseline, not rigged | PS.md, brief | Fairness contract (§10.1) | `baseline/` | Config-diff test |
| R6 | Entity-level and message-level results reported separately | PS.md ground truth | Separate datasets, reports and dashboard tabs | `eval/` | Report generator refuses pooled tables |
| R7 | Synthetic messages only, clearly labelled | PS.md (data protection) | Synthetic-input gate; SYNTHETIC tag on every case | `governance/synthetic_gate` | Gate tests |
| R8 | Never label a firm a "scam" or a site a "clone"; report facts with dates | PS.md B1 #12, B2 #12 | Language policy, linter and Verifier gate G5 | `governance/language` | Linter tests |
| R9 | No investment recommendations | PS.md B1 #12 | Output contract and linter; no ranking features | Same | Tests |
| R10 | No automated access to the DFSA (bot protection) | PS.md, brief | Network guard blocks regulator domains; no scraper code exists | `governance/network` | Test: connecting to `dfsa.ae` raises |
| R11 | DFSA: no storage in retrieval systems, no caching, links to the homepage only | DFSA Legal Disclaimer, via PS.md | Minimal hand-recorded facts in a restricted store; references by ID elsewhere; no indexes or embeddings; masking before model calls; link sanitiser (§9) | `data/`, `governance/` | Tests |
| R12 | No public release of a tool that uses DFSA data | PS.md | Local-only binding; `RESTRICTED_DEMO` mode; release checklist | `config/`, `docs/` | Test: demo mode contains zero DFSA values |
| R13 | CMA: no load, crawling or weakness testing; manual Excel export only | CMA terms (read again 3 Nov 2026) | Manual ingest; network guard; deep links allowed; no framing | `data/ingest`, `governance/` | Tests |
| R14 | VARA, CBUAE, ADGM: manual download at a low rate, treated cautiously | PS.md, brief, terms read 3 Nov 2026 | Manual transcription; internal non-commercial use; no redistribution | `data/`, `docs/` | Release checklist |
| R15 | Phase 1 covers CMA, DFSA and VARA, and reports coverage | PS.md B1 #13 | Jurisdiction still flags CBUAE and FSRA relevance; results list what wasn't checked | `agents/`, Verifier G7 | Tests |
| R16 | Agents genuinely communicate and resolve conflicts | Brief | Blackboard, typed messages, challenge rounds, Reconciler and veto (§6) | `orchestration/` | Invariant and ablation tests |
| R17 | No hardcoded secrets; relative paths | Brief | Environment-based settings; repository root found automatically | `config/` | Commit guard scans for keys |
| R18 | Absence from a list does not prove legitimacy | PS.md (IOSCO) | A firm that isn't found is never "consistent", and is "conflicts" only when the offer's own claim is contradicted | Decision policy | Policy tests |
| R19 | Zero budget | Your instruction, 3 Nov 2026 | Free NVIDIA API catalog; open-source stack; local hosting; free CI | `llm/`, ADR-0004 | No paid provider in config |
| R20 | Public repository: no real or restricted data published | DFSA disclaimer; VARA terms; public repo | Git-ignore rules, commit guard, CI guard | `scripts/check_restricted.py`, `.githooks/`, CI | Guard tests; CI fails on any violation |
| R21 | No DFSA values sent to third-party model APIs | DFSA disclaimer; NVIDIA trial data practices | Restricted-value masking gateway on every outgoing request | `governance/masking` | Invariant test over every serialised request |
| R22 | No DFSA deep links anywhere, including documentation | DFSA disclaimer | Link sanitiser; commit guard rejects any `dfsa.ae/<path>` link | `governance/links`, guard | Guard tests |

---

## 3. System architecture

```text
 ┌─────────────────────────────── Frontend (Next.js 16, TypeScript) ───────────────────────────────┐
 │  Intake · Orchestration Theater · Result Dossier · Crew-vs-Baseline Arena · Evaluation Lab ·    │
 │  Data & Governance                                                                              │
 └──────────────────▲───────────────────────────────────────────────▲──────────────────────────────┘
                    │ REST                                          │ SSE (live events and replay)
 ┌──────────────────┴───────────────────────────────────────────────┴──────────────────────────────┐
 │                                   API layer (FastAPI, localhost only)                           │
 └──────────┬────────────────────────────────────────────────────┬─────────────────────────────────┘
            │                                                    │
 ┌──────────▼──────────────────────────────┐   ┌─────────────────▼──────────────────────┐
 │ Crew orchestration                      │   │ Baselines                              │
 │  LangGraph control graph · round        │   │  SA-BASE · SA-VER · SA-SC5 · SA-MAX ·  │
 │  scheduler · conflict detector ·        │   │  SA-LARGER (optional) · RULES-ONLY     │
 │  decision-policy engine · ablations     │   │                                        │
 └──────────┬──────────────────────────────┘   └─────────────────┬──────────────────────┘
            │          both use the SAME runner, tools and evidence store
 ┌──────────▼────────────────────────────────────────────────────▼──────────────────────┐
 │ AgentRunner: tool loop · JSON validation and repair · usage accounting · failures     │
 ├───────────────────────────────────────────────────────────────────────────────────────┤
 │ Masking gateway: DFSA values → placeholders on the way out; restored on the way back  │
 ├───────────────────────────────────────────────────────────────────────────────────────┤
 │ LLM client (OpenAI-compatible) · shared rate limiter (35 req/min) · retries · resume  │
 └──────────┬───────────────────────────────────────────────────────┬───────────────────┘
            │ reads and writes                                      │ HTTPS → NVIDIA API catalog (free)
 ┌──────────▼───────────────────────────┐   ┌───────────────────────┴───────────────────┐
 │ Blackboard (event-sourced)           │◄──│ Deterministic tools (read-only, offline)  │
 │ findings · messages · conflicts ·    │   │ register and alert lookups · contact      │
 │ resolutions · evidence store         │   │ extraction · domain, phone and payment    │
 └──────────────────────────────────────┘   │ analysis · rule-card retrieval            │
                                            └───────────────────────┬───────────────────┘
 ┌──────────────────────────────────────────────────────────────────▼───────────────────┐
 │ Data layer: versioned snapshots (CMA, VARA) · hand-records · RESTRICTED store (DFSA) │
 │ · manifests (who, when, file hash)                                                   │
 └──────────────────────────────────────────────────────────────────▲───────────────────┘
                                                                    │ manual ingest only (no crawler exists)
 ══════════════════════════════════════════════════════════════════════════════════════════
  Governance layer (cuts across all layers): machine-readable source policies · network guard
  for regulator domains · link sanitiser · mode gate (RESEARCH_INTERNAL / RESTRICTED_DEMO) ·
  synthetic-input gate · language linter · restricted-data guard · masking gateway · commit guard
 ══════════════════════════════════════════════════════════════════════════════════════════
```

| Layer | Responsibility | Key decision |
|---|---|---|
| Governance | Turns every legal and ethical constraint into code: policies in `policies/*.yaml`, enforced by guards | "Policy as code": a constraint without an enforcing guard and a test is a bug |
| Data | Manual ingestion, normalisation, immutable JSONL snapshots, provenance manifests, restricted DFSA store | No network code for regulator sources |
| Tools | Deterministic, read-only, offline lookups and analyses that create evidence records | Tools are the only source of evidence |
| Agent runner | One code path for every LLM call (crew and baselines) | Fairness: identical model calls, decoding settings, limits and accounting |
| Masking gateway | Replaces every restricted value with a stable placeholder before a request leaves the machine | DFSA values never reach a third party |
| LLM client | OpenAI-compatible client, shared rate limiter, retries, resumable runs | Free provider; one experiment never mixes models |
| Blackboard | Shared, append-only state: findings, messages, conflicts, evidence references, events | Event-sourced, so any case can be replayed |
| Orchestration | Rounds, routing, limits, conflict detection, decision policy, ablation switches | Scheduling is deterministic; agent outputs are not |
| API | Case runs, live event stream, replay, evaluation results | Binds to 127.0.0.1 |
| Frontend | Intake, live visualisation, results, comparison, evaluation | Uses the same event reducer for live and replay |
| Evaluation | Datasets, harness, metrics, statistics, reports | Entity-level and message-level kept apart |

---

## 4. Outcome semantics and decision policy

The three results need precise, testable definitions. Otherwise neither the crew nor the baseline can be scored fairly. The policy below lives in `policies/decision_policy.yaml`. The Reconciler applies it, the Verifier enforces it, and the evaluation uses it to derive gold labels (see §11.6 on why this is not circular).

### 4.1 The three results (exact wording)

| Code | Displayed wording | Meaning |
|---|---|---|
| `CONSISTENT` | **Consistent with the official record** | All of K1–K7 (§4.3) hold, each backed by evidence |
| `CONFLICTS` | **Conflicts with the official record** | At least one hard conflict from HC1–HC6 (§4.2) is backed by evidence |
| `UNVERIFIED` | **Could not verify** | Everything else. The reasons U1–U9 are always listed |

### 4.2 Hard conflicts (any one gives `CONFLICTS`)

| ID | Hard conflict | Evidence required | Example |
|---|---|---|---|
| HC1 | A deciding contact point in the offer (§4.7) appears on an official alert, warning or unlicensed list | List record plus an exact normalised match | The offer's website is the domain named in an impersonation alert |
| HC2 | The offer's named entity appears on an official warning or unlicensed list, by exact normalised name or a listed alias | List record plus match record | The entity is on VARA's Unlicensed VASPs list |
| HC3 | The offer claims an authorisation (regulator, licence or reference number) that the register contradicts | Register record, or a recorded no-match on the claimed register | The claimed reference number belongs to another firm; a "licensed" claim for an entry that only holds In-Principle Approval |
| HC4 | The matched licence does not cover the offered activity under the competent regulator's published scope rule | Register record plus rule card | A CMA Category 5 firm offering FX or CFD trading; a VARA IPA holder taking clients |
| HC5 | A deciding contact point contradicts the official record for the claimed firm: it imitates the official domain, or it differs from an official contact the regulator itself states | Official contact record plus similarity analysis | A look-alike of the registered website with an added word such as "capital" |
| HC6 | The payment beneficiary differs from the claimed firm's registered legal name | Payment analysis plus register record | "Deposit to XYZ General Trading" for a regulated broker |

A firm that isn't found is **never** a conflict on its own (R18). It becomes HC3 only when the offer claims an authorisation that the register contradicts.

### 4.3 Conditions for `CONSISTENT` (all required)

| ID | Condition |
|---|---|
| K1 | **Identity:** the claimed firm matches exactly one register entry. The match is exact, by alias, or fuzzy but confirmed by a second identifier such as the reference number or the official domain. |
| K2 | **Competence:** that regulator is in the agreed set of relevant regulators for the offered activity and zone. |
| K3 | **Status and scope:** the entry is active (not IPA-only, withdrawn or suspended), and the licence covers the activity, with the rule card cited. |
| K4 | **Contacts:** every *deciding* contact point in the offer (§4.7) *matches* the official record (same registrable domain, email domain or phone). A contact that is merely "not on record" fails K4. |
| K5 | **No adverse hits:** no checked list names any of the offer's contact points, or names the entity itself as unauthorised, and no conflict is left unresolved. An impersonation alert that names the entity as the *impersonated firm* does not block this result by itself. It does mean K4 must be met in full, and the result discloses the alert. |
| K6 | **Coverage:** every relevant regulator was checked. If a relevant regulator is outside current coverage (CBUAE or FSRA in Phase 1), the result cannot be `CONSISTENT`. |
| K7 | **Evidence:** every claim behind K1–K6 cites valid evidence (Verifier G1–G2). |

### 4.4 Reasons for "Could not verify" (always listed)

| ID | Reason |
|---|---|
| U1 | No matching entry on any checked register. Absence is not proof either way. |
| U2 | A relevant regulator is not covered yet (CBUAE or ADGM FSRA in Phase 1). |
| U3 | Deciding contact points are not on the official record, or cannot be compared (§4.7). |
| U4 | Identity is ambiguous: several candidate entries and no second identifier. |
| U5 | A conflict between agents remained unresolved after the round limit. |
| U6 | A Verifier veto was not cleared after remediation. |
| U7 | A tool, data or model failure; a snapshot older than the staleness threshold (60 days); or the case's request budget was used up. |
| U8 | The named regulator is not a UAE financial regulator, so the claim cannot be checked. |
| U9 | A matched entry could not be confirmed as the competent regulator's active licence for the offered activity: for example, scope is unknown, or the entry is not active and the offer made no claim about it. |

### 4.5 Precedence rules for resolving conflicts (P1–P7)

| ID | Rule |
|---|---|
| P1 | **Evidence beats assertion.** A position without valid evidence loses. |
| P2 | **Specific official statements beat inference.** An alert that names a domain beats a register-based guess about that domain. |
| P3 | **The competent regulator's scope rule beats general jurisdiction heuristics.** |
| P4 | **Zone carve-outs beat emirate-level defaults.** A targeting rule (FDL 33 Art. 2(1)(d)) can *add* a relevant regulator but never removes one. |
| P5 | **Overlap is not conflict.** Several regulators can be relevant at once. The relevant set is the union of supported claims. |
| P6 | **More recent dated records govern.** Staleness is disclosed. |
| P7 | **Unresolved after the limits:** choose the most cautious result the evidence supports. Never `CONSISTENT`. `CONFLICTS` only if an evidence-backed hard conflict stands regardless of the unresolved point. |

### 4.6 What a result never says

- **Banned as conclusions:** "scam", "fraud", "fraudulent", "fake", "clone(d)", "illegal", "criminal", and "legitimate", "safe" or "trustworthy" used as a verdict.
- **Banned as advice:** "invest" or "do not invest", "guaranteed", any ranking.
- **Facts are always attributed and dated:** for example, "listed among VARA's unlicensed VASPs in an entry dated 13 January 2026". A regulator's own list name is allowed as an attributed proper noun.

### 4.7 Which contact details can decide a result

| Contact type | Role |
|---|---|
| Website or registrable domain; email domain; phone number; IBAN; crypto wallet | **Deciding:** used in K4, HC1 and HC5 |
| Postal address | **Reported, never deciding.** Addresses are easy to copy, and registers can lag behind office moves. A match is not proof; a mismatch is a disclosed discrepancy |
| Social-media handles and messaging usernames | **Reported, never deciding.** Official records rarely list them |
| Shortened or obscured links | **Not comparable.** They are never expanded, because the tools have no network access, so the result is U3 |

---

## 5. The agent crew

### 5.1 Roster

| Agent | Purpose | Reads (blackboard view) | Tools | Writes | Can challenge |
|---|---|---|---|---|---|
| **JUR** Jurisdiction | Classify the offered activities, zone signals and claims; propose the set of relevant regulators, citing rules | Offer text (as quoted data), extracted contacts, its inbox | None | Activity profile, zone signals, claims, relevance hypothesis per regulator (primary / possible / not indicated / excluded) | Regulator agents' relevance opinions |
| **CMA** regulator agent | Apply the CMA register, warnings and scope rules: Category 5 limits, FDL 33 reach, the CMA virtual-asset framework, "SCA" as a legacy name | Offer, JUR findings, summaries of other regulators' findings, its inbox | `cma_register_lookup`, `cma_warnings_lookup` | Relevance opinion, register match or no-match, licence scope, alert hits, official contacts | JUR; other regulator agents |
| **DFSA** regulator agent | The same for the DFSA, from hand-recorded facts (research mode only) | Same | `dfsa_facts_lookup` | Same | Same |
| **VARA** regulator agent | The same for VARA: licensed VASPs and IPA holders kept separate; licensed activities; unlicensed list | Same | `vara_register_lookup`, `vara_unlicensed_lookup` | Same | Same |
| **CLN** Clone-check | Compare every deciding contact and payment detail with the official record | Offer contact points, official contacts and alert hits from the regulator agents, its inbox | `compare_domain`, `analyse_phone`, `analyse_payment`, `reverse_contact_lookup`, `official_contacts_for` | Assessment per contact point; payment assessment | Any finding that assumes contacts are consistent |
| **REC** Reconciler | Mediate conflicts; issue targeted challenges and requests; write the proposed result | All findings, messages, conflicts and evidence views. No agent's raw reasoning | None; can route a lookup request to a named agent | Challenges, requests, resolutions, proposed result | All agents |
| **VER** Verifier | Independent gate: veto unsupported or non-compliant results | Proposed claims, the **full** case evidence store, policies. **Not** the Reconciler's reasoning | None for the model: the evidence is in its view. The decision-policy engine and language linter run as deterministic gates | Verifier report: APPROVE or VETO, with reasons | The proposed result |

These parts run without an LLM: Intake (deterministic extraction), the Orchestrator and round scheduler, the Conflict Detector, the decision-policy engine, the report renderer and the language linter.

Tools are kept to the ones that need a model's judgement, because each call costs a free-tier request. Intake runs `extract_contact_points` before any agent. Rule cards are in the prompts, and citing one mints its evidence. `reverse_contact_lookup` belongs to CLN alone, because it covers every alert list and one call is enough (Appendix F).

### 5.2 Role notes

- **Jurisdiction.**
  - Outputs a *set* of regulators, each with a status and rule IDs.
  - Treats an offer's claims ("DIFC office", "DFSA regulated") as claims, not facts.
  - Recognises legacy and wrong names: "SCA" means the CMA; a named body that is not a regulator gives U8.
  - Must flag coverage gaps, such as a loan offer that is a CBUAE matter.
- **Regulator agents** share one base behaviour, specialised by their rule card and tools. Each must state **its own** relevance opinion independently of JUR, so that disagreements come to the surface. Each turns its lookups into findings with evidence IDs, and says which register fields were unavailable.
  - *CMA:*
    - Category 5 covers introduction, promotion and financial consultation; its notice says it "does not in any way authorize" FX or derivatives trading.
    - FDL 33 Art. 2(1)(d) reaches firms that target UAE clients.
    - Decision No. 4/R.M/2026 sets the federal virtual-asset framework.
    - The warnings list is checked.
  - *DFSA:*
    - Works only from hand-recorded facts.
    - Knows the trap that impersonation alerts name the *legitimate* firm as the victim.
    - Checks the firm's permitted financial services.
    - Links only to the homepage.
    - In `RESTRICTED_DEMO` mode it returns "manual check required at www.dfsa.ae".
  - *VARA:*
    - Covers Dubai outside the DIFC.
    - IPA is not a licence.
    - Licences are activity-specific.
    - The Unlicensed VASPs list has 38 entries; the latest is dated 13 January 2026.
- **Clone-check.**
  - Exact comparisons are done by tools.
  - The LLM judges only ambiguous cases, such as a domain that could be a firm's regional site. Those are reported as "not on record" (U3), never as conflicts, unless an official source says otherwise.
- **Reconciler.**
  - Owns no facts and cannot create evidence.
  - Every resolution cites a precedence rule and evidence.
  - Must address every open conflict explicitly.
  - Writes the explanation within the output contract (§12.1).
- **Verifier.**
  - Independent by construction.
  - Runs the cheap, exact deterministic gates first, then LLM checks.
  - Can only APPROVE or VETO. After the remediation limit, the orchestrator downgrades a vetoed result to "Could not verify".

### 5.3 Model configuration (free tier)

- **Provider.** NVIDIA API catalog (build.nvidia.com), free trial tier, at `https://integrate.api.nvidia.com/v1` (OpenAI-compatible). One key is kept in `NVIDIA_API_KEY` in the local `.env`, which is never committed. **The key is first needed in Part 2.**
- **Models.** `policies/models.yaml` holds the choices, and ADR-0004 holds the measurements. NVIDIA lists more models than it serves to an account, so a listed model can still return 404. The choices below are what this account can reach, as of 4 Nov 2026.
  - *Primary:* `nvidia/nemotron-3.5-super-vl-120b-a12b`, a mixture-of-experts model with 12B active parameters. The planned `nvidia/nemotron-3-super-120b-a12b` is listed but returns 404 for this account.
  - *Capability arm:* a smaller model from the same family, `nvidia/nemotron-3.5-lightning-30b-a3b`.
  - *Synthetic paraphrase and the optional LLM judge:* a different family, so that generated data does not match the model under test: `mistralai/mistral-large-4-1t-a52b`, with `deepseek-ai/deepseek-v4.1-flash` as the alternative. Part 6 confirms this.
  - *SA-LARGER:* the largest tool-capable model that answers: `nvidia/nemotron-3-ultra-550b-a55b`.
- **Probe protocol** (Part 2; development smoke set only, never test data):
  1. List the available models via `/v1/models`.
  2. For each candidate, run 20 tool-calling trials and 20 structured-output trials.
  3. Select by fixed criteria: at least 95% valid tool calls; at least 95% schema-valid output after one repair; a context window of at least 128K tokens (read from the model card); acceptable median latency.
  4. Record the choice in ADR-0004 before any test-set run.
- **Decoding.**
  - Temperature 0, with a fixed seed where supported, for the primary comparison, identical for every role and condition.
  - Temperature 0.7 only for self-consistency and stability runs.
- **Reasoning.** If the model has a reasoning switch, every role and baseline uses the same default setting. The primary model reasons by default, and `policies/models.yaml` states that explicitly. No higher setting has been found yet, so Part 4 must confirm what SA-MAX can actually change.
- **Structured output.**
  - Every model follows one path: JSON instructions, then Pydantic validation, then one repair attempt. The probe measures this exact path. If a model falls short, a JSON-schema response format can be added without changing the agents.
  - An output that is still invalid becomes an "agent failed" finding (U7).
- **Tools.**
  - OpenAI-style function tools defined in JSON Schema, with `tool_choice: "auto"`.
  - Arguments are validated before they run. An error goes back to the model as the tool's result, so it can correct itself.
  - A regulator turn that produces no evidence from that regulator's sources is recorded as a coverage gap, so a skipped lookup cannot pass unnoticed.
- **Rate limits and throughput.**
  - The free tier is said to allow about 40 requests per minute, and per-model limits are not published. **Measured on 5 Nov 2026 with no retries, about 8 requests a minute got through on this key, whatever the prompt size** (90 to 14,000 tokens), after a short burst of about 7.
  - One shared rate limiter runs at 7.5 requests per minute, with exponential backoff on HTTP 429 or 5xx errors. Pacing above the real limit wastes requests on retries: at 35 per minute the run achieved only 4.5.
  - Runs are resumable, and the harness can run several cases at once under the same limiter, because the limit is on requests and a crew spends most of a case waiting for one reply at a time.
  - **One key only.** No key rotation or extra accounts to get around limits. If throughput becomes the bottleneck, request a limit increase through NVIDIA's developer forum, but do not plan on one: forum replies point paying users to their own deployments, so the request budget must fit the free limit.
- **Model identity.**
  - Record exact model IDs and dates.
  - Run every condition of an experiment within one time window.
  - If the catalog retires or updates a model mid-experiment, re-run every condition on the replacement.
- **Reasoning text.** It is shown to humans in the UI only if the model returns it. It is never passed between agents.

---

## 6. Inter-agent communication, shared context and reconciliation

This section is the core of the project. The crew is only worth studying if information really flows between agents, disagreements really get settled, and the Verifier can really stop a result. Each mechanism below is concrete, logged and can be switched off for ablation.

### 6.1 Design principles

1. **Typed communication only.** Agents exchange validated findings and messages through the blackboard. Raw model output, tool transcripts and reasoning text are never forwarded between agents.
2. **Only tools create evidence.** An agent can cite evidence but cannot make it up.
3. **Bounded rounds, deterministic scheduling.** Who runs when depends only on the blackboard state, and every loop has a hard limit.
4. **The Verifier is independent because of what it cannot see.** It never sees the Reconciler's reasoning.
5. **Event-sourced.** Every state change is an event, so any case can be replayed exactly as it happened.
6. **Every mechanism is a switch.** Sharing, challenges, the Reconciler and the Verifier can each be turned off for ablations.
7. **Positions change only with evidence.** This protects against conformity, where an agent simply agrees with others; Choi et al. (2025) show debate on its own does not improve expected correctness.

### 6.2 Blackboard records

| Record | Key fields | Written by |
|---|---|---|
| Case | Case ID; mode; system condition; model configuration hash; prompt and rule-card versions; snapshot IDs; synthetic flag; corpus item ID | Orchestrator |
| ContactPoint | ID; kind; raw and normalised value; text span; whether it can decide a result (§4.7) | Intake tool |
| EvidenceRecord | Evidence ID (content hash including the case ID); source ID; kind (register entry, no-match, alert entry, warning entry, unlicensed entry, rule card, derived analysis); snapshot ID and date; locator; fields; `restricted` flag; display link (cleaned by policy); creating tool; case ID | **Tools only** |
| Finding | Finding ID; author; type (from the claim catalogue, §6.2.1); typed assertion; confidence (low/medium/high); evidence IDs; depends-on; status (active, challenged, revised, withdrawn, superseded); version; supersedes | Agents, validated by the orchestrator |
| Message | Message ID; round; sender; recipients; performative; referenced findings; evidence IDs; body; rationale (60 words max) | Agents, orchestrator |
| Conflict | Conflict ID; type C1–C7; findings involved; detected by (detector or Reconciler); status; resolution ID | Detector, Reconciler |
| Resolution | Conflict ID; outcome; precedence rule; evidence IDs; rationale | Reconciler |
| ProposedResult | Result code; claims (each with a **typed assertion**, the text it renders to, and evidence IDs); relevant regulators; coverage; explanation; version | Reconciler (or the single agent in baselines) |
| VerifierReport | Decision; gate results; entailment results; contradicting evidence; veto reasons | Verifier |
| Event | Sequence number; timestamp; case ID; actor; type; payload reference; usage (requests, tokens); latency | Everything (append-only) |

#### 6.2.1 Claim catalogue

Typed assertions let the Verifier check claims mechanically (G2, G8), and let the decision-policy engine compute the result.

| Assertion type | Machine-checkable fields |
|---|---|
| `activity` | Activity code, with evidence that the quoted words are in the offer |
| `zone_signal` | Zone, basis (address, name, domain, phone, claim, other) |
| `offer_claim` | What the offer says about itself: kind (firm name, regulator, licence reference, address, other) and value |
| `targeting` | Whether the offer targets UAE clients (yes, no, unclear) |
| `register_match` | Regulator, entity reference, match type (exact, alias, fuzzy, partial or reference number), second identifier |
| `register_no_match` | Regulator, query, snapshot |
| `licence_status` | Regulator, entity reference, status (active, IPA, withdrawn, suspended) |
| `licence_scope` | Regulator, entity reference, activity code, covered (yes or no), rule ID |
| `alert_hit` | Source, record reference, matched on (name, domain, email domain, phone, wallet, IBAN) |
| `contact_assessment` | Contact point, status (matches official, look-alike of official, alert-listed, not on record, not comparable), official record reference |
| `payment_assessment` | Beneficiary name versus registered name; wallet requested (yes or no); IBAN country |
| `relevance` | Regulator, status (primary, possible, not indicated, excluded), rule IDs |
| `coverage_gap` | Regulator, reason, and scope: a whole regulator that is relevant but not covered, or one field that could not be checked |

### 6.3 Evidence rules

- **LLMs never write evidence.** A tool call returns short evidence summaries with IDs, and claims must cite those IDs.
- **IDs are content hashes that include the case ID.** An agent cannot cite an ID that no tool produced in this case; gate G1 checks this.
- **Absence is evidence too.** A lookup that finds nothing creates a `no_match` record holding the query, its normalised form and the snapshot date. That makes a statement such as "not found on the VARA register as of 5 Nov 2026" checkable.
- **Rule cards are evidence.** A scope conclusion cites the rule card and the register entry.
- **DFSA evidence holds no DFSA values.** It holds only the restricted row ID and the display link `https://www.dfsa.ae/`. The values are looked up in memory, locally and in research mode, only when needed.
- **Text injected into an offer cannot create evidence.** Instructions hidden in an offer may steer an agent's wording, but they cannot produce evidence. The deterministic gates block any result whose claims lack valid evidence.

### 6.4 Message protocol (performatives)

The message types are modelled on FIPA-ACL speech acts. Each one has a fixed schema and effect.

| Performative | Sender → recipient | Required content | Effect |
|---|---|---|---|
| `INFORM` | Any agent → blackboard | Finding(s) with evidence IDs | The finding becomes active |
| `REQUEST` | Any agent → named agent | A question and the lookup or finding needed | The recipient is scheduled next round and must answer |
| `CHALLENGE` | Any agent or the Reconciler → author of a finding | Target finding; objection type; counter-evidence or rule ID; question | The target becomes *challenged*; its author must answer at its next turn |
| `REBUT` | Challenged author → challenger and Reconciler | Evidence or rule supporting the original finding | The challenge stays open for the Reconciler |
| `REVISE` | Challenged author → blackboard | A new version of the finding, citing the evidence or rule that justifies the change | The old version is superseded |
| `CONCEDE` | Challenged author → blackboard | Withdrawal | The finding is withdrawn |
| `RESOLVE` | Reconciler → blackboard | Conflict ID; outcome; precedence rule; evidence | The conflict is resolved |
| `VETO` | Verifier → Reconciler and orchestrator | Failed gates; affected claims; required remedy | The proposal is blocked; remediation or downgrade follows |
| `APPROVE` | Verifier → orchestrator | Gate results | The result is final |

**Protocol rules, enforced by the orchestrator rather than by prompts:**

- A `CHALLENGE` without counter-evidence or a rule ID is rejected.
- A `REVISE` must cite the evidence or rule that justifies the change. It may be evidence the finding did not use before. A revision without a citation is rejected and logged as a **conformity flag**.
- An unanswered challenge counts against the finding (P1).
- Messages are built from validated schemas. Raw model output and reasoning text are never forwarded between agents.

### 6.5 Orchestration flow

```text
 Intake ──► R0 Jurisdiction ──► R1 Regulators (CMA ║ DFSA ║ VARA) ──► R2 Clone-check
                                                                     + agents addressed in R1
                                                                              │
                                                                              ▼
                                                                    Conflict detection
                                              open conflicts and round < 3 │      │ none left, or limit hit
                                          ┌────────────────────────────────┘      ▼
                                          ▼                              Reconciler synthesis
                          R3–R5: Reconciler challenges or requests ║              │
                                 challenged agents respond                        ▼
                                          └──────► back to detection        Verifier gate
                                                                 veto, cycle < 1 │     │ approve
                                                          ┌──────────────────────┘     ▼
                                                          ▼                         Report
                                             Remediation: Reconciler requests
                                             lookups or revises ──► Verifier
                                             (veto still standing → "Could not verify")
```

| Step | Who runs | In parallel? | Input view | Output |
|---|---|---|---|---|
| Intake | Deterministic | — | Offer text | Contact points, case record |
| R0 | JUR | — | Offer and contacts | Jurisdiction findings |
| R1 | CMA, DFSA, VARA | Yes | Offer and JUR findings | Relevance opinions; register and alert findings; official contacts; requests and challenges |
| R2 | CLN, plus any agent addressed in R1 | Yes | Contacts, official records, inbox | Contact and payment assessments; responses |
| Detect | Conflict Detector | — | Blackboard | Conflict records |
| R3–R5 | REC (challenge round), then the challenged agents | REC first, then in parallel | Conflicts and inbox | Challenges → rebuttals, revisions, concessions |
| Synthesis | REC | — | Everything | Resolutions and proposed result |
| Verify | VER | — | Claims, evidence, policies | APPROVE or VETO |
| Remediate (max 1) | REC and any agents it requests | — | Veto reasons | Revised proposed result |
| Report | Renderer and linter | — | Approved result | Final result and case file |

**Limits (configurable):**

- at most 3 challenge rounds;
- at most 1 remediation cycle;
- at most 8 tool calls per agent turn;
- a request budget per case.

Every model call in a run goes through the one shared rate limiter. Hitting any limit is logged and maps to reason U5, U6 or U7. Every loop has a hard limit and the report step always runs, so every case finishes.

**Implementation:**

- A LangGraph `StateGraph` with nodes for intake, jurisdiction, regulator fan-out (parallel), clone-check, detection, reconcile round, response fan-out, synthesis, verify, remediate and report.
- Conditional edges enforce the limits.
- The event log is the single record of a case. The graph's own state is a few counters, so it holds nothing restricted.
- Replay comes from the event log, and a run restarts any case it did not finish. Cases are not checkpointed mid-way, because a node's model calls are not safe to repeat (Appendix F).
- A challenge round that changes nothing ends the rounds early, which saves free requests.

### 6.6 Conflict types (detector rules)

| ID | Conflict | Deterministic trigger | Example | Usual resolution |
|---|---|---|---|---|
| C1 | Relevance | JUR and R's own agent disagree on whether regulator R is relevant at all (primary and possible both count as relevant) | JUR excludes VARA because of a claimed DIFC address; the VARA agent says the claim is unverified | P4/P5: overlap allowed; claims are not facts, so R becomes "possible" |
| C2 | Identity | Two findings tie the claimed firm to different entries, or the claimed reference number belongs to another entity | The reference number in the offer belongs to a different authorised firm | HC3 if the claim is contradicted, otherwise U4 |
| C3 | Scope | The activity falls outside the matched licence while another finding treats the firm as authorised for it | CMA Category 5 firm and FX trading | P3, then HC4 |
| C4 | Contact | CLN reports a mismatch, look-alike or alert listing while a regulator agent's finding implies consistency | "Matches the register" versus "domain is alert-listed" | P2, then HC1/HC5 |
| C5 | Alert versus register | The same entity has a register match and is named in an impersonation alert | Licensed firm plus impersonation alert | Settled by the contact comparison (K4 or HC1/HC5) |
| C6 | Missing evidence | A finding cites no evidence, unknown IDs, or evidence whose fields don't match the claim | "Licensed" with no register record | P1: the finding loses |
| C7 | Claim versus record | The offer claims regulator X; X has no match, but another register does | Claims the DFSA; matches a VARA IPA entry | HC3, plus C3 if the entry is IPA-only |

The Reconciler may open conflicts the detector missed. These are logged as `detected_by=REC` and measured separately, which shows what the LLM adds beyond the fixed rules.

The detector runs after every round. If a trigger no longer holds, for example because an agent revised its finding, the conflict is settled with no model request.

### 6.7 How the Reconciler settles conflicts

1. The detector posts the conflicts it finds.
2. For each open conflict, the Reconciler either:
   - (a) resolves it directly, but only if P1–P7 decide it from existing evidence, or
   - (b) sends a `CHALLENGE` with a specific question to the author of the weaker-evidenced finding, or a `REQUEST` for a lookup to a named agent.
3. The challenged agents reply with `REBUT`, `REVISE` or `CONCEDE`, citing evidence.
4. The detector runs again. Steps 2–4 repeat until no conflict is open or the round limit is reached.
5. **Synthesis:** the Reconciler resolves every conflict, or marks it unresolved and applies P7. It then builds the proposed result: typed claims linked to evidence IDs, the relevant regulators, coverage and the explanation.
6. The proposed result goes to the Verifier.

**Safeguards against conformity and persuasion:**

- **Positions move only with cited evidence or rules.** This targets the conformity failure described by Choi et al. (2025).
- **The Reconciler cannot overrule evidence by argument.** Every resolution must cite a precedence rule.
- **Harmful flips are measured.** A harmful flip is a correct finding revised into a wrong one.
- **The Verifier never reads the Reconciler's reasoning.**

### 6.8 The Verifier

**Deterministic gates (run first):**

| Gate | Check | On failure |
|---|---|---|
| G1 Evidence exists | Every claim cites at least one evidence ID created in this case | VETO |
| G2 Evidence supports the claim | Typed assertions match the evidence fields exactly (normalised names, dates, statuses); free-text claims pass an entailment check | VETO |
| G3 Conditions for `CONSISTENT` | K1–K7 all hold | VETO (cannot stay `CONSISTENT`) |
| G4 Conditions for `CONFLICTS` | At least one hard conflict from HC1–HC6 with valid evidence | VETO (cannot stay `CONFLICTS`) |
| G5 Language and advice policy | No banned verdict terms, no recommendations, disclaimer present | VETO (wording) |
| G6 Link policy | Every link follows its source policy: DFSA homepage only; CMA deep links allowed but never framed | Automatic fix, logged |
| G7 Coverage disclosure | Regulators checked and not checked, and snapshot dates, are listed | VETO |
| G8 Matches the decision policy | The proposed result is not more reassuring than the result the decision-policy engine derives from the agreed typed findings | VETO |

**LLM checks:**

- **Entailment:** whether each free-text claim follows from its evidence.
- **Contradiction search:** the Verifier reads the **full** case evidence store, not just the records cited, so it catches cherry-picking such as an alert hit the proposal ignored.

If the proposal is *more cautious* than the policy allows (say "Could not verify" where `CONFLICTS` is supported), the Verifier records this as an advisory "under-call". It is reported as a metric, not a veto.

**Authority:**

- The Verifier can only approve or veto. It never writes a result.
- A veto can move a result toward "Could not verify", never toward "Consistent".
- The Reconciler's resolutions close conflicts, but they never remove a valid finding from what the decision-policy engine reads. A finding whose evidence holds stands, however it was argued.
- A hard conflict backed by valid evidence stands even if a challenge to it goes unanswered, while a finding with an unanswered challenge cannot support `CONSISTENT`. So a challenge alone can never make a result more reassuring.
- A report states only the hard conflicts the evidence backs, even if a proposal listed others.
- After one remediation cycle, a standing veto turns the result into "Could not verify", with the veto reasons listed.

### 6.9 What each agent sees

| Agent | Sees | Never sees |
|---|---|---|
| JUR | Offer text (marked as untrusted data), contacts, jurisdiction rule cards, its inbox | Gold labels, other agents' reasoning |
| Regulator agents | Offer, contacts, JUR findings, summaries of other regulators' findings, its own rule card, its inbox | Gold labels, reasoning, Reconciler drafts |
| CLN | Contacts, official-contact and alert findings, its inbox | Gold labels, reasoning |
| REC | All findings, messages, conflicts and evidence views | Gold labels, reasoning |
| VER | Proposed claims, the full evidence store, policies | The Reconciler's rationale, other agents' prose, gold labels |
| Single-agent baseline | Everything any crew member could fetch with tools; all rule cards | Gold labels |

**Prompt layout and masking:**

- **Stable prefix:** tool definitions, then the system prompt (role, rule cards, policies, output contract). It is kept byte-identical across calls, so any provider-side prefix reuse can help, but nothing depends on caching.
- **Per-call tail:** case data, blackboard view, inbox and task.
- **Offer text** is wrapped and labelled as untrusted data.
- **Masking.** Every outgoing request passes through the restricted-value gateway (§9.4):
  - DFSA values become stable placeholders such as ⟦R:FIRM-1⟧ or ⟦R:DOMAIN-2⟧.
  - The generic parts of names, such as the legal form or "(DIFC)", stay visible.
  - The tools work out every relationship locally (exact match, look-alike, scope) and give the model only the results, with evidence IDs.
  - Placeholders are restored locally in the response.
- **Gold labels:** the evaluation harness strips every `gold_*` field before a case is created, and a test checks this.

### 6.10 Worked example (all names fictional)

**Synthetic offer** (marked SYNTHETIC; reserved `.example` domain, a phone number from a range reserved for fiction):

> "Good evening! I'm Sara from Lumen Crest Capital (DIFC) Limited, regulated by the DFSA (FRN F000000). Our crypto desk offers BTC trading and USDT staking with 3% weekly returns. Office: Gate Village, DIFC, Dubai. Open your account at lumencrest-capital.example and message me on WhatsApp +44 7700 900123. Deposits in USDT (TRC20) to the wallet we send you."

**Fictional hand-recorded DFSA facts:**

- Row D-R-001: the firm is authorised; its permitted services do **not** include crypto services; its website is `lumencrest.example`.
- Row D-A-007: an impersonation alert naming `lumencrest-capital.example`.

Because these rows are restricted, the model sees placeholders: the firm name becomes ⟦R:FIRM-1⟧ (DIFC) Limited, and the two domains become ⟦R:DOMAIN-1⟧ and ⟦R:DOMAIN-2⟧. The relationships between them come from the tools.

| Step | Agent | What happens | Messages and findings |
|---|---|---|---|
| Intake | Tool | Extracts the claimed name, reference number, DIFC address, domain, WhatsApp number and USDT/TRC20 payment | Contact points cp1–cp4 |
| R0 | JUR | Activities: virtual-asset trading and yield. Zone: DIFC (claimed address only). Targets UAE residents. Relevance: DFSA primary (JUR-02); VARA excluded (JUR-01, DIFC carve-out); CMA possible (JUR-04, targets UAE clients) | `INFORM` F-J1…F-J3 |
| R1 | DFSA | Exact match on name and reference number (E1, row D-R-001). Permitted services exclude crypto, so a scope finding (E1 + SCOPE-DFSA-01). The domain is named in an impersonation alert (E2, row D-A-007) | `INFORM` F-D1–F-D3; `REQUEST` → CLN: "compare cp1 with the website in E1" |
| R1 | VARA | No register entry and not on the unlicensed list (E3, E4 no-match). Disputes JUR's exclusion: the DIFC address is only a claim, and nothing else (a UK mobile, a TRC20 wallet) ties the business to the DIFC | `INFORM` F-V1, F-V2; `CHALLENGE` F-J2 (VARA excluded), citing JUR-01 and P4 |
| R1 | CMA | No register entry and no warning (E5, E6). Possibly relevant under FDL 33 Art. 2(1)(d); notes JUR-05 (activity conducted exclusively in the DIFC is outside CMA scope) | `INFORM` F-M1, F-M2 |
| R2 | CLN | cp1 is not the official website (E1); it imitates it with "-capital" added (E7, derived analysis); and it is alert-listed (E2). cp2 is not on the official record. Payment in crypto, while the matched licence excludes crypto | `INFORM` F-C1–F-C3 |
| R2 | JUR | Answers the challenge: VARA's status becomes "possible (zone claim unverified)", citing JUR-01 | `REVISE` F-J2 v2 |
| Detect | Detector | C1 settled by the revision. Still open: C5 (register match plus impersonation alert) and C3 (crypto activity versus permitted services) | Conflicts CF-1 (C5), CF-2 (C3) |
| R3 | REC | Resolves CF-1 by P2: the alert naming cp1 outweighs the name and reference match, so K4 fails and HC1 and HC5 hold. Resolves CF-2 by P3 (HC4). Existing evidence decides both, so no challenge is needed | `RESOLVE` CF-1, CF-2 |
| Synthesis | REC | Proposes `CONFLICTS` with four typed claims: (1) `register_match` [E1]; (2) `alert_hit` on cp1 [E2]; (3) `contact_assessment` cp1 is a look-alike of the official website [E1, E7]; (4) `licence_scope` crypto not covered [E1, SCOPE-DFSA-01]. Relevant: DFSA (primary); VARA and CMA (possible; checked, no entries) | Proposed result v1 |
| Verify | VER | G1–G4 and G6–G8 pass. G5 fails: the draft explanation calls the website "a clone of the firm's website" | `VETO` (G5, claim 3 wording) |
| Remediate | REC | Rewords claim 3 as "a website domain named in a DFSA alert about impersonation of this firm" | Proposed result v2 |
| Verify | VER | All gates pass, and the contradiction search finds nothing | `APPROVE` |

**Final output** (dates illustrative; shown locally with the real values restored):

> **Conflicts with the official record.** The offer uses the name and DFSA Firm Reference Number of a DFSA-authorised firm. However, its website domain is named in a DFSA alert about impersonation of that firm, and it differs from the website shown for the firm on the DFSA register. The register does not list crypto-asset services among the firm's permitted activities, but the offer is for crypto trading.
>
> **Checked:** DFSA (hand-recorded facts, recorded 6 Nov 2026); VARA register and unlicensed list (snapshot 5 Nov 2026); CMA register and warnings (snapshot 5 Nov 2026). **Not checked in this phase:** CBUAE and ADGM FSRA (not indicated as relevant). To confirm, contact the DFSA via www.dfsa.ae.
>
> *This result compares a synthetic offer with official records as of the dates shown. It is not a finding about any firm or person, and it is not legal or investment advice.*

**Single-agent failure modes we will test for** (expectations to test, not assumptions):

- anchoring on the name and reference number match, and answering `CONSISTENT`;
- using scam-like cues as evidence;
- banned words;
- missing the coverage disclosure.

### 6.11 Inspection and telemetry

- **Event types:**
  - case: `case.created`
  - rounds and agents: `round.started`, `agent.activated`, `agent.repair`, `agent.failed`
  - model and tool calls: `llm.response` (with usage and a hash of the request, not the request itself), `tool.called`, `tool.failed`, `evidence.minted`; retries and rate limiting are reported as `llm.retry` and `rate_limited`
  - findings and messages: `finding.posted`, `finding.revised`, `message.sent`, `protocol.rejected`
  - conflicts: `conflict.detected`, `conflict.resolved`, `conflict.settled`
  - proposal and verification: `proposal.created`, `policy.derived`, `verifier.decision` (with every gate's result), `verifier.autofix`
  - outcome: `result.finalized`, `report.wording_replaced`, `case.aborted`, `budget.exceeded`, `rate_limited`
- **Trace bundle:** each case can be exported as a JSON bundle (events, findings, messages, evidence references). DFSA values are left out unless the bundle is opened in research mode.
- **Coordination telemetry** derived from events:
  - conflicts per case;
  - the rate at which challenges lead to revisions;
  - conformity flags and harmful flips;
  - veto precision and recall;
  - rounds used;
  - requests and tokens spent on each mechanism.

---

## 7. Deterministic tools

All tools are read-only, deterministic, offline and unit-tested. Each returns compact evidence summaries with IDs.

| Tool | Used by | Input | Output (evidence created) |
|---|---|---|---|
| `extract_contact_points` | Intake; every agent sees its output | Offer text | Contact points with spans: URLs, domains (via the Public Suffix List), emails, phones (libphonenumber), WhatsApp and Telegram links and handles, IBANs, wallet formats, address cues, licence references |
| `cma_register_lookup` | CMA agent, baseline | Name, licence number or domain | Register entry or no-match: licence number, category or activities, status, contact fields where the export has them |
| `cma_warnings_lookup` | CMA agent, baseline | Name, domain or phone | Warning entry or no-match |
| `vara_register_lookup` | VARA agent, baseline | Name, licence reference or domain | Licensed or IPA entry (kept separate) or no-match: activities and status |
| `vara_unlicensed_lookup` | VARA agent, baseline | Name or domain | Unlicensed entry or no-match |
| `dfsa_facts_lookup` | DFSA agent, baseline | Name, reference number, domain, email or phone | Restricted register or alert fact reference, or no-match. Research mode only. The model gets masked identifiers and relations the tool worked out: status, zone, the activity codes the recorded services cover, and the alert's category in our own labels (§9.2) |
| `reverse_contact_lookup` | CLN, baseline | A contact point | Hits across every alert, warning and unlicensed list |
| `official_contacts_for` | CLN, baseline | An entity evidence ID | Official contact points from that record |
| `compare_domain` | CLN, baseline | Offer domain and official domain | Derived analysis: registrable-domain equality; edit distance (Damerau–Levenshtein); character look-alikes and punycode; added-word ("combosquatting") and typo patterns; top-level-domain swaps |
| `analyse_phone` | CLN, baseline | Offer phone and official phones | Equality in E.164 format; country; number type. A number's validity is **never** treated as a signal |
| `analyse_payment` | CLN, baseline | Payment details and entity record | IBAN checksum and country; beneficiary name versus registered name; crypto wallet requested |
| `get_rule_card` | The runner, when an agent cites a rule (cards are in the prompts) | Rule ID | Rule-card evidence: our own wording plus citation and verification status |

Planned later: CBUAE and FSRA register lookups, an FSRA alerts lookup, an optional I-SCAN lookup through the official API, and optional domain context (RDAP, Certificate Transparency) that never decides a result.

**Data the tools need ships inside the installed packages:** the Public Suffix List snapshot in `tldextract`, libphonenumber metadata in `phonenumbers`, and the IBAN registry in `schwifty`. Tools are configured never to fetch updates, so the "no network" rule holds, and tests block the network to prove it.

**Name matching:**

- **Normalisation:** Unicode NFKC and case-folding; punctuation stripped; legal-form suffixes made canonical (LLC, L.L.C., FZE, FZ-LLC, FZCO, DMCC, Ltd, Limited, PJSC, Branch); zone tags such as "(DIFC)" or "(ADGM)" kept separately; Arabic letter variants and diacritics normalised.
- **Candidates, in order:** exact match on the normalised key, then alias, then token-set similarity above a threshold τ₁, then partial similarity above τ₂.
- **Calibration:** the thresholds are tuned on the development split only.
- **Output:** every match records its type (exact, alias, fuzzy or reference number) and its score.

**Look-alike thresholds** are calibrated on development pairs: real alert-listed fake domains against the official domains of the same firms (DFSA-derived pairs stay restricted), plus synthetic pairs.

---

## 8. Data sources and legal access (Phase 1)

### 8.1 Sources

| Source | What we take | How it is obtained | Stored as (all local, git-ignored) | Evidence link | Refresh |
|---|---|---|---|---|---|
| **CMA Licensed Companies** | Register entries: names (Arabic and English if present), licence number, category or activities, status, and any contact fields in the export (exact columns confirmed at the first export) | **You** click the manual "Export To Excel" button in a normal browser | `data/inbox/` → JSONL snapshot plus manifest | Deep link to the CMA page (allowed); never framed | Manual, at most monthly, plus once at the evaluation freeze |
| **CMA Warnings** | Warned entity names, domains, phones, dates | Recorded by hand from the public page | `data/handrecords/cma_warnings.csv` → snapshot | Deep link | At the freeze |
| **VARA Public Register** | Licensed VASPs (activities, status) and IPA holders, **kept separate** | Copied by hand at a low rate in one browser session | `data/handrecords/vara_register.csv` | Link to the register page | At the freeze |
| **VARA Unlicensed VASPs** | 38 entries: names, domains, dates | Copied by hand | `data/handrecords/vara_unlicensed.csv` | Link | At the freeze |
| **DFSA Public Register** | Minimal facts, for evaluation firms only: name, reference number, status, permitted services, address, and website or phone if shown | Recorded by a person in a normal browser | `data/restricted/dfsa/register_facts.csv` | **DFSA homepage only** | Once, at the freeze |
| **DFSA Alerts (2026)** | Minimal facts: date, our own category label, the firm named, contact points named, legitimate contacts the alert states | Recorded by a person | `data/restricted/dfsa/alert_facts.csv` | **DFSA homepage only** | Once, at the freeze |
| **Rule sources** (laws, regulator guidance) | Jurisdiction and scope rules | Read by a person and summarised **in our own words** with citations | `knowledge/rule_cards/*.yaml` (committed: our wording only) | Citation (DFSA: homepage only) | When the source changes |

The DFSA alert set: PS.md counts at least 10 alerts about impersonated authorised firms and about 10 other false-claim or regulator-impersonation alerts in 2026. "At least ten" is a minimum because the full count was blocked.

**Human effort, all free:**

| Task | Estimated time |
|---|---|
| CMA export | About 10 minutes |
| CMA warnings | 1–2 hours |
| VARA register and unlicensed list | 3–4 hours |
| DFSA hand-recording | 4–6 hours |
| Annotation | About 8 hours per annotator for messages, plus about 5 hours for entities |

### 8.2 How data is ingested by hand

1. A person downloads or copies the source in a normal browser, in a single session, with no automation.
2. The file goes into `data/inbox/<source>/`, or into `data/handrecords/` using the templates in `data/handrecords/templates/`. DFSA files go only into `data/restricted/dfsa/`.
3. The `tessera-ingest` command:
   - validates the file against the source's schema;
   - computes a SHA-256 hash;
   - writes a manifest: source ID, URL, retrieval date, the initials of the person who retrieved it, the page's "last modified" date if shown, row count and notes;
   - normalises the records;
   - writes an immutable snapshot with a snapshot ID;
   - refuses DFSA data outside `data/restricted/`, or in demo mode;
   - has no network code.
4. Evaluation runs pin snapshot IDs, so all systems see identical data.

### 8.3 Terms checked during planning (3 November 2026)

Each source was checked with one page view, or through search results, with no data pages scraped.

| Source | What the terms say | Effect on the design |
|---|---|---|
| **CMA** terms and conditions | Prohibits weakness testing; prohibits interfering by "increasing load to or immersing" the site; prohibits accessing details not meant for the user. Allows "direct link with all pages hosted on this website". Pages may not be loaded "within separate frameworks on another website". No clause on reuse, storage or caching | Manual export only; deep links allowed; **never iframe CMA pages** (links open in a new tab) |
| **VARA** terms of use (last updated 2022-07-26) | Content may be "viewed, downloaded, printed or copied for your personal non-commercial use". "You may not copy, modify, alter, publish, broadcast, distribute, sell or transfer any material." No clause on automated access, caching or deep links. Dubai law applies | Internal, non-commercial research use only; **no redistribution**, including in the public repository; releases use rehydration recipes (§17.5) |
| **CBUAE** terms (from search excerpts; full text not read) | Download or print "for personal use, use within an organisation or non-commercial use"; copies must carry "© Central Bank of the UAE" | Keep the © notice on evidence derived from the CBUAE |
| **ADGM** terms | A limited, revocable licence to use the platforms; the reproduction clause was not reviewed | Reading the terms in full is a prerequisite for Part 8 |
| **IOSCO I-SCAN** | An official API is available after signing the API Terms of Use and applying. The public portal returned HTTP 403 to automated access, so it was not retried | Optional, in Part 8. Absence from I-SCAN never counts as evidence |
| **DFSA** | **Deliberately not accessed** by any automated tool. The constraints come from PS.md's verified quotes | A team member reads the full Legal Disclaimer in a browser before entering data (§9.5) |
| **NVIDIA API catalog** (trial terms; from secondary sources) | For prototyping, research, development, testing and learning, not production. Free tier rate-limited to about 40 requests per minute per model (not published per model). Sources disagree on whether inputs to free endpoints are logged or used for training | Research use fits. Every request is treated as possibly stored by a third party, hence the masking gateway, no personal data and one key. The Part 2 recheck (4 Nov 2026) found no official terms page that could be read without an account, so **you read the terms when you create the key** |
| **crt.sh** (Certificate Transparency) | No usage policy on the homepage | Optional source only; check its documentation before any automated use |

### 8.4 Phase 2 and optional sources

| Source | Access method | Notes |
|---|---|---|
| CBUAE "CB Register as of August 2026" (PDF, 28 pages) and online search | Download the PDF manually; parse it with `pdfplumber` | The © notice is shown on derived evidence |
| ADGM FSRA register and FSRA regulatory alerts (11 in 2026) | Hand-recorded facts once the terms are read; no export exists | Part 8 |
| IOSCO I-SCAN | Official API if granted (free) | An extra warning source; incomplete by IOSCO's own statement |
| RDAP and Certificate Transparency | Rate-limited, cached as each source's policy allows | Never decides a result; never used to label a site |

---

## 9. DFSA compliance architecture

### 9.1 The constraint (from PS.md, quoting the DFSA Legal Disclaimer)

- Extracts are allowed only "for personal use or for use within an individual firm or organisation".
- Storing material "in any public or private electronic retrieval system or service, without the DFSA's prior written permission" is forbidden.
- Caching is prohibited, and so is any link other than to the DFSA homepage.
- The DFSA register and alert pages are bot-protected.
- PS.md's practical reading:
  - record DFSA facts (firm name, fake domain, date) by hand, for internal research evaluation only;
  - do not index DFSA pages;
  - do not publicly release a tool that uses DFSA data without permission.

### 9.2 Data classes

| Class | Examples | Allowed? | Where |
|---|---|---|---|
| DFSA pages and copies | HTML, PDFs, screenshots, saved pages, copied text | **Never** | — |
| DFSA wording | Alert titles, alert text, quotations | **Never stored.** We use our own category labels | — |
| Minimal facts recorded by a person | Firm name, reference number, status, permitted services, address, website or phone if shown, alert date, our category label, contact points named, legitimate contacts the alert states, recorder initials, date recorded | Yes. Internal research only | `data/restricted/dfsa/` (git-ignored, never pushed) |
| Dataset items containing DFSA fact values | Entity-level queries, and synthetic messages built from DFSA facts | Yes. Internal research only | `datasets/restricted/` (git-ignored) |
| References to DFSA facts | Restricted row IDs inside evidence records, events and logs | Yes | Anywhere local |
| Indexes, embeddings, search services over DFSA data | — | **Never** | — |
| DFSA values in requests to model providers | Identifiers, recorded services, addresses, alert dates | **Never.** Identifiers are masked, and the rest is not sent (§9.4) | — |
| Relations the tools work out about a masked entity | Status; zone; which of our activity codes the recorded services cover; the alert's category in our own labels | Yes. This is all a model learns beyond placeholders (§6.9) | Requests to model providers; run logs |

### 9.3 Data flow

```text
 Person (normal browser) ──hand-records──► data/restricted/dfsa/*.csv   (the ONLY copy of DFSA values)
                                                 │ loaded into memory, RESEARCH_INTERNAL mode only
                                                 ▼
                              dfsa_facts_lookup (linear scan over a small in-memory table —
                                                 │ not an index or a search service)
                         ┌───────────────────────┼─────────────────────────────┐
                         ▼                       ▼                             ▼
            Masking gateway → model sees    Evidence record stores        UI looks up values from the ID
            placeholders only (⟦R:FIRM-1⟧)  the row ID only, and the      at display time (research mode);
            plus tool-computed relations    link https://www.dfsa.ae/     in RESTRICTED_DEMO: "DFSA fact
                                                                          (restricted) — check www.dfsa.ae"
```

### 9.4 Controls

1. **Storage:** `.gitignore` entries plus a commit guard (`scripts/check_restricted.py`, run by a git pre-commit hook and in CI). The guard blocks restricted paths, the restricted-content marker, DFSA deep links and API keys. Restricted paths are left out of any archive or release.
2. **Mode gate:**
   - In `RESEARCH_INTERNAL` mode (the default for evaluation), DFSA data loads.
   - In `RESTRICTED_DEMO` mode (screenshots, presentations), DFSA data never loads, and the DFSA agent returns "manual check required at www.dfsa.ae".
3. **No indexes, embeddings or search services** over DFSA data. Lookups are linear scans of a small table held in memory.
4. **No caching:**
   - There is no DFSA network access at all, so no HTTP caching.
   - The local development replay cache (§13.1) stores only masked requests and is switched off during evaluation.
5. **Links:** a link sanitiser rewrites any DFSA link to `https://www.dfsa.ae/`.
6. **Masking gateway:**
   - Every restricted value (firm names, reference numbers, domains, emails, phones, street-level address parts) is registered when the restricted store loads.
   - Before any request leaves the machine, each registered value is replaced with a stable placeholder for that case. Longer values are replaced first, and generic name parts and zones are kept.
   - Placeholders are restored only locally.
   - Facts that are not identifiers are not sent at all. Recorded services become activity codes through our own mapping in `knowledge/taxonomy/activities.yaml`. If a service is not understood, scope is reported as unknown. Alert dates stay local, and the report adds them at display time.
   - An invariant test serialises every outgoing request in the test suite and in evaluation runs, and fails if any registered value appears. A second test checks every recorded service, street and alert date against all outgoing requests and the event log.
7. **Local only:** the API binds to `127.0.0.1`. There is no public deployment configuration.
8. **Purge:** deleting `data/restricted/` and `datasets/restricted/` removes every DFSA value. Delete `runs/` as well: it holds no DFSA values, but it keeps row references and masked relations. The system still runs, and DFSA-dependent cases become "Could not verify".
9. **Access log:** every load of restricted data is recorded in the event log, as references only.

### 9.5 Permission and sign-off

- **Before Part 1 data entry:**
  - a team member reads the full DFSA Legal Disclaimer in a browser, through the footer of the DFSA homepage;
  - if you work within an institution, its legal or ethics contact confirms the approach.
- **Recommended in week 1:** you send the DFSA a written permission request through the contact route listed on the DFSA homepage. A draft is at `docs/dfsa-permission-request.md`.
- **Until permission is granted:** DFSA data stays internal-only, and no DFSA-derived data is ever released.

### 9.6 Residual risk

This is an engineering reading of PS.md's guidance, not legal advice. The design keeps the system useful even under the strictest reading: purge the restricted store, and DFSA cases simply become "Could not verify".

---

## 10. Baselines, ablations and the fairness contract

### 10.1 Fairness contract

**Identical across every condition:**

- model ID and decoding settings (temperature, seed, reasoning setting);
- tool implementations and the evidence store;
- rule cards and policies (equal knowledge);
- the output contract and how inputs are presented;
- runner code, retries, rate limiter and limits;
- the masking gateway;
- no access to gold labels;
- the same snapshots.

**Prompt tuning budget:** the crew and the single agent each get the **same** number of tuning iterations on the development split. Revisions are logged, the budget is capped (5 per system), and prompts are frozen before any test run.

**What differs:** only the orchestration, meaning one agent versus a crew. Each case records everything it ran with, and `tests/test_fairness.py` compares those records, so an unplanned difference fails a test. The one setting all single-agent conditions change is the tool-call allowance: one agent doing every job gets 32 calls in a turn, and a crew agent gets 8.

**Equal knowledge in practice:** the guidance on relevance, list hits, contacts and choosing a result lives in shared files that both systems load, and a test checks that the words are the same. Prompt revisions are logged in `backend/prompts/CHANGELOG.md`.

**Compute:** the primary comparison reports requests and tokens but does not force them to be equal. The compute-matched conditions do force it.

### 10.2 Conditions

| ID | System | What it tests |
|---|---|---|
| **RULES-ONLY** | No LLM: keyword activity rules, lookups, decision policy | Reference floor, and a probe of dataset difficulty (§11.2 D) |
| **SA-BASE** | One agent, all tools, all rule cards, temperature 0, default reasoning setting | **The mandatory baseline** |
| **SA-VER** | SA-BASE plus the same Verifier and one remediation cycle | The value of verification on its own |
| **SA-SC5** | Majority vote over 5 SA-BASE runs at temperature 0.7. A tie goes to the more cautious result | A control for extra compute via voting |
| **SA-MAX** | SA-BASE at the model's highest reasoning setting, with a tool-call allowance matched to the crew's median output tokens | A control for extra compute via more thinking |
| SA-LARGER *(optional)* | SA-BASE on the largest tool-capable free model | A bigger single model instead of a crew |
| **CREW-SILO** | Agents work independently with no messages; Reconciler synthesis; Verifier on | Baseline for measuring sharing |
| **CREW-SHARE** | Findings shared once; Reconciler synthesis; no challenges; Verifier on | The value of sharing |
| **CREW-FULL** | The full protocol | **The system under test** |
| **CREW-NV** | CREW-FULL with the Verifier off | The Verifier's contribution inside the crew |

**Pre-registered comparisons:**

- **Primary:** CREW-FULL versus SA-BASE.
- **Secondary (Holm-corrected):**
  - FULL versus SA-VER: does coordination add anything beyond verification?
  - FULL versus SA-SC5 and SA-MAX: is the gain just compute?
  - SHARE − SILO: the value of sharing.
  - FULL − SHARE: the value of challenges and mediation.
  - FULL − NV: the value of the Verifier in the crew.
  - SA-VER − SA-BASE: the value of the Verifier for a single agent.
  - SA-BASE − RULES-ONLY: the value of any LLM.

---

## 11. Evaluation methodology

### 11.1 Research questions and hypotheses (registered before test runs)

| ID | Question | Hypothesis and test |
|---|---|---|
| RQ1 / **H1 (primary, safety)** | Does the crew reassure falsely less often than a single agent with the same tools and knowledge? | False-reassurance rate (FRR) of FULL < FRR of SA-BASE on the message-level test set. Exact McNemar test on per-item "false reassurance" indicators |
| RQ1 / **H2 (primary, usefulness)** | Is the crew at least as useful overall? | Macro-F1 of FULL is no more than 2 points below SA-BASE (non-inferiority, paired bootstrap). Coverage is reported, so the crew cannot "win" by answering "Could not verify" more often |
| RQ2 / H3 | Which mechanisms account for any difference? | SHARE > SILO and FULL > SHARE on FRR or macro-F1; FULL > NV on FRR |
| RQ3 / H4 | Does the gain survive equal compute? | FULL beats SA-SC5 and SA-MAX on FRR. Requests and tokens are reported on a quality-against-compute frontier |
| RQ4 / H5 | Where does the gain sit? | The advantage is concentrated in copied-identifier cases (F1), cross-jurisdiction cases (F6) and scope cases (F7): an interaction test. This follows Tran & Kiela (2026), who predict multi-agent gains mainly when a single agent's use of its context is degraded |
| RQ5 / H6 *(optional)* | Does the gain shrink as models get stronger? | The crew's advantage is larger on the smaller same-family model than on the primary model, following the "capability saturation" finding of Kim et al. (2025) |

All results are reported: confirmed, null and reversed.

### 11.2 Datasets

#### A. Entity-level (real data; local only)

Each item is an entity card presented identically to every system: name, and optionally a claimed regulator, a reference or licence number, a domain, email or phone, and an activity.

| Stratum | Source | Target n | Gold logic |
|---|---|---|---|
| E1 Impersonated authorised firm with an alert-listed contact | DFSA 2026 alerts (≥10) | 15–25 | `CONFLICTS` (HC1/HC5) |
| E2 The same firms with their official contact | DFSA register facts | 10–20 | `CONSISTENT` if the official record lists that contact and the activity is in scope; otherwise U3 |
| E3 False claims of DFSA authorisation, or impersonation of the regulator | DFSA 2026 alerts (~10) | 10–15 | `CONFLICTS` (HC3/HC1) |
| E4 VARA unlicensed entities | VARA list | 38 | `CONFLICTS` (HC2) |
| E5 VARA licensed VASPs with official contact and an activity within the licence | VARA register | 30–40 | `CONSISTENT` |
| E6 VARA IPA holders offering services or claiming a licence | VARA register | 15–20 | `CONFLICTS` (HC3/HC4) |
| E7 CMA licensed firms with an activity within their category and an official contact | CMA export | 40–60 | `CONSISTENT` |
| E8 CMA Category 5 firms offering FX or derivatives trading | CMA export plus rule card | 15–20 | `CONFLICTS` (HC4) |
| E9 CMA warnings | CMA warnings | All 2026 entries | `CONFLICTS` (HC2/HC1) |
| E10 Firms licensed only by the CBUAE (outside Phase 1) | CBUAE PDF (facts used only to build test items; Phase 1 has no CBUAE tool) | 15–20 | `UNVERIFIED` (U2) |
| E11 Near-miss names and variants (hard positives and negatives) | All registers | 25–30 | Follows the underlying record |

The target is about 280–360 items, split 30% development and 70% test, stratified by stratum and label. Strata are small, so per-stratum results are case studies, and statistics come mainly from the message level.

#### B. Message-level (labelled synthetic offers; local until a release review)

**Scenario factors** (each message is tagged; balanced across labels):

| ID | Factor | ID | Factor |
|---|---|---|---|
| F1 | Copied official identifiers (name, DIFC address, reference number) | F9 | Genuine offer with complete official details |
| F2 | Look-alike domain (typo, look-alike characters, added word, top-level-domain swap) | F10 | Genuine firm using a secondary domain not on record |
| F3 | Unrelated domain (not a look-alike) | F11 | Activity that belongs to a regulator outside coverage (CBUAE or FSRA) |
| F4 | Off-platform contact (WhatsApp, Telegram) | F12 | Transliterated and variant Arabic names, in English text |
| F5 | Payment to a third party, a personal account or a crypto wallet | F13 | Several firm names in one message |
| F6 | Mixed jurisdiction signals (DIFC address with virtual assets; free-zone firm targeting the mainland) | F14 | Heavy social-engineering cues with *consistent* details, or polished text with *conflicting* details (tests that answers rest on evidence, not tone) |
| F7 | Scope violation (Category 5 with FX; IPA holder with services) | F15 | Prompt-injection attempts inside the offer text |
| F8 | Impersonation of the regulator (fake regulator letter or notice) | | |

**Generation pipeline:**

1. **Scenario specification.** Facts are taken from records, then the label and factors are set. A deterministic sampler with a fixed seed draws them, and the label is recomputed by the decision-policy engine.
2. **Writing the message text,** from three sources:
   - templates (about 30%);
   - free LLM paraphrase by a model from a *different family* than the system under test (about 50%);
   - messages written by team members (about 20%).
3. **Automatic checks:**
   - the required facts are present;
   - no unintended real identifiers appear (checked against the registers and a stop-list);
   - the label agrees with the policy engine.
4. **Human review.** Two annotators label each message without seeing the intended label. Disagreements are settled by discussion, and Cohen's κ is reported, with a target of ≥ 0.8.
   - *If only one annotator is available,* that person labels everything twice, at least two weeks apart, and we report agreement between the two passes.
   - A free model also flags items whose label it disputes, for a second look. The model never sets labels.
   - Ambiguous items are fixed or dropped, and every drop is logged.
5. **Freeze** with content hashes.

**Synthetic identifiers:**

- **Domains:**
  - domains we invent use reserved names (`.example`, `.test`; RFC 2606/6761);
  - domains copied verbatim from official alerts are public facts, used to test alert matching.
- **Phone numbers** come from ranges reserved for fiction where they exist, such as UK Ofcom 07700 900000–900999. They are never real personal numbers, and validity is never a signal.
- **IBANs and wallets** are synthetic values in a valid format, flagged in metadata.
- **Personal names** are synthetic.
- **Labelling:** every item carries `synthetic: true`, a generator version and a scenario ID.
- **Storage:** items built from DFSA facts live in `datasets/restricted/`. All dataset files stay local until a release review, because VARA's terms bar redistribution.

**Size:** 480 messages, 160 per label. 144 (30%) are for development and 336 (70%) are held for testing.

**Language:** English text only in Phase 1. Arabic-language messages are left for later unless a volunteer annotator who reads Arabic joins.

#### C. Component level (diagnoses whether errors come from tools or reasoning)

- Name matcher: precision and recall on real name variants.
- Look-alike detector: real alert-listed fake domains against official domains (DFSA pairs kept restricted), plus synthetic pairs.
- Contact extraction: accuracy against gold text spans in the synthetic messages.

#### D. Leakage and difficulty controls

- **Sealed test split:** it is never used during prompt tuning.
- **Lint check:** prompts and rule cards are scanned for test-set entity names.
- **Gold fields are stripped** before a case is created (a tested invariant).
- **The development split is used for threshold calibration only.**
- **Entity-level circularity:** these items come from the same snapshots the tools search. This is intended: the evaluation measures retrieval and reasoning, not whether the data is true. The hard positives and negatives (E11) and the component metrics show where errors come from.
- **Difficulty probe:** RULES-ONLY runs on the development split first. If it scores very high there, the synthetic messages are too formulaic, and they are made harder before the test set is frozen. The probe already fired on the hand-written smoke set: RULES-ONLY matched 21 of 25 with no model, so that set tests the plumbing and shows nothing about what a model adds. Test messages must avoid exact firm names and tidy phrasing, and must hide facts in the wording, or the comparison will not separate the systems.

### 11.3 Metrics

| Metric | Definition | Role |
|---|---|---|
| **False-reassurance rate (FRR)** | P(prediction = `CONSISTENT` \| gold ≠ `CONSISTENT`) | **Primary safety metric** |
| Unsupported-conflict rate | P(prediction = `CONFLICTS` \| gold ≠ `CONFLICTS`); reported separately for gold `CONSISTENT` (risk of wrongly implicating a genuine firm) | Safety |
| Macro-F1 (3 classes), per-class precision and recall | Standard | Primary usefulness metric |
| Coverage and decisive accuracy | P(prediction ≠ `UNVERIFIED`); accuracy where the prediction ≠ `UNVERIFIED` | Detects winning by abstaining |
| Cost-weighted error | Pre-registered cost matrix (below), with a sensitivity analysis | Summary |
| Evidence validity | Share of cited IDs that exist and were created in the case | Evidence |
| Claim support | Share of claims fully supported by their evidence (human-rated sample) | Evidence |
| Evidence completeness | Share of the key facts behind the gold label that are cited | Evidence |
| Jurisdiction accuracy | Per-item Jaccard similarity of the relevant-regulator set; micro precision and recall over (item, regulator) pairs; recall of coverage gaps | Reasoning |
| Scope-rule accuracy | Accuracy on F7 and E6/E8 items | Reasoning |
| Policy compliance | Rate of banned terms and advice; must be 0 after the gates | Ethics |
| Stability | Per-item agreement across temperature-0.7 runs (Fleiss' κ); flip rate | Reliability |
| Compute and latency | Requests, input and output tokens, p50/p95 latency, LLM and tool calls per case | Efficiency |
| **Coordination diagnostics** (crew) | Conflicts per case; share of challenges that lead to a revision; challenge efficacy (change in correctness of challenged findings); harmful flips; conformity flags; veto rate; **veto precision** (share of vetoed proposals that were wrong); **veto recall** (share of wrong pre-veto `CONSISTENT` proposals that were vetoed); rescue rate | Mechanism evidence |
| Failure taxonomy | Crew failures coded with MAST (Cemri et al., 2025) on a sample of 50 or more | Qualitative |

**Cost matrix** (rows: gold result; columns: predicted result; pre-registered):

| gold \ predicted | Consistent | Conflicts | Could not verify |
|---|---|---|---|
| **Consistent** | 0 | 3 | 1 |
| **Conflicts** | 10 | 0 | 2 |
| **Could not verify** | 8 | 3 | 0 |

**Explanation quality** (secondary):

- **Primary measure:** blinded human ratings on a stratified sample. The rubric covers faithfulness to the evidence, completeness, neutrality and compliance, and clarity for a resident.
- **Optional:** a free LLM judge from a different model family, used only if its agreement with humans reaches κ ≥ 0.6 on a calibration set.

### 11.4 Statistical analysis

- **Paired design:** every system answers every item.
- **Decoding:**
  - **Primary runs:** one run per condition at temperature 0, with a fixed seed where supported. These are nearly deterministic, though GPU batching on the provider's side can still cause small variation.
  - **Stability runs:** k = 3 runs at temperature 0.7 for SA-BASE, SA-VER and CREW-FULL on the message-level test set. SA-SC5 uses 5 such runs of SA-BASE.
- **Tests:**
  - exact McNemar tests for differences in correctness and in false reassurance;
  - paired bootstrap 95% confidence intervals (10,000 resamples of items) for differences in macro-F1 and FRR;
  - Holm–Bonferroni correction over the secondary comparisons;
  - effect sizes reported throughout.
- **Power (rough):**
  - With about 224 non-`CONSISTENT` test messages and a baseline FRR near 10%, the design can detect FRR reductions of roughly **6–7 percentage points** at α = 0.05, with power of about 0.7–0.8. The exact power depends on how often both systems fail on the same items.
  - A simulation-based power analysis is redone after the pilot.
  - If the minimum detectable effect is too large, we grow the *synthetic* test set, which is free, not the real one.
- **Subgroup analyses by factor** are exploratory and labelled as such, apart from the pre-registered H5.

### 11.5 Request budget and run time (free tier)

Money is not the constraint; the rate limit is. The budget is counted in model requests. The estimates below are replaced by measured values after the Part 6 pilot.

| Condition | Model requests per case (estimate) |
|---|---|
| RULES-ONLY | 0 |
| SA-BASE | 6–10 |
| SA-VER | 8–13 |
| SA-MAX | 6–12 (longer outputs) |
| CREW-SILO | 10–14 |
| CREW-SHARE | 12–16 |
| CREW-FULL | 15–25 |
| CREW-NV | 13–22 |
| SA-LARGER (optional; a different model, so it has its own rate limit) | 6–10 |

**Run plan:**

- **Primary:** every condition once at temperature 0 on both test sets. That is about 92 requests per item.
- **Stability and SA-SC5:** on the message-level test set only.
  - SA-BASE ×5;
  - SA-VER ×3;
  - CREW-FULL ×3.

  That adds about 130 requests per item.

**Totals:**

| Part of the run | Requests |
|---|---|
| Message-level test set: 336 × ~222 | ≈ 74.6K |
| Entity-level test set: ~225 × ~92 | ≈ 20.7K |
| **Total** | **≈ 95K** |

- **Run time (first estimate):** at 35 requests per minute this would have been about 45 hours.
- **Overheads:** development and the pilot add 20–30%. The pilot (20 items × the full run plan) is about 4.4K requests.

**Measured on 5 Nov 2026:**

- The real limit is about 8 requests a minute, so the harness paces at 7.5, or about 10,800 a day.
- CREW-FULL used 17.6 requests a case over 25 fictional cases, and SA-BASE about 4.5. Both are below the estimates above. The other conditions are measured by the pilot.
- With those figures, a full run is about 100 requests per entity item and about 178 per message item, or **about 82K requests: about 7.6 days of continuous running, or about 18 nights of 10 hours.** The harness stops and resumes at any point, so this can be split as needed.
- Replaced by final figures after the pilot.
- **The optional capability arm** uses a smaller model with its own per-model limit, so it can run in parallel: about 31K requests, or about 15 hours.

**If the free limits turn out lower** than expected, the fallback order is fixed in advance:

1. drop SA-VER stability runs to k = 2;
2. run stability only on a stratified half of the message-level test set;
3. drop the capability arm.

The primary comparison is never cut.

### 11.6 Threats to validity

| Threat | Mitigation |
|---|---|
| Synthetic messages are unrealistic or carry the generator's bias | Mixed generation (templates, a different model family, human-written); factor stratification; the RULES-ONLY difficulty probe; real entity-level evaluation reported separately |
| Prompt over-tuning favours the crew | Equal, logged tuning budget; frozen prompts; sealed test split; pre-registration |
| Compute confound | SA-SC5, SA-MAX, optional SA-LARGER; frontiers of quality against requests and tokens |
| **Circularity:** gold labels come from the same decision policy the Verifier enforces | The policy *defines* the task, and every system is given it (equal knowledge). SA-VER gets the same enforcement, so FULL versus SA-VER isolates coordination. Human annotators check labels independently |
| Errors in gold labels | Two annotators (or the single-annotator fallback), discussion of disagreements, a label audit |
| Rule-base errors | Primary-source citations; verification status per rule; a conservative jurisdiction matrix |
| Data leakage | §11.2 D |
| Small real strata | Confidence intervals; case-study framing; statistical claims mainly at message level |
| LLM non-determinism | Temperature 0 primary runs; stability runs; paired tests |
| The hosted model changes during an experiment | Model IDs and dates recorded; all conditions run in one window; a full re-run if the model changes |
| Results tied to one model family | Optional capability arm and a different-family generator; stated as a limitation |
| Phase 1 coverage and snapshot dates | Coverage is disclosed in every result; freeze dates stated; Part 8 extension |
| Evaluator bias in human ratings | Ratings blinded to the system; outputs normalised to one format |

---

## 12. Ethics and legal safeguards built into outputs

### 12.1 Output contract (every result contains)

1. The result in its exact wording.
2. An explanation of 120 words or fewer, in plain, neutral English.
3. Claims with evidence chips: source, snapshot or record date, and a link according to policy.
4. Relevant regulators with reasons; what was checked and what wasn't, and why.
5. "As of" dates for every source.
6. How to verify directly: the regulator's page (for the DFSA, the homepage only).
7. The standard disclaimer.
8. A SYNTHETIC badge, the case ID and the system condition.

### 12.2 Language and advice policy

- **Where the rules live:** `policies/language_policy.yaml` holds banned verdict and advice terms, allowed proper nouns, the required disclaimer and the result strings.
- **How they are enforced:** the deterministic linter (`governance/language`) runs on every result, and Verifier gate G5 enforces it.
- **Banned:** the terms in §4.6 are banned as conclusions. Facts must be attributed and dated.
- **No advice features:** no feature ranks firms or talks about returns or suitability.

### 12.3 Standard disclaimer

> "This result compares the details in a synthetic offer with official register and alert records as of the dates shown. It is not a finding about any firm or person, and it is not legal or investment advice. UAE authorities advise checking directly with the relevant regulator before sending money."

### 12.4 Synthetic inputs only

- The API rejects input without `synthetic: true` and either a corpus ID or an explicit statement that the text is synthetic.
- A heuristic screen warns when text looks like real personal data: an Emirates ID pattern, a card number that passes the Luhn check, an email at a personal-mail domain, or a phone number outside the reserved fiction ranges.
- The intake screen says "Synthetic offers only". There is no "paste a message you received" workflow.

### 12.5 Untrusted input and prompt injection

- Offer text is always wrapped and labelled as data.
- All tools are read-only and have no side effects.
- Text injected into an offer cannot create evidence, and the deterministic gates block claims without evidence.
- Factor F15 measures how robust the system is to injection attempts.

### 12.6 Privacy, data handling and retention

- **No personal data by design:** inputs are synthetic and identifiers come from reserved ranges.
- **Sent to NVIDIA's free endpoints,** which may record inputs and outputs: only synthetic text, public CMA and VARA facts, placeholders, and relations the tools work out about masked entities (§9.2). DFSA values never leave the machine.
- **Run logs** keep masked synthetic text, references and those relations.
- **When the paper is finished,** `runs/` is archived without any restricted data.

### 12.7 Release controls and the public repository

- **Committed:**
  - code, documentation and policies;
  - rule cards (our wording);
  - empty data templates;
  - **fictional** test fixtures using reserved `.example` domains.
- **Never committed** (git-ignored, and blocked by the commit guard and CI):
  - `PS.md`, because it quotes DFSA alerts;
  - `data/inbox/`, `data/handrecords/*.csv`, `data/snapshots/`, `data/restricted/`;
  - `datasets/` (except READMEs);
  - `runs/` and `.env`;
  - any DFSA deep link;
  - any API key.
- **Anything pushed to a public repository counts as published permanently,** because forks and caches outlive deletions. The guard therefore runs *before* each commit, not after.
- **Local only:** the API binds to localhost and there is no public deployment.
- **`RESTRICTED_DEMO` mode** is used for all screenshots and talks.
- **Release checklist:**
  - no restricted data;
  - no VARA material copied verbatim;
  - entity-level data released only as rehydration recipes;
  - DFSA-derived data released only with written permission.

### 12.8 Ethics checklist before every evaluation run

- Snapshots are frozen and the manifests are complete.
- The test split is sealed and the prompts are frozen.
- The mode is correct.
- The request budget is set.
- There is no real personal data.
- The linter self-test passes.
- The masking invariant passes.
- The restricted-data guard passes.

---

## 13. Tech stack

All components are free and open source. Versions are pinned in lock files.

| Layer | Choice | Why | Alternatives considered |
|---|---|---|---|
| Language (backend) | **Python 3.11+**, managed with `uv` | Installed on this machine; best ecosystem for data, evaluation and statistics | TypeScript end to end: weaker for research analysis |
| LLM access | **Provider-agnostic `LLMClient`** over the OpenAI-compatible Chat Completions API, called directly with `httpx` so that the whole request path is in our code. **NVIDIA API catalog** (free trial tier) is the default provider | Free; many open-weight models behind one API; open weights help others repeat the work | Paid APIs (ruled out by the $0 budget). Local inference (a 2 GB GPU is too small). Other free tiers (Gemini, Groq, OpenRouter free models, GitHub Models) are emergency backups only, never mixed inside one experiment |
| Orchestration | **LangGraph 1.x** for *control flow only*: parallel fan-out, conditional edges, SQLite checkpointing, streaming. Our own typed protocol and blackboard sit on top, and no LangChain model wrappers are used | Explicit and inspectable graph; resume and replay; stable since v1.0 (Oct 2025) | CrewAI and AutoGen/AG2 hide the message protocol or let the LLM pick who speaks, which makes ablations harder. Hosted agent platforms are paid and store session data off-machine. A fully hand-written scheduler stays possible, because the protocol does not depend on LangGraph |
| Schemas | **Pydantic v2** | One source of truth for structured outputs, the API, OpenAPI and TypeScript types | — |
| API | **FastAPI**, Uvicorn, `sse-starlette` | Typed and fast; Server-Sent Events fit one-way event streams | WebSockets: not needed |
| Storage | **JSONL** snapshots with JSON manifests; **SQLite** (WAL) for cases, events and runs; DuckDB for analysis | Transparent, easy to diff, no extra services; DuckDB reads JSONL directly | Parquet (later, only if needed); Postgres (only if multiple users need it) |
| Data and tool libraries | `openpyxl`, `pdfplumber` (Part 8), `rapidfuzz`, `tldextract` (bundled Public Suffix List, updates turned off), `phonenumbers`, `schwifty` (IBAN), PyYAML | Mature, deterministic, offline | — |
| Evaluation | `numpy`, `scipy`, `statsmodels`, `scikit-learn`, `matplotlib`/`plotly`, Jupyter | Standard and citable | — |
| Quality | `ruff`, `mypy`, `pytest` with a network block, Hypothesis for property tests; the commit guard as a git pre-commit hook | — | — |
| CI | **GitHub Actions**, free for public repositories: commit guard, lint, type check, tests | Every push to `main` is checked | — |
| Frontend | **Next.js 16** (App Router), **React 19**, **TypeScript** (strict) | Current major version; server components for the Lab | — |
| Styling | **Tailwind CSS v4** with CSS-variable design tokens; shadcn/ui (Radix) restyled as glass | Speed plus accessible primitives | — |
| Motion | **Motion for React** (the library formerly published as Framer Motion) | Springs, layout animations, shared-element transitions | GSAP |
| Graph | **React Flow (`@xyflow/react` 12)** with custom nodes and animated edges | Pan, zoom and layout; custom rendering | Hand-written SVG and D3: more work |
| Charts | **visx** (built on D3) | Full design control for the glass theme | Recharts: faster to build, less control |
| Data on the client | TanStack Query, TanStack Virtual, **Zod**-validated SSE events, `openapi-typescript` | Type safety from Pydantic to the UI | — |
| Testing (frontend) | Vitest, Testing Library, Playwright | — | — |
| Fonts | Self-hosted with `next/font`: a wide geometric display face used sparingly, Geist Sans and Geist Mono, IBM Plex Sans Arabic | Free; no third-party calls at runtime; Arabic support for entity names | — |

### 13.1 Running on the free tier

- **One endpoint and one key:**
  - The endpoint is `https://integrate.api.nvidia.com/v1`.
  - The key `NVIDIA_API_KEY` lives in the local `.env`. CI never needs it, and the commit guard blocks keys in the `nvapi-…` format.
- **Allowed hosts:** a network allowlist in `policies/sources.yaml` lets the LLM client reach only the configured provider host. Regulator domains are always blocked.
- **Rate limiter:**
  - an async pacing limiter at 7.5 requests per minute (measured, §11.5), shared across all agents in a run;
  - exponential backoff with jitter on HTTP 429 and 5xx errors;
  - a cap on concurrent requests;
  - every request is logged with its latency.
- **Resumable runs:** the harness writes each finished case to disk and skips it on restart.
- **Development replay cache:**
  - identical development requests are answered from a local SQLite cache to save free quota while debugging;
  - only masked requests are stored;
  - the cache is switched off for evaluation runs.
- **Capability probe and ADR:** the model choice is fixed before any test run (§5.3).
- **Failure handling:** a refusal, an invalid output after one repair, or a timeout becomes an `agent.failed` event, and the case resolves as reason U7. There is no silent switch to another model.

---

## 14. File and folder structure

```text
MultiAgent-Orchestration/              (local folder; GitHub: KartikJoshi23/TESSERA)
├── PS.md                              problem statement — LOCAL ONLY (git-ignored; quotes DFSA alerts)
├── implementation-plan.md             this document
├── README.md                          public-safe overview, setup, data rules
├── .env.example                       placeholders only: NVIDIA_API_KEY, TESSERA_MODE
├── .gitignore / .gitattributes        keeps real data and secrets out; normalises line endings
├── .githooks/pre-commit               runs the commit guard before every commit
├── .github/workflows/ci.yml           guard, lint, tests on every push (free for public repos)
├── scripts/check_restricted.py        commit guard: restricted paths, DFSA deep links, API keys
├── docs/
│   ├── adr/                           architecture decision records (0001–0005)
│   ├── data-governance.md             per-source procedures, DFSA handling, purge, release checklist
│   ├── annotation-guidelines.md
│   ├── dfsa-permission-request.md     draft letter (you send it)
│   └── preregistration.md             (Part 6) hypotheses and analysis plan, frozen before test runs
├── policies/
│   ├── sources.yaml                   per-source access, storage, linking, display; network rules
│   ├── decision_policy.yaml           outcomes, HC, K and U rules, P1–P7, thresholds
│   ├── models.yaml                    provider, rate limit, decoding, limits, model roles
│   └── language_policy.yaml           banned terms, allowed proper nouns, disclaimer, result strings
├── knowledge/
│   ├── rule_cards/                    jurisdiction, cma, dfsa, vara, clone (cbuae, fsra in Part 8)
│   └── taxonomy/activities.yaml
├── data/                              everything here is local except the READMEs and templates
│   ├── inbox/                         manual downloads land here (git-ignored)
│   ├── handrecords/templates/         empty CSV templates (committed)
│   ├── restricted/                    DFSA facts only; research mode only (git-ignored)
│   ├── snapshots/                     immutable JSONL snapshots and manifests (git-ignored)
│   └── README.md
├── datasets/                          local only (git-ignored apart from the README)
├── backend/
│   ├── pyproject.toml, uv.lock
│   ├── prompts/v1/                    system prompts for every role (versioned)
│   ├── src/tessera/
│   │   ├── config/                    settings, modes, repository-root discovery
│   │   ├── governance/                policies, network guard, links, modes, synthetic gate,
│   │   │                              language linter, restricted-value masking
│   │   ├── protocol/                  evidence, contacts, claims, findings, messages, conflicts,
│   │   │                              results, case
│   │   ├── normalize/                 names (incl. Arabic), domains, phones, emails
│   │   ├── data/                      schemas, adapters (CMA Excel, CSV), snapshots, registry, ingest
│   │   ├── tools/                     extraction, lookups, matching, domain/phone/payment, rule cards
│   │   ├── blackboard/                event store, protocol rules, per-agent views
│   │   ├── llm/                       transport, rate limit, retries, replay cache, leak checks,
│   │   │                              prompts, agent runner, model probe
│   │   ├── agents/                    tool belt, the seven agents, smoke command
│   │   ├── devdata.py                 installs the fictional world for tests and smoke runs
│   │   ├── orchestration/             decision engine, conflict detector, Verifier gates,
│   │   │                              crew graph, ablation switches, case runner
│   │   ├── reporting/                 final result and the report (output contract)
│   │   ├── api/                       FastAPI app, SSE stream, case service
│   │   ├── baseline/                  RULES-ONLY and the single-agent conditions
│   │   ├── evaluation/                datasets, labels, review, harness, metrics, statistics
│   │   ├── experiment.py              opens and runs any condition the same way
│   └── tests/                         unit and governance tests; fictional fixtures only
├── eval/
│   ├── smoke/                         fictional world and 25-case smoke set (committed)
│   └── plan.yaml                      the registered run plan (Part 6)
├── frontend/                          (Part 5) Next.js app
└── runs/                              experiment outputs and event logs (git-ignored)
```

---

## 15. Frontend design

### 15.1 Concept: a glass-mosaic control room

Each agent is a tile of smoked glass lit from inside. Messages travel as light between the tiles, and the final result assembles from evidence tiles: tesserae. The tone is a calm, deep-blue research instrument, not a security-alarm dashboard. The interface says plainly that it is an **internal research prototype**:

- a persistent header badge reading "INTERNAL RESEARCH PROTOTYPE · synthetic inputs only";
- a mode badge reading "Research-internal" or "Restricted demo".

### 15.2 Design tokens (starting point; refined in Part 5)

- **Background:** near-black lapis (`#05070D` → `#0A0F1C`), with a slowly drifting aurora mesh (teal, cyan, violet) and a faint mosaic grid. The animation pauses when the user prefers reduced motion.
- **Glass:**
  - layered translucent fills with a 20 px backdrop blur;
  - a 1 px border at 8–10% white and a highlight on the inner top edge;
  - a 3% noise texture to prevent banding;
  - soft deep shadows;
  - text contrast of at least 4.5:1, checked against the actual backdrop.
- **Agent colours:**
  - Jurisdiction: gold;
  - CMA: teal; DFSA: azure; VARA: violet;
  - Clone-check: rose;
  - Reconciler: pearl, at the centre;
  - Verifier: emerald.
- **Message colours and particle shapes:**

  | Message | Colour | Shape |
  |---|---|---|
  | `INFORM` | Cyan | Dot |
  | `REQUEST` | Violet | Diamond |
  | `CHALLENGE` | Amber | Triangle |
  | `REBUT` | Orange | Chevron |
  | `REVISE` | Teal | Square |
  | `CONCEDE` | Grey | Hollow dot |
  | `RESOLVE` | Pearl | Ring |
  | `VETO` | Red (the only red in the product) | Cross |
  | `APPROVE` | Emerald | Check |

- **Result styling:**
  - `CONSISTENT`: teal-green with a check-shield icon.
  - `CONFLICTS`: deep amber with a diverging-paths icon. No skulls or alarm red, so the design does not imply a verdict on the firm.
  - `UNVERIFIED`: slate-indigo with a dashed-circle icon.
  - Every state is shown by colour, icon and label together, never by colour alone.
- **Type:**
  - wide display face for large headings only;
  - Geist Sans for the interface;
  - Geist Mono for data, IDs and hashes;
  - IBM Plex Sans Arabic for Arabic entity names.

### 15.3 Views

| View | Purpose | Highlights |
|---|---|---|
| **Intake** | Choose a corpus offer or write a synthetic one; pick the system (crew, baseline, both), model and ablation switches | SYNTHETIC attestation; warning on real-looking personal data; extracted contact points shown live as chips |
| **Orchestration Theater** (signature view) | Watch the crew work, live or replayed | §15.4 |
| **Result Dossier** | The final result | A large result tile; claim cards with evidence chips; a regulator × check coverage matrix; the conflict-resolution log; the Verifier report; the disclaimer; case-file export |
| **Crew-vs-Baseline Arena** | Both systems on the same offer | Split screen: the single agent's linear tool timeline next to a compact theater; the two results compared; requests, tokens and latency; differences between their claims |
| **Evaluation Lab** | The research results | **Separate tabs for Entity-level (real) and Message-level (synthetic), never pooled**; macro-F1 and FRR with confidence-interval whiskers; quality-versus-compute frontier; ablation waterfall (SILO → SHARE → FULL, then ± Verifier); 3×3 confusion matrices; heatmap of factors by condition; coordination diagnostics (veto precision and recall, challenge efficacy, harmful flips); stability |
| **Data & Governance** | Trust and provenance | Source cards with policy badges ("manual only", "homepage links only", "restricted"); snapshot dates, counts and manifests; the DFSA notice; mode switch with explanation; masking statistics (values masked per run) |

### 15.4 Orchestration Theater

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│ CASE SYN-0142 · SYNTHETIC · Crew (full) · nemotron-3.5-super · T=0 23 req · 41K tok│
├────────────────────────────────────────────────────────┬─────────────────────────┤
│                     ◇ Jurisdiction                     │ BLACKBOARD              │
│        ◇ CMA           ◇ DFSA           ◇ VARA         │ ▣ F-J2 VARA excluded    │
│            ╲             │            ╱                │   ↳ CHALLENGE from VARA │
│             ╲      ⬡ Reconciler      ╱                 │   ↳ REVISE → v2         │
│                          │                             │ ▣ F-D3 alert hit (E2)   │
│                   ◇ Clone-check                        │ ▣ F-C1 look-alike (E7)  │
│                          │                             │ ⚠ C5 · C3 open          │
│              ◎ Verifier gate ─────► ▦ Result tile      │                         │
├────────────────────────────────────────────────────────┴─────────────────────────┤
│ R0 ▮  R1 ▮▮▮  R2 ▮▮ ⚠  R3 ▮  Synth ▮  Verify ✕  Remediate ▮  Verify ✓  Report     │
│ ⏮  ◀  ▶  ⏭   0.5× 1× 2× 4×   jump to next ⚠ conflict / ✕ veto                     │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- **Layout:**
  - the Reconciler sits at the centre, Jurisdiction at the top, the regulator agents on an arc (the arc grows to five in Part 8), and Clone-check below;
  - the Verifier is a *gate* on the only path to the result tile;
  - tools orbit their agent as small satellites, and each tool call shows a beam carrying a source badge such as "CMA snapshot 2026-11-05".
- **Agent states:**

  | State | Animation |
  |---|---|
  | Idle | Dim |
  | Thinking | Slow breathing glow, with any reasoning summary on hover |
  | Calling a tool | The satellite pulses |
  | Waiting for the rate limiter | Dashed ring |
  | Challenged | Amber outline |
  | Revised | Version badge goes up |
  | Vetoed | Red crack |

- **Messages:** particles travel along curved edges with spring easing; their speed scales with the edge length. Clicking a particle opens the structured message, its rationale and evidence chips.
- **Veto moment:** the gate flashes a red shield, the proposal tile cracks and slides back to the Reconciler, and a red particle carries the veto reasons.
- **Approval moment:** evidence tiles fly into the Result Dossier and assemble as a mosaic, using shared-element layout animation.
- **Modes:**
  - *Live* streams events over SSE.
  - *Replay* re-runs the stored event log with timing scaled to the chosen speed.
  - *Presenter* auto-focuses the camera on the active agent.

### 15.5 Frontend architecture and quality

- **Routes:** `/` (console), `/intake`, `/cases/[id]` (theater, blackboard and trace tabs), `/cases/[id]/result`, `/arena?a=&b=`, `/lab`, `/governance`.
- **Data flow:** SSE events are validated with Zod, then pass through a **pure event reducer** that derives the agent states, active edges, findings by ID and conflict threads. The components render from that state. The same reducer drives live and replay, and it is unit-tested against recorded traces.
- **Accessibility:**
  - keyboard control of the timeline;
  - visible focus rings;
  - an `aria-live` region that announces key events (for example "Verifier vetoed the proposal: claim 3 wording");
  - a reduced-motion mode with crossfades only;
  - colour-blind-safe encodings.
- **Performance:**
  - a cap on concurrent particles;
  - the blackboard list is virtualised;
  - animations run on `requestAnimationFrame` and pause when the tab is hidden.
- **The design is checked** with Playwright screenshots at desktop and laptop sizes. Phone layout is a stretch goal for an internal tool.

---

## 16. Phased build roadmap

Each part ends with a short report covering what was built, tests run, open issues and the next part. Then work **stops until you say "continue"**. Each part is pushed to `main` once its checks pass. Sizes are relative: S, M, L.

| Part | Deliverables | Acceptance criteria | Human tasks in parallel | Size |
|---|---|---|---|---|
| **1. Foundations: governance, data layer, tools** ✅ | Repository scaffold; settings and modes; `policies/*.yaml` and their guards (network guard, link sanitiser, mode gate, synthetic-input gate, language linter, restricted-value masking); commit guard, pre-commit hook and CI; manual-ingest command with manifests and snapshots; hand-record templates and validators; all deterministic tools; seed rule cards with citations and verification status; docs (data governance, DFSA permission draft, annotation guidelines v0, ADRs) | All tools unit-tested on fictional fixtures; governance tests pass (regulator domains blocked; DFSA links cleaned; zero DFSA values in demo mode; masking invariant; guard blocks restricted paths, keys and DFSA deep links) | **You:** read the DFSA disclaimer; CMA "Export To Excel"; VARA transcription; DFSA hand-recording (2026 alerts and register facts for evaluation firms); CMA warnings hand-record; optionally send the DFSA letter | L |
| **2. Protocol, blackboard, runner, the seven agents** ✅ | Pydantic schemas (findings, messages, claim catalogue); event-sourced blackboard (SQLite); per-agent views; `LLMClient` (OpenAI-compatible, rate limiter, retries, replay cache); masking wired into every request; **model probe** and ADR; `AgentRunner` (tool loop, JSON validation and repair, usage, failures); prompt v1 for all roles; a 25-case hand-written synthetic smoke set | Each agent passes fixture tests with recorded responses; live smoke runs within a request cap; invariants: evidence IDs must exist, gold fields absent, no restricted value in any outgoing request | **You:** create one NVIDIA API key and put it in `.env` (I'll ask at the start of Part 2); verify rule cards against primary sources | L |
| **3. Crew orchestration, reconciliation, Verifier, streaming API** ✅ | LangGraph crew graph; round scheduler and mailboxes; conflict detector C1–C7; Reconciler protocol; Verifier gates G1–G8 and veto loop; decision-policy engine; report renderer and linter; FastAPI and SSE; command-line case runner; ablation switches | The worked example (§6.10) and 5 more scripted cases give the expected traces; property tests: cases always finish, a veto never upgrades a result, protocol rules are enforced | Annotation of entity-level gold labels begins | L |
| **4. Baselines** ✅ | RULES-ONLY, SA-BASE, SA-VER, SA-SC5, SA-MAX (optional SA-LARGER), on the shared runner; fairness-contract checks; comparable logging | Config-diff test shows that only orchestration differs; all conditions run on the smoke set | Human-written synthetic messages | M |
| **5. Frontend** ✅ | Design system; Intake; Orchestration Theater (live and replay); Result Dossier; Arena; Evaluation Lab (using fixtures until Part 6); Data & Governance | Playwright end-to-end tests; reducer replay tests; accessibility checks; demo mode verified clean of DFSA values | Review of the visual design | L |
| **6. Datasets and evaluation harness, plus pilot** | Entity-level gold builder; synthetic generator, validators and review workflow; splits; rate-limited, resumable harness; metrics; statistics; RULES-ONLY difficulty probe; **pilot** (20 items × the full run plan, about 4.4K requests); measured requests and timing; **pre-registration frozen** | Annotation κ ≥ 0.8 (or the single-annotator fallback); pilot runs end to end | Annotation and adjudication; final freeze of snapshots | L |
| **7. Experiments, analysis, paper artefacts** | Full runs (about 82K requests, about a week of continuous running in resumable chunks, §11.5); analysis notebooks; figures and tables; MAST failure analysis; draft write-up skeleton; release checklist | All pre-registered analyses reported, including null results | Review of results | M |
| **8. Extension: CBUAE and ADGM FSRA** | Full reading of the CBUAE and ADGM terms; ingest of the CBUAE PDF (© notice kept); FSRA facts and its 11 alerts from 2026; two new regulator agents; extended rule cards; re-run on a subset; report on how much the added coverage changes results; optional I-SCAN API | Coverage-gap results (U2) shrink as expected; no regressions | Hand-recording for the FSRA | M |

---

## 17. Research-paper potential

### 17.1 Working titles

- *Do Agent Crews Reduce False Reassurance? A Controlled Study of Multi-Regulator Licence Verification in the UAE*
- *Coordination or Compute? Evidence-Linked Verification of Investment Offers Across Fragmented Financial Registers*

### 17.2 Contributions

1. **A task and benchmark design:** three-way, evidence-linked results that disclose their coverage, evaluated on real entities and labelled synthetic messages, reported separately.
2. **An inspectable coordination protocol:** typed message types, typed claims, evidence that only tools can create, bounded challenge rounds and a Verifier that can only downgrade, plus telemetry that measures each mechanism.
3. **A controlled comparison:** single-agent baselines with equal knowledge, baselines with matched compute, and ablations of each mechanism.
4. **Safety-focused metrics:** false reassurance, unsupported conflicts, evidence faithfulness, harmful flips, and veto precision and recall.
5. **A reusable governance pattern for restricted data:** source terms written as policy and enforced in code, plus the masking gateway that keeps restricted values away from third-party model APIs.
6. **Zero-cost, open-weight replication:** every experiment uses free, open-weight models, so anyone can repeat it without a budget.

### 17.3 Every outcome is publishable

| Outcome | Interpretation | Why it is publishable |
|---|---|---|
| The crew has lower FRR, and matched-compute baselines don't close the gap | Coordination helps in adversarial verification that spans several jurisdictions | A positive result backed by mechanism-level evidence: which conflicts and vetoes mattered |
| Crew ≈ SA-VER, and both beat SA-BASE | The gain comes from verification, not from the crew | Actionable advice (build one agent plus a gate), and consistent with work from 2025–26 |
| Crew ≈ every single-agent condition | Capability saturation on this task | A clean null result with equal knowledge, plus a benchmark and protocol |
| The crew helps only the smaller model | Coordination substitutes for capability | An interaction effect that connects to Kim et al. (2025) |
| The crew is worse | Coordination overhead and errors that spread between agents | Documented through MAST failure coding |

### 17.4 Related work and venues

**Positioning:**

- **Multi-agent failure analysis:** MAST (Cemri et al., NeurIPS 2025).
- **Comparisons at equal compute:** Tran & Kiela (2026); "Do More Agents Help?" (2026); OneFlow (2026).
- **Debate versus voting:** Choi et al., NeurIPS 2025.
- **Scaling laws for agent systems:** Kim et al. (2025). They find that tool-heavy tasks suffer from coordination overhead under fixed budgets, which is exactly the risk this task carries.
- **A production multi-agent system:** Anthropic Engineering (2025). There, token usage explained 80% of performance variance, which is why compute matching is mandatory here.
- **Other areas:** fact verification with evidence retrieval, selective prediction and abstention, entity resolution for KYC, and typosquatting detection.

**Venues:**

- ACM ICAIF (AI in Finance);
- the FinNLP workshop;
- AAMAS;
- ACL or EMNLP (industry or Findings tracks);
- the NeurIPS Datasets & Benchmarks track, only if the data can legally be released;
- journals on financial crime and RegTech.

**Planned figures and tables:**

- Figure 1: architecture.
- Figure 2: a protocol sequence diagram.
- Figure 3: FRR against requests and tokens.
- Figure 4: the ablation waterfall.
- Figure 5: a heatmap of scenario factors.
- Table 1: datasets.
- Table 2: main results with confidence intervals.
- Table 3: coordination diagnostics.

### 17.5 Releasing artefacts within the legal limits

- **Released:**
  - code, after review;
  - protocol schemas;
  - rule cards (our own summaries with citations);
  - synthetic messages **not** built from DFSA or VARA facts.
- **Released as rehydration recipes, not copied data:** entity-level items, as record identifiers plus scripts that rebuild the data from the user's own manual downloads.
- **Not released without the DFSA's written permission:** anything derived from DFSA data.

---

## 18. Risks and resolved decisions

### 18.1 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The DFSA disclaimer is read more strictly than PS.md reads it | M | H | Minimal facts; restricted store; masking; permission request; purge path; the system still works without DFSA data |
| **Free-tier limits, or which models are free, change** | M | H | Request budget with a fixed fallback order; resumable runs; one key with a formal limit-increase request; backup free providers for development only |
| **Free endpoints log inputs** | M | H | Masking gateway; synthetic inputs only; no personal data |
| Open models call tools less reliably | M | M | Model probe; argument validation and one repair; failures counted as U7, never hidden |
| The hosted model changes mid-experiment | L | H | IDs and dates recorded; one run window; a full re-run if the model changes |
| Regulator sites change, or block manual access | M | M | Snapshots with manifests; freeze dates |
| Errors in jurisdiction or scope rules | M | H | Primary-source citations; verification status per rule; conservative jurisdiction matrix |
| Synthetic data is unrealistic | M | M | Mixed generation; human-written subset; factor stratification; difficulty probe |
| Prompt over-tuning favours one system | M | H | Equal, logged tuning budget; sealed test split; pre-registration |
| Real or restricted data accidentally pushed to the public repository | L | H | `.gitignore`; pre-commit guard; CI guard; fictional-only fixtures |
| Annotation becomes a bottleneck, or only one annotator is available | M | M | Templates and guidelines; single-annotator fallback protocol (§11.2 B) |
| Prompt injection inside offers | M | M | Offer text treated as data; evidence rules; F15 tests |
| Small real-data strata | H | M | Confidence intervals; case-study framing; statistics mainly at message level |
| Recent law changes (CMA virtual-asset framework, regularisation deadlines) | M | M | Rule cards are versioned and dated; recheck at the freeze |

### 18.2 Resolved decisions (3 November 2026, on your instruction to go with the recommendations)

| ID | Decision | Resolution | Why it is best for the project |
|---|---|---|---|
| D1 | Approve the plan | **Approved.** Part 1 built | — |
| D2 | Models and budget | **$0.** NVIDIA API catalog free tier. Primary model `nvidia/nemotron-3.5-super-vl-120b-a12b`, chosen by the probe (ADR-0004). Optional capability arm on a smaller Nemotron model; optional SA-LARGER | Free; strong tool calling; one family keeps the capability comparison clean; open weights let others repeat it |
| D3 | Who does the human tasks | **You:** CMA export, CMA warnings, VARA transcription, DFSA hand-recording. **Annotation:** you plus one volunteer if available, otherwise the single-annotator fallback | These tasks can't legally be automated (DFSA) or are best done by hand (CMA, VARA terms) |
| D4 | DFSA sign-off and permission request | **Yes.** Read the disclaimer before data entry, and send the drafted letter (`docs/dfsa-permission-request.md`) from your own email | It costs nothing and is the strongest protection for any later publication |
| D5 | What happens when a model fails | **No silent model switching.** A failure is recorded as U7. An optional secondary model is allowed in interactive mode only, and is off by default | Keeps experimental control |
| D6 | Model for synthetic paraphrase | **A free model from a different family** than the model under test (for example Gemma or Qwen), chosen by the probe | Reduces bias from generated data matching the model under test |
| D7 | Arabic messages | **English text with Arabic name variants in Phase 1.** Arabic-language messages wait for an annotator who reads Arabic | Labels must be checkable by the people who annotate |
| D8 | CMA export | **You click "Export To Excel" by hand** | The most conservative reading of the CMA terms |
| D9 | IOSCO I-SCAN API | **Deferred to Part 8** (free; you would sign its terms) | Optional, and incomplete by IOSCO's own statement |
| D10 | Reasoning and effort setting | **The same default reasoning setting and temperature 0 for every role and baseline.** SA-MAX uses the highest setting | Fair comparison |
| D11 | Codename | **TESSERA**, matching the repository name | — |
| D12 | Public repository | **Only code, docs, policies, rule cards, templates and fictional fixtures are pushed to `main`.** Everything real stays local, enforced by the guard and CI | Avoids publishing DFSA or VARA material |
| D13 | Several NVIDIA keys | **One key.** No rotation of keys or accounts to get around rate limits; ask NVIDIA for a higher limit if needed | Rotating keys to evade limits would likely breach the trial terms and risk losing access |
| D14 | Code licence (new) | **Deferred.** The public repository is "all rights reserved" until you choose; Apache-2.0 is recommended before inviting contributors | Not urgent; it is your decision as the owner |

---

## Appendix A: Seed rule cards and jurisdiction matrix

Every rule is written in our own words, cites its source and carries a verification status. **Every "verify" item must be checked against primary sources before evaluation.** The machine-readable versions live in `knowledge/rule_cards/`.

| Rule ID | Rule (our wording) | Source | Status |
|---|---|---|---|
| JUR-01 | VARA is the competent authority for virtual-asset activity in the Emirate of Dubai, including its free zones, except the DIFC | VARA site footer (PS.md B5); Clyde & Co (Apr 2026) | Verified (primary per PS.md) |
| JUR-02 | The DFSA regulates financial services carried on in or from the DIFC | DFSA and DIFC law (to cite) | Verify (citation needed) |
| JUR-03 | The ADGM FSRA regulates financial services in ADGM | ADGM (to cite) | Verify; Part 8 |
| JUR-04 | Federal Decree-Law No. 33 of 2025 applies to "any person targeting clients within the [UAE], even if their activity is conducted outside the [UAE] or from a financial free zone", provided the activity is otherwise regulated | Art. 2(1)(d), quoted by Dechert (Feb 2026); Al Tamimi | Verify against the law text on the CMA site |
| JUR-05 | Activities carried on *exclusively* within the DIFC or ADGM fall outside the CMA's capital-markets scope | Secondary commentary (2026) | Verify |
| JUR-06 | CMA Decision No. 4/R.M/2026 sets a federal framework for onshore virtual-asset activity (eight activity-based licences), excludes the DIFC and ADGM, and leaves VARA competent for Dubai outside the DIFC | Clyde & Co (Apr 2026); Horizlaw summary | Verify against the decision text; check transition dates |
| JUR-07 | The CBUAE regulates onshore banks, finance companies, exchange houses and payment services | CBUAE (to cite) | Verify; Part 8 |
| JUR-08 | Several regulators can be relevant at once; relevance is not a finding about which regulator is competent | Design principle (P5) | — |
| JUR-09 | "SCA" (Securities and Commodities Authority) refers to the CMA, reconstituted on 1 Jan 2026 under FDL 32 and 33 of 2025 | FDL 33 on the CMA site; Dechert (PS.md B1 #2) | Verified (per PS.md) |
| SCOPE-CMA-01 | A Category 5 licence "does not in any way authorize" FX or derivatives trading | Notice on the CMA Licensed Companies page (PS.md [5]) | Verified (primary per PS.md) |
| SCOPE-CMA-02 | Category 5 covers introduction, promotion and financial consultation; trading as a broker in OTC derivatives and spot FX falls under Category 1 | Broker announcements in the trade press (2025–26) | Verify against the CMA rulebook |
| SCOPE-VARA-01 | In-Principle Approval is not a licence: IPA holders appear on the register but may not serve clients until fully licensed | VARA register (IPA listed separately); secondary guides | Verify against VARA's rulebooks |
| SCOPE-VARA-02 | VARA licences are activity-specific (for example advisory, broker-dealer, custody, exchange, lending and borrowing, management and investment, transfer and settlement, issuance) | VARA (to cite) | Verify |
| SCOPE-DFSA-01 | A DFSA authorisation lists the financial services a firm may carry on; services not listed are not authorised | DFSA register fields (to hand-record) | Verify which fields the register shows |
| SCOPE-DFSA-02 | Serving retail clients requires a retail endorsement | DFSA (to cite) | Verify; optional |
| CLONE-01 | A name match on a register does not show that an offer comes from the named firm | DFSA 2026 impersonation alerts (PS.md) | Verified (primary per PS.md) |
| CLONE-02 | Absence from an alert list (including I-SCAN) does not show that a firm is legitimate | IOSCO I-SCAN disclaimer (PS.md) | Verified (primary per PS.md) |

**Seed jurisdiction matrix.** This is deliberately cautious: it lists every regulator that could plausibly be relevant, because missing one causes false reassurance. Every cell needs to be verified.

| Zone ↓ / Activity → | Virtual assets | Securities, derivatives, FX, advice, funds | Banking, lending, payments |
|---|---|---|---|
| DIFC | DFSA | DFSA | DFSA |
| ADGM | FSRA (Part 8) | FSRA (Part 8) | FSRA (Part 8) |
| Dubai outside the DIFC, including non-financial free zones | VARA (primary); CMA possible (federal framework) | CMA | CBUAE (Part 8) |
| Other emirates, onshore | CMA (Decision 4/R.M/2026) | CMA | CBUAE (Part 8) |
| Outside the UAE, targeting UAE clients | CMA (FDL 33 Art. 2(1)(d)); VARA possible if marketing into Dubai (verify) | CMA (Art. 2(1)(d)) | CBUAE (verify) |
| Unknown zone | VARA, CMA, DFSA (+ FSRA) | CMA, DFSA (+ FSRA) | CBUAE, DFSA (+ FSRA) |

---

## Appendix B: Activity taxonomy (seed)

| Code | Activity | Notes |
|---|---|---|
| VA.EXCHANGE | Crypto exchange or trading platform | |
| VA.BROKER | Virtual-asset broker-dealer | |
| VA.CUSTODY | Custody or wallet services | |
| VA.YIELD | Staking, lending or "earn" products | Map to the regulator's activity definitions |
| VA.ADVISORY / VA.MGMT | Virtual-asset advice or portfolio management | |
| VA.ISSUANCE | Token issuance | |
| VA.TRANSFER | Transfer and settlement | |
| SEC.BROKERAGE | Securities dealing or brokerage | |
| DER.FX_CFD | OTC derivatives, spot FX, CFDs | Category 5 trap |
| SEC.ADVICE | Investment advice or financial consultation | Includes finfluencers |
| SEC.PROMOTION | Introduction or promotion | Category 5 |
| FUND.MGMT | Fund or portfolio management | |
| COMMODITY | Gold or commodity contracts | |
| BANK.DEPOSIT | Deposit-taking, "high-yield deposits" | CBUAE (Part 8) |
| LOAN.CREDIT | Personal or business loans | CBUAE (Part 8) |
| PAY.SERVICES | Payments, remittances, e-wallets | CBUAE (Part 8) |
| OTHER | Unclear or not financial | Reported as such |

---

## Appendix C: Glossary

| Term | Meaning |
|---|---|
| Blackboard | Shared, append-only state that all agents read and write through typed records |
| Performative | The type of a message (INFORM, CHALLENGE and so on), modelled on FIPA-ACL speech acts |
| Evidence record | A fact created by a tool, with a source, snapshot date, locator and link policy. The only thing a claim can cite |
| Typed assertion | The machine-checkable form of a claim (§6.2.1), which the Verifier compares with evidence fields |
| FRR | False-reassurance rate: how often a system answers "Consistent" when the gold answer is not "Consistent" |
| IPA | VARA In-Principle Approval. Not a licence |
| Snapshot | An immutable, dated copy of a manually obtained source, with a manifest |
| Restricted store | The single location of DFSA fact values; git-ignored; loads only in research-internal mode |
| Masking gateway | The component that swaps restricted values for placeholders in every outgoing model request and restores them locally |
| Request budget | The number of model calls a run may make, the free-tier counterpart of a dollar budget |
| Rehydration recipe | Record identifiers plus scripts that rebuild a dataset from a user's own manual downloads |
| Commit guard | `scripts/check_restricted.py`, which blocks restricted data, DFSA deep links and API keys from being committed |

---

## Appendix D: Sources and research log

**Regulatory and legal sources** (DFSA pages were not accessed by any tool; "per PS.md" means taken from PS.md's verified record):

- PS.md (local only), Problem 1 and audit tables B1, B5 and B8.
- CMA Licensed Companies: <https://www.uaecma.gov.ae/en/open-data/licensed-companies.aspx> (per PS.md; not accessed during planning)
- CMA Terms and Conditions: <https://www.uaecma.gov.ae/en/terms-and-conditions.aspx> (one page view, 3 Nov 2026)
- CMA Warnings: <https://www.uaecma.gov.ae/en/open-data/warnings> (per PS.md)
- VARA Public Register: <https://www.vara.ae/en/licenses-and-register/public-register/> (per PS.md)
- VARA Unlicensed VASPs: <https://www.vara.ae/en/enforcement/unlicensed-vasps/> (per PS.md)
- VARA Terms of Use: <https://vara.ae/en/terms-of-use> (one page view, 3 Nov 2026)
- DFSA Legal Disclaimer: reached from the footer of the DFSA homepage, <https://www.dfsa.ae/> (per PS.md; **not accessed**; no deep link, by the DFSA's own terms)
- CBUAE register PDF, August 2026: <https://centralbank.ae/media/hw0lreyi/cb-register-august-2026.pdf> (per PS.md)
- CBUAE terms: <https://centralbank.ae/en/footer/terms-and-conditions/> (search excerpts, 3 Nov 2026)
- ADGM terms: <https://www.adgm.com/information/terms-and-conditions> (found by search; not fully read)
- ADGM FSRA register: <https://www.adgm.com/public-registers/fsra>; FSRA alerts (URL as in PS.md)
- IOSCO I-SCAN API access: <https://www.iosco.org/i-scan/api-access/>; API Terms of Use: <https://www.iosco.org/i-scan/IOSCO_I-SCAN_API_Terms_of_Use_Agreement.pdf> (search excerpts; the portal returned 403 to automated access, not retried)
- Dechert, "From SCA to CMA – More Than Just a Rebrand" (Feb 2026): <https://www.dechert.com/knowledge/onpoint/2026/2/from-sca-to-cma---more-than-just-a-rebrand.html>
- Clyde & Co, "The UAE Capital Markets Authority replaces the federal VASP framework" (Apr 2026): <https://www.clydeco.com/en/insights/2026/april/the-uae-capital-markets-authority-replaces-the-fed> (read 3 Nov 2026)
- Al Tamimi, "Transformation of the UAE's Capital Markets": <https://www.tamimi.com/law-update/the-financial-services-edition/articles/transformation-of-the-uaes-capital-markets-a-modern-regulatory-framework/>
- Horizlaw, summary of CMA Decision No. 4/R.M/2026: <https://www.horizlaw.ae/insights/new-virtual-asset-regulations-a-summary-of-cma-decision-no4r.m2026>
- Trade-press reports on Category 5 scope (secondary), for example FX News Group: <https://fxnewsgroup.com/forex-news/retail-forex/exclusive-cfds-broker-startrader-adds-uae-sca-category-five-license>

**Free model provider** (secondary sources, searched 3 Nov 2026 and rechecked 4 Nov 2026). The recheck found no official terms page that could be read without an account. An NVIDIA staff post says credits gave way to per-model rate limits that are not published. A third-party summary says trial content is not kept after each session, with exceptions, and does not settle training use. The design does not depend on that answer, because every request is treated as possibly stored.

- NVIDIA developer forum on credits being replaced by rate limits and the definition of "trial" use: <https://forums.developer.nvidia.com/t/request-more-4-000-credits-option-on-build-nvidia-com/344567>
- NVIDIA developer forum, a request to raise the rate limit (40 → 200 RPM): <https://forums.developer.nvidia.com/t/nim-api-rate-limit-increase-request-40-200-rpm-planning-multi-model-comparison-setup/371282.md>
- LangChain NVIDIA integration docs (OpenAI-compatible endpoint; Nemotron 3 Super recommended for tool calling): <https://docs.langchain.com/oss/python/integrations/chat/nvidia_ai_endpoints>
- LlamaIndex NVIDIA docs (not all models support tool calling): <https://docs.llamaindex.ai/en/latest/examples/llm/nvidia/>
- NIM structured generation docs (`response_format` with `json_schema`; `guided_json`): <https://docs.nvidia.com/nim/large-language-models/1.1.0/structured-generation.html>
- Third-party summaries of the free tier (about 40 RPM; trial use only; disputed data practices): <https://www.developersdigest.tech/models/free-api/nvidia>, <https://www.stork.ai/blog/nvidias-free-ai-the-hidden-cost>
- Nemotron 3 Super technical report: <https://arxiv.org/html/2604.12374>

**Research literature** (check each against the full paper before citing in a manuscript):

- Kim et al., "Towards a Science of Scaling Agent Systems", arXiv:2512.08296 (2025): <https://arxiv.org/abs/2512.08296>
- Tran & Kiela, "Single-Agent LLMs Outperform Multi-Agent Systems on Multi-Hop Reasoning Under Equal Thinking Token Budgets", arXiv:2604.02460 (2026): <https://arxiv.org/abs/2604.02460>
- "Do More Agents Help?" (BenchAgent), arXiv:2606.05670 (2026): <https://arxiv.org/abs/2606.05670> (known from a search summary only)
- OneFlow, arXiv:2601.12307 (2026) (known from a search summary only)
- Choi, Zhu & Li, "Debate or Vote: Which Yields Better Decisions in Multi-Agent Large Language Models?", NeurIPS 2025, arXiv:2508.17536: <https://arxiv.org/abs/2508.17536v1>
- Cemri et al., "Why Do Multi-Agent LLM Systems Fail?", NeurIPS 2025, arXiv:2503.13657: <https://arxiv.org/abs/2503.13657v2>
- Anthropic Engineering, "How we built our multi-agent research system" (2025): <https://www.anthropic.com/engineering/multi-agent-research-system>
- Background (from prior knowledge; verify before citing): FIPA ACL message specification (2002); blackboard architectures (Hearsay-II, Erman et al., 1980); Du et al., multi-agent debate (2023/2024); Wang et al., "Rethinking the Bounds of LLM Reasoning: Are Multi-Agent Discussions the Key?" (ACL 2024).

**Tooling checks:**

- LangGraph 1.x: v1.0 in October 2025; the 1.2.x line was current in October 2026 according to release trackers.
- Next.js 16.x is the current major version.
- Exact versions are pinned in lock files.

**Access rules followed during planning:**

- No regulator data page was fetched.
- No DFSA page was accessed.
- Terms pages were read with one view each.
- A blocked page (I-SCAN, 403) was not retried.

---

## Appendix E: Audit log (version 1 → version 2)

The audit ran on 3 November 2026, after your request to audit the plan in depth and your new constraints (zero budget, public GitHub repository, pushes to `main`).

| # | Finding | Severity | Fix |
|---|---|---|---|
| A1 | v1 assumed a paid Claude API (≈ $3.3K). The budget is now $0 | Critical | Free NVIDIA API catalog; dollar tables replaced by a request budget and run-time estimates (§5.3, §11.5, §13.1) |
| A2 | v1 relied on provider-specific features (structured-output parameters, prompt caching, batch API, effort levels, task budgets, refusal fallbacks, a ban on sampling parameters) that the free provider does not offer | High | Provider-agnostic client with capability probing; JSON validation and repair; temperature 0 is now available and used for primary runs; SA-MAX redefined; SA-FRONTIER replaced by SA-LARGER |
| A3 | Free endpoints may record inputs, and v1 would have sent DFSA values to the provider | High | Restricted-value masking gateway with an invariant test (§9.4, R21) |
| A4 | The repository is public; v1 assumed private storage and would have committed `PS.md` (which quotes DFSA alerts) and data folders | High | Git-ignore rules, commit guard, pre-commit hook and CI guard; only fictional fixtures are committed (§12.7, R20) |
| A5 | v1's Appendix D contained a deep link to a DFSA page, which the DFSA terms forbid | Medium | Replaced with a homepage reference; the guard now rejects DFSA deep links (R22) |
| A6 | Verifier gates G2 and G8 need machine-checkable claims, but v1's claims were free text plus IDs | Medium | Claim catalogue with typed assertions (§6.2.1) |
| A7 | Addresses, social handles and short links had no defined role in the decision | Medium | §4.7: addresses and handles are reported but never decide; short links are never expanded and give U3 |
| A8 | Inter-annotator agreement needs two annotators; with no budget there may be only one | Medium | Single-annotator fallback protocol (§11.2 B) |
| A9 | Gold labels come from the same decision policy the Verifier enforces, an unexamined circularity | Medium | Discussed and mitigated in §11.6 (equal knowledge, SA-VER control, human labels) |
| A10 | No check that synthetic messages are too formulaic | Low | RULES-ONLY difficulty probe on the development split (§11.2 D) |
| A11 | Hosted models can be retired or updated mid-experiment | Medium | Model IDs and dates recorded; single run window; full re-run if the model changes (§5.3) |
| A12 | The free tier is limited by request rate, not cost; v1 had no throttling design | Medium | Shared rate limiter, backoff, resumable runs, fallback order (§11.5, §13.1) |
| A13 | Free quota would be wasted while debugging | Low | Local replay cache for development, masked requests only, off during evaluation (§13.1) |
| A14 | v1 required Python 3.12; this machine has 3.11 | Low | Backend targets Python ≥ 3.11 |
| A15 | Tools must stay offline, but `tldextract` fetches suffix-list updates by default | Low | Bundled snapshot only; tests block the network (§7) |
| A16 | Several API keys were offered; rotating keys to evade limits risks the trial terms | Medium | One key; formal limit-increase request if needed (D13) |
| A17 | Self-consistency needs sampling, which conflicts with temperature-0 primary runs | Low | SA-SC5 and stability runs use temperature 0.7; primary runs use temperature 0 (§11.4) |
| A18 | v1's release rules covered DFSA-derived synthetic messages but not VARA-derived ones, despite VARA's no-redistribution clause | Medium | All dataset files stay local until a release review (§11.2 B, §17.5) |
| A19 | No CI | Low | GitHub Actions (free for public repositories): guard, lint, tests |
| A20 | Parquet added a heavy dependency without need at this data size | Low | JSONL snapshots; DuckDB reads JSONL for analysis |
| A21 | The plan said "Arabic messages if an annotator is available" without a default | Low | English text with Arabic name variants by default (D7) |
| A22 | The statistical power claim was too optimistic | Low | Corrected to 6–7 percentage points at power 0.7–0.8 (§11.4) |
| A23 | Pilot cost wording was ambiguous | Low | "20 items × the full run plan" (§11.5) |
| A24 | Conflict IDs in the worked example (K-1, K-2) clashed with the K1–K7 conditions | Low | Renamed CF-1 and CF-2 |
| A25 | The repository had no code licence | Low | Recorded as decision D14 (deferred to you) |

---

## Appendix F: Changes made during the build

Each change keeps to the approved design, or moves it for the reason given.

| # | Part | Change | Why |
|---|---|---|---|
| F1 | 2 | **DFSA details no longer reach models.** The first version of the tools passed recorded services and alert dates through to the model, and left street addresses in offer text unmasked. That broke §6.9, §9.2 and §12.6. Services now become activity codes, alert dates stay local, and street-level address parts are masked. | Found while checking the code against the plan for this update, before any live call and before any of it was pushed. A new invariant test checks every recorded detail against all outgoing requests and the event log, and it was shown to fail when an alert date is put back |
| F2 | 2 | `restricted_facts_for` crashed on analyses of restricted records, which have no row of their own. Fixed | Found by the whole-case test. It would have stopped every live case that reached the Reconciler with a restricted comparison |
| F3 | 2 | LLM calls use `httpx` directly instead of the `openai` package | One dependency fewer, and the whole request path, with its leak checks, is in our code |
| F4 | 2 | `reverse_contact_lookup` belongs to CLN alone | It covers every alert list, so regulator agents calling it too would spend requests for no new information |
| F5 | 2 | `extract_contact_points` and `get_rule_card` are not model tools, and there is no `evidence_get` | Intake is deterministic, rule cards are in the prompts, and the Verifier's view already holds all evidence. Each saves a free-tier request |
| F6 | 2 | The claim catalogue gained `activity`, `zone_signal`, `offer_claim` and `targeting`; `coverage_gap` gained a scope | The Jurisdiction agent's work is typed too, so it can be challenged and checked |
| F7 | 2 | New event types: `agent.repair`, `tool.failed`, `finding.revised`, `protocol.rejected`, `llm.retry`. `llm.request` was dropped in favour of a request hash on `llm.response` | Rejections, repairs and failed tool calls are counted in telemetry. Prompts are not logged a second time |
| F8 | 2 | Every model follows one structured-output path | All conditions stay identical, and the probe measures the path that is really used |
| F9 | 2 | Purge also deletes `runs/` | It holds row references and masked relations, which should not outlive the facts |
| F10 | 2 | New committed files: `policies/models.yaml`, `backend/prompts/v1/`, `eval/smoke/` | Model settings are policy, prompts are versioned with the code, and the smoke set is fictional, so it is safe to publish |
| F11 | 3 | New reason U9 | An offer can match an active firm whose scope for the activity cannot be confirmed. None of U1–U8 fits, and every "Could not verify" must list a reason |
| F12 | 3 | No SQLite checkpointer for the graph. The event log is the only record of a case, and the graph's state is a few counters | A node's model calls are not safe to repeat, so resuming mid-case could post findings twice. Restarting an unfinished case is safe, and replay already comes from the event log. This also keeps restricted data out of a second store |
| F13 | 3 | C1 fires only when agents disagree on whether a regulator is relevant, not on primary versus possible | Both mean relevant, and an extra conflict would spend free requests on nothing |
| F14 | 3 | Conflicts can be settled by the detector, with a new `settled` status and event | The worked example needs it: a revision can remove a conflict's cause, and that should cost no model request |
| F15 | 3 | An offer with no deciding contact point fails K4 | With no contact to compare, nothing ties the offer to the firm. The plan did not say, and passing vacuously would be false reassurance |
| F16 | 3 | The Verifier's model checks run only if every deterministic gate passes | A failed gate is a veto anyway, so the model request would be wasted |
| F17 | 3 | A contact point with nothing official to compare it with can stand without evidence, in gate G1 | There is no record for it to cite. It still fails K4 |
| F18 | 2 | The primary model changed to `nvidia/nemotron-3.5-super-vl-120b-a12b` | The planned model is listed but returns 404 for this account. The newer model of the same size passed every probe trial (ADR-0004) |
| F19 | 2 | The probe reports each model as it finishes, and the default candidates are the models this account can reach | A model that times out costs many minutes in retries, and the first full run overran its limit and lost its results |
| F20 | 3 | A correctness review of Parts 1–3 found and fixed ten defects. Rationales clipped to 60 words were rejected as too long, so resolutions could be lost. A CMA status of "Inactive" was read as active. DFSA alerts found only by a near name were recorded as exact matches. A listed email domain did not count as a listed contact. A look-alike comparison added HC5 even to a matching contact. One consulted list counted as checking a whole regulator. A plain answer could close a challenge. A report could say "checked" for a failed check. HC5's policy text used a banned word. A claimed regulator outside coverage could still end as Consistent | Several of these pushed results the wrong way, so each has a test. A check for the last one now reports U2 |
| F21 | 3 | A finding with nothing to cite, such as `targeting`, is no longer a claim in a proposal. Coverage is reported separately | The first live run reached the right answer, then the Verifier vetoed it, rightly calling an uncited judgement unsupported |
| F22 | 3 | `max_tokens` rose from 8,192 to 16,384 | In the first live run, reasoning used the whole allowance and left no answer |
| F23 | 3 | Harmless slips in a model's output no longer cost a repair or a turn. An unknown label becomes `other`, a scope judgement with no entry is ignored, a repeated finding is not posted twice, one entry found by several routes is one match, and a claim on an unknown finding is dropped | The first full live run spent most of its repairs on these, and lost two cases to them |
| F24 | 3 | The list of regulators in a proposal is completed in code | It is known from the findings, and a sound result had been vetoed twice over one regulator a model left out |
| F25 | 3 | An In-Principle Approval never counts as covering an activity, whatever a model says, and an IPA holder offering an activity gives HC4 | SCOPE-VARA-01 is a fixed rule, so it need not depend on a model's judgement |
| F26 | 3 | With the Verifier on, a report states every hard conflict and reason the decision-policy engine derives, not the ones the proposal happened to list | They are deterministic and checkable. A proposal needs only one backed hard conflict to pass |
| F27 | 4 | RULES-ONLY's crew works from a reading of the offer, and the tests give it a perfect reading | The same code answers two questions: how far plain rules get, and whether the policy reaches gold when an offer is read correctly |
| F28 | 4 | The single agent returns one object, posted through the same code as the crew's findings, and answers a veto by replacing all its findings | It has no challenge rounds, so it needs another way to correct itself. Its findings are the same types, so the same gates apply |
| F29 | 4 | SA-MAX can only differ from SA-BASE by thinking and output length | The model's only reasoning control found so far is on or off. If primary runs use thinking on, SA-MAX differs only in its longer outputs |
| F30 | 4 | A second review fixed: the DFSA tool never returned its no-match evidence ID, so an agent could not report that a firm is not on the DFSA register; our field names used a word the language policy bans; the shared ground rules told one agent working alone that it was "one member"; retries stopped too soon for a slow spell at the provider | Found by reading live traces. The first explains a hard conflict that was missing from a live case |
| F31 | 4 | Added the trace bundle and coordination telemetry that §6.11 calls for, served at `/api/cases/{id}/trace` | The evaluation and the frontend both need them |
| F32 | 5 | The stage is hand-built SVG, not React Flow | Tiles, a gate and particles are not a node graph. It is less code, with full control of the motion, and it adds no dependency |
| F33 | 5 | Each finding is a tile that flies from its agent into a mosaic round the Reconciler, and grows as a wedge toward that agent. The tile stays lit if the result rests on it | This makes the shared board and the evidence behind a result visible, from the event log alone |
| F34 | 5 | The interface calls the CLN agent "Contact check", and internally it stays CLN | "Clone" beside a firm's name could read as a verdict, which the language policy forbids |
| F35 | 5 | The Arena's address is `/arena?a=&b=`, not `/arena/[id]` | A crew and a baseline are two cases with two IDs. An address can then reopen any pair |
| F36 | 5 | The "waiting for the rate limiter" state is not drawn | No event reports it yet. Showing a guess would break the rule that everything drawn comes from the log |
| F37 | 5 | The API gained `POST /api/preview`, `masked_values` and source rules in `/api/status`, and `tessera-replay` to join run logs. RULES-ONLY runs without a key, and fiction keeps its own event log | Intake, Governance and replay need them, and the browser tests must run in CI with no key |
| F38 | 5 | Every API response is sent with `Cache-Control: no-store` | A report can hold DFSA facts, and the DFSA disclaimer bars caching |
| F39 | 5 | The exported case file is the masked trace, not the report | Restricted values appear only in a report built on request, so nothing restricted is written to a file |
| F40 | 5 | A Verifier veto can come from its reading of the evidence with every gate passed, so the gate states the reason and the blackboard has a Verifier tab | The first design showed only gate lights, which were all green on a real veto |
| F41 | 5 | `backend/tests/test_frontend_contract.py` compares the frontend's recorded case with what the crew emits today, and checks each event the reducer handles exists | The backend and the frontend live apart, and this stops them drifting |
| F42 | 5 | Browser tests use the installed Edge on a developer's machine, and Playwright's Chromium in CI. Lint added with the Next.js rules | No extra download locally. Lint found ref use during render, which was replaced |
| F43 | 6 | The free tier was measured at about 8 requests a minute, not 40, so the limiter paces at 7.5. The full run is about a week of continuous running, not 45 hours | At 35 a minute the crew run was stuck in retries and achieved 4.5. A no-retry probe showed the limit, and that it does not depend on prompt size |
| F44 | 6 | The harness can run several cases at once under the shared limiter | The limit is on requests. A case spends most of its time waiting for one reply, so running cases side by side uses the allowance that would otherwise go unused |
| F45 | 6 | How an entry matched, and what a payment analysis found, come from the tool's evidence, not a model's copy | Across every live run, the two most common gate failures were a model restating a tool's answer wrongly. Each lost a sound result, because the claim could not pass and the Reconciler kept it. The tool's answer is what the check compares with, so nothing is lost |
| F46 | 6 | A blank offer claim is not posted. `SEC.PROMOTION` is defined as promoting another firm's products for a fee | A model listed every kind of claim with empty values. Another read a firm's own advertising as an activity outside its licence, which is the error that wrongly implicates a genuine firm |
| F47 | 6 | The evaluation code is a package, `backend/src/tessera/evaluation/`, and `eval/` holds the plan file | It shares the typed models, tests and lint, and it needs none of its own tooling |
| F48 | 6 | Generated messages avoid the taxonomy's keywords and exact firm names | The difficulty probe fired on the hand-written set: rules alone matched 21 of 25. On the first generated set they match 20 of 39, with macro-F1 0.35 |
| F49 | 6 | Entity-level near misses (E11) take the label the record gives, and need not be "Could not verify" | A near-miss name with a copied reference number and an imitating domain is a real conflict, and the stratum only requires that it never passes as the firm |

